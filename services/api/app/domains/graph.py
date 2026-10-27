"""
Graph 编排领域服务。

提供 Graph 运行启动、状态查询、中断恢复等业务逻辑。
Graph 执行通过 LangGraph（或降级的函数式编排）异步运行，
状态与检查点通过 checkpointer 持久化。

中断恢复协议：
    LangGraph 节点内调用 interrupt() 后，ainvoke 返回带 "__interrupt__"
    键的结构（值为 Interrupt 对象列表），run 状态置为 INTERRUPTED 并记录
    中断节点；恢复时通过 graph.ainvoke(Command(resume=<人工确认负载>))
    从 checkpointer 保存的 checkpoint（thread_id=run_id）续跑。
"""

import asyncio
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graphs.production_graph import get_graph
from app.core.logging import get_logger
from app.core.response import BizException, ErrorCode
from app.models import GraphEntryPoint, GraphRun, GraphRunStatus, Project, ProjectStatus
from app.schemas.graph import GraphResumeRequest, GraphRunRequest, GraphStateOut

logger = get_logger()

# 尝试导入 langgraph 的 Command 恢复协议；失败则走降级续跑（与 production_graph 对齐）
try:  # pragma: no cover - 依赖环境
    from langgraph.types import Command  # type: ignore

    _HAS_LANGGRAPH = True
except Exception:  # noqa: BLE001
    Command = None  # type: ignore
    _HAS_LANGGRAPH = False


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
    # 关键逻辑：后台任务不能复用请求级会话（请求返回后即关闭），
    # 这里基于请求会话绑定的引擎构造独立会话工厂传入，
    # 保证测试内存库与生产 MySQL 环境下 run 状态推进均写往正确的数据库。
    background_factory = _build_background_session_factory(db)
    asyncio.create_task(
        _run_graph_async(run_id, project_id, initial_state, background_factory)
    )

    return {"run_id": run_id}


