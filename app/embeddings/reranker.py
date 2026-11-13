"""Reranker 客户端（阶段十四）：BGE-Reranker 交叉编码器精排。

接口：硅基流动 /rerank（Jina 风格，非 OpenAI 兼容的 embeddings 端点）：
    POST {base_url}/rerank
    {"model": "BAAI/bge-reranker-v2-m3", "query": "...", "documents": [...], "top_n": 5}
    响应：{"results": [{"index": 0, "relevance_score": 0.91}, ...]}

失败策略（与 Embedding 同一纪律）：超时/5xx/429 有限重试（2 次，退避+抖动），
4xx 立即失败；最终失败抛 RerankError，由调用方**软降级**为 RRF 原始顺序
（排序质量下降但回答仍可用，错误记入 rag_rerank_errors_total）。
"""
import logging

import httpx

from app.config import settings
from app.core.errors import RerankError
from app.core.metrics import RERANK_DURATION, RERANK_ERRORS, observe
from app.core.retry import retry_call

logger = logging.getLogger(__name__)


class RerankClient:
    provider = "siliconflow"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_base_delay: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport
        self._retry_base_delay = retry_base_delay

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """返回按相关度降序的 (原文档下标, 相关度分数)。

        documents 不能为空；top_n 会被限制在 len(documents) 内。
        """
        if not documents:
            return []
        url = f"{self.base_url}/rerank"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
        }

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            async def call_once():
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return self._validate(resp.json())
                # 429（限流）虽属 4xx 区段，但可恢复 → 与 5xx 一起进入重试分类
                if resp.status_code == 429 or resp.is_server_error:
                    resp.raise_for_status()  # HTTPStatusError → retry_call 判定可重试
                raise RerankError(f"rerank 上游错误 HTTP {resp.status_code}")

            try:
                async with observe(RERANK_DURATION.labels(provider=self.provider)):
                    return await retry_call(
                        call_once,
                        max_retries=2,
                        base_delay=self._retry_base_delay,
                        on_error=lambda exc, attempt: logger.warning(
                            "rerank call retrying attempt=%s error=%s",
                            attempt,
                            exc.__class__.__name__,
                        ),
                    )
            except RerankError:
                RERANK_ERRORS.labels(provider=self.provider, error_class="RerankError").inc()
                raise
            except Exception as exc:
                RERANK_ERRORS.labels(
                    provider=self.provider, error_class=exc.__class__.__name__
                ).inc()
                raise RerankError(f"rerank 失败: {exc.__class__.__name__}")

    def _validate(self, body: dict) -> list[tuple[int, float]]:
        try:
            results = body["results"]
            # 按相关度降序排序（服务端通常已排序，此处防御性重排）
            return sorted(
                ((int(item["index"]), float(item["relevance_score"])) for item in results),
                key=lambda pair: pair[1],
                reverse=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RerankError(f"rerank 响应格式异常: {exc}")


_client = None


def get_rerank_client() -> RerankClient:
    """按配置构造客户端（复用硅基流动 Key；缺 Key 时快速失败）。"""
    global _client
    if _client is not None:
        return _client
    if not settings.embedding_api_key:
        raise RerankError("RERANK 需要 EMBEDDING_API_KEY（硅基流动）")
    _client = RerankClient(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.rerank_model,
        timeout=settings.rerank_timeout_seconds,
    )
    logger.info("rerank client ready model=%s", settings.rerank_model)
    return _client
