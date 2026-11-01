"""LangSmith 链路追踪开关（阶段十 10.1 第三部分）。

隐私与数据安全边界（10.1 明确要求）：
- **默认关闭**：未配置 LANGSMITH_API_KEY 时所有装饰器为透传，
  不向任何外部服务发送数据；
- **显式开关**：LANGSMITH_TRACING=false 可在有 Key 时强制关闭
  （测试环境默认关闭，避免把测试数据发送到外部服务）；
- 启用后仅追踪：问题文本、检索分块（id/标题/内容）、模型耗时与回答、
  链路异常 —— **不携带用户身份（user_id）与任何密钥**
  （认证信息由 LangSmith SDK 在服务端处理，不入 trace 输入）；
- 已验证（2026-10-31 实测 trace 内容）：无 user_id、无密钥、无数据库
  连接串（session 仅序列化为对象 repr）；
- 组合查询的 extra_context 含合成订单号（SYN 前缀演示数据，非真实订单）。
  **生产环境 TODO**：真实订单接入后，需对 trace 输入中的订单号/手机号
  配置 LangSmith 掩码策略（当前 SDK 0.14 无 process_inputs 钩子，
  届时升级 SDK 或在调用方脱敏后传入）；
- 结构化问题（订单/物流/商品）不经过 LLM，本就不进入追踪。
"""
import os
from functools import wraps

from app.config import settings


def is_enabled() -> bool:
    return bool(settings.langsmith_api_key) and os.environ.get(
        "LANGSMITH_TRACING", "true"
    ).lower() != "false"


def ensure_config() -> None:
    """把 Key/项目名导出到环境变量（langsmith SDK 从 os.environ 读取）。

    注意：SDK 0.14 要求 LANGSMITH_TRACING 显式设置，否则即使有 Key
    也会静默禁用追踪（实测：.env 里的值不会被 pydantic-settings
    导出到 os.environ，必须在此显式补齐）。
    """
    if not is_enabled():
        return
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ["LANGSMITH_TRACING"] = "true"


def trace(name: str, run_type: str):
    """条件追踪装饰器：未启用时原样返回函数（零开销透传）。

    在模块导入时判断一次（启用才包裹 langsmith traceable）；
    运行时用 LANGSMITH_TRACING 环境变量做总开关。
    """

    def decorator(fn):
        if not is_enabled():
            return fn
        ensure_config()

        from langsmith import traceable

        traced = traceable(run_type=run_type, name=name)(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            return traced(*args, **kwargs)

        return wrapper

    return decorator
