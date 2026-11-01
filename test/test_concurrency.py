"""并发请求测试（阶段九 9.1.11）：高并发下延迟与错误率记录。"""
import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.db.session import SessionFactory
from app.main import app
from app.models.user import User
from sqlalchemy import select


async def test_concurrent_chat_requests_all_succeed(db_available: bool):
    """15 个并发请求（订单×10 + 知识库×5）：全部成功、错误率 0。

    数据库连接池（10 常驻 + 10 溢出）足以支撑该并发（架构 7.1 起点值）。
    """
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.id == 1))).scalar_one_or_none()
    if user is None:
        pytest.skip("需要先运行种子数据")
    token = create_access_token(user.id, user.is_admin)

    messages = ["我的订单发货了吗"] * 10 + ["退货需要什么条件"] * 5

    async def one_request(message: str):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            start = time.perf_counter()
            resp = await client.post("/api/v1/chat", json={"message": message})
            return resp.status_code, (time.perf_counter() - start) * 1000

    results = await asyncio.gather(*[one_request(m) for m in messages])

    statuses = [s for s, _ in results]
    latencies = [lat for _, lat in results]
    assert all(s == 200 for s in statuses), f"存在失败请求: {statuses}"
    print(
        f"并发 15 请求：全部 200；延迟 min={min(latencies):.0f}ms "
        f"max={max(latencies):.0f}ms avg={sum(latencies) / len(latencies):.0f}ms"
    )
