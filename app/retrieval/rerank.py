"""Rerank 精排（检索层，阶段十四）：对混合检索候选做交叉编码器重排序。

注意：rerank 只影响"候选之间的先后"，不参与"有没有依据"的判断——
拒答阈值仍基于原始向量相似度（在 kb_answer 中先于 rerank 执行），
因为交叉编码器的分数分布与余弦相似度完全不同，混用会破坏阈值语义。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings.reranker import get_rerank_client
from app.models.knowledge_chunk import KnowledgeChunk
from app.retrieval.hybrid import HybridHit


async def rerank_candidates(
    session: AsyncSession,
    query: str,
    hits: list[HybridHit],
    top_n: int,
) -> list[tuple[KnowledgeChunk, float]]:
    """对 hits（混合检索 HybridHit 候选）按 rerank 相关度降序返回 top_n。

    - 返回的分数是 rerank 相关度（0~1，交叉编码器），与向量余弦不同量纲，
      仅用于本次排序与展示，不进入拒答阈值判定；
    - hits 顺序保留原始候选顺序，rerank 结果按原下标映射回 chunk。
    """
    client = get_rerank_client()
    documents = [hit.chunk.content for hit in hits]
    ranked = await client.rerank(query, documents, top_n=top_n)
    return [(hits[index].chunk, score) for index, score in ranked]
