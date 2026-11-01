"""知识库数据质量检查脚本（只读，不改动任何数据）。

检查项：
- 知识库是否为空；
- 文档是否有分块、chunk_index 是否从 0 连续；
- 分块内容是否为空、是否超过硬上限（600 字符）、是否缺少元数据；
- 跨文档是否存在完全相同内容的分块。

用法（项目根目录）：
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python -m scripts.check_knowledge_quality
退出码：全部通过 0；存在问题 1（可直接接 CI）。
"""
import asyncio

from app.db.session import SessionFactory
from app.services.kb_service import check_quality


async def main() -> None:
    async with SessionFactory() as session:
        stats, problems = await check_quality(session)

    print("=== 统计 ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("=== 检查结果 ===")
    if not problems:
        print("  全部通过，未发现问题")
        return

    for p in problems:
        print(f"  [{p['level']}] {p['item']}: {p['detail']}")
    print(f"\n共 {len(problems)} 个问题")
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
