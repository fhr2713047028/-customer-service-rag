"""结构化精确查询（检索层）：只负责"取数"，不做业务判断。

全部查询使用参数绑定（约束 5），包括 ILIKE 的关键词与 similarity() 排序词。
订单查询的归属校验（user_id）在 SQL 层强制（api_design.md 第 5 节）。
"""
from sqlalchemy import bindparam, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.metrics import DB_DURATION, observe
from app.models.logistics import Logistics
from app.models.order import Order
from app.models.product import Product


def _escape_like(keyword: str) -> str:
    """转义 LIKE 通配符，防止用户输入 % _ 改变匹配语义。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    async with observe(DB_DURATION.labels(operation="product_by_id")):
        return await session.get(Product, product_id)


async def search_products(
    session: AsyncSession,
    *,
    keyword: str | None,
    category: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[Product]]:
    """关键词（名称 ILIKE + pg_trgm similarity 排序）/ 分类过滤 + 分页。

    返回 (符合条件的总条数, 当前页商品列表)。
    """
    conditions = []
    if keyword:
        # 关键词作为绑定参数 + 转义，绝不拼接进 SQL
        pattern = f"%{_escape_like(keyword)}%"
        conditions.append(Product.name.ilike(pattern, escape="\\"))
    if category:
        conditions.append(Product.category == category)

    async with observe(DB_DURATION.labels(operation="product_search")):
        # 总数
        count_stmt = select(func.count()).select_from(Product)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = (await session.execute(count_stmt)).scalar_one()

        # 当前页
        stmt = select(Product)
        if conditions:
            stmt = stmt.where(*conditions)
        if keyword:
            # pg_trgm 相似度排序；关键词同样走绑定参数（bindparam），不进 SQL 文本
            stmt = stmt.order_by(func.similarity(Product.name, bindparam("kw", keyword)).desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        items = list((await session.execute(stmt)).scalars().all())
    return total, items


async def get_order_by_no_for_user(
    session: AsyncSession, order_no: str, user_id: int
) -> Order | None:
    """按订单号查询，归属校验合并在同一条 SQL：两条条件同时成立才返回。"""
    async with observe(DB_DURATION.labels(operation="order_by_no")):
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.logistics))
            .where(Order.order_no == order_no, Order.user_id == user_id)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def list_orders_for_user(
    session: AsyncSession, user_id: int, page: int, page_size: int
) -> tuple[int, list[Order]]:
    """当前用户的订单分页列表（按创建时间倒序，id 兜底保证顺序稳定）。"""
    async with observe(DB_DURATION.labels(operation="order_list")):
        cond = Order.user_id == user_id
        total = (
            await session.execute(select(func.count()).select_from(Order).where(cond))
        ).scalar_one()

        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.logistics))
            .where(cond)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await session.execute(stmt)).scalars().all())
    return total, items


async def get_logistics_by_tracking_for_user(
    session: AsyncSession, tracking_no: str, user_id: int
) -> Logistics | None:
    """按物流单号查询；归属校验在 SQL 层：物流必须属于该用户的订单。

    tracking_no 没有唯一约束（防御性设计），取第一条匹配记录。
    """
    async with observe(DB_DURATION.labels(operation="logistics_by_tracking")):
        stmt = (
            select(Logistics)
            .options(selectinload(Logistics.order))
            .join(Order, Logistics.order_id == Order.id)
            .where(Logistics.tracking_no == tracking_no, Order.user_id == user_id)
        )
        return (await session.execute(stmt)).scalars().first()
