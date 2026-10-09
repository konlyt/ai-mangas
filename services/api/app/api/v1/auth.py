"""
认证 API 路由。

提供用户注册、登录、刷新令牌等端点，全部使用 ApiResponse 统一包装。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ok
from app.domains import auth as auth_domain
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", summary="用户注册")
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户注册接口。

    Args:
        req: 注册请求体。
        db: 异步数据库会话。

    Returns:
        dict: 统一响应结构，data 为用户信息。
    """
    user = await auth_domain.register(db, req)
    return ok(data=user.model_dump())


@router.post("/login", summary="用户登录")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户登录接口。

    支持用户名 / 邮箱 / 手机号登录。

    Args:
        req: 登录请求体。
        db: 异步数据库会话。

    Returns:
        dict: 统一响应结构，data 为令牌与用户信息。
    """
    result = await auth_domain.login(db, req)
    return ok(data=result.model_dump())


@router.post("/refresh", summary="刷新访问令牌")
async def refresh(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """刷新访问令牌接口。

    Args:
        req: 刷新令牌请求体。
        db: 异步数据库会话。

    Returns:
        dict: 统一响应结构，data 为新的访问令牌。
    """
    result = await auth_domain.refresh_token(db, req)
    return ok(data=result.model_dump())
