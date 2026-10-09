"""
合成 API 路由。

提供全片合成、局部重合成、查询最终输出等端点。
路由挂载于 /projects 前缀下。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import compose as compose_domain
from app.models import User
from app.schemas.compose import ComposePartialRequest, ComposeRequest, ExportRequest

router = APIRouter(tags=["合成"])


@router.post("/{id}/compose", summary="全片合成")
async def compose(
    id: int,
    req: ComposeRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """创建全片合成任务。

    Args:
        id: 项目 ID。
        req: 合成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 task_id。
    """
    result = await compose_domain.compose(db, id, req)
    return ok(data=result)


@router.post("/{id}/compose/partial", summary="局部重合成")
async def partial_compose(
    id: int,
    req: ComposePartialRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """创建局部重合成任务。

    Args:
        id: 项目 ID。
        req: 局部合成请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 task_id。
    """
    result = await compose_domain.partial_compose(db, id, req)
    return ok(data=result)


@router.get("/{id}/output", summary="查询最终输出")
async def get_output(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目的最终合成输出。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为输出信息。
    """
    output = await compose_domain.get_output(db, id)
    return ok(data=output.model_dump())


@router.post("/{id}/export", summary="导出成片")
async def export_project(
    id: int,
    req: ExportRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按比例裁剪导出最新成片并返回下载 URL。

    Args:
        id: 项目 ID。
        req: 导出请求体（含可选 ratio，缺省用项目配置比例）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为导出结果（url/ratio/size）。
    """
    result = await compose_domain.export_project(
        db, id, req or ExportRequest(), user_id=user.id
    )
    return ok(data=result)


@router.get("/{id}/export/latest", summary="最近一次导出")
async def get_latest_export(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询项目最近一次导出记录（来自操作日志）。

    Args:
        id: 项目 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为导出记录（url/ratio/created_at），无记录时字段为空。
    """
    result = await compose_domain.get_latest_export(db, id)
    return ok(data=result)
