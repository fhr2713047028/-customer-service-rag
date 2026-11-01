"""监控验证脚本（阶段十 10.2）：对运行中的服务发出 ≥20 次测试请求
（含成功与失败），然后抓取 /metrics 核对指标。

请求构成（23 次）：正常 12 + 失败 11
- 正常：chat 订单×3、chat 知识库×2、商品×2、订单列表×2、healthz×2、物流×1
- 失败：无令牌 401×3、坏令牌 401×1、他人/不存在订单 404×3、商品 404×2、422×2

检查项（10.2）：
1. /metrics 可抓取且含全部指标族；
3. 成功与失败请求都反映在 http_requests_total（按状态码计数）；
6. 高基数红线：指标中不出现 request_id 标签、不出现具体订单号。

用法（先启动服务）：
    uvicorn app.main:app --port 8000
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.metrics_smoke
"""
import asyncio
import re

import httpx

from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"


async def run() -> int:
    token = create_access_token(1, is_admin=False)
    bad_token = "not.a.valid.jwt"
    h_ok = {"Authorization": f"Bearer {token}"}
    h_bad = {"Authorization": f"Bearer {bad_token}"}

    requests = [
        # 正常请求（12）
        ("POST", "/api/v1/chat", h_ok, {"message": "我的订单发货了吗"}),
        ("POST", "/api/v1/chat", h_ok, {"message": "我的订单到哪里了？"}),
        ("POST", "/api/v1/chat", h_ok, {"message": "我的订单符合退货条件吗？"}),
        ("POST", "/api/v1/chat", h_ok, {"message": "退货需要什么条件？"}),
        ("POST", "/api/v1/chat", h_ok, {"message": "退款什么时候到账？"}),
        ("GET", "/api/v1/products/1", None, None),
        ("GET", "/api/v1/products?keyword=耳机", None, None),
        ("GET", "/api/v1/orders", h_ok, None),
        ("GET", "/api/v1/orders", h_ok, None),
        ("GET", "/healthz", None, None),
        ("GET", "/readyz", None, None),
        ("POST", "/api/v1/chat", h_ok, {"message": "帮我看一下"}),
        # 失败请求（11）
        ("GET", "/api/v1/orders", None, None),  # 401
        ("GET", "/api/v1/orders", None, None),  # 401
        ("GET", "/api/v1/orders", None, None),  # 401
        ("GET", "/api/v1/orders", h_bad, None),  # 401 坏签名
        ("GET", "/api/v1/orders/SYNNOTEXIST99", h_ok, None),  # 404
        ("GET", "/api/v1/orders/SYNNOTEXIST98", h_ok, None),  # 404
        ("GET", "/api/v1/logistics/SYNNOTRACK99", h_ok, None),  # 404
        ("GET", "/api/v1/products/999999998", None, None),  # 404
        ("GET", "/api/v1/products/999999997", None, None),  # 404
        ("GET", "/api/v1/products?page_size=101", None, None),  # 422
        ("GET", "/api/v1/orders?page=0", h_ok, None),  # 422
    ]

    statuses = []
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        for method, path, headers, body in requests:
            kwargs = {"headers": headers} if headers else {}
            if method == "POST":
                resp = await client.post(path, json=body, **kwargs)
            else:
                resp = await client.get(path, **kwargs)
            statuses.append(resp.status_code)

        metrics = (await client.get("/metrics")).text

    # 核对
    def metric_count(metric: str) -> float:
        total = 0.0
        for line in metrics.splitlines():
            if line.startswith(metric) and not line.startswith("#"):
                total += float(line.rsplit(" ", 1)[-1])
        return total

    http_total = metric_count("http_requests_total")
    ok_2xx = sum(1 for s in statuses if 200 <= s < 300)
    errors_4xx = sum(1 for s in statuses if 400 <= s < 500)

    print(f"发出请求 {len(statuses)} 次：2xx={ok_2xx}，4xx={errors_4xx}")
    print(f"指标 http_requests_total = {http_total:.0f}（含本次与历史请求）")

    checks = {
        "1. /metrics 可抓取（含全部指标族）": all(
            name in metrics
            for name in (
                "http_requests_total",
                "http_request_duration_seconds",
                "db_query_duration_seconds",
                "rag_retrieval_duration_seconds",
                "rag_llm_duration_seconds",
                "rag_llm_errors_total",
                "rag_embedding_duration_seconds",
                "rag_request_duration_seconds",
            )
        ),
        "3. 失败请求进入指标（status=401/404/422 计数>0）": all(
            f'status="{s}"' in metrics for s in ("401", "404", "422")
        ),
        "3. 成功请求进入指标（status=200）": 'status="200"' in metrics,
        "6. 高基数红线：无 request_id 标签": "request_id" not in metrics,
        "6. 高基数红线：无具体订单号": "SYNNOTEXIST" not in metrics,
        "6. 路径使用路由模板": 'path="/api/v1/orders/{order_no}"' in metrics,
        "指标含 rag_request_duration（route 标签）": 'route="order_query"' in metrics,
    }
    failed = 0
    print()
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1
    print()
    print(f"检查 {len(checks)} 项，通过 {len(checks) - failed}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
