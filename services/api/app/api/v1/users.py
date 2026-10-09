"""
用户 API 路由。

提供当前用户信息、配额、用量统计、API Key 管理等端点，全部需要登录。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import models as models_domain
from app.domains import users as users_domain
from app.models import User
from app.schemas.model import UserKeyCreate, UserKeyUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", summary="获取当前用户信息")
async def get_me(user: User = Depends(get_current_user)) -> dict:
    """获取当前登录用户信息。

    Args:
        user: 当前登录用户（由 get_current_user 依赖注入）。

    Returns:
        dict: 统一响应结构，data 为用户信息。
    """
    info = users_domain.get_current_user_info(user)
    return ok(data=info.model_dump())


@router.get("/quota", summary="获取用户配额")
async def get_quota(user: User = Depends(get_current_user)) -> dict:
    """获取当前用户配额信息。

    Args:
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为配额信息。
    """
    quota = users_domain.get_quota(user)
    return ok(data=quota.model_dump())


@router.get("/usage", summary="获取用户用量统计")
async def get_usage(
    period: str = Query("month", description="统计周期：week / month"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """获取当前用户用量统计。

    Args:
        period: 统计周期，默认 "month"。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为用量统计。
    """
    usage = await users_domain.get_usage(db, user, period=period)
    return ok(data=usage.model_dump())


@router.get("/me/api-keys", summary="我的 API Key 列表")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询当前用户的 API Key 列表（掩码显示）。

    Args:
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 Key 列表。
    """
    keys = await models_domain.list_user_keys(db, user.id)
    return ok(data=keys)


@router.post("/me/api-keys", summary="添加 API Key")
async def create_api_key(
    req: UserKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """为当前用户添加 API Key（AES 加密存储）。

    Args:
        req: Key 创建请求体（厂商 / 能力 / Key 明文）。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为创建后的 Key 记录。

    Raises:
        BizException: 能力类型不合法时抛出 PARAM_ERROR。
    """
    result = await models_domain.create_user_key(
        db, user.id, req.provider, req.capability, req.api_key
    )
    return ok(data=result)


@router.put("/me/api-keys/{key_id}", summary="更新 API Key")
async def update_api_key(
    key_id: int,
    req: UserKeyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """更新当前用户的指定 API Key（api_key 留空则不修改）。

    Args:
        key_id: Key 记录 ID。
        req: Key 更新请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为更新后的 Key 记录。

    Raises:
        BizException: Key 不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await models_domain.update_user_key(
        db, user.id, key_id, req.provider, req.capability, req.api_key
    )
    return ok(data=result)


@router.delete("/me/api-keys/{key_id}", summary="删除 API Key")
async def delete_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """删除当前用户的指定 API Key。

    Args:
        key_id: Key 记录 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为 None。

    Raises:
        BizException: Key 不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    await models_domain.delete_user_key(db, user.id, key_id)
    return ok()


@router.post("/me/api-keys/{key_id}/verify", summary="测试 API Key 连通性")
async def verify_api_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """测试当前用户存储的指定 API Key 连通性。

    后端解密真实 Key 发起测试，结果持久化并返回。

    Args:
        key_id: Key 记录 ID。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为测试结果（valid/latency_ms/models）。

    Raises:
        BizException: Key 不存在或不属于当前用户时抛出 NOT_FOUND。
    """
    result = await models_domain.verify_user_key(db, user.id, key_id)
    return ok(data=result.model_dump())
