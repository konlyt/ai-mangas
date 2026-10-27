"""
订单相关请求 / 响应模型。

定义订单输出与充值请求的 Pydantic 结构。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderOut(BaseModel):
    """订单输出模型。

    Attributes:
        id: 订单 ID。
        user_id: 用户 ID。
        order_no: 订单号。
        amount: 金额。
        points: 充值点数。
        pay_type: 支付方式。
        status: 状态（0 待支付 / 1 已支付）。
        paid_at: 支付时间。
        created_at: 创建时间。
    """

    id: int
    user_id: int
    order_no: str
    amount: float
    points: int
    pay_type: Optional[str] = None
    status: int = 0
    paid_at: Optional[datetime] = None
    created_at: datetime

    # Pydantic v2 配置：允许从 ORM 对象读取属性
    model_config = ConfigDict(from_attributes=True)


class RechargeRequest(BaseModel):
    """充值请求体。

    Attributes:
        points: 充值点数。
        pay_type: 支付方式。
    """

    points: int = Field(..., gt=0, description="充值点数")
    pay_type: str = Field("wechat", description="支付方式")
