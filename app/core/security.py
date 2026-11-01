"""JWT 签发/校验与出参脱敏（纯函数，可单测）。

- JWT：HS256，密钥 JWT_SECRET 只走环境变量（config.py）；
- 脱敏：出参统一处理，日志脱敏（阶段 8）复用同一组函数；
  简化规则（合成数据场景，正式接入真实数据时按规范调整）：
    phone   → 138****1234（保留前 3 后 4）
    name    → 张**（保留首字符）
    address → 前 6 字符 + ***（近似保留省市区开头）
"""
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_access_token(user_id: int, is_admin: bool, *, expire_minutes: int | None = None) -> str:
    """签发访问令牌；expire_minutes 缺省用配置值，测试可传负数模拟过期。"""
    minutes = expire_minutes if expire_minutes is not None else settings.jwt_expire_minutes
    payload = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """解码并校验令牌。

    失败抛 jwt 异常：ExpiredSignatureError（过期）或 InvalidTokenError（无效），
    由调用方（get_current_user）区分成 10001 / 10002。
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    if len(phone) < 8:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


def mask_name(name: str | None) -> str | None:
    if not name:
        return name
    return f"{name[0]}**"


def mask_address(address: str | None) -> str | None:
    if not address:
        return address
    if len(address) <= 6:
        return "***"
    return f"{address[:6]}***"
