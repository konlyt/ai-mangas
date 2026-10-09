"""
SRT 字幕生成工具模块。

提供标准 SRT（SubRip）字幕格式的时间戳格式化与字幕文本拼装能力，
供 TTS 任务（VO-05）与字幕查询端点使用：
    - 时间戳格式为 HH:MM:SS,mmm（毫秒用逗号分隔，兼容播放器解析）。
    - 每条字幕块由「序号 + 起止时间轴 + 字幕文本」构成，块间以空行分隔。
"""

from typing import Any


def format_timestamp(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳字符串。

    Args:
        seconds: 秒数（可为小数，负数按 0 处理）。

    Returns:
        str: 形如 "HH:MM:SS,mmm" 的 SRT 时间戳字符串。

    Raises:
        TypeError: 当 seconds 无法转换为数值时抛出。
    """
    # 负数时间按 0 处理，避免生成非法时间轴
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: list[dict[str, Any]]) -> str:
    """将字幕分段列表拼装为标准 SRT 字幕文本。

    Args:
        segments: 字幕分段列表，每个分段为 dict，包含：
            - text: 字幕文本（str，必填）；
            - start: 起始秒数（float，默认 0）；
            - duration: 持续秒数（float，默认 0，结束时间 = start + duration）。
            缺失字段按默认值处理，空文本的分段将被跳过。

    Returns:
        str: 标准 SRT 格式字幕文本（以换行结尾）；分段为空时返回空字符串。

    Raises:
        TypeError: 当 start/duration 无法转换为数值时抛出。
    """
    blocks: list[str] = []
    index = 0

    for seg in segments:
        text = str(seg.get("text") or "").strip()
        if not text:
            # 空文本分段直接跳过，不占用序号
            continue
        index += 1
        start = float(seg.get("start") or 0)
        duration = float(seg.get("duration") or 0)
        end = start + duration

        block = (
            f"{index}\n"
            f"{format_timestamp(start)} --> {format_timestamp(end)}\n"
            f"{text}"
        )
        blocks.append(block)

    # SRT 规范：字幕块之间以空行分隔
    return "\n\n".join(blocks) + ("\n" if blocks else "")
