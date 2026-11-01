"""统一响应外壳与分页结构（api_design.md 4.1）。

成功: {"code": 0, "message": "ok", "data": {...}, "request_id": "..."}
失败: {"code": 20001, "message": "...", "data": null, "request_id": "..."}
"""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None
    request_id: str | None = None


class Page(BaseModel, Generic[T]):
    page: int
    page_size: int
    total: int
    items: list[T]
