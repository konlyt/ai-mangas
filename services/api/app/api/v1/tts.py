"""
配音（TTS）API 路由。

提供内置音色库查询（VO-02）与项目字幕查询（VO-05）端点。
路由自带完整路径（/tts/voices、/projects/{id}/subtitles），
在 api/v1/__init__.py 中无前缀注册。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import voice as voice_domain
from app.models import User

router = APIRouter(tags=["配音"])


@router.get("/tts/voices", summary="查询音色库")
async def get_tts_voices(
    user: User = Depends(get_current_user),
) -> dict:
    """返回内置音色映射表（VO-02）。

    覆盖 mock（default）与 agnes（OpenAI 风格预置音色）的可用音色；
    agnes 音色在网关 /audio/speech 就绪后实际生效。

    Args:
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为音色列表
            [{voice_id, name, gender, style, provider}]。
    """
    return ok(data=voice_domain.list_voices())


@router.get("/projects/{id}/subtitles", summary="查询项目字幕")
async def get_project_subtitles(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回项目全部分镜的字幕（VO-05）。

    按镜头顺序以台词 + 配音时长拼装标准 SRT 文本，同时返回分镜级
    字幕分段明细，供合成阶段（批次 D）消费。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {"srt": SRT文本, "segments": [...], "total": N}。
    """
    result = await voice_domain.get_project_subtitles(db, id)
    return ok(data=result)
