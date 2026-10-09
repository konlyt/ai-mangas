"""
SRT 字幕工具与音频时长工具冒烟测试。

覆盖点：
    1. format_timestamp：标准 HH:MM:SS,mmm 格式、毫秒进位、负数按 0 处理；
    2. generate_srt：分块拼装格式、空文本/纯空白分段跳过且不占序号、
       空分段列表返回空字符串；
    3. estimate_duration_by_text：按 4 字/秒估算、最少 1 秒；
    4. get_audio_duration：非静态/非 HTTP 的 URL 直接走估算兜底；
       远端下载失败（不可达地址）同样降级为估算路径。
"""

from app.utils.audio import estimate_duration_by_text, get_audio_duration
from app.utils.srt import format_timestamp, generate_srt


def test_format_timestamp_basic():
    """时间戳格式：秒/分/时进位与毫秒三位补零。

    Returns:
        None
    """
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(59.999) == "00:00:59,999"
    assert format_timestamp(60) == "00:01:00,000"
    assert format_timestamp(3661.5) == "01:01:01,500"
    # 小数毫秒四舍五入：65.1234s → 65123ms
    assert format_timestamp(65.1234) == "00:01:05,123"


def test_format_timestamp_negative_clamped_to_zero():
    """负数时间按 0 处理，不产生非法时间轴。

    Returns:
        None
    """
    assert format_timestamp(-3) == "00:00:00,000"
    assert format_timestamp(-0.001) == "00:00:00,000"


def test_generate_srt_blocks_and_skip_empty():
    """SRT 拼装：序号连续、时间轴正确；空文本/纯空白分段被跳过且不占序号。

    Returns:
        None
    """
    srt = generate_srt(
        [
            {"text": "你好", "start": 0, "duration": 2},
            {"text": "", "start": 2, "duration": 1},  # 空文本 → 跳过
            {"text": "   ", "start": 3, "duration": 1},  # 纯空白 → 跳过
            {"text": "世界", "start": 3, "duration": 3},
        ]
    )
    # 两个有效块：序号 1、2（空段不占序号）
    assert "1\n00:00:00,000 --> 00:00:02,000\n你好" in srt
    assert "2\n00:00:03,000 --> 00:00:06,000\n世界" in srt
    # 空段的时间轴不应出现
    assert "00:00:02,000 --> 00:00:03,000" not in srt
    # 块间以空行分隔、结尾换行
    assert srt.count("\n\n") == 1
    assert srt.endswith("\n")


def test_generate_srt_empty_segments():
    """空分段列表 / 全空文本分段 → 返回空字符串。

    Returns:
        None
    """
    assert generate_srt([]) == ""
    assert generate_srt([{"text": ""}, {"text": "  "}]) == ""


def test_estimate_duration_by_text():
    """字数估算：4 字/秒，最少 1 秒。

    Returns:
        None
    """
    assert estimate_duration_by_text("一二三四五六七八") == 2.0  # 8 字 / 4
    assert estimate_duration_by_text("一二三四五六七") == 1.0  # 7 字 // 4 = 1
    assert estimate_duration_by_text("") == 1.0  # 空文本 → 最少 1 秒
    assert estimate_duration_by_text("abc") == 1.0  # 3 字 → 0 → 兜底 1 秒


async def test_get_audio_duration_fallback_estimate():
    """时长兜底路径：无法从本地/远端解析时按字数估算。

    覆盖两类入参：
        1. 非 /static/ 且非 http(s) 协议的 URL → 不发起任何请求，直接估算；
        2. 远端 http URL 不可达（127.0.0.1:9 拒绝连接）→ 下载失败后估算。

    Returns:
        None
    """
    # 8 个字 → 估算 2.0 秒
    assert await get_audio_duration("ftp://example.com/a.mp3", "一二三四五六七八") == 2.0
    assert await get_audio_duration("http://127.0.0.1:9/a.mp3", "一二三四五六七八") == 2.0
    # 空文本兜底最少 1 秒
    assert await get_audio_duration("ftp://example.com/a.mp3", "") == 1.0
