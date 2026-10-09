"""
FFmpeg 工具模块。

提供 FFmpeg / FFprobe 可执行文件的解析（FFMPEG_PATH 环境变量 → PATH → 项目 tools/ 目录）、
异步命令执行、媒体信息探测、素材 URL 到本地文件的映射下载，以及 SRT 字幕文件生成等能力，
供合成任务（compose_tasks）与导出端点复用。
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import httpx

from app.core.logging import get_logger
from app.providers.storage import STATIC_ROOT

logger = get_logger()

# 项目根目录：本文件位于 services/api/app/utils/ 下，向上四级即为项目根
PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

# 项目内置 FFmpeg 工具目录（可放置 ffmpeg.exe / ffprobe.exe）
TOOLS_DIR: Path = PROJECT_ROOT / "tools"

# 子进程执行默认超时（秒）
DEFAULT_FFMPEG_TIMEOUT = 900


class FFmpegNotFoundError(RuntimeError):
    """未检测到 FFmpeg / FFprobe 可执行文件时抛出的异常。

    提示信息中包含完整的排查路径（环境变量 / PATH / 项目 tools 目录）。
    """


def _resolve_binary(env_key: str, binary_name: str) -> Optional[Path]:
    """按优先级解析可执行文件路径。

    解析顺序：环境变量 → 系统 PATH → 项目 tools/ 目录。

    Args:
        env_key: 环境变量名（如 FFMPEG_PATH / FFPROBE_PATH）。
        binary_name: 二进制文件名（如 ffmpeg.exe / ffmpeg）。

    Returns:
        Optional[Path]: 解析到的可执行文件路径；均未命中时返回 None。
    """
    # 1. 环境变量优先
    env_path = os.environ.get(env_key)
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return candidate
        # 环境变量也可能直接给目录
        candidate_in_dir = candidate / binary_name
        if candidate_in_dir.is_file():
            return candidate_in_dir

    # 2. 系统 PATH
    which = shutil.which(binary_name)
    if which:
        return Path(which)

    # 3. 项目 tools/ 目录（兼容 ffmpeg.exe 与 ffmpeg 两种命名）
    for name in (binary_name, Path(binary_name).stem + ".exe"):
        candidate = TOOLS_DIR / name
        if candidate.is_file():
            return candidate

    return None


def resolve_ffmpeg() -> Path:
    """解析 ffmpeg 可执行文件路径。

    Returns:
        Path: ffmpeg 可执行文件路径。

    Raises:
        FFmpegNotFoundError: 未检测到 FFmpeg 时抛出，提示信息包含排查指引。
    """
    path = _resolve_binary("FFMPEG_PATH", "ffmpeg")
    if path is None:
        raise FFmpegNotFoundError(
            "未检测到 FFmpeg：请设置环境变量 FFMPEG_PATH，或将 ffmpeg 加入系统 PATH，"
            f"或将 ffmpeg.exe 放入项目 tools/ 目录（{TOOLS_DIR}）"
        )
    return path


def resolve_ffprobe() -> Path:
    """解析 ffprobe 可执行文件路径。

    Returns:
        Path: ffprobe 可执行文件路径。

    Raises:
        FFmpegNotFoundError: 未检测到 FFprobe 时抛出。
    """
    path = _resolve_binary("FFPROBE_PATH", "ffprobe")
    if path is None:
        # 兜底：与 ffmpeg 同目录查找（静态构建通常成对出现）
        try:
            ffmpeg_path = resolve_ffmpeg()
            candidate = ffmpeg_path.parent / "ffprobe.exe"
            if candidate.is_file():
                return candidate
            candidate = ffmpeg_path.parent / "ffprobe"
            if candidate.is_file():
                return candidate
        except FFmpegNotFoundError:
            pass
        raise FFmpegNotFoundError(
            "未检测到 FFprobe：请设置环境变量 FFPROBE_PATH，或将 ffprobe 加入系统 PATH，"
            f"或将 ffprobe.exe 放入项目 tools/ 目录（{TOOLS_DIR}）"
        )
    return path


async def run_ffmpeg(
    args: list[str],
    cwd: Optional[Path] = None,
    timeout: int = DEFAULT_FFMPEG_TIMEOUT,
    log_tag: str = "ffmpeg",
) -> str:
    """异步执行 ffmpeg 命令。

    Args:
        args: ffmpeg 参数列表（不含可执行文件名本身）。
        cwd: 子进程工作目录（可选，字幕滤镜等使用相对路径时传入）。
        timeout: 超时秒数，默认 900。
        log_tag: 日志标签，便于区分调用场景。

    Returns:
        str: ffmpeg 的 stderr 输出（截断后），便于上层记录日志。

    Raises:
        FFmpegNotFoundError: 未检测到 FFmpeg 时抛出。
        RuntimeError: 命令执行失败（返回码非 0）或超时时抛出，附带 stderr 尾部信息。
    """
    ffmpeg_path = resolve_ffmpeg()
    cmd = [str(ffmpeg_path), "-hide_banner", "-loglevel", "error", *args]
    logger.info(f"[{log_tag}] 执行命令: {' '.join(cmd[:12])} ...")

    def _run() -> subprocess.CompletedProcess:
        """在线程池中同步执行子进程，避免阻塞事件循环。

        Returns:
            subprocess.CompletedProcess: 子进程执行结果。
        """
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg 执行超时（>{timeout}s）") from exc

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "")[-2000:]
        logger.error(f"[{log_tag}] 执行失败 code={proc.returncode}: {stderr_tail}")
        raise RuntimeError(f"ffmpeg 执行失败（code={proc.returncode}）: {stderr_tail}")

    return (proc.stderr or "")[-1000:]


async def probe_media(path: Path) -> dict[str, Any]:
    """探测媒体文件信息（分辨率 / 帧率 / 时长 / 是否含音频轨）。

    Args:
        path: 媒体文件本地路径。

    Returns:
        dict[str, Any]: 包含 width、height、fps、duration、has_audio 的字典；
            探测失败时各字段取默认值（width/height=0、fps=30、duration=0、has_audio=False）。
    """
    info: dict[str, Any] = {
        "width": 0,
        "height": 0,
        "fps": 30.0,
        "duration": 0.0,
        "has_audio": False,
    }
    try:
        ffprobe_path = resolve_ffprobe()
        cmd = [
            str(ffprobe_path),
            "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]

        def _run() -> subprocess.CompletedProcess:
            """在线程池中同步执行 ffprobe 子进程。

            Returns:
                subprocess.CompletedProcess: 子进程执行结果。
            """
            return subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )

        proc = await asyncio.to_thread(_run)
        if proc.returncode != 0:
            logger.warning(f"[ffmpeg] ffprobe 探测失败: {(proc.stderr or '')[-500:]}")
            return info

        data = json.loads(proc.stdout or "{}")
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and info["width"] == 0:
                info["width"] = int(stream.get("width") or 0)
                info["height"] = int(stream.get("height") or 0)
                # 帧率形如 "30/1"，解析为浮点数
                rate = str(stream.get("r_frame_rate") or "30/1")
                try:
                    num, _, den = rate.partition("/")
                    fps = float(num) / (float(den) if den else 1.0)
                    if fps > 0:
                        info["fps"] = fps
                except (ValueError, ZeroDivisionError):
                    pass
            elif stream.get("codec_type") == "audio":
                info["has_audio"] = True
        duration = data.get("format", {}).get("duration")
        if duration:
            info["duration"] = float(duration)
    except FFmpegNotFoundError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[ffmpeg] ffprobe 探测异常: {exc}")
    return info


async def fetch_url_to_file(url: str, dest: Path) -> Path:
    """将素材 URL 获取为本地文件。

    支持 /static/... 相对 URL（映射到后端静态目录直接复制）
    与 http(s):// 远程 URL（流式下载）。

    Args:
        url: 素材 URL（/static/... 或 http(s)://...）。
        dest: 目标本地文件路径。

    Returns:
        Path: 目标本地文件路径。

    Raises:
        FileNotFoundError: /static 映射的本地文件不存在时抛出。
        RuntimeError: 远程下载失败时抛出。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 本地静态文件：/static/<subdir>/<file> → STATIC_ROOT/<subdir>/<file>
    if url.startswith("/static/"):
        relative = url[len("/static/"):]
        local_path = (STATIC_ROOT / relative).resolve()
        # 防目录穿越：映射结果必须仍位于静态根目录内
        if not str(local_path).startswith(str(STATIC_ROOT.resolve())):
            raise FileNotFoundError(f"非法静态路径: {url}")
        if not local_path.is_file():
            raise FileNotFoundError(f"静态文件不存在: {local_path}")
        shutil.copyfile(local_path, dest)
        return dest

    # 远程 URL：流式下载
    if url.startswith("http://") or url.startswith("https://"):
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        f.write(chunk)
        return dest

    # 其他情况：尝试当作本地绝对/相对路径
    candidate = Path(url)
    if candidate.is_file():
        shutil.copyfile(candidate, dest)
        return candidate

    raise FileNotFoundError(f"无法识别的素材地址: {url}")


