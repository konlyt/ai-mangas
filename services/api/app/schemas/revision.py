"""
版本快照相关请求 / 响应模型。

定义版本快照输出与版本回退请求的 Pydantic 结构。
"""

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class RevisionOut(BaseModel):
    """版本快照输出模型。

    Attributes:
        id: 快照 ID。
        project_id: 项目 ID。
        stage: 阶段。
        snapshot: 阶段产出快照。
        graph_checkpoint_id: 对应检查点 ID。
        created_by: 操作用户 ID。
        created_at: 创建时间。
    """

    id: int
    project_id: int
    stage: str
    snapshot: Dict[str, Any]
    graph_checkpoint_id: str | None = None
    created_by: int
    created_at: datetime

    # Pydantic v2 配置：允许从 ORM 对象读取属性
    model_config = ConfigDict(from_attributes=True)


class RevisionRestoreRequest(BaseModel):
    """版本回退请求体。

    Attributes:
        stage: 回退到的阶段，可选。
    """

    stage: str | None = Field(None, description="回退到的阶段")
