"""
配音生成 Agent 节点（VoiceAgent）。

职责：
    为每个分镜的对白/旁白调用 TTS Provider 生成音频，
    将音频 URL 写入各分镜并更新 state.storyboards。

输入（来自 state）：
    - storyboards: 分镜列表（含 dialogue）。
    - characters: 角色列表（含 voice_id）。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - storyboards: 更新后的分镜列表（含 audio_url）。
    - stage: 下一阶段 "compose"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger
from app.providers.tts.registry import get_tts_registry

logger = get_logger()


async def voice_agent_node(state: ProductionState) -> dict:
    """配音生成节点。

    为每个分镜的对白调用 TTS Provider 生成音频。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 storyboards 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    storyboards = state.get("storyboards", []) or []

    logger.info(f"[voice_agent] 开始生成配音 project_id={project_id}, count={len(storyboards)}")

    registry = get_tts_registry()
    tts_provider = registry.get_provider()

    for sb in storyboards:
        dialogue = sb.get("dialogue") or ""
        if not dialogue:
            sb["audio_url"] = None
            continue
        try:
            audio_url = await tts_provider.synthesize(dialogue, voice_id="default")
            sb["audio_url"] = audio_url
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[voice_agent] 分镜#{sb.get('sequence')} TTS 失败: {exc}")
            sb["audio_url"] = None

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="voice_agent",
        input_digest=f"storyboards={len(storyboards)}",
        output_digest=truncate_digest(storyboards),
    )

    return {"storyboards": storyboards, "stage": "compose"}
