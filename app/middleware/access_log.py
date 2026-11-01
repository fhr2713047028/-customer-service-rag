"""请求访问日志 + HTTP 指标（阶段十）。

- 结构化日志：方法 / 路径 / 状态码 / 耗时；
- Prometheus 指标：http_requests_total 与 http_request_duration_seconds。
高基数约束：path 标签使用路由模板（request.scope["route"].path，
如 /api/v1/orders/{order_no}）；未匹配路由统一记为 "unmatched"，
绝不把实际订单号/物流单号写入指标。
"""
import logging
import re
import time

from fastapi import Request

from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = logging.getLogger("app.access")


def _metric_path(request: Request) -> str:
    """指标路径标签：带挂载前缀的路由模板，低基数。

    FastAPI 的 route.path 是相对其挂载前缀的模板（如 /orders/{order_no}，
    不含 /api/v1）。用 route.path_regex 在完整请求路径上定位模板位置，
    重建带前缀的模板（/api/v1/orders/{order_no}）。
    未匹配路由统一记为 "unmatched"。
    """
    route = request.scope.get("route")
    if route is None or not getattr(route, "path", None):
        return "unmatched"

    template = route.path
    url_path = request.url.path
    # path_regex 形如 "^/orders/(?P<order_no>[^/]+)$"，去掉锚点后在完整路径上搜索
    pattern = route.path_regex.pattern.lstrip("^").rstrip("$")
    match = re.search(pattern, url_path)
    if match is not None:
        return url_path[: match.start()] + template  # 前缀 + 模板
    return template


async def access_log_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    method = request.method
    path = _metric_path(request)
    status = str(response.status_code)

    HTTP_REQUESTS.labels(method=method, path=path, status=status).inc()
    HTTP_DURATION.labels(method=method, path=path, status=status).observe(
        (time.perf_counter() - start)
    )

    logger.info(
        "method=%s path=%s status=%s latency_ms=%s",
        method,
        request.url.path,
        status,
        latency_ms,
    )
    return response
