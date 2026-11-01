"""商品查询 API（api_design.md 4.4）。

商品信息为公开数据，无需认证（与 api_design.md 一致；
订单接口需要身份 + 归属校验，在测试身份模块后实现）。
"""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApiResponse, Page
from app.schemas.product import ProductOut
from app.services import product_service

router = APIRouter(tags=["products"])


@router.get("/products/{product_id}", response_model=ApiResponse[ProductOut])
async def get_product(
    product_id: int = Path(..., gt=0, description="商品 id"),
    db: AsyncSession = Depends(get_db),
):
    product = await product_service.get_product(db, product_id)
    return ApiResponse(data=ProductOut.model_validate(product))


@router.get("/products", response_model=ApiResponse[Page[ProductOut]])
async def list_products(
    keyword: str | None = Query(None, max_length=100, description="商品名关键词（pg_trgm 相似度排序）"),
    category: str | None = Query(None, max_length=64, description="商品类目精确过滤"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数，1~100"),
    db: AsyncSession = Depends(get_db),
):
    total, items = await product_service.list_products(
        db, keyword=keyword, category=category, page=page, page_size=page_size
    )
    return ApiResponse(
        data=Page(
            page=page,
            page_size=page_size,
            total=total,
            items=[ProductOut.model_validate(p) for p in items],
        )
    )
