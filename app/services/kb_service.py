"""知识库服务：文档入库（幂等）与数据质量检查。

入库流程由 document_processor 的纯函数完成解析/清洗/分块，
本模块负责数据库写入与幂等策略；批量导入脚本（scripts/ingest_documents.py）
与质检脚本（scripts/check_knowledge_quality.py）都是本模块的薄封装。
"""
import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import build_search_text
from app.embeddings.client import get_embedding_client
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.document_processor import (
    HARD_MAX_CHUNK_SIZE,
    chunk_document,
    parse_markdown,
)

logger = logging.getLogger(__name__)

# 文件名 → 知识库类目（v1 约定：与 api_design 的分类体系一致；未列出的归入 other）
FILENAME_CATEGORY_MAP = {
    "return_policy": "return_policy",
    "refund_policy": "refund_policy",
    "shipping_policy": "logistics",
    "product_warranty": "product",
    "order_faq": "order",
}


def category_for_source(source: str) -> str:
    return FILENAME_CATEGORY_MAP.get(Path(source).stem, "other")


async def ingest_markdown(
    session: AsyncSession, source: str, text: str
) -> tuple[int, int]:
    """导入一份 Markdown：解析 → 清洗 → 分块 → 幂等入库。

    幂等策略：按 source 查找已有文档 —— 存在则删除其分块并更新标题/类目，
    不存在则新建。返回 (document_id, 分块数)。
    调用方负责事务边界（批量导入脚本以单事务包裹全部文件）。
    """
    parsed = parse_markdown(text)
    drafts = chunk_document(parsed)

    # 向量生成（阶段五）：与检索共用同一个 embedding 客户端，保证模型/维度一致。
    # 失败时抛 EmbeddingError → 调用方事务回滚，"库里的向量要么全对要么没有"。
    embedding_client = get_embedding_client()
    vectors = await embedding_client.embed_texts([d.content for d in drafts])
    if len(vectors) != len(drafts):
        raise ValueError(f"向量数量 {len(vectors)} 与分块数 {len(drafts)} 不一致")

    doc = (
        await session.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.source == source)
        )
    ).scalar_one_or_none()

    if doc is None:
        doc = KnowledgeDocument(
            title=parsed.title,
            source=source,
            doc_type="md",
            category=category_for_source(source),
            status=1,
        )
        session.add(doc)
        await session.flush()
    else:
        doc.title = parsed.title
        doc.category = category_for_source(source)
        # 幂等：重建分块（保留 document_id，关联关系稳定）
        await session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
        )

    for draft, vec in zip(drafts, vectors):
        session.add(
            KnowledgeChunk(
                document_id=doc.id,
                chunk_index=draft.index,
                content=draft.content,
                chunk_meta=draft.metadata,
                embedding=vec,
                # 中文全文检索字段：与查询侧同一分词器（core/text.py）
                search_text=build_search_text(draft.content),
            )
        )

    logger.info(
        "document ingested source=%s title=%s chunks=%d",
        source,
        parsed.title,
        len(drafts),
    )
    return doc.id, len(drafts)


async def check_quality(session: AsyncSession) -> tuple[dict, list[dict]]:
    """只读质检：返回 (统计, 问题列表)。问题列表非空即视为未通过。"""
    problems: list[dict] = []
    docs = (
        await session.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.id))
    ).scalars().all()

    total_chunks = 0
    total_chars = 0
    all_contents: dict[str, list[int]] = {}  # content → chunk ids（查跨文档重复）

    if not docs:
        problems.append({"level": "ERROR", "item": "知识库", "detail": "知识库为空，请先运行导入脚本"})
        return {"documents": 0, "chunks": 0}, problems

    for doc in docs:
        chunks = (
            await session.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == doc.id)
                .order_by(KnowledgeChunk.chunk_index)
            )
        ).scalars().all()

        if not chunks:
            problems.append(
                {"level": "ERROR", "item": f"文档 {doc.source}", "detail": "文档没有任何分块"}
            )
            continue

        # chunk_index 连续性（必须从 0 开始无缺口）
        indexes = [c.chunk_index for c in chunks]
        if indexes != list(range(len(chunks))):
            problems.append(
                {
                    "level": "ERROR",
                    "item": f"文档 {doc.source}",
                    "detail": f"chunk_index 不连续: {indexes}",
                }
            )

        for c in chunks:
            total_chunks += 1
            total_chars += len(c.content)
            if not c.content.strip():
                problems.append(
                    {"level": "ERROR", "item": f"文档 {doc.source}", "detail": f"分块 {c.chunk_index} 内容为空"}
                )
            elif len(c.content) > HARD_MAX_CHUNK_SIZE:
                problems.append(
                    {
                        "level": "WARN",
                        "item": f"文档 {doc.source}",
                        "detail": f"分块 {c.chunk_index} 超过硬上限 {len(c.content)}/{HARD_MAX_CHUNK_SIZE}",
                    }
                )
            if not c.chunk_meta:
                problems.append(
                    {"level": "WARN", "item": f"文档 {doc.source}", "detail": f"分块 {c.chunk_index} 缺少元数据"}
                )
            if not c.search_text.strip():
                problems.append(
                    {"level": "WARN", "item": f"文档 {doc.source}",
                     "detail": f"分块 {c.chunk_index} 缺少分词字段（重新导入可修复）"}
                )
            all_contents.setdefault(c.content, []).append(c.id)

    # 跨文档内容重复（完全相同的分块内容）
    for content, ids in all_contents.items():
        if len(ids) > 1:
            problems.append(
                {"level": "WARN", "item": "重复内容", "detail": f"相同内容出现在分块 {ids}"}
            )

    stats = {
        "documents": len(docs),
        "chunks": total_chunks,
        "avg_chunk_chars": round(total_chars / total_chunks, 1) if total_chunks else 0,
    }
    return stats, problems
