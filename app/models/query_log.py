"""请求日志模型（必要的请求日志/查询记录）：2026-10-30 用户确认新增。

记录每次 API 请求的最小元数据：谁、问了什么、命中什么路径、耗时与结果。
message 可能包含用户敏感信息，脱敏在日志写入模块实现（表结构预留即可）；
数据保留/清理策略在可观测性阶段（实施阶段 8）定义。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QueryLog(Base):
    __tablename__ = "query_logs"
    __table_args__ = (
        Index("ix_query_logs_user_created", "user_id", "created_at"),
        Index("ix_query_logs_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 可空 + SET NULL：匿名请求可记录；用户删除后日志保留
    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)  # 用户输入（chat 接口），脱敏后写入
    intents: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(32)), server_default="{}"
    )
    answer_type: Mapped[str | None] = mapped_column(String(32))  # template/faq/generated/fallback
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    error_code: Mapped[str | None] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64))  # 与结构化日志关联
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
