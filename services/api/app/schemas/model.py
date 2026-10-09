"""
模型中心相关请求 / 响应模型。

定义模型配置、Key 校验的 Pydantic 结构。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import ModelCapability


class ModelOut(BaseModel):
    """模型配置输出模型。

    Attributes:
        id: 配置ID。
        capability: 能力类型。
        provider: 厂商标识。
        model_name: 模型名称。
        api_base: 自定义API地址。
        price_meta: 计价元数据。
        scope: 作用域（global / user / project）。
    """

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    capability: ModelCapability
    provider: str
    model_name: str
    api_base: Optional[str] = None
    price_meta: Optional[Dict[str, Any]] = None
    scope: str


class ModelConfigCreate(BaseModel):
    """项目级模型配置创建 / 更新请求体。

    Attributes:
        capability: 能力类型。
        provider: 厂商标识。
        model_name: 模型名称。
        api_key: API Key（可选，将加密存储）。
        api_base: 自定义API地址。
        params: 请求参数。
        price_meta: 计价元数据。
    """

    model_config = ConfigDict(protected_namespaces=())

    capability: ModelCapability
    provider: str = Field(..., max_length=50)
    model_name: str = Field(..., max_length=50)
    api_key: Optional[str] = Field(None, description="API Key")
    api_base: Optional[str] = Field(None, max_length=255, description="自定义API地址")
    params: Optional[Dict[str, Any]] = None
    price_meta: Optional[Dict[str, Any]] = None


class VerifyKeyRequest(BaseModel):
    """Key 连通性测试请求体。

    Attributes:
        provider: 厂商标识。
        model_name: 模型名称。
        api_key: API Key。
        api_base: 自定义API地址。
    """

    model_config = ConfigDict(protected_namespaces=())

    provider: str = Field(..., max_length=50)
    model_name: str = Field(..., max_length=50)
    api_key: str = Field(..., description="API Key")
    api_base: Optional[str] = Field(None, max_length=255)


class VerifyKeyOut(BaseModel):
    """Key 连通性测试结果输出模型。

    Attributes:
        valid: Key 是否有效。
        latency_ms: 请求耗时（毫秒）。
        models: 可用模型列表。
    """

    valid: bool
    latency_ms: int = 0
    models: List[str] = []


class UserKeyCreate(BaseModel):
    """用户 API Key 创建请求体。

    Attributes:
        provider: 厂商标识（如 deepseek / openai）。
        capability: 能力类型（文本 / 图像 / 视频 / 语音）。
        api_key: API Key 明文，后端 AES 加密存储。
    """

    model_config = ConfigDict(protected_namespaces=())

    provider: str = Field(..., max_length=50, description="厂商标识")
    capability: str = Field(..., description="能力类型：文本/图像/视频/语音")
    api_key: str = Field(..., min_length=8, description="API Key 明文")


class UserKeyUpdate(BaseModel):
    """用户 API Key 更新请求体。

    Attributes:
        provider: 厂商标识。
        capability: 能力类型（文本 / 图像 / 视频 / 语音）。
        api_key: API Key 明文，为空时表示不修改原 Key。
    """

    model_config = ConfigDict(protected_namespaces=())

    provider: str = Field(..., max_length=50, description="厂商标识")
    capability: str = Field(..., description="能力类型：文本/图像/视频/语音")
    api_key: Optional[str] = Field(None, description="API Key 明文，留空则不修改")


class SelectModelRequest(BaseModel):
    """项目选择模型请求体。

    Attributes:
        type: 模型类型（llm/image/video/audio），冗余字段，以后端查询为准。
        model_id: 候选模型记录 ID。
    """

    model_config = ConfigDict(protected_namespaces=())

    type: Optional[str] = Field(None, description="模型类型（冗余，可空）")
    model_id: int = Field(..., description="候选模型记录 ID")
