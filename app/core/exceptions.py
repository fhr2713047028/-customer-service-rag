"""全局异常处理器：业务异常与未预期异常 → 统一响应外壳（api_design.md 4.1）。

注册方式（main.py）：
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
"""
import logging

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """业务异常：按 AppError 携带的 code/http_status 出统一外壳。"""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
            "request_id": _request_id(request),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常：详情只进日志，出参只给 500/50003（api_design.md 4.2）。

    注意：HTTPException（404 路由不存在、422 参数校验失败等框架异常）
    必须交还 FastAPI 默认处理器，否则会把它们误报成 50003。
    """
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return await http_exception_handler(request, exc)

    logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "code": 50003,
            "message": "内部错误",
            "data": None,
            "request_id": _request_id(request),
        },
    )
