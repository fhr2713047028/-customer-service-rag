"""物流查询 API 集成测试：按物流单号查询（需认证 + 归属校验）。

覆盖安全项：他人物流单号 → 404/20001 且无信息泄露；无令牌 → 401。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app


def _client(headers=None):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test", headers=headers or {})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_logistics_requires_token(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        resp = await client.get("/api/v1/logistics/SYNTESTTRK01")
    assert resp.status_code == 401
    assert resp.json()["code"] == 10001


async def test_own_tracking_returns_detail_with_order_context(
    db_available: bool, users_and_orders
):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(users_and_orders["user_a"], is_admin=False)
    async with _client(headers=_auth(token)) as client:
        resp = await client.get("/api/v1/logistics/SYNTESTTRK01")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tracking_no"] == "SYNTESTTRK01"
    assert data["order_no"] == "SYNTESTORDA01"  # 订单上下文
    assert data["order_status"] == "shipped"


async def test_other_users_tracking_returns_404_no_leak(
    db_available: bool, users_and_orders
):
    """强制安全项：用户 B 用有效令牌查用户 A 的物流单号 → 404/20001，无信息泄露。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token_b = create_access_token(users_and_orders["user_b"], is_admin=False)
    async with _client(headers=_auth(token_b)) as client:
        resp = await client.get("/api/v1/logistics/SYNTESTTRK01")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 20001
    assert body["data"] is None
    assert "SYNTESTTRK01" not in body["message"]


async def test_nonexistent_tracking_returns_404(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(users_and_orders["user_a"], is_admin=False)
    async with _client(headers=_auth(token)) as client:
        resp = await client.get("/api/v1/logistics/SYNNOTRACK99")
    assert resp.status_code == 404
    assert resp.json()["code"] == 20001
