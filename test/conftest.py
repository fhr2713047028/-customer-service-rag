"""pytest 共享夹具。"""
import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal

# 测试环境默认关闭 LangSmith 追踪：必须在任何 app 模块导入之前设置
# （追踪装饰器在模块导入时判断开关），避免把测试数据发送到外部追踪服务
os.environ["LANGSMITH_TRACING"] = "false"

import pytest
from sqlalchemy import delete

from app.db.session import SessionFactory
from app.models.logistics import Logistics
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.user import User


@pytest.fixture(autouse=True)
def _force_mock_llm_only(monkeypatch):
    """测试环境强制 mock LLM（确定性、零费用）。

    Embedding **不强制 mock**：数据库中的向量是真实 BGE-M3 生成的，
    查询向量必须来自同一模型同一空间，否则余弦相似度失去意义
    （mock 查询向量 vs 真实库向量会出现负相似度，误触发拒答）。
    每次测试的嵌入调用次数极少（约 1 次/知识库用例）。
    另外：拒答阈值与分数强耦合，测试默认 0.0（不按分数拒答）与校准值解耦；
    拒答测试自己调高阈值（test_chat_api.py 的 no_basis 用例）。
    """
    from app.config import settings
    from app.llm import client as llm_client

    monkeypatch.setattr(llm_client, "_client", None)  # 清缓存，按下方 provider 重建
    monkeypatch.setattr(llm_client.settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "kb_refusal_min_score", 0.0)
    # Rerank 默认关闭（测试确定性；rerank 专项测试自行开启并注入 mock 客户端）
    monkeypatch.setattr(settings, "rerank_enabled", False)
    # GraphRAG 默认关闭（测试不依赖 Neo4j；图专项测试注入 mock）
    monkeypatch.setattr(settings, "graph_enabled", False)


@pytest.fixture
async def db_available() -> bool:
    """探测本机 5432 是否有 PostgreSQL 在监听（决定是否跳过需要真库的测试）。"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 5432), timeout=2
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


@pytest.fixture
async def users_and_orders():
    """订单/物流 API 集成测试共享夹具：用户 A 两单（一单带物流）、用户 B 一单（带物流）。

    测试后清理。订单明细由 DB 级联删除，物流与订单需显式删除。
    """
    async with SessionFactory() as session:
        user_a = User(username="test_ord_user_a", phone="13800001111", email="orda@example.com")
        user_b = User(username="test_ord_user_b", phone="13800002222", email="ordb@example.com")
        session.add_all([user_a, user_b])
        await session.flush()

        def make_order(user, no, amount):
            order = Order(
                order_no=no, user_id=user.id, status="shipped",
                total_amount=Decimal(amount),
                receiver_name="测试收货人", receiver_phone="13912345678",
                receiver_address="上海市浦东新区测试路 100 号",
                created_at=datetime.now(timezone.utc),
            )
            OrderItem(
                order=order, product_id=None, product_name_snapshot="测试商品A",
                sku_snapshot="SKU-A", price_snapshot=Decimal(amount), quantity=1,
            )
            return order

        order_a1 = make_order(user_a, "SYNTESTORDA01", "99.90")
        order_a2 = make_order(user_a, "SYNTESTORDA02", "199.90")
        order_b1 = make_order(user_b, "SYNTESTORDB01", "299.90")
        session.add_all([order_a1, order_a2, order_b1])
        await session.flush()

        session.add_all([
            Logistics(
                order=order_a1, tracking_no="SYNTESTTRK01", carrier="测试快递",
                status="in_transit", timeline=[], updated_at=datetime.now(timezone.utc),
            ),
            Logistics(
                order=order_b1, tracking_no="SYNTESTTRK02", carrier="测试快递",
                status="created", timeline=[], updated_at=datetime.now(timezone.utc),
            ),
        ])
        await session.commit()

        ids = {
            "user_a": user_a.id, "user_b": user_b.id,
            "order_a1": order_a1.id, "order_a2": order_a2.id, "order_b1": order_b1.id,
        }
    yield ids

    # 清理
    async with SessionFactory() as session:
        await session.execute(
            delete(Logistics).where(
                Logistics.order_id.in_([ids["order_a1"], ids["order_a2"], ids["order_b1"]])
            )
        )
        await session.execute(
            delete(Order).where(
                Order.id.in_([ids["order_a1"], ids["order_a2"], ids["order_b1"]])
            )
        )
        await session.execute(delete(User).where(User.id.in_([ids["user_a"], ids["user_b"]])))
        await session.commit()
