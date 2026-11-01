"""知识库文档模型（知识文档元数据）：对应 database_design.md。

2026-10-30 按用户确认的表名清单，原 kb_documents 更名为 knowledge_documents。
"""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_chunk import KnowledgeChunk

DOC_TYPES = ("md", "txt", "pdf")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            f"doc_type IN ({', '.join(repr(t) for t in DOC_TYPES)})",
            name="ck_knowledge_documents_doc_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(512))  # 来源文件名/URL
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", lazy="raise", cascade="all, delete-orphan"
    )
