"""
资产生成 Agent 节点（AssetAgent）。

职责：
    解析剧本，抽取角色与场景，为每个角色/场景生成视觉提示词，
    并调用图像 Provider 生成定妆照/概念图，将结果写入 state.characters 与 state.scenes。
    定妆照完成后追加生成角色四视图参考板（四宫格单图：头特写/正面/右侧90°侧面/背面），
    并将 ref_board_url 与 character_locks（不可变锚点）写入 state，
    同时以独立数据库会话回写 characters 表对应两列；
    参考板生成失败仅记录告警，不阻塞定妆照主流程。

输入（来自 state）：
    - script: 结构化剧本。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - characters: 角色列表（含 visual_prompt、image_url、ref_board_url、character_locks）。
    - scenes: 场景列表（含 visual_prompt 与 image_url）。
    - stage: 下一阶段 "consistency"。
"""

import json
import re

from sqlalchemy import select

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.agents.nodes.consistency_agent import build_consistent_prompt, extract_feature_tags
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import Character
from app.providers.image.registry import get_image_registry
from app.providers.llm.litellm_client import LLMClient, get_llm

logger = get_logger()

# 参考板生成图幅（四宫格单图，正方形）
_REF_BOARD_SIZE = 1024

# character_locks 不可变锚点字段（有序）：style_tag 画风不入锁（画风可随场景调整），
# 锁仅锚定"不可变"的形体服装外观
REF_BOARD_LOCK_KEYS = ("costume", "hairstyle", "appearance", "body_type")

# 锁定字段中文名映射（与 consistency_agent._FEATURE_TAG_LABELS 保持一致）
_REF_BOARD_LOCK_LABELS = {
    "costume": "服饰",
    "hairstyle": "发型",
    "appearance": "外貌",
    "body_type": "体型",
}

# 四视图参考板提示词模板（方案 A4：一次生成一张四宫格参考板）。
# 占位符：
#     {character_brief} - 角色外观细节简述（LLM 生成，失败时用 description/feature_tags 兜底）
#     {locks_desc} - character_locks 锁定描述强注入段（与 build_consistent_prompt 风格一致）
REF_BOARD_PROMPT_TEMPLATE = (
    "动漫风格角色四视图参考板（character reference sheet），单张图片，2x2 四宫格布局，"
    "四个格子之间用细线分隔，每个格子左上角标注编号（1、2、3、4）：\n"
    "格子1：头部特写（正面头像，含五官与发型细节）；\n"
    "格子2：正面全身立绘；\n"
    "格子3：右侧90°侧面全身立绘；\n"
    "格子4：背面全身立绘（含背部发型与服饰细节）。\n"
    "四格中必须是同一位角色，外貌、发型、服饰、体型、画风严格一致：{character_brief}。"
    "{locks_desc}"
    "纯白色背景，无阴影无道具，角色设定集风格，高清细节，画面中除四格编号外不得出现任何其他文字。"
)


def build_character_locks(feature_tags: dict | None) -> dict | None:
    """从角色特征标签中提取 character_locks 不可变锚点。

    仅保留 REF_BOARD_LOCK_KEYS 白名单内的非空字段（costume/hairstyle/appearance/body_type），
    style_tag 画风不入锁（画风可随场景调整，不属于"不可变"的形体服装锚点）。

    Args:
        feature_tags: 角色特征标签字典（extract_feature_tags 的返回值），可为 None。

    Returns:
        dict | None: 形如 {"costume": ..., "hairstyle": ..., "appearance": ..., "body_type": ...}
            的锚点字典；无任何有效字段时返回 None（不阻塞主流程）。
    """
    if not feature_tags or not isinstance(feature_tags, dict):
        return None
    locks = {
        key: str(feature_tags[key]).strip()
        for key in REF_BOARD_LOCK_KEYS
        if feature_tags.get(key) and str(feature_tags.get(key)).strip()
    }
    return locks or None


def _build_locks_desc(locks: dict | None) -> str:
    """将 character_locks 锚点字典格式化为提示词强注入段（内部辅助函数）。

    拼接风格与 consistency_agent.build_consistent_prompt 一致：
    【角色一致性约束】外貌：xxx；服饰：xxx。生成时必须严格保持...

    Args:
        locks: character_locks 锚点字典，可为 None。

    Returns:
        str: 注入段文本；locks 为空时返回空字符串。
    """
    if not locks:
        return ""
    parts = [
        f"{_REF_BOARD_LOCK_LABELS[key]}：{locks[key]}"
        for key in REF_BOARD_LOCK_KEYS
        if locks.get(key)
    ]
    if not parts:
        return ""
    return f"【角色一致性约束】{'；'.join(parts)}。四格绘制时必须严格保持上述特征前后一致。"


