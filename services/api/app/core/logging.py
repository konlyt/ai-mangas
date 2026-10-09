"""
日志模块。

基于 loguru 配置结构化日志，支持 trace_id 链路追踪，
同时输出到控制台与 logs/app.log 文件。
"""

import sys
import uuid
from pathlib import Path

from loguru import logger

# 日志目录
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"


def _trace_id_filter(record: dict) -> bool:
    """为每条日志补充 trace_id（若不存在则生成）。

    Args:
        record: loguru 日志记录字典。

    Returns:
        bool: 始终返回 True 以保留该记录。
    """
    if "trace_id" not in record["extra"]:
        record["extra"]["trace_id"] = uuid.uuid4().hex[:16]
    return True


# 移除默认处理器
logger.remove()

# 控制台输出
logger.add(
    sys.stdout,
    level="INFO",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<magenta>{extra[trace_id]}</magenta> - <level>{message}</level>"
    ),
    filter=_trace_id_filter,
)

# 文件输出（按大小轮转，保留 14 天）
logger.add(
    LOG_FILE,
    level="INFO",
    rotation="20 MB",
    retention="14 days",
    encoding="utf-8",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
        "{name}:{function}:{line} | {extra[trace_id]} - {message}"
    ),
    filter=_trace_id_filter,
)


def get_logger():
    """返回配置好的 loguru logger。

    Returns:
        logger: loguru 日志实例。
    """
    return logger
