"""LLM 路由集成测试（阶段十五）：启用后 LLM 决策优先、失败回退规则。"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app
from app.services import chat_service


async def _chat(message: str, token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        return await client.post("/api/v1/chat", json={"message": message})


async def test_llm_router_kb_decision_takes_effect(db_available: bool, monkeypatch):
    """LLM 判定 kb 时：即使规则路由会判 structured（含"我的订单"），也走知识库。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async def fake_detect(message):
        return {"route": "kb", "intents": [], "combined": False, "order_no": None}

    monkeypatch.setattr(chat_service, "detect_route_llm", fake_detect)
    monkeypatch.setattr(chat_service.settings, "router_llm_enabled", True)

    token = create_access_token(1, is_admin=False)
    resp = await _chat("我的订单符合退货条件吗", token)
    data = resp.json()["data"]
    assert data["route"] == "kb_retrieval"  # LLM 决策生效，而非规则的 combined
    assert data["route_source"] == "llm"


async def test_llm_router_failure_falls_back_to_rule(db_available: bool, monkeypatch):
    """LLM 路由失败 → 回退规则路由（我的订单 → order_query）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async def fake_detect(message):
        return None  # 模拟 LLM 路由失败

    monkeypatch.setattr(chat_service, "detect_route_llm", fake_detect)
    monkeypatch.setattr(chat_service.settings, "router_llm_enabled", True)

    token = create_access_token(1, is_admin=False)
    resp = await _chat("我的订单发货了吗", token)
    data = resp.json()["data"]
    assert data["route"] == "order_query"
    assert data["route_source"] == "rule"
