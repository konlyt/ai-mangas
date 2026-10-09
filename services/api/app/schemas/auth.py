"""
认证相关请求 / 响应模型。

定义注册、登录、刷新令牌所需的 Pydantic 校验结构。
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserOut


class RegisterRequest(BaseModel):
    """用户注册请求体。

    Attributes:
        username: 用户名（必填，唯一）。
        password: 密码（必填）。
        email: 邮箱（可选）。
        phone: 手机号（可选）。
    """

    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: Optional[str] = Field(None, max_length=100, description="邮箱")
    phone: Optional[str] = Field(None, max_length=20, description="手机号")


class LoginRequest(BaseModel):
    """用户登录请求体。

    Attributes:
        account: 账号（用户名 / 邮箱 / 手机号）。
        password: 密码。
    """

    account: str = Field(..., description="用户名/邮箱/手机号")
    password: str = Field(..., description="密码")


class LoginResponse(BaseModel):
    """登录成功响应体。

    Attributes:
        access_token: 访问令牌。
        refresh_token: 刷新令牌。
        token_type: 令牌类型，固定 "bearer"。
        user: 当前用户信息。
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    """刷新令牌请求体。

    Attributes:
        refresh_token: 刷新令牌。
    """

    refresh_token: str = Field(..., description="刷新令牌")


class TokenResponse(BaseModel):
    """刷新令牌后返回的新令牌响应体。

    Attributes:
        access_token: 新的访问令牌。
        token_type: 令牌类型，固定 "bearer"。
    """

    access_token: str
    token_type: str = "bearer"
