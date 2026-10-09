"""
语音合成任务（ARQ Worker）。

从 tasks 表取出 tts 类型任务，调用 TTS Provider（默认 agnes，失败自动
降级 mock）合成语音，将音频产物保存到本地静态目录，探测时长元数据并
生成分镜级 SRT 字幕段，回写 result_url、storyboard.audio_url、
storyboard.duration 与 status。
"""

import time
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import AgentEvent, Character, Storyboard, Task, TaskStatus
from app.providers.storage import save_artifact
from app.providers.tts.registry import get_tts_registry
from app.utils.audio import get_audio_duration
from app.utils.srt import generate_srt

logger = get_logger()

# 远端音频下载落盘超时（秒）
_ARTIFACT_DOWNLOAD_TIMEOUT = 30.0


def _get_tts_provider(name: str | None = None):
    """获取语音合成 Provider 实例（兼容 registry 接口）。

    Args:
        name: Provider 名称。

    Returns:
        TTSProvider: 语音合成 Provider 实例。
    """
    try:
        from app.providers.tts.registry import get_tts_provider  # type: ignore

        return get_tts_provider(name)
    except Exception:
        return get_tts_registry().get_provider(name)


async def _publish_task_status(project_id: int, task_id: int, status: str, progress: int = 0, extra: dict | None = None):
    """广播任务状态变更。

    Args:
        project_id: 项目 ID。
        task_id: 任务 ID。
        status: 状态字符串。
        progress: 进度百分比。
        extra: 附加字段（如 degraded 标记），合并进广播消息。

    Returns:
        None
    """
    try:
        from app.domains.tasks import get_redis

        if extra:
            import json

            message: dict[str, Any] = {
                "task_id": task_id,
                "status": status,
                "progress": progress,
            }
            message.update(extra)
            r = get_redis()
            await r.publish(f"task:{project_id}", json.dumps(message, ensure_ascii=False))
        else:
            from app.domains.tasks import publish_task_status

            await publish_task_status(project_id, task_id, status, progress)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tts-task] 广播状态失败 task_id={task_id}: {exc}")


def _resolve_voice_from_idempotency_key(idempotency_key: str | None) -> str | None:
    """从任务幂等键解析提交时指定的音色 ID。

    提交侧（generate_voices）将请求中的 voice_id 追加在 tts 幂等键尾部，
    格式为 "{project_id}-{storyboard_id}-tts-{voice_id}"。

    Args:
        idempotency_key: 任务幂等键。

    Returns:
        str | None: 音色 ID；未编码音色（键尾为空或无分隔符）时返回 None。
    """
    if not idempotency_key or "-tts-" not in idempotency_key:
        return None
    voice = idempotency_key.split("-tts-", 1)[1].strip()
    return voice or None


async def _resolve_character_voice(session: AsyncSession, storyboard: Storyboard | None) -> str | None:
    """从分镜关联角色的音色绑定中解析音色 ID。

    Args:
        session: 异步数据库会话。
        storyboard: 分镜对象（可含 character_ids JSON 列表）。

    Returns:
        str | None: 第一个绑定了 voice_id 的角色音色；无绑定时返回 None。

    Raises:
        Exception: 数据库查询异常向上透传，由调用方捕获后回退默认音色。
    """
    if storyboard is None or not storyboard.character_ids:
        return None
    try:
        for cid in storyboard.character_ids:
            if not cid:
                continue
            character = await session.get(Character, int(cid))
            if character and character.voice_id:
                return character.voice_id
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tts-task] 解析角色音色失败 storyboard_id={storyboard.id}: {exc}")
    return None


