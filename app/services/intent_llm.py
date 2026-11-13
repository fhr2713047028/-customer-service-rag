"""LLM 意图路由（阶段十五）：与规则版并行存在、数据对比。

设计定位：
- 规则路由（intent.py）是生产默认：零成本、零延迟、可单测；
- LLM 路由是可配置增强：ROUTER_LLM_ENABLED=true 时启用，
  **解析失败/模型异常自动回退规则路由**（路由升级绝不挂掉请求）；
- 两者在评估集上对比（scripts/eval_routing.py），用数据决定取舍。

输出契约（JSON）：
{"route": "structured"|"kb", "intents": [...], "combined": bool, "order_no": str|null}
"""
import json
import logging
import re

from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """你是电商客服系统的意图路由模块。分析用户问题，只输出一个 JSON 对象，格式：
{"route": "structured" 或 "kb", "intents": ["order_status"/"logistics"/"product_info" 的子集, 可为空数组], "combined": true 或 false, "order_no": "订单号" 或 null}

判定规则：
- route="structured"：问题需要查询该用户本人的订单/物流/商品数据——必须带有本人上下文（"我的订单"、"我的快递"、明确的订单号、要退掉自己买的东西）；
- route="kb"：政策/规则类问题（退货条件、退款到账、保修、发票、取消订单规则等），走知识库检索——仅出现"订单/商品/快递"等词但问的是规则时仍属 kb；
- combined=true：问题同时涉及本人订单数据与政策规则（如"我的订单符合退货条件吗"）；
- 只输出 JSON，不要任何其他文字。"""


def parse_router_output(text: str) -> dict | None:
    """容错解析模型输出：容忍代码围栏与前后杂文，提取第一个 JSON 对象。"""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "route" not in data:
        return None
    return data


async def detect_route_llm(message: str) -> dict | None:
    """LLM 路由；任何失败返回 None（调用方回退规则路由）。"""
    try:
        client = get_llm_client()
        answer = await client.generate(ROUTER_SYSTEM_PROMPT, f"【用户问题】\n{message}", [])
        return parse_router_output(answer)
    except Exception:
        logger.exception("llm router failed, fallback to rule router")
        return None
