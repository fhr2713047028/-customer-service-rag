"""对话编排（服务编排层，阶段八：业务工具调用与智能路由）。

处理路径（8.1 的流程图落地，第一版规则路由 + 受控工具，无 Agent 框架）：
    用户问题 → 意图识别/规则判断 → 业务查询 / 知识检索 / 组合查询
    → 结果校验与组织 → 返回回答

route 字段取值：order_query | logistics_query | product_query |
                 kb_retrieval | combined | clarify
每条路径的输入、输出与权限边界见 services/tools.py。
"""
import logging

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.intent import detect_intents, extract_order_no, is_combined_query
from app.services.kb_answer import generate_kb_answer
from app.services.structured_answer import (
    answer_logistics,
    answer_order_status,
    answer_product,
)
from app.services.tools import (
    OrderLookupInput,
    ProductSearchInput,
    order_lookup,
    product_search,
)

logger = logging.getLogger(__name__)

CLARIFY_TEXT = (
    "请问您想咨询订单状态、物流信息、商品价格，还是退货/退款政策？"
    "请提供订单号或具体问题，我会为您查询。"
)
# 模糊问题澄清（8.2 场景"用户提出一个模糊问题"）：
# 极短消息（≤4 字）或明确的口语化短语才算模糊——
# 注意"退货要什么条件"（7 字）是正常短问题，必须走知识库，不能误判
CLARIFY_MAX_LEN = 4
VAGUE_PHRASES = ("在吗", "帮我看一下", "帮我查", "查一下", "有人吗", "你好")


def _clean_product_keyword(message: str) -> str:
    """从商品问题中提取关键词（去掉常见问法词）。"""
    for word in ("商品", "价格", "多少钱", "是多少", "的", "吗", "？", "?"):
        message = message.replace(word, " ")
    return " ".join(message.split())


async def handle_chat(session: AsyncSession, user: User, message: str) -> dict:
    """一次问答的完整编排。返回 {answer, answer_type, route, intents, sources, confidence}。"""
    intents = detect_intents(message)

    if intents:
        result = await _structured_route(session, user, message, intents)
    elif len(message.strip()) <= CLARIFY_MAX_LEN or any(
        p in message for p in VAGUE_PHRASES
    ):
        # 模糊问题：适当追问，不乱答
        result = {
            "answer": CLARIFY_TEXT,
            "answer_type": "clarify",
            "sources": [],
            "confidence": "low",
            "route": "clarify",
        }
    else:
        result = await generate_kb_answer(session, message)
        result["route"] = "kb_retrieval"

    result["intents"] = intents
    return result


async def _structured_route(
    session: AsyncSession, user: User, message: str, intents: list[str]
) -> dict:
    if is_combined_query(message, intents):
        return await _combined_route(session, user, message)
    if "order_status" in intents:
        return await _order_route(session, user, message)
    if "logistics" in intents:
        result = await answer_logistics(session, user)
        result["route"] = "logistics_query"
        return result
    return await _product_route(session, message)


async def _order_route(session: AsyncSession, user: User, message: str) -> dict:
    """订单查询：经受控工具（Pydantic 校验 + 身份来自 JWT）。"""
    order_no = extract_order_no(message)
    if order_no is None:
        # 无有效订单号 → 最近订单摘要（不构造占位参数访问数据库）
        return await _recent_orders_route(session, user)
    try:
        params = OrderLookupInput(order_no=order_no)
    except ValidationError:
        # 入参非法（如含连字符）→ 不访问数据库，走最近订单摘要
        return await _recent_orders_route(session, user)

    result = await order_lookup(session, user, params)
    result["route"] = "order_query"
    return result


async def _recent_orders_route(session: AsyncSession, user: User) -> dict:
    from app.retrieval.structured import list_orders_for_user

    _, orders = await list_orders_for_user(session, user.id, page=1, page_size=3)
    if not orders:
        return {
            "answer": "您名下暂时没有订单记录。",
            "answer_type": "template",
            "sources": [],
            "confidence": "low",
            "route": "order_query",
        }
    from app.services.business import order_status_label

    parts = []
    for o in orders:
        part = f"{o.order_no}（{order_status_label(o.status)}）"
        if o.logistics is not None:
            part += f"，物流单号 {o.logistics.tracking_no}，物流状态 {o.logistics.status}"
        parts.append(part)
    summary = "；".join(parts)
    return {
        "answer": f"您最近的订单如下：{summary}。请提供订单号查询详情。",
        "answer_type": "template",
        "sources": [
            {
                "type": "order",
                "doc_title": None,
                "chunk_id": None,
                "section": None,
                "score": None,
                "order_no": o.order_no,
            }
            for o in orders
        ],
        "confidence": "high",
        "route": "order_query",
    }


async def _product_route(session: AsyncSession, message: str) -> dict:
    """商品查询：经受控工具（Pydantic 校验参数）。"""
    keyword = _clean_product_keyword(message)
    try:
        params = ProductSearchInput(keyword=keyword)
    except ValidationError:
        return {
            "answer": "请提供具体的商品名称或关键词。",
            "answer_type": "clarify",
            "sources": [],
            "confidence": "low",
            "route": "clarify",
        }
    result = await product_search(session, None, params)
    result["route"] = "product_query"
    return result


async def _combined_route(session: AsyncSession, user: User, message: str) -> dict:
    """组合查询：数据库（订单信息）+ RAG（政策检索）双源（8.2 场景 4）。

    订单信息作为【订单信息】分区注入提示词；政策部分照常走混合检索与拒答。
    """
    # 1) 业务数据：订单详情或最近订单摘要（归属校验同订单路径）
    order_no = extract_order_no(message)
    if order_no:
        from app.retrieval.structured import get_order_by_no_for_user

        order = await get_order_by_no_for_user(session, order_no, user.id)
        if order is None:
            result = await generate_kb_answer(session, message)
            result["route"] = "combined"
            return result
        order_context = (
            f"订单号 {order.order_no}，状态 {order.status}，金额 {order.total_amount} 元，"
            f"下单时间 {order.created_at:%Y-%m-%d}。"
        )
        order_source = {
            "type": "order",
            "doc_title": None,
            "chunk_id": None,
            "section": None,
            "score": None,
            "order_no": order.order_no,
        }
    else:
        from app.retrieval.structured import list_orders_for_user
        from app.services.business import order_status_label

        _, orders = await list_orders_for_user(session, user.id, page=1, page_size=3)
        if not orders:
            result = await generate_kb_answer(session, message)
            result["route"] = "combined"
            return result
        order_context = "；".join(
            f"{o.order_no}（{order_status_label(o.status)}，{o.total_amount} 元）" for o in orders
        )
        order_source = {
            "type": "order",
            "doc_title": None,
            "chunk_id": None,
            "section": None,
            "score": None,
            "order_no": orders[0].order_no,
        }

    # 2) 知识检索 + 生成（订单信息注入）
    result = await generate_kb_answer(session, message, extra_context=order_context)
    result["sources"] = [order_source] + result["sources"]
    result["route"] = "combined"
    return result
