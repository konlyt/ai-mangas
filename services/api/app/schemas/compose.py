"""
合成相关请求 / 响应模型。

定义全片合成、局部合成请求以及最终输出的 Pydantic 结构。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComposeRequest(BaseModel):
    """全片合成请求体。

    Attributes:
        storyboard_ids: 要合成的分镜 ID 列表，为空时合成全部分镜。
        with_audio: 是否合成配音。
        params: 额外合成参数（分辨率、帧率等）。
    """

    storyboard_ids: Optional[List[int]] = Field(None, description="分镜 ID 列表，为空时合成全部")
    with_audio: bool = Field(True, description="是否合成配音")
    params: Optional[Dict[str, Any]] = Field(None, description="额外合成参数")


class ComposePartialRequest(BaseModel):
    """局部重合成请求体。

    Attributes:
        storyboard_ids: 需要重合成的分镜 ID 列表。
        params: 额外合成参数。
    """

    storyboard_ids: List[int] = Field(..., description="需要重合成的分镜 ID 列表")
    params: Optional[Dict[str, Any]] = Field(None, description="额外合成参数")


class OutputOut(BaseModel):
    """最终合成输出模型。

    Attributes:
        video_url: 最终视频 URL。
        url: 最终视频 URL（video_url 别名，对齐前端 ComposeOutput 契约）。
        duration: 视频时长（秒）。
        size: 视频文件大小（字节）。
        cover_url: 封面 URL。
        created_at: 生成时间。
    """

    video_url: Optional[str] = None
    url: Optional[str] = None
    duration: int = 0
    size: int = 0
    cover_url: Optional[str] = None
    created_at: Optional[str] = None


class ExportRequest(BaseModel):
    """成片导出请求体。

    Attributes:
        ratio: 导出画面比例（9:16 或 16:9），缺省时使用项目配置比例。
    """

    ratio: Optional[str] = Field(None, description='导出比例："9:16" 或 "16:9"，缺省用项目配置')


class ExportOut(BaseModel):
    """成片导出结果模型。

    Attributes:
        url: 导出文件下载 URL。
        ratio: 导出比例。
        size: 导出文件大小（字节）。
        created_at: 导出时间。
    """

    url: Optional[str] = None
    ratio: Optional[str] = None
    size: int = 0
    created_at: Optional[str] = None
