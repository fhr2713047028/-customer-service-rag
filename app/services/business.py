"""业务状态判断（纯函数，无数据库依赖，重点单测）。

把散落的业务规则集中在这里，供服务层/种子脚本/后续 chat 模板回答复用：
- 状态话术（模板回答与日志展示）
- 订单状态 → 应有物流状态的推导（业务一致性规则）
- 可发货 / 可退款等状态判断

边界（架构 4.1）：后续大模型调用业务工具时，也必须经由服务层调用
这些规则；模型永远不直接操作数据库。
"""
from app.models.logistics import LOGISTICS_STATUSES
from app.models.order import ORDER_STATUSES

# 订单状态 → 中文话术（模板回答复用）
ORDER_STATUS_LABELS = {
    "pending_payment": "待支付",
    "paid": "已支付，待发货",
    "shipped": "已发货",
    "delivered": "已送达",
    "completed": "已完成",
    "cancelled": "已取消",
    "refunding": "退款中",
    "refunded": "已退款",
}

LOGISTICS_STATUS_LABELS = {
    "created": "已创建",
    "picked_up": "已揽收",
    "in_transit": "运输中",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "exception": "异常",
}

# 业务规则（合成简化版，正式接入真实业务时按实际规则调整）：
# 订单状态 → 该订单的物流应处于的状态
ORDER_TO_LOGISTICS_STATUS = {
    "pending_payment": "created",  # 未支付：不应有实际物流动作
    "paid": "created",
    "cancelled": "created",
    "shipped": "in_transit",
    "refunding": "in_transit",
    "delivered": "delivered",
    "completed": "delivered",
    "refunded": "delivered",
}


def order_status_label(status: str) -> str:
    """订单状态中文话术；未知状态原样返回（不抛错，便于日志兜底）。"""
    return ORDER_STATUS_LABELS.get(status, status)


def logistics_status_label(status: str) -> str:
    return LOGISTICS_STATUS_LABELS.get(status, status)


def derived_logistics_status(order_status: str) -> str:
    """业务推导：给定订单状态，其物流应处于的状态。

    非法订单状态抛 ValueError —— 这是业务规则入口的显式校验，
    防止拼写错误静默进入系统。
    """
    if order_status not in ORDER_STATUSES:
        raise ValueError(f"未知订单状态: {order_status}")
    if order_status not in ORDER_TO_LOGISTICS_STATUS:
        raise ValueError(f"订单状态缺少物流状态映射: {order_status}")
    return ORDER_TO_LOGISTICS_STATUS[order_status]


def validate_order_logistics_consistency(order_status: str, logistics_status: str) -> bool:
    """业务一致性校验：物流状态是否符合该订单状态应有的状态。

    例如"待支付"订单不应出现"运输中"的物流 —— 数据修复/验收时使用。
    """
    return derived_logistics_status(order_status) == logistics_status


def is_order_shippable(order_status: str) -> bool:
    """只有"已支付待发货"的订单可以发货。"""
    return order_status == "paid"


def is_order_refundable(order_status: str) -> bool:
    """可申请退款的状态（合成简化规则）：未支付/已取消/已退款不可再退款。"""
    return order_status not in ("pending_payment", "cancelled", "refunded")
