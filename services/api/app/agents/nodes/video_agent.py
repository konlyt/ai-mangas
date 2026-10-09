"""
视频生成 Agent 节点（VideoAgent）。

职责：
    为每个分镜编排视频生成任务：基于首帧图调用视频 Provider 生成视频片段，
    将视频 URL 写入各分镜并更新 state.storyboards。

输入（来自 state）：
    - storyboards: 分镜列表（含 keyframe_url）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - storyboards: 更新后的分镜列表（含 video_url）。
    - stage: 下一阶段 "voice"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger
from app.providers.video.registry import get_video_registry

logger = get_logger()


async def video_agent_node(state: ProductionState) -> dict:
    """视频生成节点。

    基于每个分镜的首帧图调用视频 Provider 生成视频片段。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 storyboards 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    storyboards = state.get("storyboards", []) or []

    logger.info(f"[video_agent] 开始生成视频 project_id={project_id}, count={len(storyboards)}")

    registry = get_video_registry()
    video_provider = registry.get_provider()

    for sb in storyboards:
        prompt = sb.get("prompt", "")
        image_url = sb.get("keyframe_url") or ""
        try:
            task_id = await video_provider.submit(prompt, image_url)
            result = await video_provider.poll(task_id)
            sb["video_url"] = result.get("url") if result.get("status") == "done" else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[video_agent] 分镜#{sb.get('sequence')} 视频生成失败: {exc}")
            sb["video_url"] = None

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="video_agent",
        input_digest=f"storyboards={len(storyboards)}",
        output_digest=truncate_digest(storyboards),
    )

    return {"storyboards": storyboards, "stage": "voice"}
