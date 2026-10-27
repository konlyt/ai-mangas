"""
视频合成任务（ARQ Worker）。

从 tasks 表取出 compose 类型任务，收集项目分镜的视频片段：
远程 URL 下载 / /static 本地复制 → 规格统一（分辨率统一，视频轨 -an 无音频）→
concat 拼接纯视频 → 逐分镜决策该段音频来源并生成定长音频段：
    - auto（默认）：该镜已有 TTS 配音则用 TTS 覆盖；否则保留原视频原声；都没有则静音；
    - keep_original：一律保留原视频原声（忽略 TTS，相当于"不重新配音"）；
    - tts：一律使用 TTS 配音（无 TTS 的段回退原声，再不行静音）；
TTS 段若时长超出本分镜镜头时长，自动倍速压缩（atempo）保证台词不串入下一分镜；
不足补静音。各段音频 concat 成全长音轨后与纯视频合流；可选 BGM 混音；
可选字幕（分镜级字幕 JSON 存在时烧录）→ 产出成片到
static/outputs/{project_id}/final_{ts}.mp4（局部合成为 preview_{ts}.mp4），
回写成片 URL 与任务状态。
"""

import json
import time
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import AgentEvent, Project, Storyboard, Task, TaskStatus
from app.providers.storage import STATIC_ROOT
from app.utils.ffmpeg import (
    FFmpegNotFoundError,
    build_srt,
    fetch_url_to_file,
    probe_media,
    run_ffmpeg,
)

logger = get_logger()

# 默认输出帧率（统一转码时使用）
DEFAULT_FPS = 30
# 音频采样率 / 声道（所有音频段统一规格，便于 concat）
AUDIO_RATE = 44100
# BGM 混音音量
BGM_VOLUME = 0.2
# 分镜级字幕数据文件（并行字幕任务产出落点，存在则烧录）
SUBTITLE_JSON_TEMPLATE = "subtitles/{project_id}.json"
# 成片输出目录模板（相对 STATIC_ROOT）
OUTPUT_DIR_TEMPLATE = "outputs/{project_id}"
# 允许的音频模式
AUDIO_MODES = {"auto", "keep_original", "tts"}


async def _publish_task_status(project_id: int, task_id: int, status: str, progress: int = 0):
    """广播任务状态变更。

    Args:
        project_id: 项目 ID。
        task_id: 任务 ID。
        status: 状态字符串。
        progress: 进度百分比。

    Returns:
        None
    """
    try:
        from app.domains.tasks import publish_task_status

        await publish_task_status(project_id, task_id, status, progress)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose-task] 广播状态失败 task_id={task_id}: {exc}")


def _parse_storyboard_ids(idempotency_key: Optional[str]) -> Optional[list[int]]:
    """从合成任务幂等键中解析局部合成的分镜 ID 列表。

    幂等键格式：{project_id}-compose-full 或 {project_id}-compose-1,2,3。

    Args:
        idempotency_key: 任务幂等键。

    Returns:
        Optional[list[int]]: 分镜 ID 列表；全片合成（无法解析）时返回 None。
    """
    if not idempotency_key or "-compose-" not in idempotency_key:
        return None
    suffix = idempotency_key.rsplit("-compose-", 1)[-1]
    if suffix in ("", "full"):
        return None
    try:
        return [int(x) for x in suffix.split(",") if x]
    except ValueError:
        return None


def _output_url(project_id: int, filename: str) -> str:
    """根据项目 ID 与文件名构造成片对外访问 URL。

    Args:
        project_id: 项目 ID。
        filename: 成片文件名（如 final_1736000000.mp4）。

    Returns:
        str: 形如 /static/outputs/{project_id}/{filename} 的相对 URL。
    """
    return f"/static/{OUTPUT_DIR_TEMPLATE.format(project_id=project_id)}/{filename}"


def _atempo_chain(ratio: float) -> str:
    """生成 atempo 滤镜链，将播放速率压缩到 ratio 倍速（ratio>1 加速）。

    ffmpeg 单级 atempo 范围 0.5~100；台词倍速一般不超过 3 倍，
    超过 2 倍时链式拼接（atempo=2,atempo=ratio/2）。

    Args:
        ratio: 目标倍速（>1 加速，<1 减速）。

    Returns:
        str: 可直接拼入 -af 的 atempo 链片段。
    """
    if ratio <= 1.0:
        return ""
    if ratio <= 2.0:
        return f"atempo={ratio:.4f}"
    rest = ratio / 2.0
    if rest <= 2.0:
        return f"atempo=2.0,atempo={rest:.4f}"
    return f"atempo=2.0,atempo=2.0,atempo={(ratio / 4.0):.4f}"


