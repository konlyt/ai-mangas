"""
任务领域服务。

提供任务列表查询、详情、重试、取消，以及基于 Redis Pub/Sub 的任务状态 SSE 推送。
同时提供任务状态变更广播函数，供 Worker 调用。
"""

import json
import math
from collections.abc import AsyncGenerator
from typing import Optional

import redis.asyncio as redis
from sqlalchemy import desc, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import Task, TaskStatus, TaskType
from app.schemas.task import TaskListOut, TaskOut

logger = get_logger()

# Redis 连接池（惰性初始化）
_redis_pool: Optional[redis.ConnectionPool] = None


def get_redis() -> redis.Redis:
    """获取（必要时创建）Redis 异步连接。

    Returns:
        redis.Redis: 异步 Redis 客户端实例。
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.get_redis_url(),
            decode_responses=True,
            max_connections=50,
        )
    return redis.Redis(connection_pool=_redis_pool)


async def publish_task_status(
    project_id: int, task_id: int, status: str, progress: int = 0
) -> None:
    """通过 Redis Pub/Sub 广播任务状态变更。

    频道名为 task:{project_id}，消息为 JSON 格式。

    Args:
        project_id: 项目 ID。
        task_id: 任务 ID。
        status: 任务状态字符串。
        progress: 进度百分比（0-100）。

    Returns:
        None
    """
    try:
        r = get_redis()
        channel = f"task:{project_id}"
        message = json.dumps(
            {"task_id": task_id, "status": status, "progress": progress},
            ensure_ascii=False,
        )
        await r.publish(channel, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tasks] 广播任务状态失败 task_id={task_id}: {exc}")


async def list_tasks(
    db: AsyncSession,
    project_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
    page: int = 1,
    page_size: int = 20,
) -> TaskListOut:
    """分页查询任务列表。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID，可选，为空则查询所有任务。
        status: 任务状态过滤，可选。
        page: 页码。
        page_size: 每页条数。

    Returns:
        TaskListOut: 分页列表结果。
    """
    conditions = []
    if project_id is not None:
        conditions.append(Task.project_id == project_id)
    if status:
        conditions.append(Task.status == status)

    if conditions:
        where_clause = conditions[0]
        for c in conditions[1:]:
            where_clause = where_clause & c
    else:
        where_clause = true()

    total = await db.scalar(
        select(func.count()).select_from(Task).where(where_clause)
    )
    total = total or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Task)
        .where(where_clause)
        .order_by(desc(Task.created_at))
        .offset(offset)
        .limit(page_size)
    )
    items = result.scalars().all()

    total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    return TaskListOut(
        list=[TaskOut.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


async def get_task(db: AsyncSession, task_id: int) -> TaskOut:
    """获取任务详情。

    Args:
        db: 异步数据库会话。
        task_id: 任务 ID。

    Returns:
        TaskOut: 任务详情。

    Raises:
        BizException: 任务不存在时抛出 NOT_FOUND。
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="任务不存在")
    return TaskOut.model_validate(task)


async def retry_task(db: AsyncSession, task_id: int, max_retry: Optional[int] = None) -> TaskOut:
    """重试任务：将状态重置为 queued，重试次数 +1。

    Args:
        db: 异步数据库会话。
        task_id: 任务 ID。
        max_retry: 新的最大重试次数，可选。

    Returns:
        TaskOut: 重试后的任务信息。

    Raises:
        BizException: 任务不存在时抛出 NOT_FOUND。
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="任务不存在")

    task.status = TaskStatus.QUEUED
    task.retry_count = task.retry_count + 1
    task.error_message = None
    if max_retry is not None:
        task.max_retry = max_retry

    await db.commit()
    await db.refresh(task)

    # 广播状态变更
    await publish_task_status(task.project_id, task.id, TaskStatus.QUEUED.value)
    return TaskOut.model_validate(task)


async def cancel_task(db: AsyncSession, task_id: int) -> TaskOut:
    """取消任务：将状态置为 failed。

    Args:
        db: 异步数据库会话。
        task_id: 任务 ID。

    Returns:
        TaskOut: 取消后的任务信息。

    Raises:
        BizException: 任务不存在时抛出 NOT_FOUND。
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="任务不存在")

    task.status = TaskStatus.FAILED
    task.error_message = "用户取消"
    await db.commit()
    await db.refresh(task)

    await publish_task_status(task.project_id, task.id, TaskStatus.FAILED.value)
    return TaskOut.model_validate(task)


async def task_stream_sse(project_id: int) -> AsyncGenerator[str, None]:
    """订阅 Redis Pub/Sub 频道，以 SSE 格式推送项目下任务状态变更。

    Args:
        project_id: 项目 ID。

    Yields:
        str: SSE 格式的任务状态数据。
    """
    r = get_redis()
    pubsub = r.pubsub()
    channel = f"task:{project_id}"
    await pubsub.subscribe(channel)

    try:
        # 先发送一条连接成功的心跳
        yield f"data: {json.dumps({'type': 'connected', 'project_id': project_id})}\n\n"

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                yield f"data: {data}\n\n"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tasks] SSE 推送异常 project_id={project_id}: {exc}")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
