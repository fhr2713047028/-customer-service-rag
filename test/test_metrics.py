"""指标端点与低基数标签测试（阶段十 10.2 第 1/6 条）。"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app


async def _get(path: str, headers=None):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers or {}
    ) as client:
        return await client.get(path)


async def test_metrics_endpoint_exposed(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    resp = await _get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text
    assert "rag_request_duration_seconds" in resp.text
    assert "rag_llm_duration_seconds" in resp.text
    assert "db_query_duration_seconds" in resp.text


async def test_path_label_uses_route_template_not_actual_value(db_available: bool):
    """低基数：路径标签是路由模板（含 {order_no}），不出现具体订单号。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(1, is_admin=False)
    await _get("/api/v1/orders/SYNNOTEXIST99", headers={"Authorization": f"Bearer {token}"})
    resp = await _get("/metrics")
    text = resp.text
    assert 'path="/api/v1/orders/{order_no}"' in text  # 路由模板
    assert 'path="/api/v1/orders/SYNNOTEXIST99"' not in text  # 绝不出现实际值


async def test_no_request_id_label_in_metrics(db_available: bool):
    """高基数红线：request_id 绝不作为指标标签。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    await _get("/api/v1/products/1")
    resp = await _get("/metrics")
    assert "request_id" not in resp.text


async def test_chat_request_produces_rag_metrics(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(1, is_admin=False)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        await client.post("/api/v1/chat", json={"message": "我的订单发货了吗"})
    resp = await _get("/metrics")
    assert 'route="order_query"' in resp.text
    assert 'answer_type="template"' in resp.text
