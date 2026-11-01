"""商品查询 API 集成测试（走真实 HTTP 语义的 ASGITransport + 真实数据库）。

测试数据自建自清（唯一的 SKU/名称标记），不依赖种子数据是否已生成。
数据库不可达时自动跳过（与 test_health.py 相同的约定）。
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import SessionFactory
from app.main import app
from app.models.product import Product

TEST_SKU = "SKU-API-TEST-001"
TEST_NAME = "API测试商品蓝牙耳机限定款"
TEST_CATEGORY = "数码"


@pytest.fixture
async def test_product():
    """插入一个专用测试商品，测试结束后删除（try/finally 保证清理）。"""
    async with SessionFactory() as session:
        product = Product(
            sku=TEST_SKU,
            name=TEST_NAME,
            category=TEST_CATEGORY,
            description="[synthetic] API 集成测试商品",
            price="99.90",
            stock=10,
            status="on_sale",
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        product_id = product.id
    yield product_id
    async with SessionFactory() as session:
        await session.execute(delete(Product).where(Product.id == product_id))
        await session.commit()


def _client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_get_product_by_id(db_available: bool, test_product):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        resp = await client.get(f"/api/v1/products/{test_product}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["request_id"]  # 中间件生成的 request_id 非空
    assert body["data"]["sku"] == TEST_SKU
    assert body["data"]["name"] == TEST_NAME
    assert body["data"]["price"] == "99.90"  # Decimal 序列化为字符串（api_design 约定）


async def test_get_product_not_found_returns_20002(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        resp = await client.get("/api/v1/products/999999999")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 20002
    assert body["data"] is None


async def test_search_by_keyword_uses_trigram(db_available: bool, test_product):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        resp = await client.get("/api/v1/products", params={"keyword": "蓝牙耳机"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 1
    # 关键词命中自建测试商品（pg_trgm 模糊匹配，无需全名）
    assert any(item["sku"] == TEST_SKU for item in data["items"])


async def test_pagination_and_validation(db_available: bool):
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    async with _client() as client:
        # 正常分页
        resp = await client.get("/api/v1/products", params={"page": 1, "page_size": 2})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["page"] == 1 and data["page_size"] == 2
        assert len(data["items"]) <= 2
        assert data["total"] >= 1
        # page_size 超上限 → FastAPI 校验 422
        resp = await client.get("/api/v1/products", params={"page_size": 101})
        assert resp.status_code == 422
        # page 从 1 开始
        resp = await client.get("/api/v1/products", params={"page": 0})
        assert resp.status_code == 422
