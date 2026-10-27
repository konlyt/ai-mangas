"""
项目相关请求 / 响应模型。

定义项目创建、更新、列表、详情、统计的 Pydantic 结构。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import ProjectStatus


class ProjectCreate(BaseModel):
    """项目创建请求体。

    Attributes:
        title: 项目标题。
        genre: 体裁（可选）。
        style: 视觉风格（可选）。
        aspect_ratio: 输出比例，默认 "9:16"。
        raw_input: 原始输入文本（可选，将存入 config）。
        meta: 额外元数据（可选，将存入 config）。
    """

    title: str = Field(..., min_length=1, max_length=100, description="项目标题")
    genre: Optional[str] = Field(None, max_length=20, description="体裁")
    style: Optional[str] = Field(None, max_length=20, description="视觉风格")
    aspect_ratio: Optional[str] = Field("9:16", max_length=10, description="输出比例")
    raw_input: Optional[str] = Field(None, description="原始输入文本")
    meta: Optional[Dict[str, Any]] = Field(None, description="额外元数据")


class ProjectUpdate(BaseModel):
    """项目更新请求体。

    所有字段均可选，仅传入需要更新的字段。

    Attributes:
        title: 项目标题。
        genre: 体裁。
        style: 视觉风格。
        status: 项目阶段。
        aspect_ratio: 输出比例。
        config: 项目级模型配置。
        cover_url: 项目封面URL。
    """

    title: Optional[str] = Field(None, max_length=100)
    genre: Optional[str] = Field(None, max_length=20)
    style: Optional[str] = Field(None, max_length=20)
    status: Optional[ProjectStatus] = None
    aspect_ratio: Optional[str] = Field(None, max_length=10)
    config: Optional[Dict[str, Any]] = None
    cover_url: Optional[str] = Field(None, max_length=255)


class ProjectOut(BaseModel):
    """项目详情输出模型。

    Attributes:
        id: 项目ID。
        user_id: 用户ID。
        title: 标题。
        genre: 体裁。
        style: 视觉风格。
        status: 项目阶段。
        aspect_ratio: 输出比例。
        config: 项目级模型配置。
        cover_url: 封面URL。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    user_id: int
    title: str
    genre: Optional[str] = None
    style: Optional[str] = None
    status: ProjectStatus
    aspect_ratio: str
    config: Optional[Dict[str, Any]] = None
    cover_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Pydantic v2 配置：允许从 ORM 对象读取属性
    model_config = ConfigDict(from_attributes=True)


class ProjectListOut(BaseModel):
    """项目分页列表输出模型。

    Attributes:
        list: 项目列表。
        total: 总记录数。
        page: 当前页码。
        page_size: 每页条数。
        total_pages: 总页数。
    """

    list: List[ProjectOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProjectStatsOut(BaseModel):
    """项目统计输出模型。

    Attributes:
        today_projects: 今日新建项目数。
        month_projects: 本月新建项目数。
        image_count: 图片数量。
        video_duration: 视频时长（秒）。
        cost_points: 累计消耗点数。
    """

    today_projects: int = 0
    month_projects: int = 0
    image_count: int = 0
    video_duration: int = 0
    cost_points: int = 0
