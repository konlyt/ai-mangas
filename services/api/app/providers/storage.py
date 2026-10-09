"""
Provider 产物本地存储模块。

为 Agnes 图像/TTS Provider 提供二进制产物（图片、音频）落盘能力：
保存到后端静态目录 services/api/static/<subdir>/ 下，
并返回可由 FastAPI StaticFiles 直接对外服务的 /static/... 相对 URL。
"""

import time
import uuid
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger()

# 后端静态根目录：services/api/static（本文件位于 services/api/app/providers/ 下，向上三级）
STATIC_ROOT: Path = Path(__file__).resolve().parents[2] / "static"
# 模块加载时即创建，保证 FastAPI StaticFiles 挂载时目录已存在
STATIC_ROOT.mkdir(parents=True, exist_ok=True)


def save_artifact(data: bytes, subdir: str, ext: str) -> str:
    """将二进制产物保存到静态目录并返回其访问 URL。

    Args:
        data: 二进制文件内容（如图片、音频字节流）。
        subdir: 静态目录下的子目录名（如 "images"、"audio"）。
        ext: 文件扩展名（不含点，如 "png"、"mp3"）。

    Returns:
        str: 形如 /static/<subdir>/<filename> 的相对访问 URL。

    Raises:
        OSError: 当文件写入失败时抛出，由调用方捕获后降级。
    """
    # 确保子目录存在（含 static 根目录）
    target_dir = STATIC_ROOT / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：时间戳 + 短 uuid，保证唯一且便于排查
    filename = f"{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
    file_path = target_dir / filename
    file_path.write_bytes(data)
    logger.info(f"[storage] 产物已保存 path={file_path}, size={len(data)} bytes")

    return f"/static/{subdir}/{filename}"
