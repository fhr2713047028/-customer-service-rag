"""订单查询 API（api_design.md 4.3）。

全部接口需要认证（Bearer JWT）；只返回当前用户自己的订单，
他人订单号一律 404/20001（防枚举，见 api_design.md 第 5 节）。
"""
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.common import ApiResponse, Page
from app.schemas.order import LogisticsOut, OrderOut
from app.services import order_service

router = APIRouter(tags=["orders"])


@router.get("/orders", response_model=ApiResponse[Page[OrderOut]])
async def list_orders(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数，1~100"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的订单分页列表（按创建时间倒序）。"""
    total, orders = await order_service.list_own_orders(db, user, page, page_size)
    return ApiResponse(
        data=Page(
            page=page,
            page_size=page_size,
            total=total,
            items=[order_service.order_to_out(o) for o in orders],
        )
    )


@router.get("/orders/{order_no}", response_model=ApiResponse[OrderOut])
async def get_order(
    order_no: str = Path(..., min_length=8, max_length=32, description="对外订单号"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """订单详情（仅本人；出参已脱敏）。"""
    order = await order_service.get_own_order(db, order_no, user)
    return ApiResponse(data=order_service.order_to_out(order))


@router.get("/orders/{order_no}/logistics", response_model=ApiResponse[LogisticsOut])
async def get_order_logistics(
    order_no: str = Path(..., min_length=8, max_length=32, description="对外订单号"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """物流时间线（仅本人；订单存在但无物流行时 data 为 null）。"""
    order = await order_service.get_own_order(db, order_no, user)
    return ApiResponse(data=order_service.logistics_to_out(order))
