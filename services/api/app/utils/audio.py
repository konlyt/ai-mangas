"""
音频元数据工具模块。

提供音频时长探测能力（VO-03）：
    - 优先使用 mutagen 从本地文件或内存字节流解析真实时长（支持 mp3 等常见格式）；
    - 解析失败（如依赖缺失、远端下载失败、格式无法识别）时，
      按中文字幕语速（约 4 字/秒）以文本字数估算时长兜底。
"""

import io
from pathlib import Path

import httpx

from app.core.logging import get_logger
from app.providers.storage import STATIC_ROOT

logger = get_logger()

# 远端音频下载超时（秒）：占位音频体积小，10s 足够
_AUDIO_DOWNLOAD_TIMEOUT = 10.0

# 估算语速：中文旁白约 4 字/秒
_CHARS_PER_SECOND = 4


def estimate_duration_by_text(text: str) -> float:
    """按文本字数估算配音时长（语速约 4 字/秒）。

    Args:
        text: 台词 / 旁白文本。

    Returns:
        float: 估算时长（秒），最少 1 秒。

    Raises:
        TypeError: 当 text 非 str 时抛出。
    """
    char_count = len((text or "").strip())
    return float(max(1, char_count // _CHARS_PER_SECOND))


def _probe_duration_bytes(data: bytes) -> float | None:
    """从音频字节流解析真实时长。

    Args:
        data: 音频二进制内容（mp3 等常见格式）。

    Returns:
        float | None: 时长（秒）；解析失败时返回 None。

    Raises:
        Exception: mutagen 内部解析异常由本函数捕获并返回 None，不向外抛出。
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(io.BytesIO(data))
        if audio is not None and audio.info is not None and audio.info.length:
            return float(audio.info.length)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[audio-utils] mutagen 解析字节流时长失败: {exc}")
    return None


def _probe_duration_file(path: Path) -> float | None:
    """从本地音频文件解析真实时长。

    Args:
        path: 本地音频文件路径（如 static/audio/xxx.mp3）。

    Returns:
        float | None: 时长（秒）；文件不存在或解析失败时返回 None。

    Raises:
        Exception: mutagen 内部解析异常由本函数捕获并返回 None，不向外抛出。
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
        if audio is not None and audio.info is not None and audio.info.length:
            return float(audio.info.length)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[audio-utils] mutagen 解析本地文件时长失败 path={path}: {exc}")
    return None


def _static_url_to_path(audio_url: str) -> Path | None:
    """将 /static/... 相对 URL 映射为本地静态目录文件路径。

    Args:
        audio_url: 音频访问 URL。

    Returns:
        Path | None: 对应本地文件路径；非 /static/ 前缀或路径越界时返回 None。
    """
    prefix = "/static/"
    if not audio_url.startswith(prefix):
        return None
    # 去掉前缀并清理相对路径，防止目录穿越
    rel = audio_url[len(prefix):].lstrip("/")
    if ".." in rel.replace("\\", "/").split("/"):
        return None
    return STATIC_ROOT / rel


async def get_audio_duration(audio_url: str, text: str) -> float:
    """获取音频时长：优先 mutagen 解析真实时长，失败按字数估算。

    处理顺序：
        1. /static/ 前缀 URL → 读取本地文件用 mutagen 解析；
        2. 其他 URL（远端 mock 占位音频等）→ 下载字节流后 mutagen 解析；
        3. 任一步骤失败 → 按 4 字/秒以台词字数估算。

    Args:
        audio_url: 音频访问 URL（本地静态 URL 或远端 URL）。
        text: 对应台词文本（估算兜底用）。

    Returns:
        float: 音频时长（秒），恒为正数。

    Raises:
        Exception: 网络下载等异常均被内部捕获降级为估算，不向外抛出。
    """
    # 1) 本地静态产物：直接读文件解析
    local_path = _static_url_to_path(audio_url or "")
    if local_path is not None:
        duration = _probe_duration_file(local_path)
        if duration:
            return duration
        return estimate_duration_by_text(text)

    # 2) 远端 URL：下载字节流后解析（mock 占位音频 / 外链音频）
    if (audio_url or "").lower().startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=_AUDIO_DOWNLOAD_TIMEOUT) as client:
                resp = await client.get(audio_url)
            if resp.status_code == 200 and resp.content:
                duration = _probe_duration_bytes(resp.content)
                if duration:
                    return duration
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[audio-utils] 下载音频探测时长失败 url={audio_url}: {exc}")

    # 3) 兜底：按字数估算
    return estimate_duration_by_text(text)