async def _ensure_local_artifact(audio_url: str) -> str:
    """确保音频产物保存到本地静态目录并返回本地 URL。

    - /static/ 前缀 URL：已是本地产物（agnes 真实路径落盘），直接返回；
    - 远端 URL（如 mock 占位音频）：下载二进制后经 save_artifact 落盘；
    - 下载失败：保留原 URL，由时长探测与字幕逻辑降级估算。

    Args:
        audio_url: Provider 返回的音频 URL。

    Returns:
        str: 本地静态 URL（/static/audio/...）或下载失败时的原 URL。

    Raises:
        Exception: 网络下载等异常均被内部捕获并保留原 URL，不向外抛出。
    """
    if (audio_url or "").startswith("/static/"):
        return audio_url

    if not (audio_url or "").lower().startswith(("http://", "https://")):
        return audio_url

    try:
        async with httpx.AsyncClient(timeout=_ARTIFACT_DOWNLOAD_TIMEOUT) as client:
            resp = await client.get(audio_url)
        if resp.status_code == 200 and resp.content:
            local_url = save_artifact(resp.content, "audio", "mp3")
            logger.info(f"[tts-task] 音频产物已落盘 {audio_url} -> {local_url}")
            return local_url
        logger.warning(
            f"[tts-task] 下载音频产物失败 status={resp.status_code}, 保留原 URL: {audio_url}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tts-task] 下载音频产物异常，保留原 URL {audio_url}: {exc}")

    return audio_url


def _normalize_voice_id(provider: Any, voice_id: str | None) -> str:
    """将解析出的音色 ID 规范化为当前 Provider 可用的值。

    mock Provider 使用 "default"；agnes Provider 在网关就绪后使用
    OpenAI 风格音色，"default"/空值回退为 "alloy"；
    通义千问 Provider 回退为 "longxiaochun"。

    Args:
        provider: 语音合成 Provider 实例。

    Returns:
        str: 规范化后的音色 ID。

    Raises:
        Exception: Provider 类型判断异常由内部捕获，返回默认值。
    """
    try:
        from app.providers.tts.agnes import AgnesTTSProvider
        from app.providers.tts.qianwen import QianwenTTSProvider

        if isinstance(provider, AgnesTTSProvider):
            return voice_id if voice_id and voice_id != "default" else "alloy"
        if isinstance(provider, QianwenTTSProvider):
            return voice_id if voice_id and voice_id != "default" else "longxiaochun"
    except Exception:  # noqa: BLE001
        pass
    return voice_id or "default"


