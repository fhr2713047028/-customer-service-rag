"""订单明细模型：对应 database_design.md 3.3。

product_name/sku/price 都是下单时快照，不随商品表变更
（订单是历史事实，不能被商品改价/改名影响）。
"""
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.product import Product


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),  # 订单详情查询
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    # 可空：商品下架后仍能回答历史订单
    product_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("products.id"))
    product_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")
    product: Mapped[Optional["Product"]] = relationship(back_populates="order_items", lazy="raise")
