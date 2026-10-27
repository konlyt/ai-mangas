"""
REST 关键帧生成链路 multiref 协议对齐测试（08 §7.1 缺陷 4）。

背景：graph 路径（keyframe_agent）已实现多角色 {{ref N}} 参考板协议，
REST 路径（POST /projects/{id}/generate/keyframes → ARQ generate_image）
此前仍是"原提示词直接生成"，与 graph 分叉。本套件验证执行侧改造后
两条路径对同一输入（2 角色：1 有参考板 + 1 无）产出结构一致的提示词。

覆盖点：
    1. REST 与 graph 提示词逐字一致：{{ref 1}} 条款、无参考板角色
       特征卡段（description 退化）、Immutable locks 尾注、逐角色锁定段；
    2. ref_images 项数与内容正确（仅持参考板角色入列，bytes/mime 一致）；
    3. 显式关联失配（character_ids=[99]）保持既有行为：原提示词生成、
       Provider 调用不携带 ref_images；
    4. character_ids 为 NULL：按"全角色分镜"语义关联全部角色（与
       resolve_storyboard_characters 第三分支一致）；
    5. last_ref_dropped 降级语义：Provider 丢弃参考图时任务仍 DONE，
       task.error_message 写入 ref_dropped 标记。
"""

import app.agents.nodes.keyframe_agent as keyframe_agent_module
import app.tasks.image_tasks as image_tasks_module
from app.agents.nodes.keyframe_agent import build_multiref_prompt
from app.models import Character, Storyboard, Task, TaskStatus, TaskType
from app.tasks.image_tasks import generate_image

# 伪造的参考板二进制内容（避免真实下载）
_FAKE_PNG_BYTES = b"\x89PNG-fake-ref-board-bytes"

# 分镜原始提示词（REST 与 graph 共用的输入）
_BASE_PROMPT = "动漫分镜，街头对话"


class FakeImageProvider:
    """测试用伪造图像 Provider：记录调用参数并模拟 last_ref_dropped 标记。

    Attributes:
        calls: 每次 generate 的调用记录（prompt / ref_images）。
        url: generate 返回的伪造图像 URL。
        _drop_ref: 是否模拟"参考图被 Provider 丢弃（降级纯 t2i）"。
        last_ref_dropped: 与真实 Provider 语义一致的降级标记。
    """

    def __init__(self, url: str = "https://fake-image.example/kf.png", drop_ref: bool = False):
        """初始化伪造 Provider。

        Args:
            url: generate 返回的伪造图像 URL。
            drop_ref: 传入参考图时是否置 last_ref_dropped=True。
        """
        self.calls: list[dict] = []
        self.url = url
        self._drop_ref = drop_ref
        self.last_ref_dropped = False

    async def generate(self, prompt: str, ref_images=None, params=None) -> str:
        """记录调用并返回伪造 URL（模拟 Provider 降级语义）。

        Args:
            prompt: 组装后的图像提示词。
            ref_images: 参考图列表（multiref 协议）。
            params: 额外参数（本测试不使用）。

        Returns:
            str: 预置的伪造图像 URL。
        """
        self.calls.append({"prompt": prompt, "ref_images": ref_images})
        self.last_ref_dropped = bool(ref_images) and self._drop_ref
        return self.url


async def _fake_load_image_bytes(url: str) -> bytes:
    """伪造参考板下载：忽略 URL 直接返回固定 PNG 字节。

    Args:
        url: 图像地址（忽略）。

    Returns:
        bytes: 伪造的参考板二进制内容。
    """
    return _FAKE_PNG_BYTES


async def _noop_publish(*args, **kwargs) -> None:
    """伪造任务状态广播（避免测试触碰 Redis）。

    Args:
        *args: 位置参数（忽略）。
        **kwargs: 关键字参数（忽略）。

    Returns:
        None
    """
    return None


async def _seed_storyboard_and_task(
    session_factory,
    make_storyboards,
    make_task,
    project_id: int,
    prompt: str,
    character_ids: list[int] | None,
) -> int:
    """为项目创建分镜（写入提示词与角色关联）并创建 image 任务。

    Args:
        session_factory: 内存库会话工厂夹具。
        make_storyboards: 分镜造数夹具。
        make_task: 任务造数夹具。
        project_id: 项目 ID。
        prompt: 分镜绘图提示词。
        character_ids: 分镜关联角色 ID 列表；None 保持 NULL。

    Returns:
        int: 创建的 image 任务 ID。
    """
    sb_ids = await make_storyboards(project_id, count=1)
    task_id = await make_task(
        project_id,
        task_type=TaskType.IMAGE,
        status=TaskStatus.QUEUED,
        storyboard_id=sb_ids[0],
    )
    async with session_factory() as session:
        sb = await session.get(Storyboard, sb_ids[0])
        sb.prompt = prompt
        if character_ids is not None:
            sb.character_ids = character_ids
        await session.commit()
    return task_id


