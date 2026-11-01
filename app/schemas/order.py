"""订单/物流相关的 Pydantic 出参模型（api_design.md 4.3）。

出参字段已经过服务层脱敏（手机号打码、地址截断、姓名打码）。
"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OrderItemOut(BaseModel):
    product_name_snapshot: str
    sku_snapshot: str
    price_snapshot: Decimal  # JSON 序列化为字符串
    quantity: int


class OrderOut(BaseModel):
    order_no: str
    status: str
    total_amount: Decimal
    receiver_name: str | None
    receiver_phone: str | None
    receiver_address: str | None
    items: list[OrderItemOut]
    created_at: datetime


class LogisticsOut(BaseModel):
    tracking_no: str
    carrier: str | None
    status: str
    timeline: list[dict]
    updated_at: datetime


class LogisticsDetailOut(LogisticsOut):
    """按物流单号查询时的出参：在基础字段上附带订单上下文。"""

    order_no: str
    order_status: str
