"""商品模型：对应 database_design.md 3.4。

name 上的 pg_trgm GIN 索引（商品关键词搜索）以 postgresql_using/ops
精确声明在模型里 —— 否则 alembic autogenerate 会把数据库里的该索引
误判成"待删除"（假 diff）。依赖 pg_trgm 扩展（迁移 #1 已建）。
"""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order_item import OrderItem

PRODUCT_STATUSES = ("on_sale", "off_sale")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in PRODUCT_STATUSES)})",
            name="ck_products_status",
        ),
        # 商品名关键词搜索：pg_trgm GIN（操作符类用 postgresql_ops 精确声明）
        Index(
            "idx_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="on_sale")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product", lazy="raise")
