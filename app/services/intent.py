"""意图识别与路由（规则版，架构 0.7 决策：先规则后 LLM）。

纯函数、零成本、可单测。LLM 版意图分类在真实模型接入后对比效果再决定切换。

v2 规则（评估驱动修正）：结构化意图必须带"用户上下文"——
- order_status：消息含订单号，或"我的订单"，或"我要退掉"（涉及本人订单）；
- logistics：含"我的"上下文且提到物流/快递；
- product_info：明确的商品目录类询问（有什么商品/推荐）。
仅出现"订单/快递/商品"等词的**政策规则类问题**（如"怎么取消订单"）
应走知识库，不再被关键词劫持（eval_rag 报告记录了这次修正）。
"""
import re

# 订单号模式（SYN 前缀或 8~32 位字母数字）
_ORDER_NO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{7,31}")

INTENT_ORDER = ("order_status", "logistics", "product_info")

# 政策类关键词（组合查询判定用）：订单上下文 + 政策词 → 需要"数据库 + RAG"双源
POLICY_KEYWORDS = ("退货", "退款", "政策", "能退", "退吗", "条件")


def extract_order_no(message: str) -> str | None:
    """提取消息中的订单号。

    v3 修正：候选含连字符 "-" 时不是订单号 —— 避免把政策编号
    （POLICY-2026-01）和商品型号（A200-Pro）误判为订单号
    （合成订单号 SYN... 不含连字符，真实订单号规则接入时按实际格式调整）。
    """
    match = _ORDER_NO_RE.search(message)
    if match is None:
        return None
    candidate = match.group(0)
    if "-" in candidate:
        return None
    return candidate


def detect_intents(message: str) -> list[str]:
    """返回命中的意图列表（按固定顺序）。"""
    intents = []
    order_no = extract_order_no(message)

    if order_no or "我的订单" in message or ("我" in message and "退掉" in message):
        intents.append("order_status")
    if (order_no or "我的" in message) and any(k in message for k in ("物流", "快递")):
        intents.append("logistics")
    if "有什么商品" in message or "推荐" in message or "多少钱" in message or "价格" in message:
        intents.append("product_info")
    return intents


def is_combined_query(message: str, intents: list[str]) -> bool:
    """组合查询判定：订单上下文 + 政策类关键词 → 数据库 + RAG 双源。"""
    return "order_status" in intents and any(k in message for k in POLICY_KEYWORDS)
