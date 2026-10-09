"""
Graph 编排相关请求 / 响应模型。

定义 Graph 运行请求、状态查询、恢复执行的 Pydantic 结构。
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.models import GraphEntryPoint


class GraphRunRequest(BaseModel):
    """Graph 运行请求体。

    Attributes:
        entry_point: 执行入口（full / stage / partial）。
        target_node: partial 模式下的目标节点。
        payload: 初始状态载荷。
    """

    entry_point: GraphEntryPoint = Field(GraphEntryPoint.FULL, description="执行入口")
    target_node: Optional[str] = Field(None, description="partial 目标节点")
    payload: Optional[Dict[str, Any]] = Field(None, description="初始状态载荷")


class GraphStateOut(BaseModel):
    """Graph 状态输出模型。

    Attributes:
        state: 当前生产状态。
        interrupt_at: 中断所在节点。
        pending: 是否处于中断等待状态。
        run_id: 当前执行 ID。
        status: 执行状态。
    """

    state: Dict[str, Any] = Field(default_factory=dict)
    interrupt_at: Optional[str] = None
    pending: bool = False
    run_id: Optional[str] = None
    status: Optional[str] = None


class GraphResumeRequest(BaseModel):
    """Graph 恢复执行请求体。

    Attributes:
        action: 操作类型：approve（确认继续）/ reject（驳回）。
        feedback: 人工反馈意见，回传给 Agent。
    """

    action: str = Field("approve", description="操作：approve / reject")
    feedback: Optional[str] = Field(None, description="人工反馈意见")
