"""FastAPI 依赖注入：数据库会话与身份解析（api_design.md 第 2 节）。

身份只来自 JWT 解析结果——任何请求体/查询参数中的 user_id 一律不读取，
禁止把客户端提交的 user_id 当作可信身份。
"""
import logging
from collections.abc import AsyncIterator

import jwt as pyjwt
from fastapi import Depends, Request
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    AuthInvalidTokenError,
    AuthMissingOrExpiredError,
    DatabaseUnavailableError,
)
from app.core.security import decode_access_token
from app.db.session import SessionFactory
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_db() -> AsyncIterator[AsyncSession]:
    """每个请求一个独立会话，请求结束后自动关闭、连接归还连接池。

    用法：路由函数参数写  db: AsyncSession = Depends(get_db)

    数据库异常在此显式封装为 AppError（503/50002）：
    依赖解析阶段的非 AppError 异常可能被框架包装成 ExceptionGroup 逃逸
    （实测 Starlette 行为），显式封装保证"数据库不可用"始终返回
    统一错误外壳，且绝不伪装成正常查询成功（阶段九 9.2/9.3）。
    """
    try:
        async with SessionFactory() as session:
            yield session
    except AppError:
        raise
    except (DBAPIError, OperationalError):
        logger.exception("database unavailable")
        raise DatabaseUnavailableError()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """解析 Authorization: Bearer <JWT> → 数据库用户。

    - 无头/过期 → 401/10001；签名错误/用户不存在/被禁用 → 401/10002
    - 与未来正式认证完全共用：接入注册登录时只新增签发入口，此依赖不变
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthMissingOrExpiredError()

    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise AuthMissingOrExpiredError()
    except pyjwt.InvalidTokenError:
        raise AuthInvalidTokenError()

    user = await db.get(User, int(payload["sub"]))
    if user is None or user.status != 1:
        raise AuthInvalidTokenError()
    return user
