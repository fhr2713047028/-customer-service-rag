"""商品相关的 Pydantic 模型（出参序列化）。"""
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # 允许直接从 ORM 对象构造

    id: int
    sku: str
    name: str
    category: str | None
    description: str | None
    price: Decimal  # JSON 序列化为字符串（与 api_design.md 示例一致）
    stock: int
    status: str
