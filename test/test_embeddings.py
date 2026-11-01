"""Embedding 客户端单测（app/embeddings/client.py）。"""
import math

import pytest

from app.config import settings
from app.embeddings.client import MockEmbeddingClient


@pytest.fixture
def mock_client() -> MockEmbeddingClient:
    return MockEmbeddingClient(dim=settings.embedding_dim)


async def test_mock_is_deterministic(mock_client):
    """同一文本两次向量化结果完全一致（评估可复现的基础）。"""
    v1 = await mock_client.embed_texts(["退货政策说明"])
    v2 = await mock_client.embed_texts(["退货政策说明"])
    assert v1[0] == v2[0]


async def test_mock_dimension_matches_config(mock_client):
    vecs = await mock_client.embed_texts(["任意文本"])
    assert len(vecs[0]) == settings.embedding_dim == 1024


async def test_mock_vectors_are_unit_norm(mock_client):
    """单位向量：余弦相似度即点积。"""
    vec = (await mock_client.embed_texts(["退款到账时间"]))[0]
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-6


async def test_mock_different_texts_different_vectors(mock_client):
    v1, v2 = await mock_client.embed_texts(["退货申请条件", "物流异常处理"])
    assert v1 != v2


async def test_mock_related_texts_more_similar_than_unrelated(mock_client):
    """词汇重叠近似：同主题文本相似度应高于无关文本（管线冒烟验证）。"""
    q, related, unrelated = await mock_client.embed_texts(
        ["买完不想要了能退吗", "退货申请条件与流程说明", "今天天气真不错"]
    )
    sim_related = sum(a * b for a, b in zip(q, related))
    sim_unrelated = sum(a * b for a, b in zip(q, unrelated))
    assert sim_related > sim_unrelated