def _build_fallback_brief(name: str, description: str, feature_tags: dict | None) -> str:
    """构造角色外观简述的兜底文本（LLM 失败时使用，内部辅助函数）。

    优先级：description > feature_tags 各字段拼接 > 角色名。

    Args:
        name: 角色名。
        description: 角色自然语言描述。
        feature_tags: 角色特征标签字典，可为 None。

    Returns:
        str: 兜底角色简述文本（至少包含角色名）。
    """
    desc = (description or "").strip()
    if desc:
        return desc
    if feature_tags and isinstance(feature_tags, dict):
        parts = [
            f"{_REF_BOARD_LOCK_LABELS.get(key, key)}：{str(feature_tags[key]).strip()}"
            for key in REF_BOARD_LOCK_KEYS
            if feature_tags.get(key) and str(feature_tags.get(key)).strip()
        ]
        if parts:
            return "；".join(parts)
    return name or "动漫风格角色"


async def generate_ref_board_prompt(
    name: str,
    description: str,
    feature_tags: dict | None,
    locks: dict | None,
    llm: LLMClient | None = None,
) -> str:
    """生成四视图参考板的图像提示词。

    流程：
        1. 调用 LLM 基于角色名 + description + feature_tags 生成角色外观细节简述
           （character_brief），供四宫格各视图保持角色一致；
        2. 将 character_brief 与 character_locks 强注入段填入
           REF_BOARD_PROMPT_TEMPLATE 模板，得到完整提示词。

    LLM 调用失败时使用 description/feature_tags 兜底简述，不向上抛出，
    保证参考板生成不被 LLM 异常阻塞。

    Args:
        name: 角色名。
        description: 角色自然语言描述。
        feature_tags: 角色特征标签字典，可为 None。
        locks: character_locks 锚点字典（build_character_locks 的返回值），可为 None。
        llm: LLM 客户端实例；为 None 时使用 agnes Provider 的默认实例。

    Returns:
        str: 四视图参考板的完整图像生成提示词。
    """
    character_brief = ""
    client = llm or get_llm("agnes")
    try:
        tags_text = (
            json.dumps(feature_tags, ensure_ascii=False) if feature_tags else "无"
        )
        prompt = (
            "你是角色设定画师助手。请根据以下角色信息，用一段不超过80字的中文"
            "描述该角色的外貌、发型、服饰与体型细节（供四视图参考板绘制使用，"
            "直接输出描述文本，不要输出任何其他内容）：\n"
            f"角色名：{name}\n"
            f"角色描述：{description or '无'}\n"
            f"特征标签：{tags_text}"
        )
        raw = await client.achat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        # 容错清洗：剥离 markdown 围栏与首尾空白
        character_brief = re.sub(r"^```(?:[a-z]*)?\s*|\s*```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[asset_agent] 参考板角色简述 LLM 生成失败，使用兜底描述: {exc}")

    # LLM 失败或输出为空时，用 description/feature_tags 兜底
    if not character_brief:
        character_brief = _build_fallback_brief(name, description, feature_tags)

    return REF_BOARD_PROMPT_TEMPLATE.format(
        character_brief=character_brief,
        locks_desc=_build_locks_desc(locks),
    )


async def _persist_ref_board(
    project_id: int,
    name: str,
    ref_board_url: str | None,
    locks: dict | None,
) -> None:
    """将参考板结果落库（内部辅助函数，独立数据库会话）。

    按 project_id + 角色名定位 characters 表记录，更新
    ref_board_url（四视图参考板 URL）与 character_locks（不可变锚点 JSON）两列。
    采用独立 AsyncSessionLocal 会话写入（与 consistency_agent._persist_consistency_results
    同款模式），避免与 domain 层并行修改冲突；写入失败仅记录告警，不影响主流程。

    Args:
        project_id: 项目 ID；非正数时跳过写入（state 中无有效项目）。
        name: 角色名（characters 表内按项目+名称唯一定位）。
        ref_board_url: 四视图参考板访问 URL，可为 None（仅回写锁时使用）。
        locks: character_locks 锚点字典，可为 None。

    Returns:
        None

    Raises:
        无：任何数据库异常均捕获并降级为告警日志。
    """
    if project_id <= 0 or not name:
        return
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Character).where(
                    Character.project_id == project_id,
                    Character.name == name,
                )
            )
            character = result.scalars().first()
            if character is None:
                logger.warning(
                    f"[asset_agent] 参考板落库跳过：characters 表中未找到角色 "
                    f"project_id={project_id}, name={name}"
                )
                return
            if ref_board_url:
                character.ref_board_url = ref_board_url
            if locks is not None:
                character.character_locks = locks
            await session.commit()
            logger.info(
                f"[asset_agent] 参考板结果已落库 project_id={project_id}, "
                f"name={name}, ref_board_url={ref_board_url}"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[asset_agent] 参考板结果落库失败 project_id={project_id}, name={name}: {exc}"
        )


