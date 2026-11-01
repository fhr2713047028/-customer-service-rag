"""上游服务故障注入测试（阶段九 9.2：Mock 传输层模拟故障，零生产调用）。

覆盖：模型接口超时 / 限流 429 / 5xx / 4xx 参数错误 / Embedding 维度校验。
"""
import json
import time

import httpx
import pytest

from app.core.errors import EmbeddingError, LLMError
from app.embeddings.client import OpenAICompatibleEmbeddingClient
from app.llm.client import OpenAICompatibleLLMClient

EMBED_OK = {
    "data": [{"index": 0, "embedding": [0.1] * 1024}],
}
CHAT_OK = {
    "id": "1", "object": "chat.completion", "created": 1, "model": "deepseek-chat",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "测试回答"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def _scripted_transport(handler):
    return httpx.MockTransport(handler)


def _embed_client(handler, **kw) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        base_url="https://fake.test/v1", api_key="sk-test", model="BAAI/bge-m3",
        dim=1024, timeout=1.0, transport=_scripted_transport(handler), **kw,
    )


def _llm_client(handler) -> OpenAICompatibleLLMClient:
    import httpx as _httpx

    http_client = _httpx.AsyncClient(transport=_scripted_transport(handler), timeout=1.0)
    return OpenAICompatibleLLMClient(
        base_url="https://fake.test/v1", api_key="sk-test", model="deepseek-chat",
        timeout=1.0, http_client=http_client,
    )


async def test_embedding_retries_on_429_then_succeeds():
    """限流错误：按退避有限重试，成功后返回（不无限重试）。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": "rate limited"}, request=request)
        return httpx.Response(200, json=EMBED_OK, request=request)

    client = _embed_client(handler, retry_base_delay=0.01)
    vecs = await client.embed_texts(["测试"])
    assert len(vecs) == 1 and len(vecs[0]) == 1024
    assert len(attempts) == 3


async def test_embedding_4xx_no_retry():
    """参数/权限错误（4xx）：立即失败，重试没有意义。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={"error": "invalid key"}, request=request)

    client = _embed_client(handler)
    with pytest.raises(EmbeddingError):
        await client.embed_texts(["测试"])
    assert len(attempts) == 1


async def test_embedding_timeout_retries_then_fails():
    """模型接口超时：有限重试（3 次）后返回可理解错误。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectTimeout("模拟超时")

    client = _embed_client(handler, retry_base_delay=0.01)
    with pytest.raises(EmbeddingError) as exc_info:
        await client.embed_texts(["测试"])
    assert "超时" in str(exc_info.value) or "ConnectTimeout" in str(exc_info.value)
    assert len(attempts) == 3


async def test_embedding_persistent_5xx_fails_controlled():
    """服务持续不可用：受控重试后失败，不无限重试。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503, json={"error": "down"}, request=request)

    client = _embed_client(handler, retry_base_delay=0.01)
    with pytest.raises(EmbeddingError):
        await client.embed_texts(["测试"])
    assert len(attempts) == 3


async def test_embedding_dimension_mismatch_rejected():
    """维度校验：接口返回维度与配置不符 → 立即报错，不静默写入。"""
    bad = {"data": [{"index": 0, "embedding": [0.1] * 768}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bad, request=request)

    client = _embed_client(handler)
    with pytest.raises(EmbeddingError) as exc_info:
        await client.embed_texts(["测试"])
    assert "维度" in str(exc_info.value)


async def test_llm_timeout_retries_then_fails():
    """LLM 超时：SDK 级有限重试后抛 LLMError（降级由调用方处理）。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectTimeout("模拟 LLM 超时")

    client = _llm_client(handler)
    with pytest.raises(LLMError):
        await client.generate("sys", "user", [])
    assert len(attempts) >= 2  # SDK 内建重试生效


async def test_llm_4xx_fails_fast():
    """LLM 401：立即失败，不通过重试绕过。"""
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    client = _llm_client(handler)
    with pytest.raises(LLMError):
        await client.generate("sys", "user", [])
    assert len(attempts) == 1  # 4xx 立即失败，不重试


async def test_llm_ok_returns_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CHAT_OK, request=request)

    client = _llm_client(handler)
    answer = await client.generate("sys", "user", [])
    assert answer == "测试回答"
