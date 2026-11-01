"""订单服务（服务编排层）：归属二次断言 + 出参脱敏。"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import OrderNotFoundError
from app.core.security import mask_address, mask_name, mask_phone
from app.models.order import Order
from app.models.user import User
from app.retrieval.structured import get_order_by_no_for_user, list_orders_for_user
from app.schemas.order import LogisticsOut, OrderItemOut, OrderOut

logger = logging.getLogger(__name__)


async def get_own_order(session: AsyncSession, order_no: str, user: User) -> Order:
    """查询本人订单；不存在或不属于本人一律 404/20001（防枚举）。"""
    order = await get_order_by_no_for_user(session, order_no, user.id)
    if order is None:
        raise OrderNotFoundError()

    # 第二层防御断言（api_design.md 5：数据层 SQL 已强制，服务层再断言）
    if order.user_id != user.id:
        raise OrderNotFoundError()
    # 安全相关事件记 INFO（订单号非敏感信息，可入日志）
    logger.info("order queried order_no=%s user_id=%s", order_no, user.id)
    return order


async def list_own_orders(
    session: AsyncSession, user: User, page: int, page_size: int
) -> tuple[int, list[Order]]:
    return await list_orders_for_user(session, user.id, page, page_size)


def order_to_out(order: Order) -> OrderOut:
    """ORM → 出参模型；敏感字段在此统一脱敏，绝不外泄明文。"""
    return OrderOut(
        order_no=order.order_no,
        status=order.status,
        total_amount=order.total_amount,
        receiver_name=mask_name(order.receiver_name),
        receiver_phone=mask_phone(order.receiver_phone),
        receiver_address=mask_address(order.receiver_address),
        items=[
            OrderItemOut(
                product_name_snapshot=item.product_name_snapshot,
                sku_snapshot=item.sku_snapshot,
                price_snapshot=item.price_snapshot,
                quantity=item.quantity,
            )
            for item in order.items
        ],
        created_at=order.created_at,
    )


def logistics_to_out(order: Order) -> LogisticsOut | None:
    """物流出参；订单存在但没有物流行时返回 None（路由层以 data=null 响应）。"""
    if order.logistics is None:
        return None
    lg = order.logistics
    return LogisticsOut(
        tracking_no=lg.tracking_no,
        carrier=lg.carrier,
        status=lg.status,
        timeline=lg.timeline,
        updated_at=lg.updated_at,
    )
