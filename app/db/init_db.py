"""开发环境快速建表：扩展 + 全部表 + 特殊索引。

正式环境请使用 alembic（唯一权威来源）：
  alembic upgrade head

本脚本与迁移保持一致；修改表结构时，两边必须同步更新。
"""
import asyncio

from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401  确保模型全部注册到 Base.metadata

# create_all 无法覆盖的特殊索引。
# 说明：pg_trgm 商品索引、DESC 复合索引、HNSW 向量索引、tsvector 表达式索引
# 都已在模型中精确声明（postgresql_using/ops 与 text() 表达式），
# create_all 会自动创建 —— 本清单当前为空，留给未来模型声明不了的场景。
_SPECIAL_INDEX_SQL: list[str] = []


async def init_db() -> None:
    """幂等：重复执行安全（IF NOT EXISTS / create_all 只建缺的表）。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
        for sql in _SPECIAL_INDEX_SQL:
            await conn.execute(text(sql))


if __name__ == "__main__":
    asyncio.run(init_db())
    print("init_db done")
