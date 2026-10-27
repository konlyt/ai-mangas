"""
Graph 中断恢复链路集成测试（P0 修复回归）。

覆盖点：
    1. 全流程中断恢复：启动 Graph 后在第一个 interrupt 节点（assets）暂停，
       run 状态置 INTERRUPTED（不得误标 done）；随后逐次以 Command(resume=...)
       协议恢复，依次推进 storyboard / keyframes / review 中断点并最终 DONE；
    2. checkpoint 推进：每次恢复后 interrupt_at 节点前移，
       图状态（aget_state）随 checkpoint 持久化推进；
    3. 驳回分支：resume action=reject 时 run 置 CANCELLED；
    4. 契约保持：无中断 run 时 resume 抛 NOT_FOUND 业务异常。

测试环境：sqlite 内存库（conftest 夹具）+ LLM/图像 Provider mock
（conftest 环境隔离），节点写库路径通过 monkeypatch 全局 AsyncSessionLocal
指向内存库，避免依赖真实 MySQL。
"""

import asyncio
import time
from typing import Optional, Set

import pytest
from sqlalchemy import select

from app.agents.graphs.production_graph import get_graph
from app.core.response import BizException, ErrorCode
from app.domains import graph as graph_domain
from app.models import GraphRun, GraphRunStatus
from app.schemas.graph import GraphResumeRequest, GraphRunRequest

# 轮询等待后台 run 状态推进的超时上限（秒）
_WAIT_TIMEOUT = 30.0

# 轮询间隔（秒）
_POLL_INTERVAL = 0.1


async def _fetch_run(session_factory, run_id: str) -> Optional[GraphRun]:
    """按 run_id 查询 GraphRun 记录（内部辅助函数）。

    Args:
        session_factory: 内存库会话工厂。
        run_id: Graph 执行 ID。

    Returns:
        Optional[GraphRun]: 对应记录；不存在时为 None。
    """
    async with session_factory() as session:
        result = await session.execute(
            select(GraphRun).where(GraphRun.run_id == run_id)
        )
        return result.scalar_one_or_none()


async def _wait_for_status(
    session_factory,
    run_id: str,
    statuses: Set[GraphRunStatus],
) -> GraphRun:
    """轮询等待 run 状态进入目标集合（内部辅助函数）。

    后台任务与轮询共享内存库的 StaticPool 单连接，交叠访问可能触发
    SQLite 事务冲突；此处对瞬时 OperationalError 做重试容错，
    最终以状态进入目标集合或超时为准。

    Args:
        session_factory: 内存库会话工厂。
        run_id: Graph 执行 ID。
        statuses: 期望到达的状态集合。

    Returns:
        GraphRun: 已到达目标状态的 run 记录。

    Raises:
        AssertionError: 超时仍未到达目标状态，或记录不存在。
    """
    from sqlalchemy.exc import OperationalError, PendingRollbackError

    deadline = time.monotonic() + _WAIT_TIMEOUT
    last: Optional[GraphRun] = None
    while time.monotonic() < deadline:
        try:
            last = await _fetch_run(session_factory, run_id)
        except (OperationalError, PendingRollbackError):
            # 连接事务瞬时冲突：稍后重试
            await asyncio.sleep(_POLL_INTERVAL)
            continue
        if last is not None and last.status in statuses:
            return last
        await asyncio.sleep(_POLL_INTERVAL)
    actual = last.status if last is not None else "记录不存在"
    raise AssertionError(
        f"等待 run 状态超时 run_id={run_id}, 期望={statuses}, 实际={actual}"
    )


@pytest.fixture
async def isolated_node_db(monkeypatch, session_factory):
    """将节点内部使用的 AsyncSessionLocal 指向内存库（夹具）。

    Agent 节点（record_agent_event / 参考板落库 / 一致性落库）通过
    from-import 将 AsyncSessionLocal 绑定在各自模块命名空间，因此需要
    分别替换 app.agents.nodes、app.agents.nodes.asset_agent、
    app.agents.nodes.consistency_agent 三处绑定，避免依赖真实 MySQL。
    monkeypatch 夹具在测试结束后自动还原。

    Args:
        monkeypatch: pytest monkeypatch 夹具。
        session_factory: 内存库会话工厂夹具。

    Yields:
        async_sessionmaker: 已生效替换的内存库会话工厂。
    """
    for target in (
        "app.agents.nodes",
        "app.agents.nodes.asset_agent",
        "app.agents.nodes.consistency_agent",
    ):
        monkeypatch.setattr(f"{target}.AsyncSessionLocal", session_factory)
    yield session_factory


@pytest.fixture
def project_factory(make_project):
    """提供默认造项目函数（内部透传夹具）。

    Args:
        make_project: 项目造数夹具。

    Returns:
        Callable: 异步项目构造函数。
    """
    return make_project


