"""
Alembic 环境配置。

Alembic 为本项目唯一的数据库 Schema 变更通道（建表、改表均通过迁移管理）。
使用 SQLAlchemy Base.metadata 作为迁移目标，连接串复用 Settings.get_database_url，
将异步驱动 asyncmy 替换为同步驱动 pymysql（Alembic 迁移在同步引擎上执行）。

Raises:
    ModuleNotFoundError: venv 缺少 pymysql 驱动时抛出。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.database import Base
from app.core.config import settings

# 确保所有模型被导入并注册到 Base.metadata
import app.models  # noqa: F401,E402

config = context.config

# 使用 settings 中的数据库连接（同步驱动）：asyncmy -> pymysql
config.set_main_option(
    "sqlalchemy.url",
    settings.get_database_url().replace("mysql+asyncmy", "mysql+pymysql"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 迁移目标元数据：包含 app.models 中注册的全部 16 张表
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式运行迁移（不连接数据库，仅输出 SQL）。

    Returns:
        None
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )


def run_migrations_online() -> None:
    """在线模式运行迁移（连接数据库执行 DDL）。

    Returns:
        None

    Raises:
        OperationalError: 数据库连接失败（MySQL 未启动或账号错误）时抛出。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
