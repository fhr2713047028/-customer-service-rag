"""知识图谱构建（阶段十六 GraphRAG，幂等：清空后重建）。

从知识库分块规则抽取实体关系写入 Neo4j：
- 节点：(:Document {doc_id,title})、(:Chunk {chunk_id})、(:Concept {name})
- 边：(:Document)-[:HAS_CHUNK]->(:Chunk)
       (:Chunk)-[:MENTIONS]->(:Concept)（分块内容命中概念词）
       (:Concept)-[:CO_OCCURS]-(:Concept)（同一分块内共现，无向）

用法：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.ingest_graph
"""
import asyncio

from neo4j import AsyncGraphDatabase
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.session import SessionFactory
from app.models.knowledge_chunk import KnowledgeChunk
from app.services.graph_extract import extract_concepts


async def main() -> None:
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    async with SessionFactory() as session:
        chunks = (
            await session.execute(
                select(KnowledgeChunk).options(selectinload(KnowledgeChunk.document))
            )
        ).scalars().all()
    if not chunks:
        print("[error] 知识库为空，先运行 scripts/ingest_documents")
        return

    async with driver.session() as gs:
        await gs.run("MATCH (n) DETACH DELETE n")  # 幂等：清空重建
        for c in chunks:
            await gs.run(
                "MERGE (d:Document {doc_id: $doc_id, title: $title}) "
                "MERGE (ch:Chunk {chunk_id: $chunk_id}) "
                "MERGE (d)-[:HAS_CHUNK]->(ch)",
                doc_id=c.document_id, title=c.document.title, chunk_id=c.id,
            )
            concepts = extract_concepts(c.content)
            for name in concepts:
                await gs.run(
                    "MATCH (ch:Chunk {chunk_id: $chunk_id}) "
                    "MERGE (c:Concept {name: $name}) "
                    "MERGE (ch)-[:MENTIONS]->(c)",
                    chunk_id=c.id, name=name,
                )
            for i, a in enumerate(concepts):
                for b in concepts[i + 1:]:
                    await gs.run(
                        "MATCH (a:Concept {name: $a}), (b:Concept {name: $b}) "
                        "MERGE (a)-[:CO_OCCURS]-(b)",
                        a=a, b=b,
                    )

    # 统计（neo4j 6.x：single() 是协程）
    async with driver.session() as gs:
        for label in ("Document", "Chunk", "Concept"):
            result = await gs.run(f"MATCH (n:{label}) RETURN count(n) AS c")
            records = [record async for record in result]
            print(f"{label}: {records[0]['c']}")
    await driver.close()
    print("知识图谱构建完成")


if __name__ == "__main__":
    asyncio.run(main())
