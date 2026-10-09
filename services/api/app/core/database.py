"""
数据库引擎与会话模块。

基于 SQLAlchemy 2.0 asyncio 构建异步引擎、会话工厂与 Base 声明基类，
提供 get_db 依赖注入和 init_db 建表函数。
引擎与会话工厂采用惰性初始化，仅在首次使用时加载 asyncmy 驱动，
便于模块在未安装驱动的环境下也能被 import。

注意：数据库 Schema 变更的正式通道为 Alembic 迁移（services/api/alembic），
start.ps1 启动时执行 `alembic upgrade head`；init_db 中的 create_all 仅为
ENV=development 且库中无表时的兜底手段，不得用于正式建表/改表。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""

    pass


# 惰性缓存
_engine = None
_session_factory = None


def get_engine():
    """获取（必要时创建）异步数据库引擎。

    Returns:
        AsyncEngine: SQLAlchemy 异步引擎实例。
    """
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.get_database_url(),
            echo=settings.ENV == "development",
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            future=True,
        )
    return _engine


def get_session_factory():
    """获取（必要时创建）异步会话工厂。

    Returns:
        async_sessionmaker: 异步会话工厂。
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def AsyncSessionLocal(**kwargs):
    """创建一个新的异步数据库会话。

    以函数形式暴露，保持与原 async_sessionmaker 相同的调用方式：
    `async with AsyncSessionLocal() as session:`。

    Args:
        **kwargs: 透传给会话工厂的参数。

    Returns:
        AsyncSession: 异步数据库会话。
    """
    return get_session_factory()(**kwargs)


# 引擎对外别名（惰性）
engine = get_engine


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供一个异步数据库会话并在请求结束后关闭。

    Yields:
        AsyncSession: 异步数据库会话对象。
    """
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """创建所有继承自 Base 的数据表（仅 development 兜底用）。

    正式的 Schema 变更通道是 Alembic 迁移（start.ps1 启动时执行
    `alembic upgrade head`）；本函数仅在 ENV=development 且库中无表时
    作为兜底建表手段，不应作为建表/改表的常规方式。

    Returns:
        None
    """
    # 确保所有模型被注册到 Base.metadata
    import app.models  # noqa: F401

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
