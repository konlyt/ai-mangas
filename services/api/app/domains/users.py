"""
用户领域服务。

提供当前用户信息、配额、用量统计等业务逻辑。
用量统计从 projects、tasks、agent_events 等表聚合。
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentEvent, Project, Task, TaskStatus, TaskType, User
from app.schemas.user import QuotaOut, UsageOut, UserOut


def get_current_user_info(user: User) -> UserOut:
    """获取当前登录用户信息。

    Args:
        user: 当前登录用户 ORM 对象。

    Returns:
        UserOut: 用户信息。
    """
    return UserOut.model_validate(user)


def get_quota(user: User) -> QuotaOut:
    """获取用户配额信息。

    Args:
        user: 当前登录用户 ORM 对象。

    Returns:
        QuotaOut: 包含剩余点数与会员等级。
    """
    return QuotaOut(quota=user.quota, vip_level=user.vip_level)


async def get_usage(db: AsyncSession, user: User, period: str = "month") -> UsageOut:
    """获取用户用量统计。

    从 projects / tasks / agent_events 表聚合统计：
    - 项目总数
    - 图片数量（已完成的图片任务数）
    - 视频时长（秒）
    - 累计消耗点数（任务 + Agent 事件）
    - 按日消耗点数数组

    Args:
        db: 异步数据库会话。
        user: 当前登录用户 ORM 对象。
        period: 统计周期，默认 "month"（最近 30 天）。

    Returns:
        UsageOut: 用量统计结果。

    Raises:
        BizException: 不抛出异常，查询失败由上层捕获。
    """
    user_id = user.id
    now = datetime.now(timezone.utc)

    # 计算周期起始时间
    if period == "month":
        start_time = now - timedelta(days=30)
    elif period == "week":
        start_time = now - timedelta(days=7)
    else:
        start_time = now - timedelta(days=30)

    # ---- 项目总数 ----
    project_count = await db.scalar(
        select(func.count()).select_from(Project).where(Project.user_id == user_id)
    )

    # ---- 图片数量：已完成的图片类型任务 ----
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

    # ---- 视频时长：所有已完成视频任务关联分镜的时长之和 ----
    # 这里直接从 tasks 表中已完成的 video 任务统计，简化为计数*5
    # 更精确的做法是关联 storyboards 取 duration 之和
    video_result = await db.execute(
        select(func.coalesce(func.sum(Task.cost_points), 0))
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.user_id == user_id,
            Task.type == TaskType.VIDEO,
            Task.status == TaskStatus.DONE,
        )
    )
    # 视频时长秒数：用已完成视频任务数 * 5 秒（默认分镜时长）近似
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

    # ---- 累计消耗点数：tasks + agent_events ----
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

    # ---- 按日消耗点数数组 ----
    # 从 tasks 表按日聚合（周期内）
    daily_result = await db.execute(
        select(
            func.date(Task.created_at).label("d"),
            func.coalesce(func.sum(Task.cost_points), 0).label("pts"),
        )
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.user_id == user_id,
            Task.created_at >= start_time,
        )
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at))
    )
    daily_map: dict[date, int] = {}
    for row in daily_result.all():
        d = row.d
        pts = int(row.pts or 0)
        if isinstance(d, datetime):
            d = d.date()
        daily_map[d] = daily_map.get(d, 0) + pts

    # 从 agent_events 表按日聚合（周期内）
    event_daily = await db.execute(
        select(
            func.date(AgentEvent.created_at).label("d"),
            func.coalesce(func.sum(AgentEvent.cost_points), 0).label("pts"),
        )
        .select_from(AgentEvent)
        .join(Project, Project.id == AgentEvent.project_id)
        .where(
            Project.user_id == user_id,
            AgentEvent.created_at >= start_time,
        )
        .group_by(func.date(AgentEvent.created_at))
        .order_by(func.date(AgentEvent.created_at))
    )
    for row in event_daily.all():
        d = row.d
        pts = int(row.pts or 0)
        if isinstance(d, datetime):
            d = d.date()
        daily_map[d] = daily_map.get(d, 0) + pts

    # 补齐周期内缺失日期为 0
    daily_list = []
    cur = start_time.date()
    end = now.date()
    while cur <= end:
        daily_list.append({"date": cur, "cost_points": daily_map.get(cur, 0)})
        cur += timedelta(days=1)

    return UsageOut(
        project_count=project_count or 0,
        image_count=image_count or 0,
        video_duration=video_duration,
        cost_points=cost_points,
        daily=daily_list,
    )
