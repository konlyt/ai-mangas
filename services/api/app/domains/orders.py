"""
订单领域服务。

提供订单列表查询与充值（mock 直接加点数）功能。
"""

import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, User
from app.schemas.order import OrderOut, RechargeRequest


async def list_orders(db: AsyncSession, user_id: int) -> List[OrderOut]:
    """查询用户的全部订单（按创建时间倒序）。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。

    Returns:
        List[OrderOut]: 订单列表。
    """
    result = await db.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(desc(Order.created_at))
    )
    items = result.scalars().all()
    return [OrderOut.model_validate(o) for o in items]


async def recharge(db: AsyncSession, user_id: int, req: RechargeRequest) -> OrderOut:
    """创建充值订单并直接为用户加点数（mock 实现）。

    真实环境应走支付回调，此处简化为直接充值。

    Args:
        db: 异步数据库会话。
        user_id: 用户 ID。
        req: 充值请求体。

    Returns:
        OrderOut: 已支付的订单信息。
    """
    # 生成订单号
    order_no = f"R{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8]}"

    # mock 单价：1 元 = 10 点数
    amount = round(req.points / 10, 2)

    order = Order(
        user_id=user_id,
        order_no=order_no,
        amount=amount,
        points=req.points,
        pay_type=req.pay_type,
        status=1,  # 已支付
        paid_at=datetime.now(timezone.utc),
    )
    db.add(order)

    # 直接为用户加点数
    user = await db.get(User, user_id)
    if user is not None:
        user.quota = (user.quota or 0) + req.points

    await db.commit()
    await db.refresh(order)
    return OrderOut.model_validate(order)
