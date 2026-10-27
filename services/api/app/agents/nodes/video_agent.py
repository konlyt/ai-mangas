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


def optimize_video_prompt(storyboard_prompt: str) -> str:
    """把分镜 prompt 优化成适合图生视频的动作描述。

    参考 Toonflow Wan 2.6 单图首帧模板：
    - 首帧图已定义起始状态，不用再描述"是什么"
    - 重点描述：接下来怎么动、动作节奏、情绪变化、摄像机运动
    - 去掉对话、剧情说明，只保留画面动作

    Args:
        storyboard_prompt: 原始分镜 prompt。

    Returns:
        优化后的视频生成 prompt。
    """
    text = storyboard_prompt.strip()
    lines = text.split("\n")

    # 提取动作描述行，跳过对话行
    action_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 跳过对话行（人物名+冒号+台词）
        if "：" in line and ("（" in line or "）" in line):
            continue
        # 跳过纯对话行（比如 "胖姐：三百万播放！"）
        if "：" in line and len(line) < 50 and not any(k in line for k in ["推门", "走进", "蹲在", "站在", "拿着", "举着"]):
            continue
        action_parts.append(line)

    action_text = "".join(action_parts)[:200]

    # 构建提示词（参考 Wan 2.6 模板结构）
    # 1. 动作描述（从首帧状态开始，接下来做什么）
    # 2. 摄像机运动
    prompt = f"""从首帧画面自然开始，{action_text}。
动作连贯自然，节奏适中。
固定镜头，保持画面稳定，无明显运镜。
光影自然变化，主体动作流畅。"""

    return prompt


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
        raw_prompt = sb.get("prompt", "")
        prompt = optimize_video_prompt(raw_prompt)
        image_url = sb.get("keyframe_url") or ""
        logger.info(f"[video_agent] 分镜#{sb.get('sequence')} 视频prompt: {prompt[:100]}...")
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
