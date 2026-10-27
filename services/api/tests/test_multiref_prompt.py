"""
多角色 {{ref N}} 注入协议（方案 A5/A6）纯函数测试。

覆盖点：
    1. build_multiref_prompt：混合角色（1 有参考板 + 1 无参考板）——
       {{ref 1}} 条款、无参考板角色特征卡段、Immutable locks 尾注、
       ref_images 数量与结构正确；
    2. 多角色均持参考板：{{ref 1}}/{{ref 2}} 编号递增、ref_images 数量正确；
    3. 参考板下载失败：该角色回退特征卡段、ref_images 为空；
    4. 空角色列表：返回原提示词与空参考图列表；
    5. resolve_storyboard_characters：character_ids 匹配 / 显式空关联 /
       无显式关联回退全部角色 / character_names 匹配；
    6. build_feature_card_text：character_locks 优先覆盖 feature_tags。
"""

import app.agents.nodes.keyframe_agent as keyframe_agent_module
from app.agents.nodes.consistency_agent import (
    build_feature_card_text,
    resolve_storyboard_characters,
)
from app.agents.nodes.keyframe_agent import build_multiref_prompt

_FAKE_PNG_BYTES = b"\x89PNG-fake-ref-board-bytes"


async def test_build_multiref_prompt_mixed_characters(monkeypatch):
    """混合角色：1 有参考板 + 1 无参考板 → {{ref 1}} 条款 + 特征卡段 + locks 尾注。

    Args:
        monkeypatch: pytest 夹具，用于伪造参考板下载。

    Returns:
        None
    """

    async def _fake_load(url: str) -> bytes:
        """伪造图像加载：直接返回固定 PNG 字节。

        Args:
            url: 图像地址（忽略）。

        Returns:
            bytes: 伪造的参考板二进制内容。
        """
        return _FAKE_PNG_BYTES

    monkeypatch.setattr(keyframe_agent_module, "_load_image_bytes", _fake_load)

    characters = [
        {
            "name": "林小满",
            "role": "主角",
            "ref_board_url": "/static/images/ref-board.png",
            "character_locks": {"costume": "蓝色校服", "hairstyle": "双马尾"},
        },
        {
            "name": "陈默",
            "role": "配角",
            "ref_board_url": None,
            "feature_tags": {"costume": "黑色风衣", "hairstyle": "短发", "style_tag": "赛博动漫"},
        },
    ]
    prompt, ref_images = await build_multiref_prompt("动漫分镜，街头对话", characters)

    # {{ref N}} 条款（含角色名与 role）
    assert "{{ref 1}}" in prompt
    assert "{{ref 1}}：林小满（主角）外观与服装完全一致" in prompt
    assert "{{ref 2}}" not in prompt  # 仅 1 个角色有参考板
    # 无参考板角色回退特征卡段
    assert "陈默：服饰：黑色风衣；发型：短发；画风：赛博动漫" in prompt
    # Immutable locks 统一尾注 + 逐角色锁（仅带 character_locks 的角色）
    assert "Immutable locks：服装、发型、画风与参考图严格一致。" in prompt
    assert "林小满锁定：服饰：蓝色校服；发型：双马尾" in prompt
    # ref_images 数量与结构正确
    assert len(ref_images) == 1
    assert ref_images[0]["data"] == _FAKE_PNG_BYTES
    assert ref_images[0]["mime"] == "image/png"
    assert ref_images[0]["character_name"] == "林小满"


async def test_build_multiref_prompt_all_with_ref_boards(monkeypatch):
    """多角色均持参考板：{{ref 1}}/{{ref 2}} 编号递增，ref_images 依次对应。

    Args:
        monkeypatch: pytest 夹具，用于伪造参考板下载。

    Returns:
        None
    """

    async def _fake_load(url: str) -> bytes:
        """伪造图像加载：按 URL 区分返回内容。

        Args:
            url: 图像地址。

        Returns:
            bytes: 与 URL 相关的伪造字节。
        """
        return b"ref-" + url.encode("utf-8")

    monkeypatch.setattr(keyframe_agent_module, "_load_image_bytes", _fake_load)

    characters = [
        {"name": "甲", "role": "主角", "ref_board_url": "/static/images/a.png"},
        {"name": "乙", "role": "配角", "ref_board_url": "/static/images/b.jpg"},
    ]
    prompt, ref_images = await build_multiref_prompt("分镜", characters)

    assert "{{ref 1}}：甲（主角）外观与服装完全一致" in prompt
    assert "{{ref 2}}：乙（配角）外观与服装完全一致" in prompt
    assert len(ref_images) == 2
    assert ref_images[0]["mime"] == "image/png"
    assert ref_images[1]["mime"] == "image/jpeg"  # 后缀推断 MIME
    assert [item["character_name"] for item in ref_images] == ["甲", "乙"]


