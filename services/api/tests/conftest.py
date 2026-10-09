"""
pytest 冒烟测试套件全局夹具（conftest）。

职责与覆盖点：
    1. 环境隔离：在任何 app 模块导入之前，将真实凭证相关环境变量置空，
       并直接覆写 settings 单例属性，确保测试绝不读取真实 .env 中的
       AGNES/DeepSeek 凭证发起外部请求（LLM 进入 mock 模式、
       Agnes Provider 未配置 Key 时走内部 mock 降级）；
    2. 数据库隔离：使用 sqlite+aiosqlite 内存库（StaticPool 共享同一连接），
       基于 Base.metadata.create_all 建表，完全不依赖真实 MySQL；
       并将 BigInteger 主键在测试元数据中替换为 Integer 以兼容 SQLite 自增；
    3. 应用夹具：通过 httpx ASGITransport 构建异步测试客户端，
       不触发 lifespan（不触碰真实 MySQL/Redis），并覆盖 get_db 依赖；
    4. 鉴权夹具：直接向 users 表插入 admin 用户（hash_password("123456")），
       用 create_access_token({"sub": "<user_id>"}) 签发 Bearer Token；
    5. 造数辅助：以 fixture 形式提供项目 / 剧本 / 分镜 / 任务的快捷构造函数，
       供各测试模块直接在内存库中准备前置数据。
"""

import os
from typing import AsyncGenerator, Callable

# ============================================================
# 环境隔离（必须在导入任何 app 模块之前执行）
# pydantic-settings 的取值优先级为 环境变量 > .env 文件，
# 将环境变量显式置空即可屏蔽真实 .env 中的凭证。
# ============================================================

_ISOLATED_ENV_KEYS: tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "AGNES_BASE_URL",
    "AGNES_LLM_API_KEY",
    "AGNES_LLM_MODEL",
    "AGNES_IMAGE_API_KEY",
    "AGNES_IMAGE_MODEL",
    "AGNES_VIDEO_API_KEY",
    "AGNES_VIDEO_MODEL",
    "AGNES_VIDEO_BASE_URL",
)

for _key in _ISOLATED_ENV_KEYS:
    os.environ[_key] = ""

