"""
生产状态图（ProductionGraph）构建模块。

基于 langgraph.graph.StateGraph 构建 AI 漫剧生产流水线状态图，
包含 9 个 Agent 节点与 4 处人工中断点（interrupt）。
当 langgraph 未安装时，自动降级为简化的函数式编排实现，
保持 build_graph / get_graph 接口不变。

流水线顺序：
    supervisor -> script -> [interrupt①] -> assets -> consistency
    -> [interrupt②] -> storyboard -> [interrupt③] -> keyframes
    -> consistency -> video -> voice -> compose -> [interrupt④] -> review
"""

import copy
from typing import Any, Callable, Optional

from app.agents.checkpointer_adapter import get_checkpointer
from app.agents.state import ProductionState
from app.core.logging import get_logger
from app.agents.nodes.script_agent import script_agent_node
from app.agents.nodes.asset_agent import asset_agent_node
from app.agents.nodes.consistency_agent import consistency_agent_node
from app.agents.nodes.storyboard_agent import storyboard_agent_node
from app.agents.nodes.keyframe_agent import keyframe_agent_node
from app.agents.nodes.video_agent import video_agent_node
from app.agents.nodes.voice_agent import voice_agent_node
from app.agents.nodes.editor_agent import editor_agent_node
from app.agents.nodes.compliance_agent import compliance_agent_node

logger = get_logger()

# 尝试导入 langgraph；失败则走函数式降级
try:  # pragma: no cover - 依赖环境
    from langgraph.graph import StateGraph  # type: ignore
    from langgraph.types import interrupt  # type: ignore

    _HAS_LANGGRAPH = True
except Exception:  # noqa: BLE001
    StateGraph = None  # type: ignore
    interrupt = None  # type: ignore
    _HAS_LANGGRAPH = False


# 节点名到执行函数的映射（不含 supervisor，由内部定义）
NODE_FUNC_MAP: dict[str, Callable] = {
    "script": script_agent_node,
    "assets": asset_agent_node,
    "consistency": consistency_agent_node,
    "storyboard": storyboard_agent_node,
    "keyframes": keyframe_agent_node,
    "video": video_agent_node,
    "voice": voice_agent_node,
    "compose": editor_agent_node,
    "review": compliance_agent_node,
}

# 需要在执行前插入 interrupt 的节点集合
# interrupt 放在下游节点开头，这样上游节点的产出已写入 state，可供人工审核
INTERRUPT_BEFORE_NODES = {"assets", "storyboard", "keyframes", "review"}

# 全流水线节点顺序（含中断标记，用于降级实现）
PIPELINE: list[str] = [
    "supervisor",
    "script",
    "interrupt_after_script",
    "assets",
    "consistency",
    "interrupt_after_assets",
    "storyboard",
    "interrupt_after_storyboard",
    "keyframes",
    "consistency",
    "video",
    "voice",
    "compose",
    "interrupt_after_compose",
    "review",
]


def _supervisor_node(state: ProductionState) -> dict:
    """Supervisor 节点：根据 state.stage 决定从哪个节点开始执行。

    本节点不产生实际业务输出，仅返回空字典，
    实际路由由 conditional_edges 完成。

    Args:
        state: 当前生产状态。

    Returns:
        dict: 空增量（路由由条件边决定）。
    """
    stage = state.get("stage", "script")
    logger.info(f"[supervisor] 根据 stage={stage} 路由到对应节点")
    return {}


def _route_by_stage(state: ProductionState) -> str:
    """Supervisor 路由函数：根据 state.stage 决定下一个节点。

    Args:
        state: 当前生产状态。

    Returns:
        str: 下一个要执行的节点名称。
    """
    stage = state.get("stage", "script")
    stage_map = {
        "script": "script",
        "assets": "assets",
        "storyboard": "storyboard",
        "keyframes": "keyframes",
        "video": "video",
        "voice": "voice",
        "compose": "compose",
        "review": "review",
    }
    return stage_map.get(stage, "script")


def _make_interrupt_wrapper(name: str, func: Callable) -> Callable:
    """为需要中断的节点创建包装函数：先调用 interrupt()，再执行业务逻辑。

    interrupt 放在节点开头，确保上游节点的产出已写入 state，
    人工审核时能看到完整的上游阶段结果。

    Args:
        name: 节点名称。
        func: 原始节点函数。

    Returns:
        Callable: 包装后的异步函数。
    """

    async def wrapper(state: ProductionState) -> dict:
        """包装节点：先触发中断，恢复后执行原函数。

        Args:
            state: 当前生产状态。

        Returns:
            dict: 原节点返回的状态增量。
        """
        if _HAS_LANGGRAPH and interrupt is not None:
            logger.info(f"[graph] 进入节点 {name} 前触发 interrupt，等待人工审核")
            interrupt({"node": name, "message": f"请人工审核后继续执行 {name}"})
        delta = await func(state)
        return delta

    return wrapper


