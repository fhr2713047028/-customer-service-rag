"""订单模型：对应 database_design.md 3.2。"""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.logistics import Logistics
    from app.models.order_item import OrderItem
    from app.models.user import User

ORDER_STATUSES = (
    "pending_payment",
    "paid",
    "shipped",
    "delivered",
    "completed",
    "cancelled",
    "refunding",
    "refunded",
)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # 状态取值约束。VARCHAR + CHECK 而非 PG enum：扩展新状态只需一次迁移
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ORDER_STATUSES)})",
            name="ck_orders_status",
        ),
        # "我的订单列表 / 最近 N 单"复合索引；
        # DESC 方向用 text() 精确声明 —— 否则 alembic autogenerate 会把
        # 数据库里的 DESC 索引误判成"需要改回 ASC"（假 diff）
        Index("ix_orders_user_id_created_at", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 归属校验的核心列：所有订单查询必须带 user_id = :current_user_id（api_design.md 第 5 节）
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    receiver_name: Mapped[str | None] = mapped_column(String(64))
    receiver_phone: Mapped[str | None] = mapped_column(String(20))
    receiver_address: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="orders", lazy="raise")
    # 明细随订单级联删除；order_by 保证"items"顺序稳定
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        lazy="raise",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
    )
    # 1:1 物流（v1 一单一物流）
    logistics: Mapped[Optional["Logistics"]] = relationship(
        back_populates="order", uselist=False, lazy="raise", cascade="all, delete-orphan"
    )
