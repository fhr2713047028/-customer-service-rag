"""结构化问题的模板回答引擎（架构 0.7 决策 2：结构化问题不经过 LLM）。

订单/物流/商品类问题的数字信息（状态、金额、轨迹）直接来自查询结果，
模板渲染 —— 从源头杜绝编造，也是性能达标的最大杠杆。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.retrieval.structured import (
    get_order_by_no_for_user,
    list_orders_for_user,
    search_products,
)
from app.services.business import order_status_label
from app.services.order_service import order_to_out


def _order_source(order: Order) -> dict:
    return {
        "type": "order",
        "doc_title": None,
        "chunk_id": None,
        "section": None,
        "score": None,
        "order_no": order.order_no,
    }


async def answer_order_status(
    session: AsyncSession, user: User, order_no: str | None
) -> dict:
    """订单查询：有单号给详情；无单号给最近订单摘要让用户确认。"""
    if order_no:
        order = await get_order_by_no_for_user(session, order_no, user.id)
        if order is None:
            return {
                "answer": f"未查到您名下订单号为 {order_no} 的订单，请核对后重试。",
                "answer_type": "template",
                "sources": [],
                "confidence": "low",
            }
        logistics_note = ""
        if order.logistics is not None:
            logistics_note = (
                f"物流单号 {order.logistics.tracking_no}，"
                f"当前物流状态：{order.logistics.status}。"
            )
        answer = (
            f"您的订单 {order.order_no} 当前状态：{order_status_label(order.status)}，"
            f"订单金额 {order.total_amount} 元。{logistics_note}"
        )
        return {
            "answer": answer,
            "answer_type": "template",
            "sources": [_order_source(order)],
            "confidence": "high",
        }

    _, orders = await list_orders_for_user(session, user.id, page=1, page_size=3)
    if not orders:
        return {
            "answer": "您名下暂时没有订单记录。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
        }
    summary = "；".join(
        f"{o.order_no}（{order_status_label(o.status)}）" for o in orders
    )
    return {
        "answer": f"您最近的订单如下：{summary}。请提供订单号查询详情。",
        "answer_type": "template",
        "sources": [_order_source(o) for o in orders],
        "confidence": "high",
    }


async def answer_logistics(session: AsyncSession, user: User) -> dict:
    """物流问题（无单号）：给出最近一单的物流状态作为参考。"""
    _, orders = await list_orders_for_user(session, user.id, page=1, page_size=1)
    if not orders or orders[0].logistics is None:
        return {
            "answer": "暂未查询到您的物流记录，请提供物流单号或订单号后重试。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
        }
    order = orders[0]
    lg = order.logistics
    timeline = "；".join(
        f"{e['time'][:10]} {e['description']}" for e in lg.timeline[-3:]
    )
    return {
        "answer": (
            f"您订单 {order.order_no} 的物流单号为 {lg.tracking_no}，"
            f"当前状态：{lg.status}。最近轨迹：{timeline}。"
        ),
        "answer_type": "template",
        "sources": [_order_source(order)],
        "confidence": "high",
    }


async def answer_product(session: AsyncSession, message: str) -> dict:
    """商品问题：按名称关键词检索，返回 Top 商品摘要。"""
    keyword = message.replace("商品", "").replace("价格", "").strip() or None
    if keyword:
        _, products = await search_products(
            session, keyword=keyword, category=None, page=1, page_size=3
        )
    else:
        products = []
    if not products:
        return {
            "answer": "未找到相关商品，请提供商品名称、型号或关键词。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
        }
    summary = "；".join(f"{p.name}（{p.sku}）售价 {p.price} 元" for p in products)
    return {
        "answer": f"为您找到以下商品：{summary}。",
        "answer_type": "template",
        "sources": [
            {
                "type": "product",
                "doc_title": p.name,
                "chunk_id": None,
                "section": None,
                "score": None,
                "order_no": None,
            }
            for p in products
        ],
        "confidence": "high",
    }
