"""业务状态判断纯函数单测（services/business.py）。"""
import pytest

from app.services.business import (
    derived_logistics_status,
    is_order_refundable,
    is_order_shippable,
    logistics_status_label,
    order_status_label,
    validate_order_logistics_consistency,
)


def test_order_status_labels():
    assert order_status_label("shipped") == "已发货"
    assert order_status_label("completed") == "已完成"
    assert order_status_label("unknown_status") == "unknown_status"  # 未知状态兜底原样返回


def test_logistics_status_labels():
    assert logistics_status_label("in_transit") == "运输中"
    assert logistics_status_label("delivered") == "已签收"


def test_derived_logistics_status_map():
    assert derived_logistics_status("pending_payment") == "created"
    assert derived_logistics_status("paid") == "created"
    assert derived_logistics_status("shipped") == "in_transit"
    assert derived_logistics_status("completed") == "delivered"


def test_derived_logistics_status_rejects_unknown():
    with pytest.raises(ValueError):
        derived_logistics_status("not_a_status")


def test_consistency_check():
    # 一致的组合
    assert validate_order_logistics_consistency("shipped", "in_transit") is True
    # 业务冲突：待支付订单不应有"运输中"的物流
    assert validate_order_logistics_consistency("pending_payment", "in_transit") is False


def test_shippable_rule():
    assert is_order_shippable("paid") is True  # 只有已支付待发货可发货
    assert is_order_shippable("pending_payment") is False
    assert is_order_shippable("shipped") is False


def test_refundable_rule():
    assert is_order_refundable("shipped") is True
    assert is_order_refundable("cancelled") is False
    assert is_order_refundable("refunded") is False
