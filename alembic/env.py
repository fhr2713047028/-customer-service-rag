"""alembic 迁移环境（异步版）。

数据库地址从应用配置（环境变量/.env）读取，不写在 alembic.ini 里。
运行方式（项目根目录）：
  alembic revision --autogenerate -m "说明"   # 生成迁移（生成后必须人工检查！）
  alembic upgrade head                        # 应用迁移
  alembic downgrade -1                        # 回退一步
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.db.base import Base
import app.models  # noqa: F401  确保模型注册到 metadata，autogenerate 才能识别

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 连接串统一走应用配置（环境变量 > .env），不在 alembic.ini 里写任何凭据
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 不执行（--sql 参数时使用）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # autogenerate 时同时对比列类型变化
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 迁移用独立连接，不占应用连接池
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
