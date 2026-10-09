"""
资产相关请求 / 响应模型。

定义角色、场景、资产变体的输出模型，以及角色生成、锁定、重生成等请求体。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models import AssetOwnerType, AssetVariantStatus


class AssetVariantOut(BaseModel):
    """资产变体输出模型。

    Attributes:
        id: 变体 ID。
        owner_type: 资产归属类型（character / scene / prop）。
        owner_id: 归属对象 ID。
        variant_type: 变体类型（front / side / half 等）。
        image_url: 图片 URL。
        visual_prompt: 变体提示词。
        feature_vector: 面部特征向量。
        similarity_score: 一致性校验得分。
        status: 状态。
        created_at: 创建时间。
    """

    id: int
    owner_type: AssetOwnerType
    owner_id: int
    variant_type: str
    image_url: Optional[str] = None
    visual_prompt: Optional[str] = None
    feature_vector: Optional[List[float]] = None
    similarity_score: Optional[float] = None
    status: AssetVariantStatus
    created_at: datetime

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class CharacterOut(BaseModel):
    """角色输出模型。

    Attributes:
        id: 角色 ID。
        project_id: 项目 ID。
        name: 角色名。
        description: 角色描述。
        visual_prompt: 视觉提示词。
        voice_id: 绑定音色 ID。
        main_asset_url: 主定妆照 URL。
        reference_url: 用户上传的参考图 URL。
        is_locked: 是否锁定。
        variants: 该角色的资产变体列表。
        created_at: 创建时间。
    """

    id: int
    project_id: int
    name: str
    description: Optional[str] = None
    visual_prompt: str
    voice_id: Optional[str] = None
    main_asset_url: Optional[str] = None
    reference_url: Optional[str] = None
    is_locked: int = 0
    variants: List[AssetVariantOut] = Field(default_factory=list)
    created_at: datetime

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class SceneOut(BaseModel):
    """场景输出模型。

    Attributes:
        id: 场景 ID。
        project_id: 项目 ID。
        name: 场景名。
        description: 场景描述。
        visual_prompt: 视觉提示词。
        asset_url: 概念图 URL。
        is_locked: 是否锁定。
        created_at: 创建时间。
    """

    id: int
    project_id: int
    name: str
    description: Optional[str] = None
    visual_prompt: str
    asset_url: Optional[str] = None
    is_locked: int = 0
    created_at: datetime

    class Config:
        """Pydantic 配置：允许从 ORM 对象读取属性。"""

        from_attributes = True


class CharacterGenerateRequest(BaseModel):
    """角色生成请求体。

    Attributes:
        names: 要生成的角色名列表，为空时从剧本自动提取。
        force: 是否强制重新生成已存在的角色。
    """

    names: Optional[List[str]] = Field(None, description="角色名列表，为空时自动提取")
    force: bool = Field(False, description="是否强制重新生成")


class CharacterLockRequest(BaseModel):
    """角色锁定请求体。

    Attributes:
        main_variant_id: 作为主定妆照的变体 ID，可选。
    """

    main_variant_id: Optional[int] = Field(None, description="主定妆照变体 ID")


class AssetRegenerateRequest(BaseModel):
    """资产变体重生成请求体。

    Attributes:
        visual_prompt: 新的视觉提示词，可选，为空时使用原提示词。
        params: 额外生成参数（尺寸、seed 等）。
    """

    visual_prompt: Optional[str] = Field(None, description="新的视觉提示词")
    params: Optional[Dict[str, Any]] = Field(None, description="额外生成参数")
