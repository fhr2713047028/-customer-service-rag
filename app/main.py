"""FastAPI 应用入口。

本模块只做：创建应用实例、注册系统端点（/healthz /readyz）。
业务路由（商品/订单/聊天等）在后续模块中以 Router 形式挂载进来。
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.routes import chat, logistics, orders, products
from app.config import settings
from app.core.errors import AppError
from app.core.exceptions import app_error_handler, unhandled_exception_handler
from app.core.logging import setup_logging
from app.db.session import engine
from app.middleware.access_log import access_log_middleware
from app.middleware.request_id import request_id_middleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动：暂无初始化动作（建表/扩展在数据层模块加入）
    yield
    # 应用关闭：释放数据库连接池，优雅退出
    await engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# 简单聊天演示页（阶段十一后追加）：纯静态单页，随应用一起部署
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """根路径返回聊天演示页。"""
    return FileResponse(_STATIC_DIR / "index.html")

# 基础设施：结构化日志、中间件（访问日志在内层、request_id 在最外层）、
# 全局异常处理器、业务路由
setup_logging()
app.middleware("http")(access_log_middleware)  # 先注册 → 内层，能读到 request_id
app.middleware("http")(request_id_middleware)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(products.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(logistics.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/metrics")
async def metrics():
    """Prometheus 抓取端点（阶段十）。

    访问控制：开发期仅本机使用；生产部署由反向代理/防火墙限制
    （architecture 6.6：监控端点不得默认向不可信网络公开）。
    """
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz():
    """存活探针：进程活着就返回 200，不依赖任何外部服务。"""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(db: AsyncSession = Depends(get_db)):
    """就绪探针：检查数据库连通性，失败返回 503（架构文档 4.3）。

    连接/命令超时已在 session.py 中设为 5 秒，
    保证数据库不可达时快速返回 503 而不是长时间挂起。
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # 数据库不可达/认证失败等，一律视为未就绪
        logger.exception("readyz: database check failed")
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}
