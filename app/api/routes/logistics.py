"""物流查询 API：按物流单号查询（需认证 + 归属校验）。

按订单号查物流的接口在 orders.py（GET /orders/{order_no}/logistics）。
"""
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.order import LogisticsDetailOut
from app.services import logistics_service

router = APIRouter(tags=["logistics"])


@router.get("/logistics/{tracking_no}", response_model=ApiResponse[LogisticsDetailOut])
async def get_logistics(
    tracking_no: str = Path(..., min_length=4, max_length=64, description="物流单号"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """物流详情：单号必须属于当前用户的订单，否则 404/20001（防单号枚举）。"""
    logistics = await logistics_service.get_own_logistics(db, tracking_no, user)
    return ApiResponse(data=logistics_service.logistics_detail_to_out(logistics))