async def generate_tts(ctx: dict[str, Any], task_id: int, voice_id: str | None = None) -> dict[str, Any]:
    """执行语音合成任务。

    从分镜获取对白文本，解析音色（优先级：ARQ 参数 voice_id > 幂等键编码 >
    角色绑定音色 > 默认音色），调用 tts provider（默认 agnes，失败自动降级
    mock）合成语音，产物落盘本地后探测时长，回写音频 URL 到
    storyboard.audio_url、实际配音时长到 storyboard.duration 与
    task.result_url，并生成分镜级 SRT 字幕段。

    Args:
        ctx: ARQ 任务上下文。
        task_id: 任务 ID。
        voice_id: 音色 ID（ARQ 投递时可经 kwargs 传入，优先级最高）。

    Returns:
        dict: 包含 task_id、status、url、voice_id、duration_seconds、
            segments（分镜级字幕段）与 srt（单镜 SRT 文本）的结果字典。

    Raises:
        Exception: 当重试次数未耗尽时抛出，触发 ARQ 重试。
    """
    async with AsyncSessionLocal() as session:
        task = await session.get(Task, task_id)
        if task is None:
            logger.error(f"[tts-task] 任务不存在 task_id={task_id}")
            return {"task_id": task_id, "status": "not_found"}

        if task.status == TaskStatus.DONE:
            return {"task_id": task_id, "status": "done"}

        # 查询关联分镜获取对白
        storyboard = None
        if task.storyboard_id:
            storyboard = await session.get(Storyboard, task.storyboard_id)

        text = (
            storyboard.dialogue
            if storyboard and storyboard.dialogue
            else ""
        )
        if not text:
            task.status = TaskStatus.DONE
            task.error_message = "无对白内容，跳过合成"
            await session.commit()
            return {"task_id": task_id, "status": "skipped"}

        # 音色解析优先级：ARQ 参数 > 幂等键编码 > 角色绑定 > 默认音色
        resolved_voice = (
            voice_id
            or _resolve_voice_from_idempotency_key(task.idempotency_key)
            or await _resolve_character_voice(session, storyboard)
        )
        provider = _get_tts_provider()
        resolved_voice = _normalize_voice_id(provider, resolved_voice)

        task.status = TaskStatus.RUNNING
        await session.commit()
        await _publish_task_status(task.project_id, task_id, TaskStatus.RUNNING.value, 10)

        start_time = time.time()
        try:
            audio_url = await provider.synthesize(text, resolved_voice)

            # 产物本地化：远端 URL 下载落盘，保证本地产物可被时长探测与合成阶段使用
            local_url = await _ensure_local_artifact(audio_url)

            # 时长元数据：mutagen 解析真实时长，失败按字数估算
            duration_seconds = await get_audio_duration(local_url, text)

            # 检查是否发生了降级（mock 兜底），降级结果不计费并显式标记
            is_degraded = getattr(provider, "last_degraded", False)
            task.result_url = local_url
            task.status = TaskStatus.DONE
            task.cost_points = 0 if is_degraded else 1
            if is_degraded:
                task.error_message = "降级生成(mock)：真实 TTS 暂不可用"
            else:
                task.error_message = None
            if storyboard:
                storyboard.audio_url = local_url
                # 注意：不覆盖 storyboard.duration（预估时长），
                # 实际配音时长从音频文件动态探测，保留预估时长用于规划展示

            await session.commit()
            extra_fields = {"degraded": True} if is_degraded else None
            await _publish_task_status(task.project_id, task_id, TaskStatus.DONE.value, 100, extra=extra_fields)

            latency_ms = int((time.time() - start_time) * 1000)
            # 记录 agent_events（provider 调用耗时与点数）
            event = AgentEvent(
                graph_run_id=task.graph_run_id or "",
                project_id=task.project_id,
                node_name="tts_provider",
                latency_ms=latency_ms,
                cost_points=task.cost_points,
                input_digest=f"voice={resolved_voice}; {text[:200]}",
                output_digest=local_url,
            )
            session.add(event)
            await session.commit()

            # 分镜级字幕段（VO-05）：全片字幕由 /projects/{id}/subtitles 按
            # storyboard.dialogue + duration 动态拼装，此处随任务结果输出单镜数据
            segments = [
                {
                    "sequence": storyboard.sequence if storyboard else None,
                    "text": text,
                    "start": 0.0,
                    "duration": round(duration_seconds, 3),
                }
            ]
            logger.info(
                f"[tts-task] 合成成功 task_id={task_id}, voice={resolved_voice}, "
                f"duration={duration_seconds:.2f}s, latency={latency_ms}ms, url={local_url}"
            )
            return {
                "task_id": task_id,
                "status": "done",
                "url": local_url,
                "voice_id": resolved_voice,
                "duration_seconds": round(duration_seconds, 3),
                "segments": segments,
                "srt": generate_srt(segments),
            }

        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start_time) * 1000)
            task.retry_count = (task.retry_count or 0) + 1
            task.error_message = str(exc)[:500]

            if task.retry_count >= (task.max_retry or 3):
                task.status = TaskStatus.DEAD
                await session.commit()
                await _publish_task_status(task.project_id, task_id, TaskStatus.DEAD.value)
                logger.error(
                    f"[tts-task] 任务耗尽重试 task_id={task_id}, "
                    f"latency={latency_ms}ms, error={exc}"
                )
                return {"task_id": task_id, "status": "dead", "error": str(exc)}

            task.status = TaskStatus.FAILED
            await session.commit()
            await _publish_task_status(task.project_id, task_id, TaskStatus.FAILED.value)
            logger.warning(
                f"[tts-task] 合成失败，将重试 task_id={task_id}, "
                f"retry={task.retry_count}, error={exc}"
            )
            raise
