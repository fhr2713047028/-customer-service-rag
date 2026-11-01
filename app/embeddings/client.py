"""Embedding 客户端：provider 可配置（mock / openai 兼容协议）。

- **mock**（默认）：确定性词袋哈希向量 —— 用 jieba 分词后对词元做固定种子
  哈希生成随机单位向量。优点是零网络零费用、结果可复现，能完整跑通
  "向量生成→存储→检索→评估"管线；缺点是没有语义能力，只反映词汇重叠，
  **其结果不代表真实语义模型的检索效果**（预算 0 元策略，见 development_plan 4.4）。
- **openai**：任意 OpenAI 兼容接口（硅基流动 BGE-M3 等）。**维度以实际接口
  返回为准**：每次响应校验向量长度 == settings.embedding_dim，不一致立即报错，
  防止换模型后新旧向量混用导致检索静默失效（rag_design 4.4）。

错误处理：超时/5xx/429 指数退避重试 2 次；4xx 不重试；最终失败抛
EmbeddingError(502/50001)，由调用方决定降级或中止（入库场景选择中止，
保证"库里的向量要么全对要么没有"）。
"""
import hashlib
import logging
import math
import random

import httpx

from app.config import settings
from app.core.errors import EmbeddingError
from app.core.metrics import EMBED_DURATION, EMBED_ERRORS, observe
from app.core.retry import retry_call
from app.core.text import tokenize_list  # 与全文检索共享同一分词器（含自定义词典）

logger = logging.getLogger(__name__)


class MockEmbeddingClient:
    """确定性词袋哈希向量（仅离线开发/管线测试，标注 mock）。"""

    provider = "mock"

    def __init__(self, dim: int):
        self.dim = dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        async with observe(EMBED_DURATION.labels(provider=self.provider)):
            return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in tokenize_list(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324 固定哈希用于确定性
            rng = random.Random(int.from_bytes(digest[:8], "big"))
            for i in range(self.dim):
                vec[i] += rng.uniform(-1.0, 1.0)
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]  # 单位化：余弦相似度即点积


class OpenAICompatibleEmbeddingClient:
    """OpenAI 兼容协议客户端（httpx 异步 + 重试 + 维度运行时校验）。

    重试策略统一走 core/retry.py（有限重试 + 指数退避 + 抖动 + 错误分类）：
    - 超时/连接中断/5xx/429 → 重试（最多 2 次）；
    - 4xx（参数/权限错误）→ 立即失败，不重试；
    - transport 参数用于故障注入测试（MockTransport 模拟超时/限流/5xx）。
    """

    provider = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_base_delay: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.timeout = timeout
        self._transport = transport
        self._retry_base_delay = retry_base_delay

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "input": texts}

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            async def call_once():
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    return self._validate(resp.json())
                # 429（限流）虽属 4xx 区段，但可恢复 → 与 5xx 一起进入重试分类
                if resp.status_code == 429 or resp.is_server_error:
                    resp.raise_for_status()  # HTTPStatusError → retry_call 判定可重试
                # 其余 4xx：参数/权限错误，重试没有意义（9.1 错误分类）
                raise EmbeddingError(f"embedding 上游错误 HTTP {resp.status_code}")

            try:
                async with observe(EMBED_DURATION.labels(provider=self.provider)):
                    return await retry_call(
                        call_once,
                        max_retries=2,
                        base_delay=self._retry_base_delay,
                        on_error=lambda exc, attempt: logger.warning(
                            "embedding call retrying attempt=%s error=%s",
                            attempt,
                            exc.__class__.__name__,
                        ),
                    )
            except EmbeddingError as exc:
                EMBED_ERRORS.labels(
                    provider=self.provider, error_class="EmbeddingError"
                ).inc()
                raise
            except Exception as exc:
                # 重试耗尽后的超时/5xx/429 → 统一为业务错误（可理解、可分类）
                EMBED_ERRORS.labels(
                    provider=self.provider, error_class=exc.__class__.__name__
                ).inc()
                raise EmbeddingError(f"embedding 失败: {exc.__class__.__name__}")

    def _validate(self, body: dict) -> list[list[float]]:
        try:
            data = sorted(body["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in data]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(f"embedding 响应格式异常: {exc}")
        # 维度运行时校验（rag_design 4.4）：与配置不符立即报错
        for vec in vectors:
            if len(vec) != self.dim:
                raise EmbeddingError(
                    f"embedding 实际维度 {len(vec)} 与配置 {self.dim} 不一致，"
                    "请检查 EMBEDDING_MODEL / EMBEDDING_DIM"
                )
        return vectors


_client = None


def get_embedding_client():
    """按配置选择 provider；mock 无密钥也能用，openai 缺密钥时启动即报错（快速失败）。"""
    global _client
    if _client is not None:
        return _client

    if settings.embedding_provider == "mock":
        _client = MockEmbeddingClient(dim=settings.embedding_dim)
    elif settings.embedding_provider == "openai":
        if not settings.embedding_api_key:
            raise EmbeddingError("EMBEDDING_PROVIDER=openai 但 EMBEDDING_API_KEY 为空")
        _client = OpenAICompatibleEmbeddingClient(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
            timeout=settings.embedding_timeout_seconds,
        )
    else:
        raise EmbeddingError(f"未知 EMBEDDING_PROVIDER: {settings.embedding_provider}")

    logger.info(
        "embedding client ready provider=%s model=%s dim=%d",
        _client.provider,
        settings.embedding_model if _client.provider == "openai" else "mock-hash",
        settings.embedding_dim,
    )
    return _client
