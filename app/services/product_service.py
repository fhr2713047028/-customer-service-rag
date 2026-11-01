"""商品服务（服务编排层）：路由 → 服务 → 检索，分层单向依赖（架构 1.3）。"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProductNotFoundError
from app.models.product import Product
from app.retrieval.structured import get_product_by_id, search_products

logger = logging.getLogger(__name__)


async def get_product(session: AsyncSession, product_id: int) -> Product:
    product = await get_product_by_id(session, product_id)
    if product is None:
        raise ProductNotFoundError()  # 404 / 20002，由全局异常处理器转统一外壳
    # 商品查询量大，用 DEBUG 级别避免刷屏（演示日志分级用法）
    logger.debug("product queried id=%s", product_id)
    return product


async def list_products(
    session: AsyncSession,
    *,
    keyword: str | None,
    category: str | None,
    page: int,
    page_size: int,
) -> tuple[int, list[Product]]:
    return await search_products(
        session, keyword=keyword, category=category, page=page, page_size=page_size
    )
