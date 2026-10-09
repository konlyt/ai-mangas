"""
关键帧生成 Agent 节点（KeyframeAgent）。

职责：
    为每个分镜生成首帧与尾帧图像，编排图像生成任务，
    将关键帧 URL 写入各分镜并更新 state.storyboards。

输入（来自 state）：
    - storyboards: 分镜列表。
    - characters: 角色列表（用于一致性参考图）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - storyboards: 更新后的分镜列表（含 keyframe_url/endframe_url）。
    - stage: 下一阶段 "consistency"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.agents.nodes.consistency_agent import build_consistent_prompt, extract_feature_tags
from app.core.logging import get_logger
from app.providers.image.registry import get_image_registry
from app.providers.llm.litellm_client import get_llm

logger = get_logger()


async def keyframe_agent_node(state: ProductionState) -> dict:
    """关键帧生成节点。

    为每个分镜生成首帧与尾帧图像。生成前会将主角色的特征标签
    （feature_tags）注入分镜提示词，保障关键帧与角色定妆照之间的
    角色一致性；角色缺失 feature_tags 时现场调用 LLM 提取一次并复用。

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

    # 关键逻辑：确定主角色（首个带描述的角色）并解析其特征标签。
    # 若角色列表中已携带 feature_tags 则直接复用；
    # 否则现场调用 LLM 提取一次，供全部分镜复用，避免重复调用。
    llm = get_llm("agnes")
    reference_char = next((c for c in characters if c.get("description")), None)
    feature_tags: dict = {}
    if reference_char is not None:
        feature_tags = reference_char.get("feature_tags") or {}
        if not feature_tags:
            feature_tags = await extract_feature_tags(reference_char.get("description", ""), llm)
        if reference_char is not None and isinstance(reference_char, dict):
            reference_char["feature_tags"] = feature_tags

    for sb in storyboards:
        raw_prompt = sb.get("prompt", "")
        # 注入角色一致性约束后缀，保证关键帧与角色定妆照特征一致
        prompt = build_consistent_prompt(raw_prompt, feature_tags)
        try:
            keyframe_url = await image_provider.generate(prompt)
            endframe_url = await image_provider.generate(prompt + "，结尾画面")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[keyframe_agent] 分镜#{sb.get('sequence')} 图像生成失败: {exc}")
            keyframe_url = None
            endframe_url = None
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
