"""结构化日志：JSON 单行输出 + 脱敏（架构 6.6）。

- setup_logging() 在应用启动时调用一次（main.py），幂等；
- request_id 由中间件写入 contextvar，所有日志自动携带 request_id 字段；
- 敏感信息（手机号、Authorization 头）在输出前统一打码 —— redact_text
  是公开纯函数，后续 LangSmith/告警等出口继续复用；
- 日志绝不包含：密码字段、JWT 全文、完整手机号（api_design 4.2 / 安全要求 5）。
"""
import contextvars
import json
import logging
import re
import sys

# 中间件写入、日志读取的请求级上下文
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization[=:]\s*bearer\s+)[^\s,]+")


def redact_text(text: str) -> str:
    """敏感信息打码（纯函数，可单测）。"""
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)[:3]}****{m.group(1)[-4:]}", text)
    text = _AUTH_HEADER_RE.sub(r"\1***", text)
    return text


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info:
            entry["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """安装结构化日志（幂等：重复调用不重复注册）。"""
    root = logging.getLogger()
    if any(isinstance(h.formatter, _JsonFormatter) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
    # 数据库引擎日志较噪，压到 WARNING（调试 SQL 用 DB_ECHO）
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
