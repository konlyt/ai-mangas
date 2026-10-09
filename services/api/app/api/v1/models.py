"""
模型中心 API 路由。

提供模型列表查询、项目级配置设置、Key 连通性测试、
用户自有 Key 列表等端点。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import models as models_domain
from app.models import ModelCapability, User
from app.schemas.model import ModelConfigCreate, VerifyKeyRequest

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", summary="模型列表")
async def list_models(
    capability: ModelCapability = Query(None, description="能力类型过滤"),
    project_id: int = Query(None, description="项目ID（用于标记当前默认模型）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询当前用户可见的模型列表。

    返回前端 Model 结构（id/name/provider/type/is_default/key_configured），
    合并全局默认配置与用户自有 Key 配置。

    Args:
        capability: 能力类型过滤（可选）。
        project_id: 项目 ID（可选，用于标记当前默认模型）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为模型列表。
    """
    models = await models_domain.list_models_for_user(db, user.id, project_id)
    if capability is not None:
        fe_type = models_domain.CAPABILITY_TO_FRONTEND_TYPE.get(capability.value)
        models = [m for m in models if m["type"] == fe_type]
    return ok(data=models)


@router.put("/projects/{project_id}", summary="设置项目级模型配置")
async def set_project_config(
    project_id: int,
    req: ModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """设置项目级模型配置。

    若项目已存在相同 capability 的配置则更新，否则新建。

    Args:
        project_id: 项目ID。
        req: 模型配置请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为保存后的模型配置。
    """
    config = await models_domain.set_project_config(db, project_id, user.id, req)
    return ok(data=config.model_dump())


@router.post("/verify-key", summary="Key 连通性测试")
async def verify_key(req: VerifyKeyRequest) -> dict:
    """测试 API Key 连通性。

    根据 provider 选择对应测试端点，返回是否有效、耗时与可用模型。

    Args:
        req: Key 测试请求体。

    Returns:
        dict: 统一响应结构，data 为测试结果。
    """
    result = await models_domain.verify_key(req)
    return ok(data=result.model_dump())


@router.get("/keys", summary="我的 Key 列表")
async def list_my_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询用户自有 Key 列表（掩码显示）。

    Args:
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 Key 列表。
    """
    keys = await models_domain.list_my_keys(db, user.id)
    return ok(data=keys)
