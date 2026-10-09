"""
版本快照 API 路由。

提供版本快照列表查询与版本回退端点。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import revisions as revisions_domain
from app.models import User

router = APIRouter(tags=["版本"])


@router.get("/{id}/revisions", summary="版本快照列表")
async def list_revisions(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目的全部版本快照。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为版本快照列表。
    """
    revisions = await revisions_domain.list_revisions(db, id)
    return ok(data=[r.model_dump() for r in revisions])


@router.post("/{id}/revisions/{rid}/restore", summary="回退到指定版本")
async def restore_revision(
    id: int,
    rid: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """回退项目到指定版本快照。

    Args:
        id: 项目 ID。
        rid: 快照 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为回退到的版本快照。
    """
    revision = await revisions_domain.restore_revision(db, id, rid, user.id)
    return ok(data=revision.model_dump())