def _build_background_session_factory(db: AsyncSession) -> async_sessionmaker:
    """基于请求会话绑定的引擎构造后台任务用的会话工厂。

    后台任务不能复用请求级会话（请求返回后即关闭），这里取请求会话
    绑定的 AsyncEngine 新建独立会话工厂，保证测试内存库与生产 MySQL
    环境下 run 状态推进均写往正确的数据库；无法取得 AsyncEngine 时
    回退到应用全局会话工厂。

    Args:
        db: 请求级异步数据库会话。

    Returns:
        async_sessionmaker: 后台任务可用的会话工厂（expire_on_commit=False，
        便于后台任务 commit 后继续读取 ORM 属性）。
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    bind = getattr(db, "bind", None)
    if isinstance(bind, AsyncEngine):
        return async_sessionmaker(
            bind=bind,
            expire_on_commit=False,
            autoflush=False,
        )
    from app.core.database import get_session_factory

    return get_session_factory()


def _extract_interrupt_node(result: Any) -> Optional[str]:
    """从 Graph 执行结果中识别中断信息并提取中断节点名。

    兼容三种形态：
        1. langgraph interrupt() 协议（>=0.2.x，实测 1.2.14 行为一致）：
           ainvoke 返回 dict，带 "__interrupt__" 键，值为 Interrupt 对象
           列表/元组，Interrupt.value 为节点写入的中断负载（含 node 字段）；
        2. 非 dict 返回值：部分版本/场景下可能直接返回 Interrupt 对象或其
           容器，通过 getattr 兜底识别，避免误判为正常完成；
        3. 降级版 SimpleProductionGraph：state 中带 "_interrupted_at" 标记
           （形如 "interrupt_after_assets"）。

    Args:
        result: graph.ainvoke 的返回值。

    Returns:
        Optional[str]: 中断所在节点名（如 "assets"）；未发生中断时返回 None。
    """
    if result is None:
        return None
    if isinstance(result, dict):
        # 降级实现：_interrupted_at 形如 interrupt_after_<node>
        legacy = result.get("_interrupted_at")
        if legacy:
            return str(legacy).replace("interrupt_after_", "")[:50]
        intr = result.get("__interrupt__")
    else:
        intr = getattr(result, "__interrupt__", None)
    if not intr:
        return None
    if isinstance(intr, (list, tuple)):
        intr = intr[0] if intr else None
        if intr is None:
            return None
    value = getattr(intr, "value", intr)
    node = ""
    if isinstance(value, dict):
        node = str(value.get("node") or "").strip()
    if not node:
        node = str(value)[:50] if value is not None else "unknown"
    return node[:50]


async def _finalize_graph_run(
    run_id: str, result: Any, session_factory: async_sessionmaker
) -> None:
    """根据 Graph 执行结果推进 run 终态（中断等待 / 正常完成）。

    命中中断协议时状态置 INTERRUPTED 并记录中断节点（不得标 done）；
    正常完成才置 DONE 并清空中断标记。

    Args:
        run_id: Graph 执行 ID。
        result: graph.ainvoke 的返回值。
        session_factory: 后台任务使用的会话工厂。

    Returns:
        None
    """
    interrupt_node = _extract_interrupt_node(result)
    async with session_factory() as session:
        result_db = await session.execute(
            select(GraphRun).where(GraphRun.run_id == run_id)
        )
        graph_run = result_db.scalar_one_or_none()
        if graph_run:
            if interrupt_node:
                graph_run.status = GraphRunStatus.INTERRUPTED
                graph_run.interrupt_at = interrupt_node
                logger.info(
                    f"[graph] 运行到达人工审核中断 run_id={run_id}, node={interrupt_node}"
                )
            else:
                graph_run.status = GraphRunStatus.DONE
                graph_run.interrupt_at = None
                logger.info(f"[graph] 执行完成 run_id={run_id}")
            await session.commit()


async def _mark_graph_run_failed(
    run_id: str, session_factory: async_sessionmaker
) -> None:
    """将 run 标记为失败（内部辅助函数）。

    Args:
        run_id: Graph 执行 ID。
        session_factory: 后台任务使用的会话工厂。

    Returns:
        None
    """
    async with session_factory() as session:
        result_db = await session.execute(
            select(GraphRun).where(GraphRun.run_id == run_id)
        )
        graph_run = result_db.scalar_one_or_none()
        if graph_run:
            graph_run.status = GraphRunStatus.FAILED
            graph_run.interrupt_at = None
            await session.commit()


async def _run_graph_async(
    run_id: str,
    project_id: int,
    state: Dict[str, Any],
    session_factory: Optional[async_sessionmaker] = None,
) -> None:
    """后台执行 Graph 流水线并按结果推进 run 状态。

    Args:
        run_id: Graph 执行 ID。
        project_id: 项目 ID。
        state: 初始生产状态。
        session_factory: 后台任务使用的会话工厂；为 None 时回退全局
            AsyncSessionLocal（兼容旧调用方式）。

    Returns:
        None
    """
    if session_factory is None:
        from app.core.database import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}
        result = await graph.ainvoke(state, config=config)
        await _finalize_graph_run(run_id, result, session_factory)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[graph] 执行失败 run_id={run_id}: {exc}")
        await _mark_graph_run_failed(run_id, session_factory)


async def _resume_graph_async(
    run_id: str,
    project_id: int,
    resume_payload: Dict[str, Any],
    session_factory: async_sessionmaker,
) -> None:
    """后台以 Command(resume=...) 协议恢复被中断的 Graph 执行。

    从 checkpointer 保存的 checkpoint（thread_id=run_id）续跑，
    恢复完成后按结果推进 run 终态（到下一中断点或跑完全流程）。

    Args:
        run_id: Graph 执行 ID（同时作为 checkpointer 的 thread_id）。
        project_id: 项目 ID。
        resume_payload: 回传给 interrupt 点的人工确认负载（action/feedback）。
        session_factory: 后台任务使用的会话工厂。

    Returns:
        None
    """
    try:
        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}
        if _HAS_LANGGRAPH and Command is not None:
            result = await graph.ainvoke(Command(resume=resume_payload), config=config)
        else:
            # 降级编排对象：无 checkpoint 协议，直接续跑
            result = await graph.ainvoke({}, config=config)
        await _finalize_graph_run(run_id, result, session_factory)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[graph] 恢复执行失败 run_id={run_id}: {exc}")
        await _mark_graph_run_failed(run_id, session_factory)


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

    根据 action 决定继续执行或驳回（附 feedback 回传 Agent）：
        - reject：run 置 CANCELLED，终止本次执行；
        - approve：run 置 RUNNING，后台通过 graph.ainvoke(Command(resume=...))
          从 checkpointer 保存的 checkpoint（thread_id=run_id）续跑。

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

    run_id = graph_run.run_id

    # 后台任务会话工厂（与 run_graph 一致，绑定请求会话的引擎）
    background_factory = _build_background_session_factory(db)

    if req.action == "reject":
        # 驳回：标记为 cancelled，终止本次执行并清空中断标记
        graph_run.status = GraphRunStatus.CANCELLED
        graph_run.interrupt_at = None
        await db.commit()
        logger.info(f"[graph] 人工驳回终止执行 run_id={run_id}, feedback={req.feedback}")
        return {"run_id": run_id, "action": "reject", "feedback": req.feedback}

    # 确认继续：置 RUNNING 后，以 Command(resume=...) 协议从 checkpoint 续跑
    graph_run.status = GraphRunStatus.RUNNING
    graph_run.interrupt_at = None
    await db.commit()

    # 关键逻辑：恢复负载随 Command(resume=...) 回传给 interrupt 点，
    # 节点内 interrupt() 的返回值即该负载（action/feedback 可被下游消费）。
    resume_payload: Dict[str, Any] = {"action": req.action, "feedback": req.feedback}
    asyncio.create_task(
        _resume_graph_async(run_id, project_id, resume_payload, background_factory)
    )

    logger.info(f"[graph] 恢复执行已提交 run_id={run_id}, action={req.action}")
    return {"run_id": run_id, "action": "approve", "feedback": req.feedback}
