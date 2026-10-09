"""
分镜生成 Agent 节点（StoryboardAgent）。

职责：
    将剧本拆解为分镜，为每个分镜合成视觉提示词（融合角色、场景、景别、运镜等信息），
    并调用合规节点（内联简化）后将结果写入 state.storyboards。

输入（来自 state）：
    - script: 结构化剧本。
    - characters: 角色列表。
    - scenes: 场景列表。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - storyboards: 分镜列表（含 sequence、shot_type、prompt 等）。
    - stage: 下一阶段 "keyframes"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger

logger = get_logger()


async def storyboard_agent_node(state: ProductionState) -> dict:
    """分镜生成节点。

    将剧本拆解为分镜并合成视觉提示词。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 storyboards 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    script = state.get("script", {})
    characters = state.get("characters", []) or []
    scenes = state.get("scenes", []) or []

    logger.info(f"[storyboard_agent] 开始生成分镜 project_id={project_id}")

    script_scenes = script.get("scenes", []) if isinstance(script, dict) else []
    if not script_scenes:
        script_scenes = [{"description": "默认分镜"}]

    shot_types = ["特写", "近景", "中景", "全景", "远景"]
    camera_movements = ["固定", "推镜", "拉镜", "摇镜", "移镜"]

    storyboards = []
    for idx, sc in enumerate(script_scenes, start=1):
        char_names = "、".join(c.get("name", "") for c in characters)
        scene_name = scenes[0].get("name", "") if scenes else ""
        prompt = (
            f"动漫分镜，{sc.get('description', '')}；"
            f"角色：{char_names}；场景：{scene_name}；"
            f"景别：{shot_types[idx % len(shot_types)]}；"
            f"运镜：{camera_movements[idx % len(camera_movements)]}。"
        )
        storyboards.append({
            "sequence": idx,
            "shot_type": shot_types[idx % len(shot_types)],
            "camera_movement": camera_movements[idx % len(camera_movements)],
            "duration": 5,
            "visual_description": sc.get("description", ""),
            "dialogue": sc.get("dialogue", ""),
            "prompt": prompt,
            "status": "pending",
        })

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="storyboard_agent",
        input_digest=truncate_digest(script),
        output_digest=f"storyboards={len(storyboards)}",
    )

    return {"storyboards": storyboards, "stage": "keyframes"}
