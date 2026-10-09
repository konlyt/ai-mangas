"""
项目 API 路由。

提供项目的增删改查、列表分页、最近项目、统计等端点，全部需要登录。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import models as models_domain
from app.domains import projects as projects_domain
from app.models import ProjectStatus, User
from app.schemas.model import SelectModelRequest
from app.schemas.project import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", summary="项目列表")
async def list_projects(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    keyword: str = Query(None, description="标题关键词"),
    status: ProjectStatus = Query(None, description="项目阶段"),
    genre: str = Query(None, description="体裁"),
    sort: str = Query("newest", description="排序：newest / oldest"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """分页查询项目列表。

    Args:
        page: 页码。
        page_size: 每页条数。
        keyword: 标题关键词。
        status: 项目阶段过滤。
        genre: 体裁过滤。
        sort: 排序方式。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为分页列表。
    """
    result = await projects_domain.list_projects(
        db,
        user_id=user.id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        genre=genre,
        sort=sort,
    )
    return ok(data=result.model_dump())


@router.post("", summary="创建项目")
async def create_project(
    req: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """创建新项目。

    Args:
        req: 项目创建请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为新项目信息。
    """
    project = await projects_domain.create_project(db, user.id, req)
    return ok(data=project.model_dump())


@router.get("/recent", summary="最近项目")
async def get_recent_projects(
    limit: int = Query(3, ge=1, le=20, description="返回条数"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取最近创建的项目列表。

    Args:
        limit: 返回条数。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为项目列表。
    """
    items = await projects_domain.get_recent_projects(db, user.id, limit=limit)
    return ok(data=[item.model_dump() for item in items])


@router.get("/stats", summary="项目统计")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取项目统计信息。

    Args:
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为统计信息。
    """
    stats = await projects_domain.get_stats(db, user.id)
    return ok(data=stats.model_dump())


@router.get("/{project_id}", summary="项目详情")
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取项目详情。

    Args:
        project_id: 项目ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为项目详情。
    """
    project = await projects_domain.get_project(db, project_id, user.id)
    return ok(data=project.model_dump())


@router.put("/{project_id}", summary="更新项目")
async def update_project(
    project_id: int,
    req: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """更新项目信息。

    Args:
        project_id: 项目ID。
        req: 项目更新请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为更新后的项目信息。
    """
    project = await projects_domain.update_project(db, project_id, user.id, req)
    return ok(data=project.model_dump())


@router.delete("/{project_id}", summary="删除项目")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """删除项目。

    Args:
        project_id: 项目ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 None。
    """
    await projects_domain.delete_project(db, project_id, user.id)
    return ok(data=None, message="删除成功")


@router.post("/{project_id}/models", summary="设置项目使用的模型")
async def select_project_model(
    project_id: int,
    req: SelectModelRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """为项目选择指定模型（写入项目级模型配置）。

    Args:
        project_id: 项目 ID。
        req: 选模型请求体（含候选模型 model_id）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为选择结果。

    Raises:
        BizException: 项目或模型不存在、不归属当前用户时抛出 NOT_FOUND。
    """
    result = await models_domain.select_project_model(db, user.id, project_id, req.model_id)
    return ok(data=result)
