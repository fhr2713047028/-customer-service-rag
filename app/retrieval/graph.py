"""图检索（阶段十六 GraphRAG）：Neo4j 实体关系网络查询。

查询流程：
1. 问题 → 规则版概念抽取（graph_extract.extract_concepts）；
2. 一跳：直接提及这些概念的分块（权重 1.0）；
3. 二跳：通过"概念共现"关联到的分块（权重 0.5）——多跳遍历；
4. 按加权分排序返回 chunk（附文档上下文）。

失败软降级：Neo4j 不可用/查询失败 → 返回空列表并记录日志，
绝不阻塞主检索链（kb_answer 把图召回当作候选池补充）。
"""
import logging

from neo4j import AsyncGraphDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.metrics import GRAPH_DURATION, observe
from app.models.knowledge_chunk import KnowledgeChunk
from app.services.graph_extract import extract_concepts

logger = logging.getLogger(__name__)

_GRAPH_QUERY = """
MATCH (c:Concept)-[:MENTIONS]-(ch:Chunk)
WHERE c.name IN $names
WITH ch, count(c) AS direct
OPTIONAL MATCH (c2:Concept)-[:CO_OCCURS]-(c3:Concept)-[:MENTIONS]-(ch)
WHERE c2.name IN $names
WITH ch, direct, count(c3) AS hop2
RETURN ch.chunk_id AS chunk_id, direct + hop2 * 0.5 AS score
ORDER BY score DESC
LIMIT $top_k
"""

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
    return _driver


async def search_graph(
    session: AsyncSession, question: str, top_k: int | None = None
) -> list[tuple[KnowledgeChunk, float]]:
    """图检索：返回 [(chunk, 加权分)]；无概念命中/图不可用 → 空列表。"""
    concepts = extract_concepts(question)
    if not concepts:
        return []

    async with observe(GRAPH_DURATION):
        try:
            async with get_driver().session() as gs:
                result = await gs.run(_GRAPH_QUERY, names=concepts, top_k=top_k or settings.graph_top_k)
                records = [record async for record in result]
        except Exception:
            logger.exception("graph search failed, return empty")
            return []

    if not records:
        return []

    chunk_ids = [r["chunk_id"] for r in records]
    score_map = {r["chunk_id"]: float(r["score"]) for r in records}
    chunks = (
        await session.execute(
            select(KnowledgeChunk)
            .options(selectinload(KnowledgeChunk.document))
            .where(KnowledgeChunk.id.in_(chunk_ids))
        )
    ).scalars().all()
    by_id = {c.id: c for c in chunks}
    return [(by_id[cid], score_map[cid]) for cid in chunk_ids if cid in by_id]
