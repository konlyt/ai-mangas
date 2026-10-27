"""
关键帧生成 Agent 节点（KeyframeAgent）。

职责：
    为每个分镜生成首帧与尾帧图像，编排图像生成任务，
    将关键帧 URL 写入各分镜并更新 state.storyboards。

多角色注入协议（方案 A5）：
    按分镜关联角色（resolve_storyboard_characters）组装多角色一致性提示词：
        - 持有四视图参考板（ref_board_url）的角色：下载参考板图并按
          {{ref N}} 协议注入（N 为参考图序号，从 1 递增），参考图经
          ref_images 参数传给图像 Provider（i2i）；
        - 无参考板或参考板下载失败的角色：回退特征卡文本段约束；
        - 全部角色追加 Immutable locks 尾注（携带 character_locks 的角色
          额外逐角色列出锁定字段）。
    生成后读取 Provider 实例的 last_ref_dropped 标记：参考图被丢弃
    （i2i 失败降级纯 t2i）时记录告警并在分镜上标记 ref_dropped=True——
    此时特征卡内容仍在提示词中，画面约束不丢失。
    分镜解析不出关联角色时回退旧逻辑（主角色特征卡注入），行为零变化。

输入（来自 state）：
    - storyboards: 分镜列表。
    - characters: 角色列表（含 name/role/ref_board_url/character_locks/feature_tags 等）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - storyboards: 更新后的分镜列表（含 keyframe_url/endframe_url，以及
      多角色注入标记 ref_count / ref_character_names / ref_dropped，
      供一致性校验判定 check_mode）。
    - stage: 下一阶段 "consistency"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.agents.nodes.asset_agent import REF_BOARD_LOCK_KEYS
from app.agents.nodes.consistency_agent import (
    _load_image_bytes,
    build_consistent_prompt,
    build_feature_card_text,
    extract_feature_tags,
    resolve_storyboard_characters,
)
from app.core.logging import get_logger
from app.providers.image.registry import get_image_registry
from app.providers.llm.litellm_client import get_llm

logger = get_logger()

# Immutable locks 统一尾注（方案 A5：多角色不可变锚点强约束）
_IMMUTABLE_LOCKS_TAIL = "Immutable locks：服装、发型、画风与参考图严格一致。绝对禁止多格分镜、绝对禁止对话气泡、绝对禁止字幕、绝对禁止编号、绝对禁止水印，只生成一整张完整画面。"

# character_locks 锁定字段中文名映射（与 asset_agent._REF_BOARD_LOCK_LABELS 保持一致）
_LOCK_LABELS = {
    "costume": "服饰",
    "hairstyle": "发型",
    "appearance": "外貌",
    "body_type": "体型",
}

# 参考板 URL 后缀到 MIME 类型的映射（未命中后缀时默认 image/png）
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _guess_image_mime(image_url: str) -> str:
    """根据图像 URL 后缀推断 MIME 类型（内部辅助函数）。

    Args:
        image_url: 图像访问地址（查询参数部分会被剥离后再匹配后缀）。

    Returns:
        str: MIME 类型字符串；后缀无法识别时默认 "image/png"。
    """
    url = (image_url or "").split("?")[0].lower()
    for suffix, mime in _MIME_BY_SUFFIX.items():
        if url.endswith(suffix):
            return mime
    return "image/png"


def _build_role_lock_text(char: dict) -> str:
    """构造单角色的锁定描述段（Immutable locks 逐角色部分，内部辅助函数）。

    Args:
        char: 角色字典（含 name / character_locks）。

    Returns:
        str: 形如 "{name}锁定：服饰…；发型…" 的文本；
            角色无有效锁字段时返回空字符串。
    """
    name = str(char.get("name", "")).strip() or "未命名角色"
    locks = char.get("character_locks")
    if not isinstance(locks, dict):
        return ""
    parts = [
        f"{_LOCK_LABELS[key]}：{str(locks[key]).strip()}"
        for key in REF_BOARD_LOCK_KEYS
        if locks.get(key) and str(locks.get(key)).strip()
    ]
    if not parts:
        return ""
    return f"{name}锁定：{'；'.join(parts)}"


async def build_multiref_prompt(base_prompt: str, characters: list[dict]) -> tuple[str, list[dict]]:
    """按多角色 {{ref N}} 协议组装图像生成提示词（方案 A5）。

    组装规则：
        - 有 ref_board_url 且下载成功的角色：提示词追加
          "{{ref N}}：{name}（{role}）外观与服装完全一致"（N 从 1 递增，
          与 ref_images 列表顺序一一对应），参考板图（bytes）收进 ref_images，
          每项形如 {"data": bytes, "mime": str, "character_name": str}
          （character_name 为附加元数据，Provider 只消费 data/mime）；
        - 无 ref_board_url 或参考板下载失败的角色：回退特征卡文本段
          （build_feature_card_text，character_locks 优先 + feature_tags 补充）；
        - 所有角色追加 Immutable locks 统一尾注；携带 character_locks 的
          角色额外逐角色列出锁定字段。

    Args:
        base_prompt: 分镜原始绘图提示词。
        characters: 分镜关联角色列表（含 name/role/ref_board_url/
            character_locks/feature_tags）。

    Returns:
        tuple[str, list[dict]]: (组装后的提示词, 参考图列表)。
            characters 为空时返回 (base_prompt, [])。

    Raises:
        无：单张参考板下载失败仅记录告警并回退该角色特征卡段，不向上抛出。
    """
    if not characters:
        return base_prompt, []

    ref_clauses: list[str] = []
    card_clauses: list[str] = []
    ref_images: list[dict] = []

    for char in characters:
        name = str(char.get("name", "")).strip() or "未命名角色"
        role = str(char.get("role", "") or "角色").strip()
        board_url = str(char.get("ref_board_url") or "").strip()

        if board_url:
            try:
                image_bytes = await _load_image_bytes(board_url)
            except Exception as exc:  # noqa: BLE001
                # 下载失败：该角色回退特征卡段（画面约束不丢失）
                logger.warning(f"[keyframe_agent] 角色 {name} 参考板下载失败，回退特征卡约束: {exc}")
                image_bytes = None
            if image_bytes is not None:
                ref_index = len(ref_images) + 1
                ref_images.append({
                    "data": image_bytes,
                    "mime": _guess_image_mime(board_url),
                    "character_name": name,
                })
                ref_clauses.append(f"{{{{ref {ref_index}}}}}：{name}（{role}）外观与服装完全一致")
                continue

        card_clauses.append(build_feature_card_text(char))

    clauses = ref_clauses + card_clauses
    # 开头强制声明：单张电影关键帧画面（避免模型自由发挥成多格漫画页）
    prompt = f"单张电影关键帧画面，完整单幅构图，{base_prompt}，【多角色一致性参考】{'；'.join(clauses)}。"

    lock_clauses = [
        text for text in (_build_role_lock_text(char) for char in characters) if text
    ]
    if lock_clauses:
        prompt += "；".join(lock_clauses) + "。"
    prompt += _IMMUTABLE_LOCKS_TAIL
    return prompt, ref_images


async def keyframe_agent_node(state: ProductionState) -> dict:
    """关键帧生成节点。

    为每个分镜生成首帧与尾帧图像。生成前按分镜关联角色组装多角色
    一致性提示词（{{ref N}} 参考板协议 + 特征卡回退 + Immutable locks
    尾注），参考图经 ref_images 传入 Provider 并在生成后检查
    last_ref_dropped 标记；分镜解析不出关联角色时回退旧逻辑
    （主角色特征卡注入，主角色缺 feature_tags 时现场调用 LLM 提取一次并复用）。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 storyboards 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    storyboards = state.get("storyboards", []) or []
    characters = state.get("characters", []) or []

    logger.info(f"[keyframe_agent] 开始生成关键帧 project_id={project_id}, count={len(storyboards)}")

    registry = get_image_registry()
    image_provider = registry.get_provider()

    # 回退路径准备：分镜解析不出关联角色时按旧逻辑注入主角色特征卡。
    # 若角色列表中已携带 feature_tags 则直接复用；
    # 否则现场调用 LLM 提取一次，供回退分镜复用，避免重复调用。
    llm = get_llm("agnes")
    reference_char = next((c for c in characters if c.get("description")), None)
    feature_tags: dict = {}
    if reference_char is not None:
        feature_tags = reference_char.get("feature_tags") or {}
        if not feature_tags:
            feature_tags = await extract_feature_tags(reference_char.get("description", ""), llm)
        if isinstance(reference_char, dict):
            reference_char["feature_tags"] = feature_tags

    for sb in storyboards:
        raw_prompt = sb.get("prompt", "")
        # 关键逻辑（方案 A5）：按分镜关联角色组装多角色提示词与参考图；
        # 解析结果为空（角色列表为空/显式关联匹配失败）时回退旧的单角色注入。
        linked_chars = resolve_storyboard_characters(sb, characters)
        if linked_chars:
            prompt, ref_images = await build_multiref_prompt(raw_prompt, linked_chars)
            sb["ref_count"] = len(ref_images)
            sb["ref_character_names"] = [item["character_name"] for item in ref_images]
        else:
            # 注入角色一致性约束后缀，保证关键帧与角色定妆照特征一致（旧逻辑）
            prompt = build_consistent_prompt(raw_prompt, feature_tags)
            ref_images = []
            sb["ref_count"] = 0
            sb["ref_character_names"] = []

        ref_dropped = False
        try:
            if ref_images:
                # 方案 A5：携带参考板参考图生成（Provider 内部优先 i2i，
                # 失败自动降级纯 t2i 并置 last_ref_dropped=True）
                keyframe_url = await image_provider.generate(prompt, ref_images=ref_images)
                kf_dropped = bool(getattr(image_provider, "last_ref_dropped", False))
                if kf_dropped:
                    logger.warning(
                        f"[keyframe_agent] 分镜#{sb.get('sequence')} 参考图未被 Provider 消费"
                        "（已降级纯 t2i，特征卡约束仍在提示词中）"
                    )
                endframe_url = await image_provider.generate(prompt + "，结尾画面", ref_images=ref_images)
                ef_dropped = bool(getattr(image_provider, "last_ref_dropped", False))
                ref_dropped = kf_dropped or ef_dropped
            else:
                keyframe_url = await image_provider.generate(prompt)
                endframe_url = await image_provider.generate(prompt + "，结尾画面")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[keyframe_agent] 分镜#{sb.get('sequence')} 图像生成失败: {exc}")
            keyframe_url = None
            endframe_url = None

        # 标记参考图消费状态（供 consistency_agent 判定 ref_lock/feature_card 模式）
        sb["ref_dropped"] = ref_dropped
        sb["keyframe_url"] = keyframe_url
        sb["endframe_url"] = endframe_url
        sb["status"] = "done"

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="keyframe_agent",
        input_digest=f"storyboards={len(storyboards)}",
        output_digest=truncate_digest(storyboards),
    )

    return {"storyboards": storyboards, "stage": "consistency"}
