"""物流查询服务（服务编排层）：归属二次断言 + 出参组装。"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LogisticsNotFoundError
from app.models.logistics import Logistics
from app.models.user import User
from app.retrieval.structured import get_logistics_by_tracking_for_user
from app.schemas.order import LogisticsDetailOut

logger = logging.getLogger(__name__)


async def get_own_logistics(
    session: AsyncSession, tracking_no: str, user: User
) -> Logistics:
    """查询本人物流；不存在或不属于本人一律 404/20001（防单号枚举）。"""
    logistics = await get_logistics_by_tracking_for_user(session, tracking_no, user.id)
    if logistics is None:
        raise LogisticsNotFoundError()

    # 第二层防御断言（api_design.md 5 的同一策略）
    if logistics.order.user_id != user.id:
        raise LogisticsNotFoundError()
    logger.info("logistics queried tracking_no=%s user_id=%s", tracking_no, user.id)
    return logistics


def logistics_detail_to_out(logistics: Logistics) -> LogisticsDetailOut:
    """出参带订单上下文：客服场景需要回答"该单号对应您的哪个订单"。"""
    order = logistics.order
    return LogisticsDetailOut(
        tracking_no=logistics.tracking_no,
        carrier=logistics.carrier,
        status=logistics.status,
        timeline=logistics.timeline,
        updated_at=logistics.updated_at,
        order_no=order.order_no,
        order_status=order.status,
    )
