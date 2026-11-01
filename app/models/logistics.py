"""物流模型：对应 database_design.md 3.5。"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order import Order

LOGISTICS_STATUSES = (
    "created",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "exception",
)


class Logistics(Base):
    __tablename__ = "logistics"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in LOGISTICS_STATUSES)})",
            name="ck_logistics_status",
        ),
        Index("ix_logistics_tracking_no", "tracking_no"),  # 物流单号查询
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # UNIQUE：v1 一单一物流（多包裹后期扩展）
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.id"), unique=True, nullable=False
    )
    tracking_no: Mapped[str] = mapped_column(String(64), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 轨迹数组：[{"time": "...", "location": "...", "description": "..."}]
    timeline: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # 每次同步物流时由代码显式更新（无 onupdate，避免无意覆盖）
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="logistics", lazy="raise")
