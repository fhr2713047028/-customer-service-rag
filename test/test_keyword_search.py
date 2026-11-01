"""关键词检索与混合检索集成测试（真实数据库）。"""
import pytest
from sqlalchemy import delete, select

from app.db.session import SessionFactory
from app.embeddings.client import get_embedding_client
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.retrieval.hybrid import hybrid_search
from app.retrieval.keyword import search_chunks_keyword
from app.services.kb_service import ingest_markdown

SOURCE = "test/fixture_keyword.md"
TEXT = """# 测试关键词文档

## 型号规格小节

商品型号 KW-9999 是测试型号，规格为 100W 快充。

## 退货小节

签收后七天之内可以申请退货。
"""


async def _setup(session):
    async with session.begin():
        return await ingest_markdown(session, SOURCE, TEXT)


async def _cleanup(session, doc_id):
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id))
    doc = await session.get(KnowledgeDocument, doc_id)
    if doc is not None:
        await session.delete(doc)
    await session.commit()


async def test_keyword_search_hits_exact_model_code(db_available: bool):
    """关键词型问题：型号代码 KW-9999 精确命中（向量检索未必能做到的点）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with SessionFactory() as session:
        doc_id, _ = await _setup(session)
        try:
            results = await search_chunks_keyword(session, "KW-9999 的规格是什么", top_k=5)
            assert results, "关键词检索应命中型号代码"
            assert any(c.chunk_meta["section"] == "型号规格小节" for c, _ in results)
        finally:
            await _cleanup(session, doc_id)


async def test_hybrid_dedup_and_source_info(db_available: bool):
    """混合检索：同源分块不重复返回；保留双路排名与来源信息。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with SessionFactory() as session:
        doc_id, _ = await _setup(session)
        try:
            client = get_embedding_client()
            query_vec = (await client.embed_texts(["KW-9999 型号规格"]))[0]
            hits = await hybrid_search(session, "KW-9999 型号规格", query_vec, top_k=5)
            assert hits, "混合检索应有结果"

            # 去重：chunk id 不重复
            ids = [h.chunk.id for h in hits]
            assert len(ids) == len(set(ids))

            # 来源与排序信息保留
            for h in hits:
                assert h.chunk.document is not None  # 来源文档
                assert h.fused_score > 0
                # 至少来自一路
                assert h.keyword_rank is not None or h.vector_rank is not None

            # 型号代码分块应被融合到前排（关键词路可精确命中）
            top_hit = hits[0]
            assert top_hit.chunk.chunk_meta["section"] == "型号规格小节"
        finally:
            await _cleanup(session, doc_id)
