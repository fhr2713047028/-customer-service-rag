"""知识库批量导入脚本：Markdown 文档 → knowledge_documents + knowledge_chunks（含向量）。

- 扫描目录下全部 .md 文件（默认 data/faq）；
- 解析/清洗/分块由 app/services/document_processor.py 完成；
- 每个分块用配置的 embedding provider 生成向量一并入库
  （默认 mock 确定性向量；EMBEDDING_PROVIDER=openai 时用真实 BGE-M3）；
- 幂等：按 source 路径 upsert，重跑会重建该文档的分块与向量；
- 全部文件在单个事务内导入：任一失败（含向量化失败）整体回滚。

用法（项目根目录）：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.ingest_documents
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.ingest_documents --dir data/faq
"""
import argparse
import asyncio
from pathlib import Path

from app.db.session import SessionFactory
from app.services.kb_service import ingest_markdown


async def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Markdown 文档到知识库")
    parser.add_argument("--dir", default="data/faq", help="Markdown 文档目录，默认 data/faq")
    args = parser.parse_args()

    data_dir = Path(args.dir)
    files = sorted(data_dir.glob("*.md"))
    if not files:
        print(f"[error] {data_dir} 下没有 .md 文件")
        return

    async with SessionFactory() as session:
        async with session.begin():  # 单事务：全部成功或全部回滚
            results = []
            for path in files:
                text = path.read_text(encoding="utf-8")
                source = path.as_posix()  # 例如 data/faq/return_policy.md
                doc_id, n_chunks = await ingest_markdown(session, source, text)
                results.append((path.name, doc_id, n_chunks))

    print(f"{'文件':<24}{'文档id':<10}{'分块数'}")
    for name, doc_id, n_chunks in results:
        print(f"{name:<24}{doc_id:<10}{n_chunks}")
    print(f"\n导入完成：{len(results)} 份文档（含向量，provider={args.provider if hasattr(args, 'provider') else '配置默认'}）")


if __name__ == "__main__":
    asyncio.run(main())
