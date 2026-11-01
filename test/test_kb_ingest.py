"""知识库入库集成测试：文档↔分块关联、元数据落库、幂等重导。"""
import pytest
from sqlalchemy import delete, func, select

from app.db.session import SessionFactory
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.kb_service import ingest_markdown

SOURCE = "test/fixture_kb.md"
TEXT = """# 测试退货政策

> 模拟规则声明

## 申请条件

签收后 7 天内可申请。

## 申请流程

通过售后入口提交申请。
"""


async def test_ingest_roundtrip_and_idempotency(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async with SessionFactory() as session:
        try:
            async with session.begin():
                doc_id, n = await ingest_markdown(session, SOURCE, TEXT)
            async with session.begin():  # 重导：幂等，不产生重复文档
                doc_id2, n2 = await ingest_markdown(session, SOURCE, TEXT)

            # 同一 source 只有一份文档，且两次导入返回同一 id
            assert doc_id == doc_id2
            assert n == n2
            count = (
                await session.execute(
                    select(func.count()).select_from(KnowledgeDocument).where(
                        KnowledgeDocument.source == SOURCE
                    )
                )
            ).scalar_one()
            assert count == 1

            # 文档元数据与关联关系
            doc = await session.get(KnowledgeDocument, doc_id)
            assert doc.title == "测试退货政策"
            assert doc.category == "other"  # 文件名不在映射表 → other

            chunks = (
                await session.execute(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == doc_id)
                    .order_by(KnowledgeChunk.chunk_index)
                )
            ).scalars().all()
            assert len(chunks) == n
            assert [c.chunk_index for c in chunks] == list(range(n))  # 从 0 连续
            # 块引用声明行不进入知识内容 → 前言为空被跳过，第一个分块是"申请条件"
            assert chunks[0].chunk_meta["doc_title"] == "测试退货政策"
            assert chunks[0].chunk_meta["section"] == "申请条件"
            assert all("模拟规则声明" not in c.content for c in chunks)
        finally:
            # 清理
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
            )
            doc = await session.get(KnowledgeDocument, doc_id)
            if doc is not None:
                await session.delete(doc)
            await session.commit()
