"""向量相似度检索（检索层）：pgvector HNSW 余弦 Top-K。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.metrics import RETRIEVAL_DURATION, observe
from app.models.knowledge_chunk import KnowledgeChunk


async def search_chunks(
    session: AsyncSession, query_vec: list[float], top_k: int = 5
) -> list[tuple[KnowledgeChunk, float]]:
    """按余弦相似度返回 Top-K 分块（附文档上下文与分数）。

    - 查询向量由调用方用与入库相同的 embedding 客户端生成（保证同模型同维度）；
    - 分数 = 1 - cosine_distance，即余弦相似度；**分数是相似度不是正确概率**
      （rag_design 5.4），阈值必须用评估集验证后才能设定；
    - 未向量化的分块（embedding 为 NULL）不参与检索。
    """
    async with observe(RETRIEVAL_DURATION.labels(source="vector")):
        distance = KnowledgeChunk.embedding.cosine_distance(query_vec)
        stmt = (
            select(KnowledgeChunk, (1 - distance).label("score"))
            .options(selectinload(KnowledgeChunk.document))
            .where(KnowledgeChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await session.execute(stmt)).all()
    return [(chunk, float(score)) for chunk, score in rows]
