"""
批量生成 API 路由。

提供关键帧、视频、语音的批量生成端点。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import generation as generation_domain
from app.models import User
from app.schemas.generate import GenerateRequest, VideoRegenerateRequest

router = APIRouter(tags=["生成"])


@router.post("/{id}/generate/keyframes", summary="批量生成关键帧")
async def generate_keyframes(
    id: int,
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """为分镜创建关键帧（image）生成任务。

    Args:
        id: 项目 ID。
        req: 生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为生成结果（含 task_ids）。
    """
    result = await generation_domain.generate_keyframes(db, id, req)
    return ok(data=result.model_dump())


@router.post("/{id}/generate/videos", summary="批量生成视频")
async def generate_videos(
    id: int,
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """为分镜创建视频（video）生成任务。

    Args:
        id: 项目 ID。
        req: 生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为生成结果（含 task_ids）。
    """
    result = await generation_domain.generate_videos(db, id, req)
    return ok(data=result.model_dump())


@router.post("/{id}/generate/voices", summary="批量生成语音")
async def generate_voices(
    id: int,
    req: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """为分镜创建语音（tts）合成任务。

    Args:
        id: 项目 ID。
        req: 生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为生成结果（含 task_ids）。
    """
    result = await generation_domain.generate_voices(db, id, req)
    return ok(data=result.model_dump())


@router.post("/{id}/video/{task_id}/regenerate", summary="视频任务换模重新生成")
async def regenerate_video(
    id: int,
    task_id: int,
    req: VideoRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """视频片段降级换模重新生成（VID-07）。

    标记原视频任务废弃并创建新的视频生成任务，可通过 body 指定
    provider（agnes / mock）实现换模。

    Args:
        id: 项目 ID。
        task_id: 原视频任务 ID。
        req: 重新生成请求体（可选，含 provider 字段）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 含 new_task_id 与 provider。

    Raises:
        BizException: 项目/任务不存在或无权访问、任务类型非视频时抛出。
    """
    result = await generation_domain.regenerate_video(db, id, task_id, req, user.id)
    return ok(data=result.model_dump())
