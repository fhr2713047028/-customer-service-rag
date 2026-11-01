"""安全纯函数单测：脱敏规则 + JWT 签发/校验。"""
import jwt as pyjwt

from app.core.security import (
    create_access_token,
    decode_access_token,
    mask_address,
    mask_name,
    mask_phone,
)


def test_mask_phone():
    assert mask_phone("13812341234") == "138****1234"
    assert mask_phone("123") == "***"  # 过短整体打码
    assert mask_phone(None) is None


def test_mask_name_and_address():
    assert mask_name("张三") == "张**"
    assert mask_name(None) is None
    assert mask_address("北京市朝阳区某某街道 1 号") == "北京市朝阳区***"
    assert mask_address("短地址") == "***"
    assert mask_address(None) is None


def test_jwt_roundtrip():
    token = create_access_token(7, is_admin=False, expire_minutes=60)
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["is_admin"] is False


def test_jwt_expired_raises():
    token = create_access_token(7, is_admin=False, expire_minutes=-1)
    try:
        decode_access_token(token)
        assert False, "过期令牌应当抛 ExpiredSignatureError"
    except pyjwt.ExpiredSignatureError:
        pass
