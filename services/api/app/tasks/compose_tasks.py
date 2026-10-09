"""
视频合成任务（ARQ Worker）。

从 tasks 表取出 compose 类型任务，收集项目分镜的视频片段：
远程 URL 下载 / /static 本地复制 → 规格统一（分辨率不一致时转码）→ concat 拼接 →
逐段混入 TTS 配音（无配音分段以静音补齐）→ 可选 BGM（音量 0.2）混音 →
可选字幕（分镜级字幕 JSON 存在时生成 SRT 烧录；缺失时从分镜 dialogue +
配音时长动态构建并写盘兜底，台词全空则跳过）→ 产出成片到
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
# 音频采样率 / 声道（配音与静音段统一规格，便于 concat）
AUDIO_RATE = 44100
# BGM 混音音量
BGM_VOLUME = 0.2
# 分镜级字幕数据文件（并行字幕任务产出落点，存在则烧录）
SUBTITLE_JSON_TEMPLATE = "subtitles/{project_id}.json"
# 成片输出目录模板（相对 STATIC_ROOT）
OUTPUT_DIR_TEMPLATE = "outputs/{project_id}"


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


def _build_audio_filter(has_voice: bool, has_bgm: bool) -> tuple[list[str], str]:
    """构建混音 filter_complex 参数与音频输出标签。

    Args:
        has_voice: 是否存在完整配音轨（输入索引 1）。
        has_bgm: 是否存在 BGM（输入索引 2，若同时有配音轨，否则为 1）。

    Returns:
        tuple[list[str], str]: (filter_complex 参数列表, 音频输出标签映射参数)。
    """
    if has_voice and has_bgm:
        fc = f"[2:a]volume={BGM_VOLUME}[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=3[aout]"
        return ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]"]
    if has_voice:
        return ["-map", "0:v", "-map", "1:a"]
    if has_bgm:
        return ["-filter_complex", f"[1:a]volume={BGM_VOLUME}[aout]", "-map", "0:v", "-map", "[aout]"]
    return ["-map", "0:v"]


async def _prepare_audio_track(
    segments: list[dict[str, Any]],
    work_dir: Path,
    progress_cb,
) -> Optional[Path]:
    """将各分镜 TTS 配音逐段补齐为分段时长并拼接成完整配音轨。

    每段处理：有配音则 apad 补齐 + 截断到分段时长；无配音生成静音段。
    全部分段统一为 mp3 后经 concat demuxer 拼接，保证与视频时间轴对齐。

    Args:
        segments: 分段信息列表，每项含 index（序号）、duration（分段秒数）、
            audio_url（TTS 音频 URL，可空）。
        work_dir: 工作临时目录。
        progress_cb: 进度回调（异步函数，参数为进度百分比）。

    Returns:
        Optional[Path]: 完整配音轨文件路径；项目完全无配音时返回 None。
    """
    audio_items = [s for s in segments if s.get("audio_url")]
    if not audio_items:
        return None

    voice_dir = work_dir / "audio"
    voice_dir.mkdir(parents=True, exist_ok=True)
    part_files: list[Path] = []

    total = len(segments)
    for i, seg in enumerate(segments):
        dur = float(seg["duration"])
        part = voice_dir / f"aud_{i:04d}.mp3"
        audio_url = seg.get("audio_url")
        if audio_url:
            src = voice_dir / f"tts_{i:04d}.bin"
            try:
                await fetch_url_to_file(audio_url, src)
                await run_ffmpeg(
                    ["-y", "-i", str(src), "-af", "apad", "-t", f"{dur:.3f}",
                     "-ar", str(AUDIO_RATE), "-ac", "2", "-c:a", "libmp3lame", "-q:a", "4",
                     str(part)],
                    log_tag="compose-audio",
                )
            except Exception as exc:  # noqa: BLE001
                # 单段配音获取失败：容错降级为该段静音，不中断整体合成
                logger.warning(
                    f"[compose-task] 分段 {seg.get('storyboard_id')} 配音获取失败，改用静音: {exc}"
                )
            finally:
                src.unlink(missing_ok=True)
        if not part.is_file():
            # 静音段补齐（anullsrc 源生成指定时长静音）
            await run_ffmpeg(
                ["-y", "-f", "lavfi", "-i", f"anullsrc=r={AUDIO_RATE}:cl=stereo",
                 "-t", f"{dur:.3f}", "-c:a", "libmp3lame", "-q:a", "4", str(part)],
                log_tag="compose-audio",
            )
        part_files.append(part)
        await progress_cb(55 + int(15 * (i + 1) / total))

    # 拼接音频分段
    audio_list = voice_dir / "audio_list.txt"
    audio_list.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in part_files), encoding="utf-8"
    )
    full_audio = voice_dir / "full_audio.mp3"
    await run_ffmpeg(
        ["-y", "-f", "concat", "-safe", "0", "-i", str(audio_list),
         "-c", "copy", str(full_audio)],
        log_tag="compose-audio",
    )
    return full_audio if full_audio.is_file() else None


def _build_subtitle_segments(
    boards: list[tuple[Storyboard, Path]],
    seg_durations: list[float],
) -> list[dict[str, Any]]:
    """从参与合成的分镜数据动态构建字幕分段（成片全局时间轴）。

    字幕文件缺失时的兜底数据源（跨任务胶水）：以分镜 dialogue 为字幕文本，
    时长优先取配音时长（storyboard.duration，TTS 任务回写的秒数），缺失时
    回退该段视频实际时长；起始时间按前面各有效分段的视频时长累计，保证与
    成片 concat 后的时间轴对齐。

    Args:
        boards: 参与合成的（分镜, 本地视频文件）配对列表，顺序与成片一致。
        seg_durations: 各分段视频实际时长（秒），与 boards 一一对应。

    Returns:
        list[dict[str, Any]]: 字幕分段列表，每项含 storyboard_id / text /
            start（成片全局秒）/ duration（秒）；台词全空时返回空列表。
    """
    segments: list[dict[str, Any]] = []
    cursor = 0.0  # 成片时间轴游标：前面各有效分段的视频时长累计
    for (sb, _file), seg_dur in zip(boards, seg_durations):
        seg_dur = float(seg_dur or 0)
        text = (sb.dialogue or "").strip()
        if text:
            # 字幕时长优先取配音时长（秒），缺失时回退分段视频实际时长
            duration = float(sb.duration or 0) or seg_dur
            segments.append(
                {
                    "storyboard_id": sb.id,
                    "text": text,
                    "start": round(cursor, 3),
                    "duration": round(max(duration, 0), 3),
                }
            )
        # 无台词分段不生成字幕，但仍消耗其画面时长（与全片字幕拼装逻辑一致）
        cursor += seg_dur
    return segments


def _ensure_subtitle_file(
    project_id: int,
    boards: list[tuple[Storyboard, Path]],
    seg_durations: list[float],
) -> bool:
    """确保分镜级字幕 JSON 存在：缺失时从分镜数据动态构建并写盘（胶水逻辑）。

    配音任务仅在 API 层按 dialogue + duration 动态拼装字幕、不落盘字幕
    文件，而合成阶段只读 static/subtitles/{project_id}.json，导致字幕永远
    不烧录；此处在合成侧兜底生成该文件，使既有烧录逻辑自然生效。

    Args:
        project_id: 项目 ID。
        boards: 参与合成的（分镜, 本地视频文件）配对列表。
        seg_durations: 各分段视频实际时长（秒），与 boards 一一对应。

    Returns:
        bool: 字幕文件已存在或本次成功生成时返回 True；台词全空或写盘
            失败时返回 False（调用方跳过烧录）。
    """
    sub_json = STATIC_ROOT / SUBTITLE_JSON_TEMPLATE.format(project_id=project_id)
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
        logger.info(
            f"[compose-task] 字幕文件缺失，已从分镜数据动态生成 "
            f"project_id={project_id}, segments={len(segments)}"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[compose-task] 字幕文件生成失败，跳过烧录: {exc}")
        return False


async def compose_video(ctx: dict[str, Any], task_id: int, storyboard_ids: Optional[list[int]] = None) -> dict[str, Any]:
    """执行视频合成任务。

    收集项目（或指定分镜）的视频片段，经统一规格、拼接、混音、烧录字幕后
    产出成片并回写任务结果。

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
        # 异常分支中引用的变量预定义，避免 NameError
        storyboards: list[Storyboard] = []
        is_partial = False
        try:
            # ---- 0. 前置检查：FFmpeg 可用性与参数解析 ----
            try:
                await run_ffmpeg(["-version"], log_tag="compose-check")
            except FFmpegNotFoundError:
                # FFmpeg 缺失属于环境问题，重试无意义：直接置 DEAD 并给出明确错误信息
                task.status = TaskStatus.DEAD
                task.error_message = (
                    "未检测到 FFmpeg，无法合成视频：请设置 FFMPEG_PATH 环境变量、"
                    "将 ffmpeg 加入 PATH，或将 ffmpeg.exe 放入项目 tools/ 目录"
                )[:500]
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                logger.error(f"[compose-task] 未检测到 FFmpeg task_id={task_id}")
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
                logger.warning(f"[compose-task] 无可用分镜视频 task_id={task_id}")
                return {"task_id": task_id, "status": "failed", "error": "没有可合成的视频素材"}

            project = await session.get(Project, task.project_id)
            bgm_url = (project.config or {}).get("bgm_url") if project else None

            # ---- 2. 下载 / 复制视频片段到临时目录（成功与否与分镜对象保持配对） ----
            with TemporaryDirectory(prefix="compose_") as tmp:
                work_dir = Path(tmp)
                board_file_pairs: list[tuple[Storyboard, Path]] = []
                total = len(video_boards)
                for i, sb in enumerate(video_boards):
                    dest = work_dir / f"src_{i:04d}.mp4"
                    try:
                        await fetch_url_to_file(sb.video_url, dest)
                        board_file_pairs.append((sb, dest))
                    except Exception as exc:  # noqa: BLE001
                        # 单段素材获取失败：跳过该段继续合成（容错）
                        logger.warning(
                            f"[compose-task] 分镜 {sb.id} 视频获取失败，跳过: {exc}"
                        )
                    await _publish_task_status(
                        task.project_id, task_id, TaskStatus.RUNNING.value,
                        10 + int(20 * (i + 1) / total),
                    )

                if not board_file_pairs:
                    raise RuntimeError("所有分镜视频片段均获取失败，无法合成")
                seg_files = [p for _, p in board_file_pairs]

                # ---- 3. 规格统一：以首段分辨率为基准，分辨率不一致的段落转码 ----
                await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 32)
                base_info = await probe_media(seg_files[0])
                target_w = max(2, (base_info["width"] or 640) // 2 * 2)
                target_h = max(2, (base_info["height"] or 360) // 2 * 2)
                target_fps = base_info["fps"] or DEFAULT_FPS

                std_files: list[Path] = []
                seg_durations: list[float] = []
                for i, src in enumerate(seg_files):
                    info = await probe_media(src)
                    dst = work_dir / f"seg_{i:04d}.mp4"
                    if (info["width"], info["height"]) != (target_w, target_h):
                        # 分辨率不一致：统一缩放到目标规格并去掉原始音轨，
                        # 保证 concat demuxer 流参数一致（配音由 TTS 轨负责）
                        await run_ffmpeg(
                            ["-y", "-i", str(src),
                             "-vf", f"scale={target_w}:{target_h},setsar=1",
                             "-r", f"{target_fps:.6f}",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                             "-pix_fmt", "yuv420p", "-an", str(dst)],
                            log_tag="compose-normalize",
                        )
                    else:
                        # 规格一致：直接复制，避免重复转码
                        dst.write_bytes(src.read_bytes())
                    std_files.append(dst)
                    # 探测时长失败时回退到分镜预计时长（仅用于配音对齐）
                    fallback_dur = float(board_file_pairs[i][0].duration or 0)
                    seg_durations.append(info["duration"] or fallback_dur)

                # ---- 4. concat demuxer 拼接（转场/xfade 为简化取舍未实现） ----
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

                # ---- 5. 配音轨：逐段混入 TTS（无配音段静音补齐） ----
                audio_segments = [
                    {
                        "index": i,
                        "storyboard_id": board_file_pairs[i][0].id,
                        "duration": seg_durations[i] or 0.0,
                        "audio_url": board_file_pairs[i][0].audio_url,
                    }
                    for i in range(len(std_files))
                    if (seg_durations[i] or 0.0) > 0
                ]

                async def _progress(p: int) -> None:
                    """进度回调：广播音频处理阶段进度。

                    Args:
                        p: 进度百分比。

                    Returns:
                        None
                    """
                    await _publish_task_status(
                        task.project_id, task_id, TaskStatus.RUNNING.value, min(p, 72)
                    )

                full_audio = await _prepare_audio_track(audio_segments, work_dir, _progress)

                # ---- 5.5 字幕兜底：字幕 JSON 缺失时从分镜数据动态生成（跨任务胶水） ----
                # 仅全片合成时落盘（局部成片时间轴与全片字幕文件不一致，
                # 落盘会污染全片字幕数据）；生成后步骤 7 的烧录逻辑自然生效
                if not is_partial:
                    _ensure_subtitle_file(task.project_id, board_file_pairs, seg_durations)

                # ---- 6. BGM 下载（可选，来自项目配置 bgm_url） ----
                bgm_file: Optional[Path] = None
                if bgm_url:
                    bgm_file = work_dir / "bgm.bin"
                    try:
                        await fetch_url_to_file(bgm_url, bgm_file)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[compose-task] BGM 获取失败，忽略: {exc}")
                        bgm_file = None

                # ---- 7. 字幕：字幕 JSON 存在则生成 SRT（契约见 build_srt / 报告） ----
                sub_srt: Optional[Path] = None
                sub_json = STATIC_ROOT / SUBTITLE_JSON_TEMPLATE.format(project_id=task.project_id)
                if sub_json.is_file():
                    try:
                        data = json.loads(sub_json.read_text(encoding="utf-8"))
                        srt_content = build_srt(data.get("segments") or [])
                        if srt_content:
                            sub_srt = work_dir / "sub.srt"
                            sub_srt.write_text(srt_content, encoding="utf-8")
                            logger.info(
                                f"[compose-task] 已加载字幕 project_id={task.project_id}, "
                                f"segments={len(data.get('segments') or [])}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"[compose-task] 字幕数据解析失败，跳过烧录: {exc}")

                # ---- 8. 最终混流：视频 + 配音 + BGM（可选） + 字幕烧录（可选） ----
                await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 78)
                out_dir = STATIC_ROOT / OUTPUT_DIR_TEMPLATE.format(project_id=task.project_id)
                out_dir.mkdir(parents=True, exist_ok=True)
                ts = int(datetime.now().timestamp())
                prefix = "preview" if is_partial else "final"
                out_file = out_dir / f"{prefix}_{ts}.mp4"

                has_voice = full_audio is not None
                has_bgm = bgm_file is not None
                inputs = ["-i", str(silent_video)]
                if has_voice:
                    inputs += ["-i", str(full_audio)]
                if has_bgm:
                    # BGM 循环播放，后续以 -shortest 截断到主轨长度
                    inputs += ["-stream_loop", "-1", "-i", str(bgm_file)]

                args = ["-y", *inputs]
                audio_maps = _build_audio_filter(has_voice, has_bgm)
                args += audio_maps
                if sub_srt is not None:
                    # 烧录字幕需重编码视频；工作目录为临时目录，此处用相对路径避免 Windows 盘符转义
                    args += ["-vf", "subtitles=sub.srt",
                             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                             "-pix_fmt", "yuv420p"]
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
                logger.error(
                    f"[compose-task] 任务耗尽重试 task_id={task_id}, "
                    f"latency={latency_ms}ms, error={exc}"
                )
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
        task.cost_points = 0  # 本地 FFmpeg 合成不消耗 AI 点数
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.DONE.value, 100)

        latency_ms = int((time.time() - start_time) * 1000)
        # 记录 agent_events（合成耗时）
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

        logger.info(
            f"[compose-task] 合成成功 task_id={task_id}, segments={len(board_file_pairs)}, "
            f"partial={is_partial}, url={final_url}, latency={latency_ms}ms"
        )
        return {"task_id": task_id, "status": "done", "url": final_url}
