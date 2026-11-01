"""向量检索集成测试：向量入库 → 相似度检索 → Top-K（真实数据库）。"""
import pytest
from sqlalchemy import delete, select

from app.db.session import SessionFactory
from app.embeddings.client import get_embedding_client
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.retrieval.vector import search_chunks
from app.services.kb_service import ingest_markdown

SOURCE = "test/fixture_vector.md"
TEXT = """# 测试向量文档

## 退货相关小节

签收后七天之内可以申请退货，退货需要商品完好。

## 物流相关小节

快递长时间没有更新物流信息，可以联系客服催查。
"""


async def test_vector_ingest_and_search_roundtrip(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async with SessionFactory() as session:
        try:
            async with session.begin():
                doc_id, _ = await ingest_markdown(session, SOURCE, TEXT)

            # 分块都有向量
            chunks = (
                await session.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
                )
            ).scalars().all()
            assert all(c.embedding is not None for c in chunks)

            # 查询向量与入库向量同客户端同模型（同维度）
            client = get_embedding_client()
            query_vec = (await client.embed_texts(["买完不想要了能退吗"]))[0]
            results = await search_chunks(session, query_vec, top_k=5)
            assert 1 <= len(results) <= 5

            # 管线断言：分数都在余弦相似度范围内且降序排列
            scores = [score for _, score in results]
            assert all(-1.0 <= s <= 1.0 for s in scores)
            assert scores == sorted(scores, reverse=True)

            # 全局检索会包含真实语料库的分块（词汇重叠），不能断言 Top-1 一定是
            # 测试文档 —— 断言 Top-5 中至少出现测试文档的一个分块
            fixture_chunks = [(c, s) for c, s in results if c.document_id == doc_id]
            assert fixture_chunks, "Top-5 中应出现测试文档的分块"

            # 文档内相对排序：对"退货"类问句，退货小节应排在物流小节之前
            fixture_sections = [c.chunk_meta["section"] for c, _ in fixture_chunks]
            if "退货相关小节" in fixture_sections and "物流相关小节" in fixture_sections:
                assert fixture_sections.index("退货相关小节") < fixture_sections.index("物流相关小节")
        finally:
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
            )
            doc = await session.get(KnowledgeDocument, doc_id)
            if doc is not None:
                await session.delete(doc)
            await session.commit()
