"""知识库分块模型（文档分块）：对应 database_design.md。

2026-10-30 按用户确认的表名清单，原 kb_chunks 更名为 knowledge_chunks。

注意：向量列 `embedding`（VECTOR(1024)）暂未加入 —— 原生 PostgreSQL 尚未安装
pgvector 扩展（用户待选安装方案 A/B/C）。扩展装好后通过一次 alembic 迁移追加该列，
并同步补上 HNSW 索引。
"""
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_document import KnowledgeDocument


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_chunk"),
        # HNSW 余弦索引：精确声明（postgresql_using/ops），autogenerate 才能识别
        Index(
            "idx_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # 中文全文检索表达式索引：text() 表达式精确声明，否则 autogenerate
        # 会把数据库里的该索引误判成"待删除"（假 diff）
        Index(
            "idx_knowledge_chunks_search_text",
            text("to_tsvector('simple', search_text)"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 分块元数据（阶段四）：{doc_title, section, source_line, char_count}
    # Python 属性名用 chunk_meta：'metadata' 是 SQLAlchemy 声明类的保留属性
    # （指向表的 MetaData），直接占用会冲突；数据库列名仍是 metadata
    chunk_meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # 中文全文检索字段（阶段六）：jieba 预分词结果（空格连接词元）。
    # 表达式 GIN 索引在迁移 #4 / init_db.py 以原始 SQL 创建（模型无法声明表达式索引）
    search_text: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # 向量（阶段五）：BGE-M3 维度 1024（以实际 API 返回为准，运行时校验）。
    # 可空：早期导入的分块尚未向量化时可先入库，重新导入后补齐
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024), nullable=True)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks", lazy="raise")
