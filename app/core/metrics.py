"""Prometheus 指标定义（阶段十 10.1 第一部分，架构 7.4 清单落地）。

高基数约束（10.2 第 6 条）：
- path 标签一律用路由模板（如 /api/v1/orders/{order_no}），绝不用
  实际请求值（订单号/物流单号）——既防高基数，也防把敏感值写入指标；
- request_id 绝不作为任何指标的标签；
- 错误标签只用 error_class（异常类型名）与状态码分类，不携带消息文本。
"""
import time
from contextlib import asynccontextmanager

from prometheus_client import Counter, Histogram

# HTTP 层
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP 请求总数", ["method", "path", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求延迟（秒）",
    ["method", "path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

# 数据库操作耗时（主要查询路径）
DB_DURATION = Histogram(
    "db_query_duration_seconds",
    "数据库查询耗时（秒）",
    ["operation"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2),
)

# 检索耗时（关键词/向量/混合）
RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "检索耗时（秒）",
    ["source"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, 5),
)

# 模型调用耗时与错误
LLM_DURATION = Histogram(
    "rag_llm_duration_seconds",
    "模型调用耗时（秒）",
    ["provider"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30),
)
LLM_ERRORS = Counter(
    "rag_llm_errors_total", "模型调用错误数", ["provider", "error_class"]
)
EMBED_DURATION = Histogram(
    "rag_embedding_duration_seconds",
    "Embedding 调用耗时（秒）",
    ["provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
EMBED_ERRORS = Counter(
    "rag_embedding_errors_total", "Embedding 调用错误数", ["provider", "error_class"]
)

# Rerank 调用耗时与错误（阶段十四）
RERANK_DURATION = Histogram(
    "rag_rerank_duration_seconds",
    "Rerank 调用耗时（秒）",
    ["provider"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
RERANK_ERRORS = Counter(
    "rag_rerank_errors_total", "Rerank 调用错误数", ["provider", "error_class"]
)

# 图检索耗时（阶段十六 GraphRAG）
GRAPH_DURATION = Histogram(
    "rag_graph_duration_seconds",
    "图检索耗时（秒）",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1),
)

# RAG 请求总耗时（按处理路径与回答类型）
RAG_DURATION = Histogram(
    "rag_request_duration_seconds",
    "RAG 请求总耗时（秒）",
    ["route", "answer_type"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
)


@asynccontextmanager
async def observe(histogram: Histogram):
    """异步计时上下文：with 块结束后写入直方图。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        histogram.observe(time.perf_counter() - start)
