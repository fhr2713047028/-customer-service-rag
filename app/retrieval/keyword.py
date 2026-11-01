"""关键词检索（检索层）：jieba 预分词 + PostgreSQL 全文检索（tsvector）。

查询构造为参数化 tsquery（bindparam），绝不拼接 SQL（约束 5）。
排序分数为 ts_rank（词频/覆盖度），仅在关键词检索内部用于排序；
进入 RRF 融合时只用排名（见 hybrid.py）。
"""
from sqlalchemy import bindparam, column, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.metrics import RETRIEVAL_DURATION, observe
from app.core.text import build_tsquery
from app.models.knowledge_chunk import KnowledgeChunk

# search_text 上的 tsvector 表达式（与迁移 #4 的 GIN 索引口径一致）。
# 用 column() 构造列引用（TextClause 不支持 .op 运算符重载）
_TSV = func.to_tsvector("simple", column("search_text"))


async def _execute(
    session: AsyncSession, tsq: str, top_k: int
) -> list[tuple[KnowledgeChunk, float]]:
    tsq_expr = func.to_tsquery("simple", bindparam("tsq", tsq))
    rank = func.ts_rank(_TSV, tsq_expr)
    stmt = (
        select(KnowledgeChunk, rank.label("rank"))
        .options(selectinload(KnowledgeChunk.document))
        .where(_TSV.op("@@")(tsq_expr))
        .order_by(rank.desc())
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    return [(chunk, float(r)) for chunk, r in rows]


async def search_chunks_keyword(
    session: AsyncSession, query: str, top_k: int = 10
) -> list[tuple[KnowledgeChunk, float]]:
    """中文关键词检索。

    - 无有效词元 → 返回空列表（不检索）；
    - AND 查询无结果时退化为 OR（召回兜底，候选数量调优点）；
    - 未分词的内容（search_text 为空的历史分块）不会命中 —— 由质检脚本提示。
    """
    async with observe(RETRIEVAL_DURATION.labels(source="keyword")):
        tsq_and = build_tsquery(query, operator="&")
        if tsq_and is None:
            return []
        results = await _execute(session, tsq_and, top_k)
        if results:
            return results
        tsq_or = build_tsquery(query, operator="|")
        if tsq_or is None:
            return []
        return await _execute(session, tsq_or, top_k)
