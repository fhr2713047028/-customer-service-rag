"""订单查询 API 集成测试（真实数据库 + 真实 JWT 链路）。

覆盖 api_design.md 的强制安全项：
- 无 token / 坏签名 / 过期 → 401（10001/10002）
- 用户 B 查用户 A 的订单号 → 404/20001 且响应体不含任何订单信息（防枚举）
- 出参脱敏断言

测试数据来自 conftest.py 的 users_and_orders 共享夹具。
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


async def test_orders_require_token(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        resp = await client.get("/api/v1/orders")
    assert resp.status_code == 401
    assert resp.json()["code"] == 10001


async def test_orders_bad_signature_returns_10002(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client(headers=_auth("not.a.valid.jwt")) as client:
        resp = await client.get("/api/v1/orders")
    assert resp.status_code == 401
    assert resp.json()["code"] == 10002


async def test_orders_expired_token_returns_10001(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    expired = create_access_token(users_and_orders["user_a"], is_admin=False, expire_minutes=-1)
    async with _client(headers=_auth(expired)) as client:
        resp = await client.get("/api/v1/orders")
    assert resp.status_code == 401
    assert resp.json()["code"] == 10001


async def test_list_own_orders_only(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(users_and_orders["user_a"], is_admin=False)
    async with _client(headers=_auth(token)) as client:
        resp = await client.get("/api/v1/orders", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200
    data = resp.json()["data"]
    order_nos = {item["order_no"] for item in data["items"]}
    assert {"SYNTESTORDA01", "SYNTESTORDA02"} <= order_nos
    assert "SYNTESTORDB01" not in order_nos  # 绝不混入他人订单


async def test_own_order_detail_with_masking(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(users_and_orders["user_a"], is_admin=False)
    async with _client(headers=_auth(token)) as client:
        resp = await client.get("/api/v1/orders/SYNTESTORDA01")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["receiver_phone"] == "139****5678"  # 打码
    assert data["receiver_name"] == "测**"
    assert data["receiver_address"].endswith("***")
    assert data["total_amount"] == "99.90"
    assert len(data["items"]) == 1


async def test_other_users_order_returns_404_no_leak(db_available: bool, users_and_orders):
    """强制安全项：用户 B 用有效令牌查用户 A 的订单号 → 404/20001，无任何信息泄露。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token_b = create_access_token(users_and_orders["user_b"], is_admin=False)
    async with _client(headers=_auth(token_b)) as client:
        resp = await client.get("/api/v1/orders/SYNTESTORDA01")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 20001
    assert body["data"] is None
    assert "SYNTESTORDA01" not in body["message"]


async def test_order_not_exists_returns_20001(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token = create_access_token(users_and_orders["user_a"], is_admin=False)
    async with _client(headers=_auth(token)) as client:
        resp = await client.get("/api/v1/orders/SYNNOTEXIST1")
    assert resp.status_code == 404
    assert resp.json()["code"] == 20001


async def test_own_logistics_and_other_users_404(db_available: bool, users_and_orders):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    token_a = create_access_token(users_and_orders["user_a"], is_admin=False)
    token_b = create_access_token(users_and_orders["user_b"], is_admin=False)

    async with _client(headers=_auth(token_a)) as client:
        resp = await client.get("/api/v1/orders/SYNTESTORDA01/logistics")
    assert resp.status_code == 200
    assert resp.json()["data"]["tracking_no"] == "SYNTESTTRK01"

    async with _client(headers=_auth(token_b)) as client:
        resp = await client.get("/api/v1/orders/SYNTESTORDA01/logistics")
    assert resp.status_code == 404
    assert resp.json()["code"] == 20001