def _format_srt_time(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳。

    Args:
        seconds: 秒数（非负）。

    Returns:
        str: 形如 "HH:MM:SS,mmm" 的 SRT 时间戳字符串。
    """
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    # 毫秒进位保护
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def build_srt(segments: list[dict[str, Any]]) -> str:
    """根据字幕分段数据构建 SRT 字幕内容。

    Args:
        segments: 字幕分段列表，每段包含 text（文本）、start（成片全局起始秒）、
            duration（持续秒）字段；缺 start/duration 的分段将被跳过。

    Returns:
        str: 完整的 SRT 字幕文本；无有效分段时返回空字符串。
    """
    lines: list[str] = []
    index = 0
    for seg in segments:
        text = str(seg.get("text") or "").strip()
        start = seg.get("start")
        duration = seg.get("duration")
        if not text or start is None or duration is None:
            continue
        try:
            start_s = float(start)
            dur_s = float(duration)
        except (TypeError, ValueError):
            continue
        if dur_s <= 0:
            continue
        index += 1
        lines.append(str(index))
        lines.append(
            f"{_format_srt_time(start_s)} --> {_format_srt_time(start_s + dur_s)}"
        )
        # 支持多行字幕文本
        lines.extend(text.splitlines() or [text])
        lines.append("")
    return "\n".join(lines)