async def test_graph_interrupt_and_resume_full_flow(
    session_factory, db_session, project_factory, isolated_node_db
):
    """全流程中断恢复冒烟：中断 → 逐次恢复 → 最终完成。

    Args:
        session_factory: 内存库会话工厂夹具。
        db_session: 测试直接使用的数据库会话夹具。
        project_factory: 项目造数夹具。
        isolated_node_db: 节点写库隔离夹具。

    Returns:
        None
    """
    project_id = await project_factory(title="中断恢复测试项目")

    # ---- 启动 Graph：full 入口，后台执行 ----
    result = await graph_domain.run_graph(
        db_session, project_id, 1, GraphRunRequest()
    )
    run_id = result["run_id"]

    # ---- 断言：跑到第一个 interrupt（assets）后状态为中断等待 ----
    run = await _wait_for_status(
        session_factory, run_id,
        {GraphRunStatus.INTERRUPTED, GraphRunStatus.FAILED},
    )
    assert run.status == GraphRunStatus.INTERRUPTED, f"应中断等待而非失败"
    assert run.interrupt_at == "assets", f"首个中断节点应为 assets，实际 {run.interrupt_at}"

    # ---- 断言：checkpoint 已持久化，图停在 assets 节点 ----
    graph = get_graph()
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("assets",), f"checkpoint next 应为 assets，实际 {snapshot.next}"
    assert snapshot.values.get("script"), "checkpoint 应包含 script 阶段产出"

    # ---- 逐次恢复：assets → storyboard → keyframes → review → DONE ----
    expected_next = {"assets": "storyboard", "storyboard": "keyframes", "keyframes": "review"}
    current = "assets"
    for _ in range(4):
        resume_result = await graph_domain.resume_graph(
            db_session, project_id,
            GraphResumeRequest(action="approve", feedback=f"确认 {current} 阶段产出"),
        )
        assert resume_result["run_id"] == run_id
        assert resume_result["action"] == "approve"

        run = await _wait_for_status(
            session_factory, run_id,
            {GraphRunStatus.INTERRUPTED, GraphRunStatus.DONE, GraphRunStatus.FAILED},
        )
        assert run.status != GraphRunStatus.FAILED, "恢复执行不应失败"

        nxt = expected_next.get(current)
        if nxt is None:
            break
        assert run.status == GraphRunStatus.INTERRUPTED, \
            f"恢复 {current} 后应在 {nxt} 中断等待，实际 {run.status}"
        assert run.interrupt_at == nxt, \
            f"checkpoint 应推进到 {nxt}，实际 {run.interrupt_at}"
        current = nxt

    # ---- 断言：最终完成，中断标记清空 ----
    final = await _fetch_run(session_factory, run_id)
    assert final.status == GraphRunStatus.DONE, f"全流程恢复后应为 done，实际 {final.status}"
    assert final.interrupt_at is None, "完成态不应残留中断节点"

    # ---- 断言：完成态 checkpoint next 为空（无待执行节点）----
    snapshot = await graph.aget_state(config)
    assert snapshot.next == (), f"完成后 checkpoint next 应为空，实际 {snapshot.next}"
    assert snapshot.values.get("script"), "完成态 checkpoint 应保留全程状态"


async def test_graph_resume_reject_cancels_run(
    session_factory, db_session, project_factory, isolated_node_db
):
    """驳回分支：resume action=reject 时 run 置 CANCELLED。

    Args:
        session_factory: 内存库会话工厂夹具。
        db_session: 测试直接使用的数据库会话夹具。
        project_factory: 项目造数夹具。
        isolated_node_db: 节点写库隔离夹具。

    Returns:
        None
    """
    project_id = await project_factory(title="驳回测试项目")

    result = await graph_domain.run_graph(db_session, project_id, 1, GraphRunRequest())
    run_id = result["run_id"]

    run = await _wait_for_status(
        session_factory, run_id, {GraphRunStatus.INTERRUPTED, GraphRunStatus.FAILED}
    )
    assert run.status == GraphRunStatus.INTERRUPTED

    # ---- 驳回：置 CANCELLED 且清空中断标记 ----
    reject_result = await graph_domain.resume_graph(
        db_session, project_id,
        GraphResumeRequest(action="reject", feedback="剧本不合格，重新生成"),
    )
    assert reject_result == {
        "run_id": run_id, "action": "reject", "feedback": "剧本不合格，重新生成",
    }

    run = await _fetch_run(session_factory, run_id)
    assert run.status == GraphRunStatus.CANCELLED, f"驳回后应 cancelled，实际 {run.status}"
    assert run.interrupt_at is None, "驳回后不应残留中断节点"


async def test_graph_resume_without_interrupt_raises_not_found(db_session, project_factory):
    """契约保持：项目无中断 run 时 resume 抛 NOT_FOUND 业务异常。

    Args:
        db_session: 测试直接使用的数据库会话夹具。
        project_factory: 项目造数夹具。

    Returns:
        None
    """
    project_id = await project_factory(title="无中断项目")

    with pytest.raises(BizException) as exc_info:
        await graph_domain.resume_graph(
            db_session, project_id,
            GraphResumeRequest(action="approve"),
        )
    assert exc_info.value.code == ErrorCode.NOT_FOUND
