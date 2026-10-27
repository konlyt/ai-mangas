"""
剧本相关请求 / 响应模型。

定义剧本生成请求、剧本输出、剧本更新请求的 Pydantic 结构。
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ScriptGenerateRequest(BaseModel):
    """剧本生成请求体。

    Attributes:
        raw_input: 原始输入文本（标题、题材、原始文本等）。
        meta: 额外元数据（用户 ID、trace_id 等）。
    """

    raw_input: str = Field(..., min_length=1, description="原始输入文本")
    meta: Optional[Dict[str, Any]] = Field(None, description="额外元数据")


class ScriptUpdateRequest(BaseModel):
    """剧本更新请求体。

    Attributes:
        content: 结构化剧本内容（JSON）。
        raw_text: 原始文本，可选。
    """

    content: Dict[str, Any] = Field(..., description="结构化剧本内容")
    raw_text: Optional[str] = Field(None, description="原始文本")


class ScriptOut(BaseModel):
    """剧本输出模型。

    Attributes:
        id: 剧本 ID。
        project_id: 项目 ID。
        content: 结构化剧本内容。
        raw_text: 原始输入文本。
        version: 版本号。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    content: Dict[str, Any]
    raw_text: Optional[str] = None
    version: int = 1
    created_at: datetime
    updated_at: datetime

    # Pydantic v2 配置：允许从 ORM 对象读取属性
    model_config = ConfigDict(from_attributes=True)