async def _build_silence_segment(dur: float, out: Path) -> None:
    """生成指定时长的静音音频段（统一采样率/声道）。

    Args:
        dur: 段时长（秒）。
        out: 输出文件路径（m4a）。

    Returns:
        None
    """
    await run_ffmpeg(
        ["-y", "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo",
         "-t", f"{dur:.3f}", "-c:a", "aac", "-b:a", "192k", str(out)],
        log_tag="compose-audio-silence",
    )


async def _build_original_audio_segment(src_video: Path, dur: float, out: Path) -> None:
    """从原视频片段中抽取音轨并统一规格（用于"保留原声"分镜）。

    Args:
        src_video: 原始下载后的分镜视频文件。
        dur: 段时长（秒），用于精确截断对齐。
        out: 输出文件路径（m4a）。

    Returns:
        None
    """
    await run_ffmpeg(
        ["-y", "-i", str(src_video), "-vn",
         "-t", f"{dur:.3f}",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-ac", "2",
         str(out)],
        log_tag="compose-audio-original",
    )


async def _build_tts_segment(tts_url: str, dur: float, work_dir: Path, index: int) -> Optional[Path]:
    """将 TTS 配音压成严格等于本分镜时长的音频段（台词不串镜）。

    TTS 音频短于分镜时长：末尾补静音；长于分镜时长：atempo 倍速压缩，
    保证完整台词在本镜头内播完、绝不溢出到下一分镜。

    Args:
        tts_url: TTS 音频 URL（/static/ 或 http）。
        dur: 本分镜视频时长（秒）。
        work_dir: 临时工作目录。
        index: 段序号（用于命名）。

    Returns:
        Optional[Path]: 生成的音频段文件路径；失败时 None（调用方降级静音）。
    """
    tts_file = work_dir / f"tts_src_{index:04d}.bin"
    try:
        await fetch_url_to_file(tts_url, tts_file)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose-task] TTS 音频获取失败 index={index}: {exc}")
        return None

    out = work_dir / f"aud_{index:04d}.m4a"
    try:
        info = await probe_media(tts_file)
        tts_dur = float(info.get("duration") or 0)
        if tts_dur <= 0:
            # 探测失败：直接 apad 截断
            af = "apad"
        elif tts_dur > dur:
            ratio = tts_dur / dur
            chain = _atempo_chain(ratio)
            # 倍速后再 apad（防止浮点误差不足），最后 -t 硬截到 dur
            af = f"{chain},apad" if chain else "apad"
        else:
            # 短了：补静音到 dur
            af = "apad"
        await run_ffmpeg(
            ["-y", "-i", str(tts_file),
             "-af", af,
             "-t", f"{dur:.3f}",
             "-ar", str(AUDIO_RATE), "-ac", "2",
             "-c:a", "aac", "-b:a", "192k",
             str(out)],
            log_tag="compose-audio-tts",
        )
        return out if out.is_file() else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose-task] TTS 段处理失败 index={index}: {exc}")
        return None
    finally:
        tts_file.unlink(missing_ok=True)