async def generate_ref_board(
    name: str,
    description: str,
    feature_tags: dict | None,
    llm: LLMClient | None = None,
    image_provider=None,
) -> tuple[str | None, dict | None]:
    """生成角色四视图参考板（四宫格单图）。

    流程：
        1. 从 feature_tags 提取 character_locks 不可变锚点；
        2. 生成参考板提示词（LLM 简述 + 模板 + 锁定强注入）；
        3. 调用图像 Provider 生成一张 1024x1024 四宫格参考板图
           （不传 ref_images，避免与 t2i 接口并行修改耦合）。

    Args:
        name: 角色名。
        description: 角色自然语言描述。
        feature_tags: 角色特征标签字典，可为 None。
        llm: LLM 客户端实例；为 None 时使用 agnes Provider 的默认实例。
        image_provider: 图像生成 Provider 实例；为 None 时使用注册表默认 Provider。

    Returns:
        tuple[str | None, dict | None]: (ref_board_url, character_locks)。
            ref_board_url 为参考板图访问 URL（本地 /static/... 或远程 URL），
            character_locks 为锚点字典；feature_tags 无有效字段时为 None。

    Raises:
        Exception: 图像 Provider 生成失败时向上抛出，由调用方决定降级
            （参考板失败不阻塞定妆照主流程）。
    """
    if image_provider is None:
        image_provider = get_image_registry().get_provider()

    locks = build_character_locks(feature_tags)
    prompt = await generate_ref_board_prompt(name, description, feature_tags, locks, llm)
    ref_board_url = await image_provider.generate(
        prompt,
        params={"width": _REF_BOARD_SIZE, "height": _REF_BOARD_SIZE},
    )
    return ref_board_url, locks


async def asset_agent_node(state: ProductionState) -> dict:
    """资产生成节点。

    从剧本中抽取角色与场景，调用图像 Provider 生成资产图片。
    角色定妆照生成前会通过 LLM 提取结构化特征标签，
    并将特征标签注入图像提示词以保障多图之间的角色一致性；
    定妆照完成后追加生成四视图参考板（四宫格单图）并落库
    ref_board_url / character_locks，参考板失败不阻塞主流程。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 characters、scenes 与 stage 的状态增量；
            characters 每项含 name / description / feature_tags /
            visual_prompt / image_url / ref_board_url / character_locks。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    script = state.get("script", {})

    logger.info(f"[asset_agent] 开始生成资产 project_id={project_id}")

    registry = get_image_registry()
    image_provider = registry.get_provider()

    # 简化实现：从剧本中抽取角色与场景
    characters = []
    scenes = []

    script_characters = script.get("characters", []) if isinstance(script, dict) else []
    script_scenes = script.get("scenes", []) if isinstance(script, dict) else []

    # 若剧本未提供结构化字段，则生成占位数据
    if not script_characters:
        script_characters = [{"name": "主角", "description": "故事的主要角色"}]
    if not script_scenes:
        script_scenes = [{"name": "主场景", "description": "故事发生的主要场所"}]

    # 角色特征提取用的 LLM 客户端（agnes 文本模型）
    llm = get_llm("agnes")

    for char in script_characters:
        # 关键逻辑：优先复用角色已有 feature_tags；缺失时现场调用 LLM 提取一次并写入角色数据
        feature_tags = char.get("feature_tags") if isinstance(char, dict) else None
        if not feature_tags:
            feature_tags = await extract_feature_tags(char.get("description", ""), llm)

        raw_prompt = f"动漫风格角色定妆照，{char.get('name', '')}，{char.get('description', '')}"
        # 注入角色一致性约束后缀，保证定妆照与后续关键帧特征一致
        prompt = build_consistent_prompt(raw_prompt, feature_tags)

        try:
            image_url = await image_provider.generate(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[asset_agent] 角色图像生成失败: {exc}")
            image_url = None

        # 关键逻辑：定妆照完成后追加四视图参考板生成（方案 A4，四宫格单图）。
        # 参考板生成失败（LLM/provider 异常）不阻塞定妆照主流程：
        # 仅记录告警，ref_board_url 保持 None，character_locks 仍随 state 下发。
        char_name = char.get("name", "")
        locks = build_character_locks(feature_tags)
        ref_board_url = None
        try:
            ref_board_url, locks = await generate_ref_board(
                name=char_name,
                description=char.get("description", ""),
                feature_tags=feature_tags,
                llm=llm,
                image_provider=image_provider,
            )
            await _persist_ref_board(project_id, char_name, ref_board_url, locks)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[asset_agent] 角色 {char_name} 四视图参考板生成失败（不阻塞主流程）: {exc}"
            )
            ref_board_url = None

        characters.append({
            "name": char.get("name", ""),
            "description": char.get("description", ""),
            "feature_tags": feature_tags,
            "visual_prompt": prompt,
            "image_url": image_url,
            "ref_board_url": ref_board_url,
            "character_locks": locks,
        })

    for scene in script_scenes:
        prompt = f"动漫风格场景概念图，{scene.get('name', '')}，{scene.get('description', '')}"
        try:
            image_url = await image_provider.generate(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[asset_agent] 场景图像生成失败: {exc}")
            image_url = None
        scenes.append({
            "name": scene.get("name", ""),
            "description": scene.get("description", ""),
            "visual_prompt": prompt,
            "image_url": image_url,
        })

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="asset_agent",
        input_digest=truncate_digest(script),
        output_digest=f"characters={len(characters)}, scenes={len(scenes)}",
    )

    return {"characters": characters, "scenes": scenes, "stage": "consistency"}