def _route_after_consistency(state: ProductionState) -> str:
    """一致性校验后的路由函数：根据 state.stage 决定流向 storyboard 或 video。

    Args:
        state: 当前生产状态。

    Returns:
        str: 下一个节点名称（storyboard 或 video）。
    """
    stage = state.get("stage", "storyboard")
    return "video" if stage == "video" else "storyboard"


def build_graph() -> Any:
    """构建 ProductionGraph 状态图。

    若 langgraph 可用，则使用 StateGraph 构建并编译；
    否则返回一个简化的函数式编排对象（SimpleProductionGraph）。

    Returns:
        Any: 编译后的 langgraph 图，或简化的函数式编排对象。
    """
    if not _HAS_LANGGRAPH:
        logger.warning("[graph] langgraph 未安装，使用简化函数式编排。")
        return SimpleProductionGraph()

    workflow = StateGraph(ProductionState)

    # 添加 supervisor 节点
    workflow.add_node("supervisor", _supervisor_node)

    # 添加业务节点，对需要中断的节点进行包装
    for name, func in NODE_FUNC_MAP.items():
        if name in INTERRUPT_BEFORE_NODES:
            workflow.add_node(name, _make_interrupt_wrapper(name, func))
        else:
            workflow.add_node(name, func)

    # 起始边：supervisor 根据 stage 路由
    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _route_by_stage,
        {name: name for name in NODE_FUNC_MAP},
    )

    # 主流水线顺序边（含两处 consistency 校验）
    workflow.add_edge("script", "assets")
    workflow.add_edge("assets", "consistency")
    # consistency 根据 stage 路由到 storyboard（资产校验后）或 video（关键帧校验后）
    workflow.add_conditional_edges(
        "consistency",
        _route_after_consistency,
        {"storyboard": "storyboard", "video": "video"},
    )
    workflow.add_edge("storyboard", "keyframes")
    workflow.add_edge("keyframes", "consistency")
    workflow.add_edge("video", "voice")
    workflow.add_edge("voice", "compose")
    workflow.add_edge("compose", "review")
    workflow.add_edge("review", "__end__")

    # 编译并传入 checkpointer
    compiled = workflow.compile(checkpointer=get_checkpointer().get_saver())
    return compiled


class SimpleProductionGraph:
    """简化的函数式编排（langgraph 不可用时的降级实现）。

    保持与 langgraph 编译图相似的调用接口（ainvoke），
    按 PIPELINE 顺序依次执行节点，遇到中断标记则暂停并返回当前状态。

    Attributes:
        _resume_from: 恢复执行时的起始索引。
    """

    def __init__(self) -> None:
        """初始化简化编排对象。

        Returns:
            None
        """
        self._resume_from: int = 0

    async def ainvoke(self, state: dict, config: Optional[dict] = None) -> dict:
        """异步执行流水线。

        Args:
            state: 初始生产状态。
            config: 配置字典（含 thread_id 等，简化版忽略）。

        Returns:
            dict: 执行后的完整状态。若遇到中断点，则返回中断时的状态，
                  可再次调用 ainvoke 恢复执行。
        """
        current = copy.deepcopy(state)
        start_idx = self._resume_from

        for idx in range(start_idx, len(PIPELINE)):
            step = PIPELINE[idx]

            # 中断点：暂停执行
            if step.startswith("interrupt_"):
                logger.info(f"[graph] 到达中断点: {step}")
                self._resume_from = idx + 1
                current["_interrupted_at"] = step
                return current

            # supervisor 节点：根据 stage 跳转到对应节点
            if step == "supervisor":
                target = _route_by_stage(current)
                if target in PIPELINE:
                    target_idx = PIPELINE.index(target)
                    idx = target_idx - 1  # for 循环会 +1
                    continue

            # 普通节点
            func = NODE_FUNC_MAP.get(step)
            if func is None:
                continue
            try:
                delta = await func(current)
                current.update(delta)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[graph] 节点 {step} 执行失败: {exc}")
                current.setdefault("errors", []).append({"node": step, "error": str(exc)})

        self._resume_from = 0
        current.pop("_interrupted_at", None)
        return current


# 单例缓存
_graph: Optional[Any] = None


def get_graph() -> Any:
    """获取 ProductionGraph 单例。

    Returns:
        Any: 编译后的图实例或简化编排对象。
    """
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
