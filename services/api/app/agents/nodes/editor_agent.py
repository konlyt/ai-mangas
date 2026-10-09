"""
合成 Agent 节点（EditorAgent）。

职责：
    将所有分镜的视频片段与配音进行合成，编排最终视频合成任务，
    将合成结果写入 state.composition。

输入（来自 state）：
    - storyboards: 分镜列表（含 video_url、audio_url）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - composition: 合成结果字典（含 final_url、duration 等）。
    - stage: 下一阶段 "review"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger

logger = get_logger()


async def editor_agent_node(state: ProductionState) -> dict:
    """视频合成节点。

    将分镜视频与配音合成为最终视频（简化版：取第一个分镜的视频 URL 作为占位）。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 composition 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    storyboards = state.get("storyboards", []) or []

    logger.info(f"[editor_agent] 开始合成 project_id={project_id}, count={len(storyboards)}")

    video_urls = [sb.get("video_url") for sb in storyboards if sb.get("video_url")]
    audio_urls = [sb.get("audio_url") for sb in storyboards if sb.get("audio_url")]

    # 简化版：取首个视频 URL 作为最终合成结果占位
    final_url = video_urls[0] if video_urls else None
    total_duration = sum(sb.get("duration", 5) for sb in storyboards)

    composition = {
        "final_url": final_url,
        "duration": total_duration,
        "clip_count": len(storyboards),
        "video_count": len(video_urls),
        "audio_count": len(audio_urls),
        "status": "composed",
    }

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="editor_agent",
        input_digest=f"storyboards={len(storyboards)}",
        output_digest=truncate_digest(composition),
    )

    return {"composition": composition, "stage": "review"}
