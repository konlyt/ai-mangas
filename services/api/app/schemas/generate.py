"""
批量生成相关请求 / 响应模型。

定义关键帧 / 视频 / 语音批量生成的请求与响应结构。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """批量生成请求体。

    Attributes:
        storyboard_ids: 要生成的分镜 ID 列表，为空时生成全部分镜。
        mode: 生成模式，如 "all" / "only_pending"。
        voice_id: 音色 ID，仅配音（tts）任务使用；为空时按角色绑定与默认音色回退。
    """

    storyboard_ids: Optional[List[int]] = Field(None, description="分镜 ID 列表，为空时生成全部")
    mode: str = Field("only_pending", description="生成模式：all / only_pending")
    voice_id: Optional[str] = Field(None, description="音色 ID（仅 tts 任务，如 alloy/nova/default）")


class GenerateResponse(BaseModel):
    """批量生成响应体。

    Attributes:
        task_ids: 创建的任务 ID 列表。
        total: 任务总数。
    """

    task_ids: List[int] = Field(default_factory=list, description="任务 ID 列表")
    total: int = 0


class VideoRegenerateRequest(BaseModel):
    """视频片段降级换模重新生成请求体（VID-07）。

    Attributes:
        provider: 指定的视频生成厂商标识，"agnes"（默认，真实生成）或
            "mock"（降级占位生成）；为空时使用系统默认 Provider。
    """

    provider: Optional[Literal["agnes", "mock"]] = Field(
        None, description='视频 Provider："agnes" / "mock"，为空时使用默认'
    )


class VideoRegenerateResponse(BaseModel):
    """视频重新生成响应体。

    Attributes:
        new_task_id: 新创建的视频生成任务 ID。
        provider: 本次生成使用的 Provider 名称（为空表示使用系统默认）。
    """

    new_task_id: int = Field(..., description="新视频生成任务 ID")
    provider: Optional[str] = Field(None, description="指定使用的 Provider 名称")
