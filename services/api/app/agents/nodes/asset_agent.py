"""
资产生成 Agent 节点（AssetAgent）。

职责：
    解析剧本，抽取角色与场景，为每个角色/场景生成视觉提示词，
    并调用图像 Provider 生成定妆照/概念图，将结果写入 state.characters 与 state.scenes。

输入（来自 state）：
    - script: 结构化剧本。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - characters: 角色列表（含 visual_prompt 与 image_url）。
    - scenes: 场景列表（含 visual_prompt 与 image_url）。
    - stage: 下一阶段 "consistency"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.agents.nodes.consistency_agent import build_consistent_prompt, extract_feature_tags
from app.core.logging import get_logger
from app.providers.image.registry import get_image_registry
from app.providers.llm.litellm_client import get_llm

logger = get_logger()


async def asset_agent_node(state: ProductionState) -> dict:
    """资产生成节点。

    从剧本中抽取角色与场景，调用图像 Provider 生成资产图片。
    角色定妆照生成前会通过 LLM 提取结构化特征标签，
    并将特征标签注入图像提示词以保障多图之间的角色一致性。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 characters、scenes 与 stage 的状态增量。
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
        characters.append({
            "name": char.get("name", ""),
            "description": char.get("description", ""),
            "feature_tags": feature_tags,
            "visual_prompt": prompt,
            "image_url": image_url,
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
