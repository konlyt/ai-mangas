"""
认证领域服务。

提供用户注册、登录、令牌刷新等业务逻辑，
负责密码校验、JWT 签发与用户唯一性校验。
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import BizException, ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserOut

# 新用户默认点数
DEFAULT_QUOTA = 1000


async def register(db: AsyncSession, req: RegisterRequest) -> UserOut:
    """用户注册：校验用户名唯一，创建用户并返回用户信息。

    Args:
        db: 异步数据库会话。
        req: 注册请求体。

    Returns:
        UserOut: 新创建的用户信息。

    Raises:
        BizException: 用户名已存在时抛出 PARAM_ERROR。
    """
    # 校验用户名唯一性
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none() is not None:
        raise BizException(code=ErrorCode.PARAM_ERROR, message="用户名已被注册")

    # 若提供了邮箱，校验邮箱唯一性
    if req.email:
        result = await db.execute(select(User).where(User.email == req.email))
        if result.scalar_one_or_none() is not None:
            raise BizException(code=ErrorCode.PARAM_ERROR, message="邮箱已被注册")

    # 若提供了手机号，校验手机号唯一性
    if req.phone:
        result = await db.execute(select(User).where(User.phone == req.phone))
        if result.scalar_one_or_none() is not None:
            raise BizException(code=ErrorCode.PARAM_ERROR, message="手机号已被注册")

    # 创建用户
    user = User(
        username=req.username,
        email=req.email,
        phone=req.phone,
        password_hash=hash_password(req.password),
        quota=DEFAULT_QUOTA,
        status=1,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserOut.model_validate(user)


async def login(db: AsyncSession, req: LoginRequest) -> LoginResponse:
    """用户登录：支持用户名 / 邮箱 / 手机号登录，校验密码后签发令牌。

    Args:
        db: 异步数据库会话。
        req: 登录请求体。

    Returns:
        LoginResponse: 包含 access_token、refresh_token、token_type、user。

    Raises:
        BizException: 账号不存在或密码错误时抛出 UNAUTHORIZED；
                      用户被禁用时抛出 UNAUTHORIZED。
    """
    # 按用户名 / 邮箱 / 手机号查找用户
    result = await db.execute(
        select(User).where(
            or_(
                User.username == req.account,
                User.email == req.account,
                User.phone == req.account,
            )
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="账号或密码错误")

    # 校验密码
    if not verify_password(req.password, user.password_hash):
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="账号或密码错误")

    # 校验状态
    if user.status != 1:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="账号已被禁用")

    # 签发令牌
    token_data = {"sub": str(user.id), "username": user.username}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


async def refresh_token(db: AsyncSession, req: RefreshRequest) -> TokenResponse:
    """刷新访问令牌：校验 refresh token，签发新的 access token。

    Args:
        db: 异步数据库会话。
        req: 刷新令牌请求体。

    Returns:
        TokenResponse: 包含新的 access_token 和 token_type。

    Raises:
        BizException: refresh token 无效、类型错误或用户不存在时抛出 UNAUTHORIZED。
    """
    try:
        payload = decode_token(req.refresh_token)
    except Exception:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="刷新令牌无效或已过期")

    # 校验令牌类型
    if payload.get("type") != "refresh":
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="令牌类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="令牌中缺少用户标识")

    # 校验用户存在且状态正常
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="用户不存在")
    if user.status != 1:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="用户已被禁用")

    # 签发新的 access token
    new_access = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=new_access, token_type="bearer")
