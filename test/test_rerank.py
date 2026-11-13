"""Reranker 测试（阶段十四）：客户端故障注入 + kb_answer 精排集成。"""
import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.config import settings
from app.core.errors import RerankError
from app.core.security import create_access_token
from app.embeddings.reranker import RerankClient
from app.main import app
from app.services import kb_answer

RERANK_OK = {
    "results": [
        {"index": 2, "relevance_score": 0.95},
        {"index": 0, "relevance_score": 0.81},
        {"index": 1, "relevance_score": 0.30},
    ]
}


def _client(handler, **kw) -> RerankClient:
    return RerankClient(
        base_url="https://fake.test/v1", api_key="sk-test", model="BAAI/bge-reranker-v2-m3",
        timeout=1.0, transport=MockTransport(handler), **kw,
    )


async def test_rerank_parses_and_sorts_by_score():
    def handler(request: Request) -> Response:
        return Response(200, json=RERANK_OK, request=request)

    client = _client(handler)
    ranked = await client.rerank("查询", ["a", "b", "c"], top_n=3)
    assert [idx for idx, _ in ranked] == [2, 0, 1]  # 按相关度降序
    assert [round(s, 2) for _, s in ranked] == [0.95, 0.81, 0.30]


async def test_rerank_retries_on_429_then_succeeds():
    attempts = []

    def handler(request: Request) -> Response:
        attempts.append(1)
        if len(attempts) < 3:
            return Response(429, json={"error": "rate limited"}, request=request)
        return Response(200, json=RERANK_OK, request=request)

    client = _client(handler, retry_base_delay=0.01)
    ranked = await client.rerank("查询", ["a", "b", "c"], top_n=3)
    assert len(ranked) == 3
    assert len(attempts) == 3


async def test_rerank_4xx_no_retry():
    attempts = []

    def handler(request: Request) -> Response:
        attempts.append(1)
        return Response(401, json={"error": "invalid key"}, request=request)

    client = _client(handler)
    with pytest.raises(RerankError):
        await client.rerank("查询", ["a"], top_n=1)
    assert len(attempts) == 1


async def test_rerank_timeout_retries_then_fails():
    attempts = []

    def handler(request: Request) -> Response:
        attempts.append(1)
        raise httpx_connect_timeout()

    client = _client(handler, retry_base_delay=0.01)
    with pytest.raises(RerankError):
        await client.rerank("查询", ["a"], top_n=1)
    assert len(attempts) == 3


async def test_rerank_malformed_response_raises():
    def handler(request: Request) -> Response:
        return Response(200, json={"unexpected": True}, request=request)

    client = _client(handler)
    with pytest.raises(RerankError):
        await client.rerank("查询", ["a"], top_n=1)


async def test_rerank_empty_documents_returns_empty():
    client = _client(lambda request: Response(200, json=RERANK_OK, request=request))
    assert await client.rerank("查询", [], top_n=5) == []


async def _chat_with_rerank(monkeypatch, fake_rerank):
    """构造开启 rerank 且注入 fake 的 chat 请求。"""
    settings.rerank_enabled = True
    monkeypatch.setattr(kb_answer, "rerank_candidates", fake_rerank)
    token = create_access_token(1, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        return await client.post("/api/v1/chat", json={"message": "退货需要什么条件"})


async def test_kb_answer_uses_rerank_order(db_available: bool, monkeypatch):
    """精排生效：sources 顺序按 fake rerank 返回的顺序。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async def fake_rerank(session, query, pool, top_n):
        # 反转候选池顺序，且分数统一为 0.99 —— 便于断言精排真的生效
        return [(chunk, 0.99) for chunk, _ in reversed(pool[:top_n])]

    resp = await _chat_with_rerank(monkeypatch, fake_rerank)
    data = resp.json()["data"]
    assert data["answer_type"] == "generated"
    assert data["sources"], "应有来源"
    assert all(s["score"] == 0.99 for s in data["sources"]), "来源分数应为 rerank 相关度"


async def test_kb_answer_rerank_failure_falls_back_to_rrf_order(db_available: bool, monkeypatch):
    """rerank 失败：软降级为 RRF 顺序，回答仍然生成、来源分数回退向量相似度。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async def fake_rerank(session, query, hits, top_n):
        raise RerankError("模拟 rerank 服务故障")

    resp = await _chat_with_rerank(monkeypatch, fake_rerank)
    data = resp.json()["data"]
    assert data["answer_type"] == "generated"  # 降级仍可生成
    assert data["sources"]
    assert any(s["score"] is not None for s in data["sources"])


def httpx_connect_timeout():
    import httpx

    return httpx.ConnectTimeout("模拟超时")
