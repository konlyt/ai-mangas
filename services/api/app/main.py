"""
FastAPI 应用入口。

创建 AI 漫剧制作平台后端应用，配置 CORS、异常处理器、生命周期事件
（建表 + 初始化数据），挂载 /api/v1 路由与健康检查端点。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.database import AsyncSessionLocal, init_db
from app.core.logging import get_logger
from app.core.response import ok, register_exception_handlers
from app.db.init_data import init_default_data
from app.providers.storage import STATIC_ROOT

logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时建表并初始化默认数据。

    Args:
        app: FastAPI 应用实例。

    Yields:
        None
    """
    logger.info("应用启动中：开始创建数据表...")
    await init_db()
    logger.info("数据表创建完成。")

    logger.info("开始初始化默认数据...")
    async with AsyncSessionLocal() as session:
        await init_default_data(session)
    logger.info("默认数据初始化完成。")

    yield

    logger.info("应用关闭。")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    Returns:
        FastAPI: 配置完成的应用实例。
    """
    app = FastAPI(
        title="AI漫剧制作平台",
        version="1.0.0",
        description="AI 驱动的漫剧制作平台后端服务",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS：开发期允许所有来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册全局异常处理器
    register_exception_handlers(app)

    # 挂载静态目录：对外服务 Provider 落盘的图片/音频产物（/static/... URL）
    app.mount("/static", StaticFiles(directory=str(STATIC_ROOT)), name="static")

    # 挂载 v1 路由
    app.include_router(api_router, prefix="/api/v1")

    # 根健康检查
    @app.get("/health", summary="健康检查")
    async def root_health() -> dict:
        """根路径健康检查。"""
        return ok(data={"status": "ok"})

    return app


# 应用实例
app = create_app()
