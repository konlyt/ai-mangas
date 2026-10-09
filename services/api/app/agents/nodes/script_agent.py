"""
剧本生成 Agent 节点（ScriptAgent）。

职责：
    根据用户的原始输入（标题、题材、风格、原始文本等）调用大模型，
    生成结构化剧本，并将结果写入 state.script。

输入（来自 state）：
    - raw_input: 用户原始输入。
    - meta: 元数据。
    - project_id: 项目 ID。
    - graph_run_id: Graph 执行 ID。

输出（返回 state 增量）：
    - script: 结构化剧本字典。
    - stage: 下一阶段 "assets"。
"""

from app.agents.state import ProductionState
from app.agents.nodes import record_agent_event, truncate_digest
from app.core.logging import get_logger
from app.providers.llm.litellm_client import get_llm

logger = get_logger()


async def script_agent_node(state: ProductionState) -> dict:
    """剧本生成节点。

    调用 LLM 根据 raw_input 生成结构化剧本，写入 agent_events 并返回 state 增量。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 包含 script 与 stage 的状态增量。
    """
    project_id = state.get("project_id", 0)
    graph_run_id = state.get("graph_run_id", "")
    raw_input = state.get("raw_input", {})
    title = raw_input.get("title", "未命名项目")
    genre = raw_input.get("genre", "")
    style = raw_input.get("style", "")
    raw_text = raw_input.get("raw_text", "")

    logger.info(f"[script_agent] 开始生成剧本 project_id={project_id}, title={title}")

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个专业的动漫剧本编剧。请根据用户提供的信息生成结构化剧本，"
                "返回 JSON 格式，包含 title、logline、characters、scenes 字段。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"标题：{title}\n"
                f"题材：{genre}\n"
                f"风格：{style}\n"
                f"原始文本：{raw_text}\n"
                "请生成结构化剧本。"
            ),
        },
    ]

    try:
        llm = get_llm()
        content = await llm.achat(messages, temperature=0.8)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[script_agent] LLM 调用失败: {exc}")
        content = f"{{\"title\":\"{title}\",\"logline\":\"剧本生成失败\",\"characters\":[],\"scenes\":[]}}"

    script = {"title": title, "raw": content, "status": "generated"}

    await record_agent_event(
        graph_run_id=graph_run_id,
        project_id=project_id,
        node_name="script_agent",
        input_digest=truncate_digest(raw_input),
        output_digest=truncate_digest(content),
    )

    return {"script": script, "stage": "assets"}