def _patch_runtime(monkeypatch, session_factory, provider: FakeImageProvider) -> None:
    """为 REST 执行链路打齐 monkeypatch（数据库/Provider/广播/参考板下载）。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存库会话工厂（替换 image_tasks.AsyncSessionLocal）。
        provider: 伪造图像 Provider（替换 _get_image_provider 返回值）。

    Returns:
        None
    """
    monkeypatch.setattr(image_tasks_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(image_tasks_module, "_get_image_provider", lambda name=None: provider)
    monkeypatch.setattr(image_tasks_module, "_publish_task_status", _noop_publish)
    # build_multiref_prompt 内部经 keyframe_agent 命名空间调用 _load_image_bytes，
    # 两条路径（REST/graph）共用该下载入口，patch 一处即全覆盖
    monkeypatch.setattr(keyframe_agent_module, "_load_image_bytes", _fake_load_image_bytes)


def _build_graph_side_characters(char1: Character, char2: Character) -> list[dict]:
    """构造 graph 路径（state 形态）的角色输入，与 REST 侧 DB 数据同源。

    角色 1 与 REST 侧同构（locks 直供特征卡）；角色 2 模拟 graph 侧
    LLM 提取产物 feature_tags={"appearance": description}，与 REST 侧
    _character_to_state_dict 的退化规则产出一致，保证"同一输入"成立。

    Args:
        char1: 角色 1 ORM 对象（有参考板）。
        char2: 角色 2 ORM 对象（无参考板）。

    Returns:
        list[dict]: graph 路径 state.characters 形态的角色列表。
    """
    return [
        {
            "id": char1.id,
            "name": "林小满",
            "ref_board_url": "/static/images/ref-board.png",
            "character_locks": {"costume": "蓝色校服", "hairstyle": "双马尾"},
            "feature_tags": {},
        },
        {
            "id": char2.id,
            "name": "陈默",
            "ref_board_url": None,
            "character_locks": {},
            "feature_tags": {"appearance": "黑衣短发少年，冷峻寡言"},
        },
    ]


async def test_rest_prompt_matches_graph_multiref(
    monkeypatch, session_factory, make_project, make_storyboards, make_task, db_session
):
    """核心一致性：REST 与 graph 对同一输入产出逐字一致的多角色提示词。

    验证 {{ref 1}} 条款、无参考板角色特征卡段（description 退化）、
    Immutable locks 尾注、逐角色锁定段完全一致，且 ref_images 仅含
    持参考板角色的 1 张图（bytes/mime/character_name 正确）。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存库会话工厂夹具。
        make_project: 项目造数夹具。
        make_storyboards: 分镜造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具（读回角色 ORM）。

    Returns:
        None
    """
    project_id = await make_project(title="REST multiref 对齐项目")
    char1 = Character(
        project_id=project_id,
        name="林小满",
        description="16岁高中女生，元气满满",
        visual_prompt="动漫风格女主角",
        ref_board_url="/static/images/ref-board.png",
        character_locks={"costume": "蓝色校服", "hairstyle": "双马尾"},
    )
    char2 = Character(
        project_id=project_id,
        name="陈默",
        description="黑衣短发少年，冷峻寡言",
        visual_prompt="动漫风格男配角",
        ref_board_url=None,
        character_locks=None,
    )
    db_session.add_all([char1, char2])
    await db_session.commit()
    await db_session.refresh(char1)
    await db_session.refresh(char2)

    task_id = await _seed_storyboard_and_task(
        session_factory, make_storyboards, make_task,
        project_id, _BASE_PROMPT, [char1.id, char2.id],
    )

    # 先打齐运行时 patch（REST 与 graph 组装共用同一下载入口，
    # patch 必须先于 graph 侧组装调用，保证两路走同一伪造下载）
    provider = FakeImageProvider()
    _patch_runtime(monkeypatch, session_factory, provider)

    # graph 路径：同输入直接调 keyframe_agent.build_multiref_prompt
    graph_prompt, graph_refs = await build_multiref_prompt(
        _BASE_PROMPT, _build_graph_side_characters(char1, char2)
    )

    # REST 路径：完整执行 generate_image（内存库 + 伪造 Provider）
    result = await generate_image({}, task_id)

    assert result["status"] == "done"
    assert len(provider.calls) == 1
    rest_prompt = provider.calls[0]["prompt"]
    rest_refs = provider.calls[0]["ref_images"]

    # 两路提示词逐字一致（同一协议函数产出）
    assert rest_prompt == graph_prompt
    # {{ref N}} 参考板条款（REST 侧角色无 role 列，role 兜底为"角色"）
    assert "{{ref 1}}：林小满（角色）外观与服装完全一致" in rest_prompt
    assert "{{ref 2}}" not in rest_prompt
    # 无参考板角色特征卡段（REST 侧 description 退化注入）
    assert "陈默：外貌：黑衣短发少年，冷峻寡言" in rest_prompt
    # 逐角色锁定段 + Immutable locks 统一尾注
    assert "林小满锁定：服饰：蓝色校服；发型：双马尾" in rest_prompt
    assert "Immutable locks：服装、发型、画风与参考图严格一致。" in rest_prompt
    # ref_images 项数与内容正确（仅 1 个角色持参考板）
    assert len(rest_refs) == len(graph_refs) == 1
    assert rest_refs[0]["data"] == _FAKE_PNG_BYTES
    assert rest_refs[0]["mime"] == "image/png"
    assert rest_refs[0]["character_name"] == "林小满"
    # 关键帧回写与分镜状态
    sb = await db_session.get(Storyboard, (await db_session.get(Task, task_id)).storyboard_id)
    assert sb.keyframe_url == provider.url
    assert sb.status.value == "done"


async def test_rest_unmatched_character_ids_keeps_legacy_behavior(
    monkeypatch, session_factory, make_project, make_storyboards, make_task, db_session
):
    """显式关联失配（character_ids=[99]）：保持既有行为。

    原提示词直接生成，Provider 调用不携带 ref_images，提示词不含任何
    multiref 注入段。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存库会话工厂夹具。
        make_project: 项目造数夹具。
        make_storyboards: 分镜造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。

    Returns:
        None
    """
    project_id = await make_project(title="REST 失配回退项目")
    task_id = await _seed_storyboard_and_task(
        session_factory, make_storyboards, make_task,
        project_id, _BASE_PROMPT, [99],
    )

    provider = FakeImageProvider()
    _patch_runtime(monkeypatch, session_factory, provider)
    result = await generate_image({}, task_id)

    assert result["status"] == "done"
    assert len(provider.calls) == 1
    # 关键断言：原提示词 + 无参考图参数（既有行为零变化）
    assert provider.calls[0]["prompt"] == _BASE_PROMPT
    assert provider.calls[0]["ref_images"] is None


async def test_rest_null_character_ids_links_all_characters(
    monkeypatch, session_factory, make_project, make_storyboards, make_task, db_session
):
    """character_ids 为 NULL：按"全角色分镜"语义关联全部角色。

    与 resolve_storyboard_characters 第三分支（graph 路径语义）一致：
    2 个角色全部参与组装，仅 1 个持参考板者进入 ref_images。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存库会话工厂夹具。
        make_project: 项目造数夹具。
        make_storyboards: 分镜造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。

    Returns:
        None
    """
    project_id = await make_project(title="REST 全角色分镜项目")
    char1 = Character(
        project_id=project_id,
        name="林小满",
        description="16岁高中女生，元气满满",
        visual_prompt="动漫风格女主角",
        ref_board_url="/static/images/ref-board.png",
        character_locks={"costume": "蓝色校服"},
    )
    char2 = Character(
        project_id=project_id,
        name="陈默",
        description="黑衣短发少年，冷峻寡言",
        visual_prompt="动漫风格男配角",
        ref_board_url=None,
        character_locks=None,
    )
    db_session.add_all([char1, char2])
    await db_session.commit()

    task_id = await _seed_storyboard_and_task(
        session_factory, make_storyboards, make_task,
        project_id, _BASE_PROMPT, None,  # NULL → 全角色
    )

    provider = FakeImageProvider()
    _patch_runtime(monkeypatch, session_factory, provider)
    result = await generate_image({}, task_id)

    assert result["status"] == "done"
    prompt = provider.calls[0]["prompt"]
    # 全角色注入：参考板条款 + 退化特征卡段同时存在
    assert "{{ref 1}}：林小满（角色）外观与服装完全一致" in prompt
    assert "陈默：外貌：黑衣短发少年，冷峻寡言" in prompt
    assert "Immutable locks" in prompt
    # ref_images 项数正确：仅 1 个角色持参考板
    assert len(provider.calls[0]["ref_images"]) == 1


async def test_rest_ref_dropped_marks_error_message(
    monkeypatch, session_factory, make_project, make_storyboards, make_task, db_session
):
    """last_ref_dropped 降级语义：Provider 丢弃参考图时任务仍完成。

    task.error_message 写入 ref_dropped 标记（与 graph 路径
    sb["ref_dropped"]=True 同款降级语义），状态仍为 DONE，关键帧正常回写。

    Args:
        monkeypatch: pytest 夹具。
        session_factory: 内存库会话工厂夹具。
        make_project: 项目造数夹具。
        make_storyboards: 分镜造数夹具。
        make_task: 任务造数夹具。
        db_session: 数据库会话夹具。

    Returns:
        None
    """
    project_id = await make_project(title="REST 降级标记项目")
    char1 = Character(
        project_id=project_id,
        name="林小满",
        description="16岁高中女生",
        visual_prompt="动漫风格女主角",
        ref_board_url="/static/images/ref-board.png",
        character_locks={"costume": "蓝色校服"},
    )
    db_session.add(char1)
    await db_session.commit()

    task_id = await _seed_storyboard_and_task(
        session_factory, make_storyboards, make_task,
        project_id, _BASE_PROMPT, [char1.id],
    )

    provider = FakeImageProvider(drop_ref=True)
    _patch_runtime(monkeypatch, session_factory, provider)
    result = await generate_image({}, task_id)

    assert result["status"] == "done"
    # 关键断言：任务正常完成 + error_message 携带降级标记
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.DONE
    assert task.error_message is not None
    assert task.error_message.startswith("ref_dropped")
    assert task.result_url == provider.url
