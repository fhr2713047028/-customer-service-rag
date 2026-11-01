"""日志脱敏测试（core/logging.py，阶段九 9.2 最后一项）。"""
import logging

from app.core.logging import _JsonFormatter, redact_text


def test_redact_phone():
    text = redact_text("用户手机 13812341234 来电咨询")
    assert "13812341234" not in text
    assert "138****1234" in text


def test_redact_auth_header():
    text = redact_text("authorization: bearer eyJsecret.jwt.token 请求")
    assert "eyJsecret.jwt.token" not in text
    assert "bearer ***" in text


def test_redact_keeps_normal_text():
    assert redact_text("订单查询完成") == "订单查询完成"


def test_json_formatter_masks_sensitive_data():
    """结构化日志格式化器端到端脱敏：手机号与令牌不进入最终日志行。"""
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="用户 %s 发起请求，header=%s", args=("13812341234", "authorization: bearer secret.jwt"),
        exc_info=None,
    )
    line = formatter.format(record)
    assert "13812341234" not in line
    assert "138****1234" in line
    assert "secret.jwt" not in line
    assert '"level": "INFO"' in line  # JSON 结构保留
