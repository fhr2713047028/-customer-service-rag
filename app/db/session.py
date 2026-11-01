"""异步数据库引擎与会话工厂（架构文档 7.1）。

- engine：进程级单例，负责连接池，应用关闭时由 main.py 的 lifespan 释放
- SessionFactory：会话工厂，每次请求通过 get_db 依赖取一个独立会话
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,       # 连接池常驻连接数（起点 10）
    max_overflow=settings.db_max_overflow, # 超出时的临时连接数（起点 10）
    pool_pre_ping=True,                    # 取连接前探活，避免拿到断连
    pool_recycle=1800,                     # 连接最长复用 30 分钟
    echo=settings.db_echo,
    # asyncpg 连接参数：连接/命令 5 秒超时，
    # 保证 /readyz 在数据库不可达时快速返回 503
    connect_args={"timeout": 5, "command_timeout": 5},
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
