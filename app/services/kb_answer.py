"""知识库回答（阶段七）：检索上下文组装 → 拒答判断 → LLM 生成 → 来源引用。

拒答规则（7.4）：
- "无依据" = 关键词路无结果 **且** 向量 top-1 相似度低于 kb_refusal_min_score；
- 阈值只用于拒答边界（低分=没有依据），不用于"高分即正确"的判定；
  具体数值用评估集校准（rag_eval_report.md 记录校准过程）。
- LLM 失败降级：返回检索原文 + 来源（answer_type=degraded），不编造。
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import EmbeddingError, LLMError
from app.core.tracing import trace
from app.embeddings.client import get_embedding_client
from app.llm.client import REFUSAL_TEXT, get_llm_client
from app.retrieval.hybrid import hybrid_search
from app.retrieval.keyword import search_chunks_keyword
from app.services.prompts import SYSTEM_PROMPT, build_rag_user_prompt

logger = logging.getLogger(__name__)


@trace("kb_answer", "chain")
async def generate_kb_answer(
    session: AsyncSession, question: str, extra_context: str | None = None
) -> dict:
    """知识库问答：返回 {answer, answer_type, sources, confidence}。

    answer_type: generated | fallback | degraded
    extra_context: 组合查询时注入的业务数据（【订单信息】分区）
    """
    embedding_client = get_embedding_client()
    try:
        query_vec = (await embedding_client.embed_texts([question]))[0]
        hits = await hybrid_search(session, question, query_vec, top_k=5)
    except EmbeddingError:
        # Embedding 服务失败（阶段九降级边界）：退化为关键词检索，
        # 明确记录错误、明确标注结果性质 —— 不伪造检索结果
        logger.error("embedding failed, degrade to keyword-only, question=%r", question[:50])
        kw_hits = await search_chunks_keyword(session, question, top_k=5)
        if not kw_hits:
            raise  # 关键词也无所获：如实抛出 502/50001，不伪装成"无依据"
        chunks = [c for c, _ in kw_hits]
        answer = (
            "向量检索服务暂时不可用，以下仅为关键词检索到的相关内容（非完整回答）：\n\n"
            + "\n\n".join(
                f"《{c.document.title}》{c.chunk_meta.get('section', '')}：\n{c.content}"
                for c in chunks
            )
        )
        return {
            "answer": answer,
            "answer_type": "degraded",
            "sources": [
                {
                    "type": "kb",
                    "doc_title": c.document.title,
                    "chunk_id": c.id,
                    "section": c.chunk_meta.get("section", "") if c.chunk_meta else "",
                    "score": None,
                    "order_no": None,
                }
                for c in chunks
            ],
            "confidence": "low",
        }

    # 拒答判断：所有候选的最大向量相似度低于阈值 → 无依据（阈值校准见 config.py 注释）。
    # 用"最大值"而非 top-1：融合排序的第一名可能只是关键词路独有的分块
    # （其 vector_score 为 None），用 top-1 判断会导致拒答条件落空。
    scores = [h.vector_score for h in hits if h.vector_score is not None]
    if not hits or not scores or max(scores) < settings.kb_refusal_min_score:
        logger.info("kb answer refused: no reliable basis, question=%r", question[:50])
        return {
            "answer": REFUSAL_TEXT,
            "answer_type": "fallback",
            "sources": [],
            "confidence": "low",
        }

    chunks = [h.chunk for h in hits]
    user_prompt = build_rag_user_prompt(question, chunks, extra_context=extra_context)
    llm_client = get_llm_client()
    try:
        answer = await llm_client.generate(SYSTEM_PROMPT, user_prompt, chunks)
        answer_type = "generated"
        confidence = "high"
    except LLMError:
        # 降级：返回检索原文 + 来源，不生成（架构 6.4 降级链）
        logger.exception("kb answer degraded to retrieval-only")
        answer = "模型服务暂时不可用，以下为检索到的相关内容：\n\n" + "\n\n".join(
            f"《{c.document.title}》{c.chunk_meta.get('section', '')}：\n{c.content}"
            for c in chunks
        )
        answer_type = "degraded"
        confidence = "low"

    sources = [
        {
            "type": "kb",
            "doc_title": c.document.title,
            "chunk_id": c.id,
            "section": c.chunk_meta.get("section", "") if c.chunk_meta else "",
            "score": round(h.vector_score, 4) if h.vector_score is not None else None,
            "order_no": None,
        }
        for c, h in zip(chunks, hits)
    ]
    return {"answer": answer, "answer_type": answer_type, "sources": sources, "confidence": confidence}
