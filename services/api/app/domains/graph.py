"""
Graph 编排领域服务。

提供 Graph 运行启动、状态查询、中断恢复等业务逻辑。
Graph 执行通过 LangGraph（或降级的函数式编排）异步运行，
状态与检查点通过 checkpointer 持久化。
"""

import asyncio
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graphs.production_graph import get_graph
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import GraphEntryPoint, GraphRun, GraphRunStatus, Project, ProjectStatus
from app.schemas.graph import GraphResumeRequest, GraphRunRequest, GraphStateOut

logger = get_logger()


async def run_graph(
    db: AsyncSession, project_id: int, user_id: int, req: GraphRunRequest
) -> Dict[str, str]:
    """创建 Graph 执行记录并启动流水线。

    在 graph_runs 表中插入一条记录，然后后台异步调用 get_graph().ainvoke
    执行生产流水线。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        user_id: 触发用户 ID。
        req: Graph 运行请求体。

    Returns:
        dict: 包含 run_id 的字典。

    Raises:
        BizException: 项目不存在时抛出 NOT_FOUND。
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="项目不存在")

    run_id = uuid.uuid4().hex

    # 确定起始阶段
    entry_point = req.entry_point
    if entry_point == GraphEntryPoint.FULL:
        stage = "script"
    elif entry_point == GraphEntryPoint.STAGE:
        stage = project.status.value if isinstance(project.status, ProjectStatus) else str(project.status)
    else:  # partial
        stage = req.target_node or "script"

    # 创建 graph_run 记录
    graph_run = GraphRun(
        run_id=run_id,
        project_id=project_id,
        entry_point=entry_point,
        target_node=req.target_node,
        status=GraphRunStatus.RUNNING,
        created_by=user_id,
    )
    db.add(graph_run)
    await db.commit()

    # 构建初始 state
    initial_state: Dict[str, Any] = {
        "project_id": project_id,
        "stage": stage,
        "raw_input": req.payload or {},
        "meta": {"user_id": user_id, "run_id": run_id},
        "graph_run_id": run_id,
    }

    # 后台异步执行 graph（不阻塞请求返回）
    asyncio.create_task(_run_graph_async(run_id, project_id, initial_state))

    return {"run_id": run_id}


async def _run_graph_async(run_id: str, project_id: int, state: Dict[str, Any]) -> None:
    """后台执行 Graph 流水线。

    Args:
        run_id: Graph 执行 ID。
        project_id: 项目 ID。
        state: 初始生产状态。

    Returns:
        None
    """
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}
        result = await graph.ainvoke(state, config=config)

        # 执行完成后更新 graph_run 状态
        from app.core.database import AsyncSessionLocal
        from app.models import GraphRun, GraphRunStatus

        async with AsyncSessionLocal() as session:
            result_db = await session.execute(
                select(GraphRun).where(GraphRun.run_id == run_id)
            )
            graph_run = result_db.scalar_one_or_none()
            if graph_run:
                # 若结果包含中断标记，则状态为 interrupted
                if isinstance(result, dict) and result.get("_interrupted_at"):
                    graph_run.status = GraphRunStatus.INTERRUPTED
                    graph_run.interrupt_at = result.get("_interrupted_at")
                else:
                    graph_run.status = GraphRunStatus.DONE
                await session.commit()
        logger.info(f"[graph] 执行完成 run_id={run_id}")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[graph] 执行失败 run_id={run_id}: {exc}")
        from app.core.database import AsyncSessionLocal
        from app.models import GraphRun, GraphRunStatus

        async with AsyncSessionLocal() as session:
            result_db = await session.execute(
                select(GraphRun).where(GraphRun.run_id == run_id)
            )
            graph_run = result_db.scalar_one_or_none()
            if graph_run:
                graph_run.status = GraphRunStatus.FAILED
                graph_run.interrupt_at = None
                await session.commit()


async def get_graph_state(db: AsyncSession, project_id: int) -> GraphStateOut:
    """查询项目当前 Graph 执行状态。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。

    Returns:
        GraphStateOut: 当前状态信息。
    """
    result = await db.execute(
        select(GraphRun)
        .where(GraphRun.project_id == project_id)
        .order_by(desc(GraphRun.created_at))
        .limit(1)
    )
    graph_run = result.scalar_one_or_none()

    if graph_run is None:
        return GraphStateOut()

    # 尝试从 checkpointer 获取最新状态
    state: Dict[str, Any] = {}
    try:
        from app.agents.checkpointer_adapter import get_checkpointer

        checkpoint = await get_checkpointer().get(graph_run.run_id)
        if checkpoint and isinstance(checkpoint, dict):
            state = checkpoint.get("channel_values", {}) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[graph] 读取检查点失败 run_id={graph_run.run_id}: {exc}")

    return GraphStateOut(
        state=state,
        interrupt_at=graph_run.interrupt_at,
        pending=graph_run.status == GraphRunStatus.INTERRUPTED,
        run_id=graph_run.run_id,
        status=graph_run.status.value,
    )


async def resume_graph(
    db: AsyncSession, project_id: int, req: GraphResumeRequest
) -> Dict[str, Any]:
    """恢复中断的 Graph 执行。

    根据 action 决定继续执行或驳回（附 feedback 回传 Agent）。

    Args:
        db: 异步数据库会话。
        project_id: 项目 ID。
        req: 恢复执行请求体。

    Returns:
        dict: 包含 run_id 与 action 的字典。

    Raises:
        BizException: 没有可恢复的执行时抛出 NOT_FOUND。
    """
    result = await db.execute(
        select(GraphRun)
        .where(
            GraphRun.project_id == project_id,
            GraphRun.status == GraphRunStatus.INTERRUPTED,
        )
        .order_by(desc(GraphRun.created_at))
        .limit(1)
    )
    graph_run = result.scalar_one_or_none()
    if graph_run is None:
        raise BizException(code=ErrorCode.NOT_FOUND, message="没有处于中断状态的 Graph 执行")

    # 恢复执行：重新调用 graph.ainvoke，传入 feedback
    run_id = graph_run.run_id
    resume_state: Dict[str, Any] = {
        "project_id": project_id,
        "graph_run_id": run_id,
        "meta": {"action": req.action, "feedback": req.feedback},
    }

    if req.action == "reject":
        # 驳回：标记为 cancelled 并记录 feedback
        graph_run.status = GraphRunStatus.CANCELLED
        await db.commit()
        return {"run_id": run_id, "action": "reject", "feedback": req.feedback}

    # 确认继续：后台恢复执行
    graph_run.status = GraphRunStatus.RUNNING
    graph_run.interrupt_at = None
    await db.commit()

    asyncio.create_task(_run_graph_async(run_id, project_id, resume_state))

    return {"run_id": run_id, "action": "approve", "feedback": req.feedback}
