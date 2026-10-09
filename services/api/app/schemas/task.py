"""
任务相关请求 / 响应模型。

定义任务输出、任务分页列表、任务重试请求的 Pydantic 结构。
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import QueueName, TaskStatus, TaskType


class TaskOut(BaseModel):
    """任务输出模型。

    Attributes:
        id: 任务 ID。
        project_id: 项目 ID。
        storyboard_id: 分镜 ID。
        graph_run_id: 关联 Graph 执行 ID。
        type: 任务类型（image / video / tts / compose）。
        status: 状态。
        queue_name: 队列名称。
        priority: 优先级。
        idempotency_key: 幂等键。
        provider_task_id: 第三方任务 ID。
        result_url: 结果文件 URL。
        error_message: 错误信息。
        retry_count: 已重试次数。
        max_retry: 最大重试次数。
        next_retry_at: 下次重试时间。
        cost_points: 消耗点数。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    storyboard_id: Optional[int] = None
    graph_run_id: Optional[str] = None
    type: TaskType
    status: TaskStatus
    queue_name: QueueName
    priority: int = 5
    idempotency_key: str
    provider_task_id: Optional[str] = None
    result_url: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retry: int = 3
    next_retry_at: Optional[datetime] = None
    cost_points: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class TaskListOut(BaseModel):
    """任务分页列表输出模型。

    Attributes:
        list: 任务列表。
        total: 总记录数。
        page: 当前页码。
        page_size: 每页条数。
        total_pages: 总页数。
    """

    list: List[TaskOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class TaskRetryRequest(BaseModel):
    """任务重试请求体。

    Attributes:
        max_retry: 新的最大重试次数，为空时使用原配置。
    """

    max_retry: Optional[int] = Field(None, description="新的最大重试次数")
