"""数据模型测试：表结构、约束、外键、索引。

- 元数据类测试不依赖数据库，任何时候可跑；
- 关系往返测试需要真实数据库，不可达时自动跳过。
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import selectinload

from app.db.base import Base
import app.models  # noqa: F401  确保模型注册到 metadata

EXPECTED_TABLES = {
    "users",
    "orders",
    "order_items",
    "products",
    "logistics",
    "knowledge_documents",
    "knowledge_chunks",
    "query_logs",
}


def test_all_8_tables_registered():
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_orders_ownership_fk_points_to_users():
    """归属校验的核心外键：orders.user_id → users.id，且不允许为空。"""
    orders = Base.metadata.tables["orders"]
    fk = list(orders.c.user_id.foreign_keys)[0]
    assert fk.target_fullname == "users.id"
    assert not orders.c.user_id.nullable


def test_order_status_check_constraint_exists():
    constraints = {c.name: c for c in Base.metadata.tables["orders"].constraints}
    assert isinstance(constraints["ck_orders_status"], CheckConstraint)


def test_knowledge_chunks_unique_document_chunk():
    constraints = {c.name: c for c in Base.metadata.tables["knowledge_chunks"].constraints}
    assert isinstance(constraints["uq_knowledge_chunks_document_chunk"], UniqueConstraint)


def test_query_logs_fk_points_to_users_set_null():
    """请求日志：user_id 可空（匿名请求），用户删除后置空而非删除日志。"""
    logs = Base.metadata.tables["query_logs"]
    fk = list(logs.c.user_id.foreign_keys)[0]
    assert fk.target_fullname == "users.id"
    assert fk.ondelete == "SET NULL"
    assert logs.c.user_id.nullable


def test_orders_composite_index_exists():
    names = {i.name for i in Base.metadata.tables["orders"].indexes}
    assert "ix_orders_user_id_created_at" in names


async def test_relationship_roundtrip_with_selectinload(db_available: bool):
    """真实数据库上的关系往返 + 懒加载护栏（架构文档 7.1）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    from app.db.session import SessionFactory
    from app.models.logistics import Logistics
    from app.models.order import Order
    from app.models.order_item import OrderItem
    from app.models.user import User

    async with SessionFactory() as session:
        user = User(username="test_rel_user", phone="13900001111", email="rel@example.com")
        session.add(user)  # add 是同步方法，不能 await
        await session.flush()  # 先拿到 user.id

        # 注意：user_id 直接赋值，不经过 relationship —— 这样 order.user 关系是"未加载"状态，
        # 才能验证 lazy="raise" 护栏。正常业务代码建议用 order.user = user 的方式。
        order = Order(
            order_no="SYNTESTREL001", user_id=user.id, status="paid",
            total_amount=Decimal("9.90"), receiver_name="测试用户",
        )
        item = OrderItem(
            order=order, product_id=None, product_name_snapshot="测试商品",
            sku_snapshot="SKU-TEST", price_snapshot=Decimal("9.90"), quantity=1,
        )
        logistics = Logistics(
            order=order, tracking_no="SYNTRACK001", carrier="测试快递",
            status="in_transit", timeline=[], updated_at=datetime.now(timezone.utc),
        )
        session.add_all([order, item, logistics])  # add_all 同样是同步方法
        await session.flush()  # 写入当前事务，未提交

        # 护栏 1：未预加载的关系，访问必须报错（防止异步下隐式 IO）
        plain = (
            await session.execute(select(Order).where(Order.order_no == "SYNTESTREL001"))
        ).scalar_one()
        with pytest.raises(InvalidRequestError):
            _ = plain.user

        # 正确用法：selectinload 预加载
        loaded = (
            await session.execute(
                select(Order)
                .options(
                    selectinload(Order.user),
                    selectinload(Order.items),
                    selectinload(Order.logistics),
                )
                .where(Order.order_no == "SYNTESTREL001")
            )
        ).scalar_one()
        assert loaded.user.username == "test_rel_user"
        assert [i.product_name_snapshot for i in loaded.items] == ["测试商品"]
        assert loaded.logistics.tracking_no == "SYNTRACK001"

        await session.rollback()  # 回滚：测试数据不落库
