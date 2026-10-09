"""
FastAPI 依赖注入模块。

提供数据库会话依赖 get_db 与当前登录用户依赖 get_current_user。
"""

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import BizException, ErrorCode
from app.core.security import decode_token

# OAuth2 令牌获取方案，tokenUrl 指向登录接口
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """从 JWT 令牌解析当前登录用户。

    Args:
        token: Bearer Token。
        db: 数据库会话。

    Returns:
        User: 当前用户 ORM 对象。

    Raises:
        BizException: 令牌缺失、无效或用户不存在时抛出 401。
    """
    if not token:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="未提供访问令牌")

    try:
        payload = decode_token(token)
    except Exception:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="访问令牌无效或已过期")

    if payload.get("type") != "access":
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="令牌类型错误")

    user_id = payload.get("sub")
    if not user_id:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="令牌中缺少用户标识")

    # 延迟导入以避免循环依赖
    from app.models import User

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="用户不存在")
    if user.status != 1:
        raise BizException(code=ErrorCode.UNAUTHORIZED, message="用户已被禁用")

    return user
