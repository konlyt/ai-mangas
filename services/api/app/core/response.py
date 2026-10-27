"""
统一响应模型与异常处理模块。

定义 ApiResponse 泛型响应结构、ErrorCode 错误码常量、BizException 业务异常，
以及 register_exception_handlers 函数用于向 FastAPI 应用注册全局异常处理器。
"""

import time
from typing import Any, Generic, Optional, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应模型。

    Attributes:
        code: 业务状态码，0 表示成功。
        data: 响应数据。
        message: 响应消息。
        timestamp: 时间戳（秒）。
    """

    code: int = 0
    data: Optional[T] = None
    message: str = "success"
    timestamp: int = 0


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    """构造成功响应字典。

    Args:
        data: 响应数据。
        message: 响应消息，默认 "success"。

    Returns:
        dict: 包含 code/data/message/timestamp 的字典。
    """
    return {
        "code": ErrorCode.SUCCESS,
        "data": data,
        "message": message,
        "timestamp": int(time.time()),
    }


class ErrorCode:
    """业务错误码常量。"""

    SUCCESS = 0
    PARAM_ERROR = 40001
    UNAUTHORIZED = 40101
    FORBIDDEN = 40301
    NOT_FOUND = 40401
    CONFLICT = 40901
    RATE_LIMIT = 42901
    SERVER_ERROR = 50001
    AI_ERROR = 50002
    QUOTA_ERROR = 50003
    COMPLIANCE_ERROR = 50004


class BizException(Exception):
    """业务异常。

    Attributes:
        code: 错误码。
        message: 错误消息。
    """

    def __init__(self, code: int = ErrorCode.SERVER_ERROR, message: str = "server error") -> None:
        """初始化业务异常。

        Args:
            code: 错误码，默认 SERVER_ERROR。
            message: 错误消息。
        """
        self.code = code
        self.message = message
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册全局异常处理器。

    Args:
        app: FastAPI 应用实例。

    Returns:
        None
    """

    @app.exception_handler(BizException)
    async def biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
        """业务异常处理器。"""
        return JSONResponse(
            status_code=200,
            content={
                "code": exc.code,
                "data": None,
                "message": exc.message,
                "timestamp": int(time.time()),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """请求参数校验异常处理器。

        说明：Pydantic v2 自定义校验器（model_validator 等）抛出的 ValueError
        会以异常对象形式挂在 err["ctx"]["error"] 上，直接放入 JSON 响应会
        序列化失败，这里统一把 ctx 内对象转为字符串再返回。
        """
        errors = exc.errors()
        for err in errors:
            ctx = err.get("ctx")
            if ctx:
                err["ctx"] = {k: str(v) for k, v in ctx.items()}
        return JSONResponse(
            status_code=200,
            content={
                "code": ErrorCode.PARAM_ERROR,
                "data": errors,
                "message": "参数校验失败",
                "timestamp": int(time.time()),
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底全局异常处理器。"""
        return JSONResponse(
            status_code=200,
            content={
                "code": ErrorCode.SERVER_ERROR,
                "data": None,
                "message": f"服务器内部错误: {exc}",
                "timestamp": int(time.time()),
            },
        )
