"""
订单 API 路由。

提供订单列表查询与充值端点。
路由挂载于 /orders 前缀下。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import ok
from app.domains import orders as orders_domain
from app.models import User
from app.schemas.order import RechargeRequest

router = APIRouter(tags=["订单"])


@router.get("", summary="订单列表")
async def list_orders(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """查询当前用户的全部订单。

    Args:
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为订单列表。
    """
    orders = await orders_domain.list_orders(db, user.id)
    return ok(data=[o.model_dump() for o in orders])


@router.post("/recharge", summary="充值")
async def recharge(
    req: RechargeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """创建充值订单并加点数（mock 实现）。

    Args:
        req: 充值请求体。
        db: 异步数据库会话。
        user: 当前登录用户。

    Returns:
        dict: 统一响应结构，data 为订单信息。
    """
    order = await orders_domain.recharge(db, user.id, req)
    return ok(data=order.model_dump())