async def test_build_multiref_prompt_download_failure_falls_back(monkeypatch):
    """参考板下载失败：该角色回退特征卡段，ref_images 为空，不抛异常。

    Args:
        monkeypatch: pytest 夹具，用于让参考板下载抛错。

    Returns:
        None
    """

    async def _broken_load(url: str) -> bytes:
        """伪造图像加载失败。

        Args:
            url: 图像地址（忽略）。

        Returns:
            bytes: 永远不会返回。

        Raises:
            ValueError: 模拟下载失败。
        """
        raise ValueError("图像下载失败")

    monkeypatch.setattr(keyframe_agent_module, "_load_image_bytes", _broken_load)

    characters = [
        {
            "name": "林小满",
            "ref_board_url": "/static/images/ref-board.png",
            "character_locks": {"costume": "蓝色校服"},
        },
    ]
    prompt, ref_images = await build_multiref_prompt("分镜", characters)

    assert "{{ref" not in prompt  # 无参考图条款
    assert "林小满：服饰：蓝色校服" in prompt  # 回退特征卡段
    assert "Immutable locks" in prompt
    assert ref_images == []


async def test_build_multiref_prompt_empty_characters():
    """空角色列表：返回原提示词与空参考图列表。

    Returns:
        None
    """
    prompt, ref_images = await build_multiref_prompt("原始分镜", [])
    assert prompt == "原始分镜"
    assert ref_images == []


def test_resolve_storyboard_characters_by_ids():
    """character_ids 显式关联：按角色 id 匹配（str/int 容错）。

    Returns:
        None
    """
    characters = [
        {"id": 1, "name": "甲"},
        {"id": 2, "name": "乙"},
        {"id": 3, "name": "丙"},
    ]
    linked = resolve_storyboard_characters({"character_ids": ["1", 3]}, characters)
    assert [c["name"] for c in linked] == ["甲", "丙"]


def test_resolve_storyboard_characters_explicit_empty_returns_empty():
    """显式空关联（character_ids=[]）：返回空列表（调用方回退旧逻辑）。

    Returns:
        None
    """
    characters = [{"id": 1, "name": "甲"}]
    assert resolve_storyboard_characters({"character_ids": []}, characters) == []
    assert resolve_storyboard_characters({"character_ids": [99]}, characters) == []


def test_resolve_storyboard_characters_no_explicit_link_returns_all():
    """无显式关联字段：视为全角色分镜，返回全部角色。

    Returns:
        None
    """
    characters = [{"name": "甲"}, {"name": "乙"}]
    linked = resolve_storyboard_characters({"sequence": 1}, characters)
    assert len(linked) == 2


def test_resolve_storyboard_characters_by_names():
    """character_names 显式关联：按角色名匹配。

    Returns:
        None
    """
    characters = [{"name": "甲"}, {"name": "乙"}]
    linked = resolve_storyboard_characters({"character_names": ["乙"]}, characters)
    assert [c["name"] for c in linked] == ["乙"]


def test_build_feature_card_text_locks_override_feature_tags():
    """特征卡：character_locks 优先覆盖 feature_tags 同名字段。

    Returns:
        None
    """
    char = {
        "name": "林小满",
        "feature_tags": {"costume": "旧外套", "hairstyle": "长发", "style_tag": "水墨"},
        "character_locks": {"costume": "蓝色校服"},
    }
    text = build_feature_card_text(char)
    assert "服饰：蓝色校服" in text  # locks 覆盖 feature_tags
    assert "旧外套" not in text
    assert "发型：长发" in text
    assert "画风：水墨" in text
    assert text.startswith("林小满：")


def test_build_feature_card_text_no_features_returns_name():
    """无任何有效特征字段：仅返回角色名。

    Returns:
        None
    """
    assert build_feature_card_text({"name": "路人"}) == "路人"
