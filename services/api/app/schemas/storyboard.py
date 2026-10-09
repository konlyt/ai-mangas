"""
分镜相关请求 / 响应模型。

定义分镜输出、生成、更新、批量操作的 Pydantic 结构。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models import StoryboardStatus


class StoryboardOut(BaseModel):
    """分镜输出模型。

    Attributes:
        id: 分镜 ID。
        project_id: 项目 ID。
        script_id: 剧本 ID。
        episode_id: 剧集 ID。
        sequence: 镜头序号。
        shot_type: 景别。
        camera_movement: 运镜方式。
        duration: 预计时长（秒）。
        visual_description: 画面描述。
        dialogue: 对白 / 旁白。
        character_ids: 涉及角色 ID 列表。
        scene_id: 场景 ID。
        prompt: 绘图提示词。
        keyframe_url: 首帧 URL。
        endframe_url: 尾帧 URL。
        video_url: 视频片段 URL。
        audio_url: 配音 URL。
        status: 状态。
        created_at: 创建时间。
        updated_at: 更新时间。
    """

    id: int
    project_id: int
    script_id: int
    episode_id: Optional[int] = None
    sequence: int
    shot_type: Optional[str] = None
    camera_movement: Optional[str] = None
    duration: int = 5
    visual_description: Optional[str] = None
    dialogue: Optional[str] = None
    character_ids: Optional[List[int]] = None
    scene_id: Optional[int] = None
    prompt: Optional[str] = None
    keyframe_url: Optional[str] = None
    endframe_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    status: StoryboardStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class StoryboardGenerateRequest(BaseModel):
    """分镜生成请求体。

    Attributes:
        script_id: 指定剧本 ID，为空时使用项目最新剧本。
        episode_id: 剧集 ID，可选。
    """

    script_id: Optional[int] = Field(None, description="剧本 ID，为空时使用最新剧本")
    episode_id: Optional[int] = Field(None, description="剧集 ID")


class StoryboardUpdateRequest(BaseModel):
    """分镜更新请求体。

    所有字段均可选，仅传入需要更新的字段。

    Attributes:
        shot_type: 景别。
        camera_movement: 运镜方式。
        duration: 预计时长。
        visual_description: 画面描述。
        dialogue: 对白 / 旁白。
        character_ids: 涉及角色 ID 列表。
        scene_id: 场景 ID。
        prompt: 绘图提示词。
    """

    shot_type: Optional[str] = None
    camera_movement: Optional[str] = None
    duration: Optional[int] = None
    visual_description: Optional[str] = None
    dialogue: Optional[str] = None
    character_ids: Optional[List[int]] = None
    scene_id: Optional[int] = None
    prompt: Optional[str] = None


class StoryboardBatchOperation(BaseModel):
    """分镜批量操作单项。

    Attributes:
        op: 操作类型：add / delete / reorder / update。
        sequence: 目标镜头序号。
        data: 操作数据（add/update 时使用）。
    """

    op: str = Field(..., description="操作类型：add / delete / reorder / update")
    sequence: Optional[int] = Field(None, description="目标镜头序号")
    data: Optional[Dict[str, Any]] = Field(None, description="操作数据")


class StoryboardBatchRequest(BaseModel):
    """分镜批量操作请求体。

    Attributes:
        operations: 操作列表。
    """

    operations: List[StoryboardBatchOperation] = Field(..., description="批量操作列表")


class StoryboardReorderRequest(BaseModel):
    """分镜重排请求体（拖拽排序 SB-04）。

    Attributes:
        ordered_ids: 按新顺序排列的分镜 ID 列表，必须完整覆盖项目下全部分镜。
    """

    ordered_ids: List[int] = Field(..., description="按新顺序排列的分镜 ID 列表")


class ContinuityIssue(BaseModel):
    """连续性问题项（SB-06）。

    Attributes:
        between: 出现衔接问题的相邻两个分镜的镜头序号。
        type: 问题类型（角色 / 场景 / 时间 / 道具等）。
        message: 问题描述。
        severity: 严重程度（low / medium / high）。
    """

    between: List[int] = Field(default_factory=list, description="相邻两个分镜的镜头序号")
    type: str = Field(default="", description="问题类型：角色 / 场景 / 时间 / 道具")
    message: str = Field(default="", description="问题描述")
    severity: str = Field(default="medium", description="严重程度：low / medium / high")


class ContinuityCheckOut(BaseModel):
    """连续性检查结果（SB-06）。

    Attributes:
        checked: LLM 检查是否成功完成。
        issues: 发现的衔接问题列表。
    """

    checked: bool = Field(..., description="LLM 检查是否成功完成")
    issues: List[ContinuityIssue] = Field(default_factory=list, description="衔接问题列表")
