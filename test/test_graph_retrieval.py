"""图检索集成测试（阶段十六）：图召回并入候选池，交给 rerank 决定去留。"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.security import create_access_token
from app.main import app
from app.services import kb_answer


async def test_graph_pool_merges_into_candidates(db_available: bool, monkeypatch):
    """fake 图检索返回新块 + fake rerank 原样保留 → 来源包含图块。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    # 取一个与"退货"无关的块（商品型号小节）——保证它不在混合检索 top-10 里，
    # 从而真正走"图召回新块并入候选池"的路径
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.session import SessionFactory
    from app.models.knowledge_chunk import KnowledgeChunk

    async with SessionFactory() as session:
        chunk = (
            await session.execute(
                select(KnowledgeChunk)
                .options(selectinload(KnowledgeChunk.document))
                .where(KnowledgeChunk.chunk_meta["section"].astext == "商品型号与规格")
                .limit(1)
            )
        ).scalar_one()

    async def fake_search_graph(session, question, top_k):
        return [(chunk, 0.88)]

    async def fake_rerank(session, query, pool, top_n):
        # 返回候选池末尾 top_n（图召回的新块追加在末尾）——证明图块能进入最终来源
        return pool[-top_n:]

    monkeypatch.setattr(kb_answer, "search_graph", fake_search_graph)
    monkeypatch.setattr(kb_answer, "rerank_candidates", fake_rerank)
    monkeypatch.setattr(settings, "graph_enabled", True)
    monkeypatch.setattr(settings, "rerank_enabled", True)

    token = create_access_token(1, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "退货需要什么条件"})
    data = resp.json()["data"]
    assert data["answer_type"] == "generated"
    assert any(s["chunk_id"] == chunk.id for s in data["sources"]), "图召回的新块应进入来源"


async def test_graph_down_degrades_to_empty(db_available: bool, monkeypatch):
    """图不可用：软降级为空，主检索链不受影响。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async def broken_search_graph(session, question, top_k):
        raise RuntimeError("neo4j 不可用")

    monkeypatch.setattr(kb_answer, "search_graph", broken_search_graph)
    monkeypatch.setattr(settings, "graph_enabled", True)

    token = create_access_token(1, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        resp = await client.post("/api/v1/chat", json={"message": "退货需要什么条件"})
    data = resp.json()["data"]
    assert data["answer_type"] == "generated"
    assert data["sources"]
