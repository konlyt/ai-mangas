"""
任务 API 路由。

提供任务列表查询、详情、SSE 状态推送、重试、取消等端点。
路由挂载于 /tasks 前缀下。
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import tasks as tasks_domain
from app.models import TaskStatus, User
from app.schemas.task import TaskRetryRequest

router = APIRouter(tags=["任务"])


@router.get("", summary="任务列表")
async def list_tasks(
    project_id: int | None = Query(None, description="项目 ID"),
    status: TaskStatus | None = Query(None, description="任务状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """分页查询项目下的任务列表。

    Args:
        project_id: 项目 ID。
        status: 任务状态过滤。
        page: 页码。
        page_size: 每页条数。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为分页任务列表。
    """
    result = await tasks_domain.list_tasks(
        db, project_id=project_id, status=status, page=page, page_size=page_size
    )
    return ok(data=result.model_dump())


@router.get("/{task_id}", summary="任务详情")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取任务详情。

    Args:
        task_id: 任务 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为任务详情。
    """
    task = await tasks_domain.get_task(db, task_id)
    return ok(data=task.model_dump())


@router.get("/{task_id}/status", summary="任务状态查询")
async def get_task_status(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询任务当前状态（轻量端点，仅返回状态相关字段）。

    Args:
        task_id: 任务 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 包含 task_id/status/progress/error_message。
    """
    task = await tasks_domain.get_task(db, task_id)
    return ok(
        data={
            "task_id": task.id,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "progress": 100 if task.status.value == "done" else (50 if task.status.value == "running" else 0),
            "error_message": task.error_message,
        }
    )


@router.get("/{task_id}/stream", summary="任务状态 SSE 推送")
async def stream_task(
    task_id: int,
    project_id: int = Query(None, description="项目 ID（可选，自动从任务记录获取）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """订阅任务状态变更，以 SSE 格式推送。

    若未传入 project_id，则自动从任务记录中获取（需先校验任务归属）。

    Args:
        task_id: 任务 ID。
        project_id: 项目 ID（可选）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        StreamingResponse: SSE 流式响应。
    """
    # 未传 project_id 时，从任务记录中自动获取
    if project_id is None:
        task = await tasks_domain.get_task(db, task_id)
        project_id = task.project_id

    return StreamingResponse(
        tasks_domain.task_stream_sse(project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/retry", summary="重试任务")
async def retry_task(
    task_id: int,
    req: TaskRetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """重试失败的任务。

    Args:
        task_id: 任务 ID。
        req: 重试请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为任务信息。
    """
    max_retry = req.max_retry if req else None
    task = await tasks_domain.retry_task(db, task_id, max_retry)
    return ok(data=task.model_dump())


@router.post("/{task_id}/cancel", summary="取消任务")
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """取消任务。

    Args:
        task_id: 任务 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为任务信息。
    """
    task = await tasks_domain.cancel_task(db, task_id)
    return ok(data=task.model_dump())
