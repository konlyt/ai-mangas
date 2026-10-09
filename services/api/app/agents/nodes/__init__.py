"""
Agent 节点包。

包含生产流水线中全部 9 个 Agent 节点：
script / asset / consistency / storyboard / keyframe / video / voice / editor / compliance。
同时提供 record_agent_event 公共辅助函数，用于将节点执行情况写入 agent_events 表。
"""

from typing import Any, Optional

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models import AgentEvent

logger = get_logger()


async def record_agent_event(
    graph_run_id: str,
    project_id: int,
    node_name: str,
    *,
    trace_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    cost_points: int = 0,
    input_digest: Optional[str] = None,
    output_digest: Optional[str] = None,
) -> None:
    """将 Agent 节点执行事件写入 agent_events 表。

    Args:
        graph_run_id: 关联的 Graph 执行 ID。
        project_id: 关联的项目 ID。
        node_name: 节点名称。
        trace_id: 链路追踪 ID，可选。
        latency_ms: 耗时（毫秒），可选。
        tokens_in: 输入 token 数，可选。
        tokens_out: 输出 token 数，可选。
        cost_points: 消耗点数，默认 0。
        input_digest: 输入摘要，可选。
        output_digest: 输出摘要，可选。

    Returns:
        None

    Raises:
        无：写入失败仅记录日志，不向上抛出，避免影响主流程。
    """
    try:
        async with AsyncSessionLocal() as session:
            event = AgentEvent(
                graph_run_id=graph_run_id,
                project_id=project_id,
                node_name=node_name,
                trace_id=trace_id,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_points=cost_points,
                input_digest=input_digest,
                output_digest=output_digest,
            )
            session.add(event)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[nodes] 写入 agent_events 失败 node={node_name}: {exc}")


def truncate_digest(data: Any, max_len: int = 200) -> str:
    """将任意数据截断为摘要字符串，用于写入 agent_events。

    Args:
        data: 待摘要的数据。
        max_len: 最大长度，默认 200。

    Returns:
        str: 截断后的摘要字符串。
    """
    text = str(data)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
