"""LLM 客户端单测（llm/client.py，mock provider）。"""
import pytest

from app.config import settings
from app.core.errors import LLMError
from app.llm.client import REFUSAL_TEXT, MockLLMClient, get_llm_client
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument


def _chunk(cid: int, content: str, section: str) -> KnowledgeChunk:
    doc = KnowledgeDocument(id=1, title="退货政策", doc_type="md", category="other", status=1)
    return KnowledgeChunk(
        id=cid, document_id=1, chunk_index=cid, content=content,
        chunk_meta={"section": section}, document=doc,
    )


async def test_mock_llm_refuses_without_context():
    client = MockLLMClient()
    answer = await client.generate("sys", "user", [])
    assert answer == REFUSAL_TEXT


async def test_mock_llm_answers_from_context_with_citations():
    client = MockLLMClient()
    chunks = [_chunk(1, "签收后七天之内可以申请退货。", "退货时限")]
    answer = await client.generate("sys", "user", chunks)
    assert "签收后七天之内" in answer
    assert "[1]《退货政策》退货时限" in answer  # 引用与上下文一一对应


def test_get_llm_client_mock_by_default():
    client = get_llm_client()
    assert client.provider == "mock"
    assert settings.llm_provider == "mock"


def test_openai_provider_without_key_raises(monkeypatch):
    """openai provider 缺密钥 → 快速失败，不静默降级。"""
    import app.llm.client as llm_client

    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(llm_client, "_client", None)
    with pytest.raises(LLMError):
        get_llm_client()
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(llm_client, "_client", None)
