"""
版本快照领域服务。

提供版本快照列表查询与版本回退功能。
"""

from typing import List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BizException, ErrorCode
from app.models import Project, ProjectStatus, Revision
from app.schemas.revision import RevisionOut


async def list_revisions(db: AsyncSession, project_id: int) -> List[RevisionOut]:
    """查询项目的全部版本快照（按创建时间倒序）。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        List[RevisionOut]: 版本快照列表。
    """
    result = await db.execute(
        select(Revision)
        .where(Revision.project_id == project_id)
        .order_by(desc(Revision.created_at))
    )
    items = result.scalars().all()
    return [RevisionOut.model_validate(r) for r in items]


async def restore_revision(
    db: AsyncSession, project_id: int, revision_id: int, user_id: int
) -> RevisionOut:
    """回退到指定版本快照。

    将项目状态回退到快照对应的阶段，并返回快照内容。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        revision_id: 快照 ID。
        user_id: 操作用户 ID。

    Returns:
        RevisionOut: 回退到的版本快照。

    Raises:
        BizException: 快照不存在或不属于该项目时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Revision).where(
            Revision.id == revision_id, Revision.project_id == project_id
        )
    )
    revision = result.scalar_one_or_none()
    if revision is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="版本快照不存在")

    # 将项目状态回退到快照阶段
    project = await db.get(Project, project_id)
    if project is not None:
        stage = revision.stage
        stage_map = {
            "script": ProjectStatus.ASSETS,
            "assets": ProjectStatus.STORYBOARD,
            "storyboard": ProjectStatus.KEYFRAMES,
            "keyframes": ProjectStatus.VIDEO,
        }
        project.status = stage_map.get(stage, ProjectStatus.DRAFT)

    await db.commit()
    return RevisionOut.model_validate(revision)
