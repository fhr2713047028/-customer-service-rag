"""混合检索：关键词 + 向量 → RRF 排名融合。

RRF（Reciprocal Rank Fusion）只比较排名、不比较原始分数：
    RRF(d) = Σ 1 / (k + rank_r(d))，k 为平滑常数（默认 60）。
关键词检索的 ts_rank 与向量检索的余弦分数量纲完全不同，直接相加
没有意义；按排名融合才公平（阶段六 6.2 的公式与直觉一致）。
"""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import RETRIEVAL_DURATION, observe
from app.core.tracing import trace
from app.models.knowledge_chunk import KnowledgeChunk
from app.retrieval.keyword import search_chunks_keyword
from app.retrieval.vector import search_chunks

RRF_K = 60


@dataclass
class HybridHit:
    """融合后的命中项：保留来源（chunk→document）、双路排序与原始向量分数。"""

    chunk: KnowledgeChunk
    fused_score: float
    keyword_rank: int | None  # None = 该路未返回此候选
    vector_rank: int | None
    vector_score: float | None  # 原始余弦相似度（拒答阈值判定用）


def rrf_fuse(
    keyword_hits: list[tuple[KnowledgeChunk, float]],
    vector_hits: list[tuple[KnowledgeChunk, float]],
    k: int = RRF_K,
) -> list[tuple[int, float]]:
    """纯函数：按排名融合两路结果，返回按融合分降序的 (chunk_id, fused_score)。

    - 同一 chunk 在两路都出现时分数**累加**而非重复返回（dict 天然去重）；
    - 融合分只用于排序，不是相似度也不是概率。
    """
    scores: dict[int, float] = {}
    for rank, (chunk, _score) in enumerate(keyword_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (k + rank)
    for rank, (chunk, _score) in enumerate(vector_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


@trace("hybrid_search", "retriever")
async def hybrid_search(
    session: AsyncSession,
    query_text: str,
    query_vec: list[float],
    top_k: int = 5,
    keyword_candidates: int = 10,
    vector_candidates: int = 10,
) -> list[HybridHit]:
    """两路检索 → RRF 融合 → Top-K 组装（保留来源与排序信息）。

    注意：SQLAlchemy AsyncSession **不支持同一会话内的并发操作**
    （InvalidRequestError: session is provisioning a new connection），
    因此两路检索在同一会话内顺序执行；单查询为毫秒级，顺序代价可忽略。
    压测阶段（阶段 9）若延迟成为瓶颈，再评估双会话并行方案。
    """
    async with observe(RETRIEVAL_DURATION.labels(source="hybrid")):
        kw_hits = await search_chunks_keyword(session, query_text, top_k=keyword_candidates)
        vec_hits = await search_chunks(session, query_vec, top_k=vector_candidates)

    fused = rrf_fuse(kw_hits, vec_hits)
    chunk_by_id = {c.id: c for c, _ in kw_hits} | {c.id: c for c, _ in vec_hits}
    kw_rank = {c.id: i for i, (c, _) in enumerate(kw_hits, start=1)}
    vec_rank = {c.id: i for i, (c, _) in enumerate(vec_hits, start=1)}
    vec_score = {c.id: s for c, s in vec_hits}

    hits: list[HybridHit] = []
    for chunk_id, score in fused[:top_k]:
        hits.append(
            HybridHit(
                chunk=chunk_by_id[chunk_id],
                fused_score=score,
                keyword_rank=kw_rank.get(chunk_id),
                vector_rank=vec_rank.get(chunk_id),
                vector_score=vec_score.get(chunk_id),
            )
        )
    return hits