# 测试环境 LLM 策略：显式改用 mock 占位文本、并关闭直连 HTTP 兜底，
# 保证测试既不访问外网也不依赖真实模型（默认配置下生产环境两者相反）。
os.environ["LLM_ALLOW_MOCK_FALLBACK"] = "true"
os.environ["LLM_ENABLE_HTTP_FALLBACK"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import Integer, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402, F401  —— 确保全部模型表注册进 Base.metadata
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import (  # noqa: E402
    Project,
    QueueName,
    Script,
    Storyboard,
    Task,
    TaskStatus,
    TaskType,
    User,
)

# 兜底加固：settings 单例若在导入前已从 .env 读到真实凭证，这里直接清空，
# 保证 LLM 客户端进入 mock 模式、Agnes Provider 走未配置/降级路径。
for _key in _ISOLATED_ENV_KEYS:
    setattr(settings, _key, "")

# 同步覆写 LLM 策略开关（settings 单例可能已在导入前从 .env 读到生产值）
settings.LLM_ALLOW_MOCK_FALLBACK = True
settings.LLM_ENABLE_HTTP_FALLBACK = False

# 测试默认用户 ID（与 admin 夹具插入的用户一致）
TEST_USER_ID = 1

# 统一 API 前缀
API_PREFIX = "/api/v1"


def _patch_bigint_primary_keys_for_sqlite() -> None:
    """将 Base.metadata 中的 BigInteger 主键替换为 Integer，以兼容 SQLite。

    SQLite 仅对声明类型恰好为 INTEGER 的主键列启用 rowid 自增别名，
    BIGINT PRIMARY KEY 不会自增，插入缺省 id 时会报 NOT NULL 约束错误。

    Returns:
        None
    """
    from sqlalchemy import BigInteger

    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if column.primary_key and isinstance(column.type, BigInteger):
                column.type = Integer()


def _dedupe_index_names_for_sqlite() -> None:
    """为 SQLite 全局唯一化 Base.metadata 中的索引名。

    MySQL 的索引名仅在表内唯一，而 SQLite 的索引名是 schema 级全局唯一；
    业务模型中多张表复用了相同索引名（idx_project_id / idx_status /
    idx_project_time），在 SQLite 建表时会产生
    "index already exists" 错误。此处为重名索引附加表名前缀，
    仅作用于测试进程内的元数据，不修改任何业务代码。

    Returns:
        None
    """
    seen: set[str] = set()
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            if index.name in seen:
                # 附加表名前缀保证全局唯一（Index.name 为可写实例属性，
                # 建表 DDL 在 create_all 时才生成，改名即时生效）
                index.name = f"ix_{table.name}_{index.name}"
            seen.add(index.name)


# 模块导入时执行一次（两处处理均幂等：Integer 非 BigInteger 实例；
# 改名后的索引再次进入 seen 集合不会重复改名）
_patch_bigint_primary_keys_for_sqlite()
_dedupe_index_names_for_sqlite()


# ============================================================
# 数据库夹具（每个测试独享一个全新内存库）
# ============================================================


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator:
    """每个测试独享的内存 SQLite 异步引擎。

    使用 StaticPool 让所有会话共享同一条底层连接，
    保证 create_all 建出的表在整个测试期间可见。

    Yields:
        AsyncEngine: 已完成建表的异步引擎实例。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine) -> async_sessionmaker:
    """绑定内存库的异步会话工厂。

    Args:
        db_engine: 内存 SQLite 引擎夹具。

    Returns:
        async_sessionmaker: expire_on_commit=False 的会话工厂，
        便于测试在 commit 后继续读取 ORM 属性。
    """
    return async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """供测试直接造数 / 断言使用的数据库会话。

    Args:
        session_factory: 会话工厂夹具。

    Yields:
        AsyncSession: 异步数据库会话。
    """
    async with session_factory() as session:
        yield session


# ============================================================
# 应用 / 客户端 / 鉴权夹具
# ============================================================


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncGenerator[httpx.AsyncClient, None]:
    """挂载内存库的 FastAPI 异步测试客户端。

    通过 app.dependency_overrides 覆盖 get_db 依赖指向内存 SQLite；
    使用 httpx.ASGITransport 直接调用 ASGI 应用，不运行 lifespan，
    因此不会触发真实 MySQL 建表与默认数据初始化。

    Args:
        session_factory: 内存库会话工厂夹具。

    Yields:
        httpx.AsyncClient: 可直接请求 /api/v1/* 的测试客户端。
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        """替代 get_db 的依赖：从内存库会话工厂创建请求级会话。

        Yields:
            AsyncSession: 异步数据库会话。
        """
        async with session_factory() as session:
            try:
                yield session
            finally:
                await session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    fastapi_app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def admin_user(session_factory) -> User:
    """直接在 users 表插入一个 admin 用户（等价于验证脚本的做法）。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        User: 已落库的 admin 用户 ORM 对象（id 一般为 1）。
    """
    async with session_factory() as session:
        user = User(
            username="admin",
            password_hash=hash_password("123456"),
            quota=1000,
            status=1,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def auth_headers(admin_user) -> dict[str, str]:
    """为 admin 用户签发 JWT 并返回 Bearer 请求头。

    Args:
        admin_user: 已插入的 admin 用户夹具。

    Returns:
        dict[str, str]: 形如 {"Authorization": "Bearer <token>"} 的请求头。
    """
    token = create_access_token({"sub": str(admin_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_client(client, auth_headers) -> httpx.AsyncClient:
    """已登录（自动携带 admin Token）的测试客户端。

    Args:
        client: 基础测试客户端夹具。
        auth_headers: Bearer 请求头夹具。

    Returns:
        httpx.AsyncClient: 后续请求均自动携带鉴权头的客户端。
    """
    client.headers.update(auth_headers)
    return client


# ============================================================
# 造数辅助夹具（返回异步构造函数，供各测试模块按需调用）
# ============================================================


@pytest_asyncio.fixture
def make_project(session_factory) -> Callable:
    """提供「直接落库创建项目」的异步构造函数。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        Callable: 异步函数 _make_project。
    """

    async def _make_project(title: str = "种子项目", user_id: int = TEST_USER_ID) -> int:
        """创建一条项目记录并返回其 ID。

        Args:
            title: 项目标题。
            user_id: 归属用户 ID。

        Returns:
            int: 新项目 ID。
        """
        async with session_factory() as session:
            project = Project(user_id=user_id, title=title)
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return project.id

    return _make_project


@pytest_asyncio.fixture
def make_script(session_factory) -> Callable:
    """提供「直接落库创建剧本」的异步构造函数。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        Callable: 异步函数 _make_script。
    """

    async def _make_script(project_id: int, scene_count: int = 7) -> int:
        """为指定项目创建含 N 个场次的剧本并返回其 ID。

        Args:
            project_id: 项目 ID。
            scene_count: scenes 场次数量（默认 7，可整除出 3 个自动分集）。

        Returns:
            int: 新剧本 ID。
        """
        content = {
            "title": "冒烟测试剧本",
            "characters": [{"name": "小星", "role": "主角"}],
            "scenes": [
                {
                    "scene_id": idx,
                    "title": f"第{idx}场",
                    "description": "小星发现了神秘装置并展开一段冒险",
                    "dialogue": "这是怎么回事？",
                }
                for idx in range(1, scene_count + 1)
            ],
        }
        async with session_factory() as session:
            script = Script(
                project_id=project_id,
                content=content,
                raw_text="冒烟测试原始文本",
                version=1,
            )
            session.add(script)
            await session.commit()
            await session.refresh(script)
            return script.id

    return _make_script


@pytest_asyncio.fixture
def make_storyboards(session_factory) -> Callable:
    """提供「直接落库批量创建分镜」的异步构造函数。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        Callable: 异步函数 _make_storyboards。
    """

    async def _make_storyboards(
        project_id: int, count: int = 3, script_id: int | None = None
    ) -> list[int]:
        """为指定项目创建 count 条分镜（sequence 从 1 递增）并返回 ID 列表。

        Args:
            project_id: 项目 ID。
            count: 分镜数量。
            script_id: 关联剧本 ID；为 None 时自动创建一条单场次剧本。

        Returns:
            list[int]: 按 sequence 升序排列的分镜 ID 列表。
        """
        if script_id is None:
            script_id = await _make_script_for_storyboard(project_id)
        async with session_factory() as session:
            storyboards = [
                Storyboard(
                    project_id=project_id,
                    script_id=script_id,
                    sequence=seq,
                    duration=5,
                )
                for seq in range(1, count + 1)
            ]
            session.add_all(storyboards)
            await session.commit()
            result = await session.execute(
                select(Storyboard.id)
                .where(Storyboard.project_id == project_id)
                .order_by(Storyboard.sequence)
            )
            return [row[0] for row in result.all()]

    async def _make_script_for_storyboard(project_id: int) -> int:
        """为分镜补一条最小剧本记录（script_id 非空约束）。

        Args:
            project_id: 项目 ID。

        Returns:
            int: 新剧本 ID。
        """
        async with session_factory() as session:
            script = Script(
                project_id=project_id,
                content={"title": "分镜配套剧本", "scenes": []},
                version=1,
            )
            session.add(script)
            await session.commit()
            await session.refresh(script)
            return script.id

    return _make_storyboards


@pytest_asyncio.fixture
def make_task(session_factory) -> Callable:
    """提供「直接落库创建任务」的异步构造函数。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        Callable: 异步函数 _make_task。
    """

    async def _make_task(
        project_id: int,
        task_type: TaskType = TaskType.VIDEO,
        status: TaskStatus = TaskStatus.DONE,
        storyboard_id: int | None = None,
    ) -> int:
        """为指定项目创建一条任务记录并返回其 ID。

        Args:
            project_id: 项目 ID。
            task_type: 任务类型（默认 video）。
            status: 任务状态（默认 done）。
            storyboard_id: 关联分镜 ID（可空）。

        Returns:
            int: 新任务 ID。
        """
        async with session_factory() as session:
            task = Task(
                project_id=project_id,
                storyboard_id=storyboard_id,
                type=task_type,
                status=status,
                queue_name=QueueName.NORMAL,
                idempotency_key=f"smoke-{os.urandom(8).hex()}",
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task.id

    return _make_task


# 复用 make_project 造项目（供 make_storyboards 内部不再额外造项目）
@pytest_asyncio.fixture
def make_project_with_storyboards(make_project, make_storyboards) -> Callable:
    """提供「项目 + N 条分镜」一站式造数函数。

    Args:
        make_project: 项目造数夹具。
        make_storyboards: 分镜造数夹具。

    Returns:
        Callable: 异步函数 _make_project_with_storyboards。
    """

    async def _make_project_with_storyboards(count: int = 3) -> dict:
        """创建项目并为其造 count 条分镜。

        Args:
            count: 分镜数量。

        Returns:
            dict: {"project_id": int, "storyboard_ids": list[int]}。
        """
        project_id = await make_project(title="分镜测试项目")
        storyboard_ids = await make_storyboards(project_id, count=count)
        return {"project_id": project_id, "storyboard_ids": storyboard_ids}

    return _make_project_with_storyboards
