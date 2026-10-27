"""
角色一致性锚点编辑端点冒烟测试（PUT /api/v1/projects/{id}/assets/characters/{cid}/locks）。

覆盖点：
    1. 归属校验：操作他人项目下的角色返回 40301（FORBIDDEN）；
    2. 角色不存在：项目存在但角色 ID 无效返回 40401（NOT_FOUND）；
    3. 白名单校验：请求体携带白名单外键（如 style_tag）被静默忽略，
       不落库、不报错；
    4. 正常更新落库：整体替换语义——非空值覆盖、None/空串清空对应键，
       返回值与 characters.character_locks 落库内容一致；
    5. 参数校验：四字段全为 None（空请求体）返回 40001（PARAM_ERROR）。
"""

import pytest_asyncio
from sqlalchemy import select

from app.core.response import ErrorCode
from app.models import Character

# 统一 API 前缀（与 conftest.API_PREFIX 保持一致，本地定义避免交叉导入）
API_PREFIX = "/api/v1"


def _locks_url(project_id: int, character_id: int) -> str:
    """构造锚点更新端点 URL。

    Args:
        project_id: 项目 ID。
        character_id: 角色 ID。

    Returns:
        str: 完整请求路径。
    """
    return f"{API_PREFIX}/projects/{project_id}/assets/characters/{character_id}/locks"


async def test_update_locks_forbidden_on_other_users_project(
    session_factory, make_character, make_project, auth_client
):
    """归属校验：更新他人项目下角色的锚点返回 40301。

    Args:
        session_factory: 内存库会话工厂夹具。
        make_character: 角色造数夹具。
        make_project: 项目造数夹具。
        auth_client: 已登录的测试客户端（admin，user_id=1）。

    Returns:
        None
    """
    # 归属 user_id=999 的项目（非当前登录用户 admin）
    other_project_id = await make_project(title="他人项目", user_id=999)
    char_id = await make_character(other_project_id)

    resp = await auth_client.put(
        _locks_url(other_project_id, char_id),
        json={"costume": "红色披风"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == ErrorCode.FORBIDDEN
    assert body["data"] is None


async def test_update_locks_character_not_found(make_project, auth_client):
    """角色不存在：项目有效但角色 ID 无效返回 40401。

    Args:
        make_project: 项目造数夹具。
        auth_client: 已登录的测试客户端。

    Returns:
        None
    """
    project_id = await make_project(title="锚点测试项目")
    resp = await auth_client.put(
        _locks_url(project_id, 99999),
        json={"costume": "红色披风"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == ErrorCode.NOT_FOUND
    assert body["message"] == "角色不存在"


async def test_update_locks_ignores_out_of_whitelist_keys(
    session_factory, make_character, make_project, auth_client
):
    """白名单校验：白名单外键（style_tag）被静默忽略。

    Args:
        session_factory: 内存库会话工厂夹具。
        make_character: 角色造数夹具。
        make_project: 项目造数夹具。
        auth_client: 已登录的测试客户端。

    Returns:
        None
    """
    project_id = await make_project(title="白名单测试项目")
    char_id = await make_character(project_id)

    resp = await auth_client.put(
        _locks_url(project_id, char_id),
        json={"costume": "蓝色校服", "style_tag": "赛博朋克"},
    )
    body = resp.json()
    assert body["code"] == 0
    # 白名单外键不进入返回值
    assert body["data"] == {"costume": "蓝色校服"}

    # 落库内容同样不含白名单外键
    async with session_factory() as session:
        result = await session.execute(
            select(Character).where(Character.id == char_id)
        )
        character = result.scalar_one()
        assert character.character_locks == {"costume": "蓝色校服"}


async def test_update_locks_full_replace_and_persist(
    session_factory, make_character, make_project, auth_client
):
    """正常更新落库：整体替换语义（非空覆盖 / None 清空 / 全空清空全部）。

    Args:
        session_factory: 内存库会话工厂夹具。
        make_character: 角色造数夹具。
        make_project: 项目造数夹具。
        auth_client: 已登录的测试客户端。

    Returns:
        None
    """
    project_id = await make_project(title="整体替换测试项目")
    # 预置已有锚点，验证被整体替换而非合并
    char_id = await make_character(
        project_id,
        locks={"costume": "旧服饰", "hairstyle": "旧发型", "appearance": "旧外貌"},
    )

    # ---- 第一次更新：仅提供 costume，其余键（None）被清空 ----
    resp = await auth_client.put(
        _locks_url(project_id, char_id),
        json={"costume": "红色披风"},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {"costume": "红色披风"}

    async with session_factory() as session:
        result = await session.execute(
            select(Character).where(Character.id == char_id)
        )
        character = result.scalar_one()
        assert character.character_locks == {"costume": "红色披风"}

    # ---- 第二次更新：四键全为空串 → 全部清空（空对象）----
    resp = await auth_client.put(
        _locks_url(project_id, char_id),
        json={"costume": "", "hairstyle": "", "appearance": "", "body_type": ""},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {}

    async with session_factory() as session:
        result = await session.execute(
            select(Character).where(Character.id == char_id)
        )
        character = result.scalar_one()
        assert character.character_locks == {}


async def test_update_locks_empty_body_rejected(make_project, auth_client):
    """参数校验：四字段全为 None 的空请求体返回 40001。

    Args:
        make_project: 项目造数夹具。
        auth_client: 已登录的测试客户端。

    Returns:
        None
    """
    project_id = await make_project(title="空请求体测试项目")
    resp = await auth_client.put(_locks_url(project_id, 1), json={})
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == ErrorCode.PARAM_ERROR


async def test_project_not_found(make_project, auth_client):
    """项目不存在：返回 40401。

    Args:
        make_project: 项目造数夹具（此用例仅用于对齐夹具依赖）。
        auth_client: 已登录的测试客户端。

    Returns:
        None
    """
    resp = await auth_client.put(
        _locks_url(99999, 1),
        json={"costume": "红色披风"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == ErrorCode.NOT_FOUND
    assert body["message"] == "项目不存在"


# ============================================================
# 造数辅助：conftest 未提供角色夹具，此处补一个模块级角色构造夹具
# ============================================================


@pytest_asyncio.fixture
def make_character(session_factory):
    """提供「直接落库创建角色」的异步构造函数。

    Args:
        session_factory: 内存库会话工厂夹具。

    Returns:
        Callable: 异步函数 _make_character。
    """

    async def _make_character(
        project_id: int,
        name: str = "小星",
        locks: dict | None = None,
    ) -> int:
        """创建一条角色记录并返回其 ID。

        Args:
            project_id: 所属项目 ID。
            name: 角色名。
            locks: 预置的一致性锚点（character_locks JSON），可空。

        Returns:
            int: 新角色 ID。
        """
        async with session_factory() as session:
            character = Character(
                project_id=project_id,
                name=name,
                visual_prompt=f"{name}的视觉提示词",
                character_locks=locks,
            )
            session.add(character)
            await session.commit()
            await session.refresh(character)
            return character.id

    return _make_character
