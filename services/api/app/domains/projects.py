"""
项目领域服务。

提供项目的增删改查、列表分页、最近项目、统计等业务逻辑。
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BizException, ErrorCode
from app.models import AgentEvent, Project, ProjectStatus, Task, TaskStatus, TaskType
from app.schemas.project import (
    ProjectCreate,
    ProjectListOut,
    ProjectOut,
    ProjectStatsOut,
    ProjectUpdate,
)


async def list_projects(
    db: AsyncSession,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[ProjectStatus] = None,
    genre: Optional[str] = None,
    sort: str = "newest",
) -> ProjectListOut:
    """分页查询用户项目列表。

    Args:
        db: 异步数据库会话。
        user_id: 用户ID。
        page: 页码（从1开始）。
        page_size: 每页条数。
        keyword: 标题关键词模糊搜索。
        status: 项目阶段过滤。
        genre: 体裁过滤。
        sort: 排序方式，"newest"（默认）或 "oldest"。

    Returns:
        ProjectListOut: 分页列表结果。
    """
    # 构建过滤条件
    conditions = [Project.user_id == user_id]
    if keyword:
        conditions.append(Project.title.like(f"%{keyword}%"))
    if status:
        conditions.append(Project.status == status)
    if genre:
        conditions.append(Project.genre == genre)

    where_clause = and_(*conditions)

    # 总数
    total = await db.scalar(
        select(func.count()).select_from(Project).where(where_clause)
    )
    total = total or 0

    # 分页查询
    offset = (page - 1) * page_size
    order = desc(Project.created_at) if sort == "newest" else Project.created_at
    result = await db.execute(
        select(Project)
        .where(where_clause)
        .order_by(order)
        .offset(offset)
        .limit(page_size)
    )
    items = result.scalars().all()

    total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    return ProjectListOut(
        list=[ProjectOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def create_project(db: AsyncSession, user_id: int, req: ProjectCreate) -> ProjectOut:
    """创建新项目。

    将 raw_input 与 meta 合并存入 config JSON 字段。

    Args:
        db: 异步数据库会话。
        user_id: 用户ID。
        req: 项目创建请求体。

    Returns:
        ProjectOut: 新创建的项目信息。
    """
    # 合并 raw_input 与 meta 到 config
    config = {}
    if req.raw_input is not None:
        config["raw_input"] = req.raw_input
    if req.meta is not None:
        config["meta"] = req.meta

    project = Project(
        user_id=user_id,
        title=req.title,
        genre=req.genre,
        style=req.style,
        status=ProjectStatus.DRAFT,
        aspect_ratio=req.aspect_ratio or "9:16",
        config=config or None,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    return ProjectOut.model_validate(project)


async def get_project(db: AsyncSession, project_id: int, user_id: int) -> ProjectOut:
    """获取项目详情。

    Args:
        db: 异步数据库会话。
        project_id: 项目ID。
        user_id: 用户ID（用于校验归属）。

    Returns:
        ProjectOut: 项目详情。

    Raises:
        BizException: 项目不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    return ProjectOut.model_validate(project)


async def update_project(
    db: AsyncSession, project_id: int, user_id: int, req: ProjectUpdate
) -> ProjectOut:
    """更新项目信息。

    仅更新请求中传入的非空字段。

    Args:
        db: 异步数据库会话。
        project_id: 项目ID。
        user_id: 用户ID（用于校验归属）。
        req: 项目更新请求体。

    Returns:
        ProjectOut: 更新后的项目信息。

    Raises:
        BizException: 项目不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    # 按字段更新
    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)

    return ProjectOut.model_validate(project)


async def delete_project(db: AsyncSession, project_id: int, user_id: int) -> None:
    """删除项目（硬删除）。

    Args:
        db: 异步数据库会话。
        project_id: 项目ID。
        user_id: 用户ID（用于校验归属）。

    Returns:
        None

    Raises:
        BizException: 项目不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    await db.delete(project)
    await db.commit()


async def get_recent_projects(db: AsyncSession, user_id: int, limit: int = 3) -> list:
    """获取最近创建的项目列表。

    Args:
        db: 异步数据库会话。
        user_id: 用户ID。
        limit: 返回条数，默认 3。

    Returns:
        list: 项目列表（ProjectOut）。
    """
    result = await db.execute(
        select(Project)
        .where(Project.user_id == user_id)
        .order_by(desc(Project.created_at))
        .limit(limit)
    )
    items = result.scalars().all()
    return [ProjectOut.model_validate(item) for item in items]


async def get_stats(db: AsyncSession, user_id: int) -> ProjectStatsOut:
    """获取项目统计信息。

    统计今日 / 本月新建项目数、图片数量、视频时长、累计消耗点数。

    Args:
        db: 异步数据库会话。
        user_id: 用户ID。

    Returns:
        ProjectStatsOut: 统计结果。
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 今日新建项目数
    today_projects = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.user_id == user_id,
            Project.created_at >= today_start,
        )
    )

    # 本月新建项目数
    month_projects = await db.scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.user_id == user_id,
            Project.created_at >= month_start,
        )
    )

    # 图片数量：已完成的图片任务
    image_count = await db.scalar(
        select(func.count())
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.user_id == user_id,
            Task.type == TaskType.IMAGE,
            Task.status == TaskStatus.DONE,
        )
    )

    # 视频时长：已完成视频任务数 * 5 秒
    video_task_count = await db.scalar(
        select(func.count())
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.user_id == user_id,
            Task.type == TaskType.VIDEO,
            Task.status == TaskStatus.DONE,
        )
    )
    video_duration = (video_task_count or 0) * 5

    # 累计消耗点数
    task_cost = await db.scalar(
        select(func.coalesce(func.sum(Task.cost_points), 0))
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(Project.user_id == user_id)
    )
    event_cost = await db.scalar(
        select(func.coalesce(func.sum(AgentEvent.cost_points), 0))
        .select_from(AgentEvent)
        .join(Project, Project.id == AgentEvent.project_id)
        .where(Project.user_id == user_id)
    )
    cost_points = (task_cost or 0) + (event_cost or 0)

    return ProjectStatsOut(
        today_projects=today_projects or 0,
        month_projects=month_projects or 0,
        image_count=image_count or 0,
        video_duration=video_duration,
        cost_points=cost_points,
    )
