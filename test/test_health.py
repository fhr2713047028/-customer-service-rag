"""系统端点冒烟测试：/healthz 与 /readyz。

- /healthz 不依赖数据库，恒 200
- /readyz：数据库可达 → 200；不可达 → 503（两种状态都有测试覆盖）
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.main import app


async def test_healthz_returns_200():
    """存活探针不依赖任何外部服务，永远 200。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readyz_returns_503_when_db_unreachable():
    """用指向不存在端口的引擎覆盖 get_db 依赖，模拟"数据库宕机"。"""
    bad_engine = create_async_engine(
        "postgresql+asyncpg://rag:rag_password@127.0.0.1:59999/rag_db",
        connect_args={"timeout": 2},
    )
    bad_factory = async_sessionmaker(bad_engine, expire_on_commit=False)

    async def override_get_db():
        async with bad_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")
    finally:
        app.dependency_overrides.clear()
        await bad_engine.dispose()

    assert resp.status_code == 503


async def test_readyz_returns_200_when_db_up(db_available: bool):
    """需要真实数据库：先运行 docker compose up -d postgres，否则自动跳过。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL：先运行 docker compose up -d postgres")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