async def _build_full_audio_track(
    decisions: list[dict[str, Any]],
    work_dir: Path,
    progress_cb,
) -> Optional[Path]:
    """按逐分镜决策生成全长音频轨。

    每段决策为 tts / original / silence，分别产出定长音频段后 concat。

    Args:
        decisions: 每段决策列表，含 index / kind（tts|original|silence）/
            duration / tts_url / src_video。
        work_dir: 临时工作目录。
        progress_cb: 进度回调。

    Returns:
        Optional[Path]: 全长音频轨路径；全部段失败时 None。
    """
    audio_dir = work_dir / "audio_segs"
    audio_dir.mkdir(parents=True, exist_ok=True)
    part_files: list[Path] = []
    total = max(1, len(decisions))

    for i, dec in enumerate(decisions):
        dur = float(dec["duration"])
        part = audio_dir / f"seg_{i:04d}.m4a"
        made: Optional[Path] = None
        if dec["kind"] == "tts" and dec.get("tts_url"):
            made = await _build_tts_segment(dec["tts_url"], dur, work_dir, i)
        if made is None and dec["kind"] == "original" and dec.get("src_video"):
            try:
                await _build_original_audio_segment(dec["src_video"], dur, part)
                made = part
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[compose-task] 原声段抽取失败 index={i}: {exc}")
        if made is None:
            await _build_silence_segment(dur, part)
            made = part
        elif made != part:
            # TTS 输出文件改名到统一命名
            made.replace(part)
        part_files.append(part)
        await progress_cb(55 + int(15 * (i + 1) / total))

    if not part_files:
        return None
    list_file = audio_dir / "list.txt"
    list_file.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in part_files), encoding="utf-8"
    )
    full = work_dir / "full_audio.m4a"
    await run_ffmpeg(
        ["-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(full)],
        log_tag="compose-audio-concat",
    )
    return full if full.is_file() else None


def _extract_dialogue_lines(desc: str) -> list[str]:
    """从分镜 visual_description 中提取所有"角色：台词"行，逐句返回。

    跳过以 △ 开头的动作描写行；角色名后的（动作）括号内容也去掉。
    """
    import re

    lines: list[str] = []
    for raw in (desc or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("△"):
            continue
        # 匹配 "角色名（动作）：台词" 或 "角色名：台词"
        m = re.match(r"^([^：:（(]+?)(?:（[^）]*）)?[：:](.+)$", line)
        if m:
            speaker = m.group(1).strip()
            speech = m.group(2).strip()
            if speaker and speech:
                lines.append(f"{speaker}：{speech}")
    return lines


def _build_subtitle_segments(
    boards: list[tuple[Storyboard, Path]],
    seg_durations: list[float],
) -> list[dict[str, Any]]:
    """从参与合成的分镜数据动态构建字幕分段（成片全局时间轴）。

    每个分镜按台词句数均分该镜头时长，逐句显示（说一句切一句）。
    字幕文本从 visual_description 提取；为空时回退 dialogue 字段。
    """
    segments: list[dict[str, Any]] = []
    cursor = 0.0
    for (sb, _file), seg_dur in zip(boards, seg_durations):
        seg_dur = float(seg_dur or 0)
        dialogue_lines = _extract_dialogue_lines(sb.visual_description)
        if not dialogue_lines:
            fallback = (sb.dialogue or "").strip()
            dialogue_lines = [fallback] if fallback else []
        if not dialogue_lines:
            cursor += seg_dur
            continue
        # 每句固定显示 1.0 秒；超过分镜时长的句子截断
        line_dur = 1.0
        max_lines = max(1, int(seg_dur // line_dur))
        dialogue_lines = dialogue_lines[:max_lines]
        for idx, text in enumerate(dialogue_lines):
            segments.append(
                {
                    "storyboard_id": sb.id,
                    "text": text,
                    "start": round(cursor + idx * line_dur, 3),
                    "duration": line_dur,
                }
            )
        cursor += seg_dur
    return segments


def _ensure_subtitle_file(
    project_id: int,
    boards: list[tuple[Storyboard, Path]],
    seg_durations: list[float],
) -> bool:
    """确保分镜级字幕 JSON 存在：缺失时从分镜数据动态构建并写盘。

    Args:
        project_id: 项目 ID。
        boards: 参与合成的（分镜, 本地视频文件）配对列表。
        seg_durations: 各分段视频实际时长（秒）。

    Returns:
        bool: 字幕文件已存在或本次成功生成时返回 True。
    """
    sub_json = STATIC_ROOT / SUBTITLE_JSON_TEMPLATE.format(project_id=project_id)
    # 优先使用用户在配音工作台勾选的台词
    selected_file = STATIC_ROOT / "subtitles" / f"{project_id}_selected.json"
    if selected_file.is_file():
        try:
            selected_texts = json.loads(selected_file.read_text(encoding="utf-8"))
            if selected_texts:
                segments = []
                t = 0.0
                per = sum(seg_durations) / len(selected_texts) if selected_texts else 0
                for text in selected_texts:
                    segments.append({"start": round(t, 2), "duration": round(per, 2), "text": text})
                    t += per
                sub_json.parent.mkdir(parents=True, exist_ok=True)
                sub_json.write_text(json.dumps({"project_id": project_id, "segments": segments}, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"[compose-task] 使用用户勾选字幕 {len(segments)} 条 project_id={project_id}")
                return True
        except Exception as exc:
            logger.warning(f"[compose-task] 读取勾选字幕失败，回退默认: {exc}")
    if sub_json.is_file():
        return True
    segments = _build_subtitle_segments(boards, seg_durations)
    if not segments:
        logger.info(f"[compose-task] 分镜台词全空，不生成字幕文件 project_id={project_id}")
        return False
    try:
        sub_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"project_id": project_id, "segments": segments}
        sub_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose-task] 字幕文件生成失败，跳过烧录: {exc}")
        return False


async def compose_video(ctx: dict[str, Any], task_id: int, storyboard_ids: Optional[list[int]] = None) -> dict[str, Any]:
    """执行视频合成任务。

    Args:
        ctx: ARQ 任务上下文。
        task_id: 任务 ID。
        storyboard_ids: 局部合成的分镜 ID 列表；None 表示全片合成。

    Returns:
        dict: 包含 task_id 与 status 的结果字典。

    Raises:
        Exception: 当重试次数未耗尽时抛出，触发 ARQ 重试。
    """
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if task is None:
            logger.error(f"[compose-task] 任务不存在 task_id={task_id}")
            return {"task_id": task_id, "status": "not_found"}

        if task.status == TaskStatus.DONE:
            return {"task_id": task_id, "status": "done"}

        task.status = TaskStatus.RUNNING
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 5)

        start_time = time.time()
        storyboards: list[Storyboard] = []
        is_partial = False
        final_url = ""
        try:
            # ---- 0. 前置检查：FFmpeg 可用性 ----
            try:
                await run_ffmpeg(["-version"], log_tag="compose-check")
            except FFmpegNotFoundError:
                task.status = TaskStatus.DEAD
                task.error_message = (
                    "未检测到 FFmpeg，无法合成视频：请设置 FFMPEG_PATH 环境变量、"
                    "将 ffmpeg 加入 PATH，或将 ffmpeg.exe 放入项目 tools/ 目录"
                )[:500]
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                return {"task_id": task_id, "status": "dead", "error": task.error_message}

            ids = storyboard_ids or _parse_storyboard_ids(task.idempotency_key)
            is_partial = bool(ids)

            # ---- 1. 收集分镜视频（跳过无视频的分镜） ----
            query = (
                select(Storyboard)
                .where(Storyboard.project_id == task.project_id)
                .order_by(Storyboard.sequence)
            )
            if ids:
                query = query.where(Storyboard.id.in_(ids))
            rows = await session.execute(query)
            storyboards = list(rows.scalars().all())
            video_boards = [s for s in storyboards if s.video_url]

            if not video_boards:
                task.status = TaskStatus.FAILED
                task.error_message = "没有可合成的分镜视频片段，请先生成视频素材"
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
                return {"task_id": task_id, "status": "failed", "error": "没有可合成的视频素材"}

            project = await session.get(Project, task.project_id)
            project_config = (project.config or {}) if project else {}
            bgm_url = project_config.get("bgm_url")
            audio_mode = project_config.get("audio_mode") or "auto"
            if audio_mode not in AUDIO_MODES:
                audio_mode = "auto"

            est_duration = sum(float(s.duration or 0) for s in video_boards)
            logger.info(
                f"[compose-task] 开始合成 task_id={task_id}, "
                f"storyboards={len(storyboards)}, video_segments={len(video_boards)}, "
                f"partial={is_partial}, audio_mode={audio_mode}, est_duration={est_duration:.1f}s"
            )

            # ---- 2. 下载视频片段到临时目录 ----
            fetch_start = time.time()
            with TemporaryDirectory(prefix="compose_", ignore_cleanup_errors=True) as tmp:
                work_dir = Path(tmp)
                board_file_pairs: list[tuple[Storyboard, Path]] = []
                total = len(video_boards)
                for i, sb in enumerate(video_boards):
                    dest = work_dir / f"src_{i:04d}.mp4"
                    try:
                        await fetch_url_to_file(sb.video_url, dest)
                        board_file_pairs.append((sb, dest))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            f"[compose-task] 分镜 {sb.id} 视频获取失败，跳过: {exc}"
                        )
                    await _publish_task_status(
                        task.project_id, task_id, TaskStatus.RUNNING.value,
                        10 + int(20 * (i + 1) / total),
                    )

                if not board_file_pairs:
                    raise RuntimeError("所有分镜视频片段均获取失败，无法合成")
                logger.info(
                    f"[compose-task] 片段获取完成 task_id={task_id}, "
                    f"fetched={len(board_file_pairs)}/{total}, "
                    f"fetch_latency={time.time() - fetch_start:.1f}s"
                )

                # ---- 3. 规格统一：纯视频（-an），逐段探测是否含原声 ----
                await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 32)
                normalize_start = time.time()
                base_info = await probe_media(board_file_pairs[0][1])
                target_w = max(2, (base_info["width"] or 640) // 2 * 2)
                target_h = max(2, (base_info["height"] or 360) // 2 * 2)
                target_fps = base_info["fps"] or DEFAULT_FPS

                std_files: list[Path] = []
                seg_durations: list[float] = []
                seg_has_audio: list[bool] = []
                for i, src in enumerate([p for _, p in board_file_pairs]):
                    info = await probe_media(src)
                    dst = work_dir / f"seg_{i:04d}.mp4"
                    # 视频统一规格，音频轨不带到 concat（后面单独逐段决策混音）
                    await run_ffmpeg(
                        ["-y", "-i", str(src),
                         "-vf", f"scale={target_w}:{target_h},setsar=1",
                         "-r", f"{target_fps:.6f}",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                         "-pix_fmt", "yuv420p", "-an",
                         str(dst)],
                        log_tag="compose-normalize",
                    )
                    std_files.append(dst)
                    fallback_dur = float(board_file_pairs[i][0].duration or 0)
                    seg_durations.append(info["duration"] or fallback_dur)
                    seg_has_audio.append(bool(info.get("has_audio")))

                logger.info(
                    f"[compose-task] 规格统一完成 task_id={task_id}, "
                    f"segments={len(std_files)}, target={target_w}x{target_h}, "
                    f"normalize_latency={time.time() - normalize_start:.1f}s"
                )

                # ---- 4. concat demuxer 拼接纯视频 ----
                await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 45)
                concat_list = work_dir / "filelist.txt"
                concat_list.write_text(
                    "".join(f"file '{p.as_posix()}'\n" for p in std_files), encoding="utf-8"
                )
                silent_video = work_dir / "concat_silent.mp4"
                await run_ffmpeg(
                    ["-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                     "-c", "copy", str(silent_video)],
                    log_tag="compose-concat",
                )

                # ---- 5. 逐分镜音频决策并生成全长音轨 ----
                decisions: list[dict[str, Any]] = []
                for i, (sb, src) in enumerate(board_file_pairs):
                    dur = seg_durations[i] or 0.0
                    if dur <= 0:
                        continue
                    has_tts = bool(sb.audio_url)
                    has_orig = seg_has_audio[i]
                    if audio_mode == "keep_original":
                        kind = "original" if has_orig else "silence"
                    elif audio_mode == "tts":
                        kind = "tts" if has_tts else ("original" if has_orig else "silence")
                    else:  # auto：有 TTS 用 TTS，否则保留原声，都没有静音
                        kind = "tts" if has_tts else ("original" if has_orig else "silence")
                    decisions.append({
                        "index": i,
                        "kind": kind,
                        "duration": dur,
                        "tts_url": sb.audio_url,
                        "src_video": src,
                    })

                async def _progress(p: int) -> None:
                    await _publish_task_status(
                        task.project_id, task_id, TaskStatus.RUNNING.value, min(p, 72)
                    )

                full_audio = await _build_full_audio_track(decisions, work_dir, _progress)

                # ---- 5.5 字幕兜底（仅全片合成落盘） ----
                if not is_partial:
                    _ensure_subtitle_file(task.project_id, board_file_pairs, seg_durations)

                # ---- 6. BGM 下载 ----
                bgm_file: Optional[Path] = None
                if bgm_url:
                    bgm_file = work_dir / "bgm.bin"
                    try:
                        await fetch_url_to_file(bgm_url, bgm_file)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[compose-task] BGM 获取失败，忽略: {exc}")
                        bgm_file = None

                # ---- 7. 字幕 SRT ----
                sub_srt: Optional[Path] = None
                sub_json = STATIC_ROOT / SUBTITLE_JSON_TEMPLATE.format(project_id=task.project_id)
                if sub_json.is_file():
                    try:
                        data = json.loads(sub_json.read_text(encoding="utf-8"))
                        srt_content = build_srt(data.get("segments") or [])
                        if srt_content:
                            sub_srt = work_dir / "sub.srt"
                            sub_srt.write_text(srt_content, encoding="utf-8")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[compose-task] 字幕数据解析失败，跳过烧录: {exc}")

                # ---- 8. 最终混流：纯视频 + 全长音轨 + BGM（可选）+ 字幕 ----
                await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 78)
                out_dir = STATIC_ROOT / OUTPUT_DIR_TEMPLATE.format(project_id=task.project_id)
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = int(datetime.now().timestamp())
                prefix = "preview" if is_partial else "final"
                out_file = out_dir / f"{prefix}_{ts}.mp4"

                inputs = ["-i", str(silent_video)]
                has_audio_track = full_audio is not None
                if has_audio_track:
                    inputs += ["-i", str(full_audio)]
                if bgm_file is not None:
                    inputs += ["-stream_loop", "-1", "-i", str(bgm_file)]

                args = ["-y", *inputs]
                if has_audio_track and bgm_file is not None:
                    # 音轨（1）与 BGM（2）混音：人声轨为主，BGM 压低
                    args += [
                        "-filter_complex",
                        f"[2:a]volume={BGM_VOLUME}[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=3[aout]",
                        "-map", "0:v", "-map", "[aout]",
                    ]
                elif has_audio_track:
                    args += ["-map", "0:v", "-map", "1:a"]
                elif bgm_file is not None:
                    args += [
                        "-filter_complex", f"[1:a]volume={BGM_VOLUME}[aout]",
                        "-map", "0:v", "-map", "[aout]",
                    ]
                else:
                    args += ["-map", "0:v"]

                if sub_srt is not None:
                    args += [
                        "-vf",
                        "subtitles=sub.srt:force_style='FontName=Microsoft YaHei,FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=45'",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-pix_fmt", "yuv420p",
                    ]
                else:
                    args += ["-c:v", "copy"]
                args += ["-c:a", "aac", "-b:a", "192k", "-shortest",
                         "-movflags", "+faststart", str(out_file)]
                await run_ffmpeg(args, cwd=work_dir, log_tag="compose-final")

                if not out_file.is_file():
                    raise RuntimeError("合成产物未生成")

                final_url = _output_url(task.project_id, out_file.name)
        except FFmpegNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start_time) * 1000)
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(exc)[:500]

            if task.retry_count >= (task.max_retry or 3):
                task.status = TaskStatus.DEAD
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                return {"task_id": task_id, "status": "dead", "error": str(exc)}

            task.status = TaskStatus.FAILED
            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
            logger.warning(
                f"[compose-task] 合成失败，将重试 task_id={task_id}, "
                f"retry={task.retry_count}, error={exc}"
            )
            raise

        # ---- 9. 回写任务结果与事件 ----
        task.result_url = final_url
        task.status = TaskStatus.DONE
        task.cost_points = 0
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.DONE.value, 100)

        latency_ms = int((time.time() - start_time) * 1000)
        event = AgentEvent(
            graph_run_id=task.graph_run_id or "",
            project_id=task.project_id,
            node_name="compose_provider",
            latency_ms=latency_ms,
            cost_points=task.cost_points,
            input_digest=f"segments={len(board_file_pairs)}, partial={is_partial}",
            output_digest=final_url,
        )
        session.add(event)
        await session.commit()

        out_size_mb = out_file.stat().st_size / (1024 * 1024)
        logger.info(
            f"[compose-task] 合成成功 task_id={task_id}, segments={len(board_file_pairs)}, "
            f"partial={is_partial}, url={final_url}, size={out_size_mb:.2f}MB, "
            f"latency={latency_ms}ms"
        )
        return {"task_id": task_id, "status": "done", "url": final_url}
