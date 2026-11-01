"""用户模型：对应 database_design.md 3.1。"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order import Order


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    # v1 不使用（测试身份由脚本签发 JWT，无密码）；正式认证阶段启用 + bcrypt
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")  # 1 正常 / 0 禁用
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # 关系：一个用户多笔订单。lazy="raise" 是防懒加载护栏：
    # 异步下访问未预加载的关系会直接报错，强制使用 selectinload（架构文档 7.1）
    orders: Mapped[list["Order"]] = relationship(back_populates="user", lazy="raise")
