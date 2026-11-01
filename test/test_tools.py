"""受控业务工具测试：Pydantic 参数校验 + 权限边界（阶段八 8.2）。"""
import pytest
from pydantic import ValidationError

from app.services.tools import (
    OrderLookupInput,
    ProductSearchInput,
    TOOLS,
)


def test_tool_registry_covers_three_tools():
    assert set(TOOLS) == {"order_lookup", "logistics_lookup", "product_search"}


def test_order_lookup_input_validation():
    OrderLookupInput(order_no="SYN202610200001")  # 合法
    with pytest.raises(ValidationError):
        OrderLookupInput(order_no="短")  # 过短
    with pytest.raises(ValidationError):
        OrderLookupInput(order_no="含-连字符-2026-01")  # 不符合字母数字模式
    with pytest.raises(ValidationError):
        OrderLookupInput(order_no="'; DROP TABLE orders;--")  # 非法字符被拒绝


def test_product_search_input_validation():
    ProductSearchInput(keyword="保温杯")
    with pytest.raises(ValidationError):
        ProductSearchInput(keyword="")  # 空关键词


def test_order_tool_requires_user_param():
    """权限边界：订单工具的函数签名强制要求 user 参数（身份来自 JWT）。

    用户消息中的"忽略权限检查"等内容只是文本，无法改变函数签名——
    权限不可能被消息内容绕过（8.2 要求）。
    """
    import inspect

    from app.services.tools import order_lookup

    sig = inspect.signature(order_lookup)
    params = list(sig.parameters)
    assert params == ["session", "user", "params"], "订单工具必须显式接收 user 参数"
