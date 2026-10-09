"""
分镜 API 路由。

提供分镜生成、查询、拖拽重排（SB-04）、连续性检查（SB-06）、
单条更新、批量操作、确认等端点。
路由挂载于 /projects 前缀下。

注意：/storyboard/reorder 等静态路径路由必须注册在 /storyboard/{seq}
动态路由之前，否则会被 int 路径参数吞掉并返回 422。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import storyboard as storyboard_domain
from app.models import User
from app.schemas.storyboard import (
    StoryboardBatchRequest,
    StoryboardGenerateRequest,
    StoryboardReorderRequest,
    StoryboardUpdateRequest,
)

router = APIRouter(tags=["分镜"])


@router.post("/{id}/storyboard/generate", summary="生成分镜")
async def generate_storyboard(
    id: int,
    req: StoryboardGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """将剧本拆解为分镜。

    Args:
        id: 项目 ID。
        req: 分镜生成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为分镜列表。
    """
    storyboards = await storyboard_domain.generate_storyboard(db, id, req)
    return ok(data=[s.model_dump() for s in storyboards])


@router.get("/{id}/storyboard", summary="查询分镜列表")
async def get_storyboard(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目下的全部分镜。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为分镜列表。
    """
    storyboards = await storyboard_domain.get_storyboard(db, id)
    return ok(data=[s.model_dump() for s in storyboards])


@router.put("/{id}/storyboard/reorder", summary="拖拽重排分镜")
async def reorder_storyboard(
    id: int,
    req: StoryboardReorderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按传入的分镜 ID 顺序重排项目全部分镜（SB-04）。

    Args:
        id: 项目 ID。
        req: 重排请求体，ordered_ids 为按新顺序排列的分镜 ID 列表。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为重排后的分镜列表。
    """
    storyboards = await storyboard_domain.reorder_storyboard(db, id, req)
    return ok(data=[s.model_dump() for s in storyboards], message="分镜顺序已更新")


@router.post("/{id}/storyboard/continuity-check", summary="分镜连续性检查")
async def continuity_check(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """调用 LLM 检查相邻分镜衔接问题（SB-06）。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 {"checked": bool, "issues": [...]}。
    """
    result = await storyboard_domain.continuity_check(db, id)
    return ok(data=result)


@router.put("/{id}/storyboard/{seq}", summary="更新单个分镜")
async def update_storyboard(
    id: int,
    seq: int,
    req: StoryboardUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """更新单个分镜的字段。

    Args:
        id: 项目 ID。
        seq: 镜头序号。
        req: 分镜更新请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为更新后的分镜信息。
    """
    storyboard = await storyboard_domain.update_storyboard(db, id, seq, req)
    return ok(data=storyboard.model_dump())


@router.post("/{id}/storyboard/batch", summary="批量操作分镜")
async def batch_operations(
    id: int,
    req: StoryboardBatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """批量执行分镜的新增、删除、重排序、更新操作。

    Args:
        id: 项目 ID。
        req: 批量操作请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为操作后的分镜列表。
    """
    storyboards = await storyboard_domain.batch_operations(db, id, req)
    return ok(data=[s.model_dump() for s in storyboards])


@router.post("/{id}/storyboard/confirm", summary="确认分镜")
async def confirm_storyboard(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """确认分镜，推进到关键帧阶段并创建版本快照。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 None。
    """
    await storyboard_domain.confirm_storyboard(db, id)
    return ok(data=None, message="分镜已确认")
