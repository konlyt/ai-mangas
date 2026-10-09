"""
配音（TTS）领域服务。

提供内置音色库映射表（VO-02）与项目级 SRT 字幕拼装（VO-05）：
    - 音色库为静态常量，覆盖 mock 与 agnes 两个 Provider 的可用音色；
    - 字幕拼装基于分镜表已有的 dialogue（台词）与 duration（配音时长秒）字段，
      按镜头顺序累计时间轴并生成标准 SRT 文本，无需额外存储字段。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BizException, ErrorCode
from app.models import Project, Storyboard
from app.utils.srt import generate_srt

# ============================================================
# 内置音色库映射表（VO-02，静态常量，无需建表）
# ============================================================

# mock Provider：单一占位音色（合成时忽略音色参数）
_MOCK_VOICES: list[dict[str, Any]] = [
    {
        "voice_id": "default",
        "name": "默认音色",
        "gender": "neutral",
        "style": "占位",
        "provider": "mock",
    },
]

# agnes Provider：OpenAI TTS 风格预置音色映射（网关 /audio/speech 就绪后生效；
# 当前网关暂不支持 TTS，实际合成会自动降级 mock，音色仅作预留选择项）
_AGNES_VOICES: list[dict[str, Any]] = [
    {
        "voice_id": "alloy",
        "name": "中性声线",
        "gender": "neutral",
        "style": "沉稳通用",
        "provider": "agnes",
    },
    {
        "voice_id": "echo",
        "name": "沉稳男声",
        "gender": "male",
        "style": "低沉磁性",
        "provider": "agnes",
    },
    {
        "voice_id": "fable",
        "name": "叙述男声",
        "gender": "male",
        "style": "故事旁白",
        "provider": "agnes",
    },
    {
        "voice_id": "onyx",
        "name": "浑厚男声",
        "gender": "male",
        "style": "庄重有力",
        "provider": "agnes",
    },
    {
        "voice_id": "nova",
        "name": "活力女声",
        "gender": "female",
        "style": "清亮明快",
        "provider": "agnes",
    },
    {
        "voice_id": "shimmer",
        "name": "温柔女声",
        "gender": "female",
        "style": "柔和亲切",
        "provider": "agnes",
    },
]

# 完整音色库：mock + agnes 全量映射
TTS_VOICES: list[dict[str, Any]] = _MOCK_VOICES + _AGNES_VOICES

# agnes 默认音色（请求未指定或指定 mock 的 default 时回退到该值）
AGNES_DEFAULT_VOICE_ID = "alloy"


def list_voices() -> list[dict[str, Any]]:
    """获取内置音色库映射表。

    Returns:
        list[dict[str, Any]]: 音色列表，每项包含
            voice_id / name / gender / style / provider 五个字段。
    """
    return TTS_VOICES


async def get_project_subtitles(db: AsyncSession, project_id: int) -> dict[str, Any]:
    """拼装项目全部分镜的 SRT 字幕（VO-05）。

    以分镜的 dialogue 作为字幕文本、duration（TTS 完成后回写的实际配音
    时长，秒）作为该镜字幕时长，按 sequence 顺序累计起始时间，生成全片
    标准 SRT 文本与分段明细。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        dict[str, Any]: 包含以下键：
            - srt: 拼装完成的全片 SRT 字幕文本；
            - segments: 分镜级字幕分段列表（text/start/duration/sequence）；
            - total: 字幕分段总数。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    result = await db.execute(
        select(Storyboard)
        .where(Storyboard.project_id == project_id)
        .order_by(Storyboard.sequence)
    )
    storyboards = result.scalars().all()

    segments: list[dict[str, Any]] = []
    cursor = 0.0  # 时间轴游标：前一镜结束时间即下一镜起始时间

    for sb in storyboards:
        text = (sb.dialogue or "").strip()
        if not text:
            # 无台词分镜不生成字幕，但仍消耗其时长（画面预留）
            cursor += float(sb.duration or 0)
            continue
        duration = float(sb.duration or 0)
        segments.append(
            {
                "sequence": sb.sequence,
                "text": text,
                "start": round(cursor, 3),
                "duration": round(duration, 3),
            }
        )
        cursor += duration

    return {
        "srt": generate_srt(segments),
        "segments": segments,
        "total": len(segments),
    }
