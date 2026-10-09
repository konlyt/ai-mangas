"""
Graph 编排 API 路由。

提供 Graph 运行启动、状态查询、中断恢复等端点。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import graph as graph_domain
from app.models import User
from app.schemas.graph import GraphResumeRequest, GraphRunRequest

router = APIRouter(tags=["Graph"])


@router.post("/{id}/graph/runs", summary="启动 Graph 执行")
async def run_graph(
    id: int,
    req: GraphRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """创建并启动 Graph 生产流水线。

    Args:
        id: 项目 ID。
        req: Graph 运行请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 run_id。
    """
    result = await graph_domain.run_graph(db, id, user.id, req)
    return ok(data=result)


@router.get("/{id}/graph/state", summary="查询 Graph 状态")
async def get_graph_state(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目当前 Graph 执行状态。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 Graph 状态。
    """
    state = await graph_domain.get_graph_state(db, id)
    return ok(data=state.model_dump())


@router.post("/{id}/graph/resume", summary="恢复 Graph 执行")
async def resume_graph(
    id: int,
    req: GraphResumeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """恢复中断的 Graph 执行（确认或驳回）。

    Args:
        id: 项目 ID。
        req: 恢复执行请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为恢复结果。
    """
    result = await graph_domain.resume_graph(db, id, req)
    return ok(data=result)
