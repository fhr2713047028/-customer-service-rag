"""request_id 中间件：每个请求一个唯一标识，贯穿响应体与响应头。

- 调用方可自带 X-Request-ID 请求头（用于跨系统串联），否则自动生成；
- 响应头回传 X-Request-ID；
- 统一外壳的 request_id 字段在此统一写入（业务异常响应由异常处理器携带，
  这里覆盖为同一值，保证成功/失败/422 三种响应体一致）；
- 结构化日志模块（实施阶段 8）将复用同一 request_id 串联全链路。

实现要点：FastAPI 的 @app.middleware("http")（BaseHTTPMiddleware）下，
call_next 返回的是 _StreamingResponse 流式包装，必须消费 body_iterator
才能拿到完整响应体；只对 JSON 响应做改写，其余（/docs 的 HTML、未来的
SSE 流式等）原样放行。
"""
import json
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.core.logging import request_id_var


async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    # 写入 contextvar：内层所有模块（访问日志/服务层/异常处理器）的日志都带上同一 rid
    token = request_id_var.set(rid)

    response = await call_next(request)

    try:
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            # 消费流式包装，拿到完整 JSON 字节
            body_bytes = b"".join([chunk async for chunk in response.body_iterator])
            try:
                body = json.loads(body_bytes)
            except Exception:
                # 极端情况：content-type 是 JSON 但内容不是，原样返回
                response = Response(
                    content=body_bytes, status_code=response.status_code, media_type=content_type
                )
            else:
                if isinstance(body, dict):
                    body["request_id"] = rid
                response = JSONResponse(content=body, status_code=response.status_code)

        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id_var.reset(token)
