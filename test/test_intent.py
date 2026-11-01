"""规则版意图路由单测（services/intent.py，v2 规则：结构化意图必须带用户上下文）。"""
from app.services.intent import detect_intents, extract_order_no


def test_order_intent_with_order_no():
    assert "order_status" in detect_intents("订单 SYN202610200001 发货了吗")


def test_order_intent_with_my_context():
    assert detect_intents("我的订单发货了吗") == ["order_status"]


def test_return_intent_with_my_context():
    assert detect_intents("我要退掉上个月买的商品") == ["order_status"]


def test_logistics_intent_with_my_context():
    assert detect_intents("帮我查一下我的快递到哪了") == ["logistics"]


def test_policy_questions_go_to_kb_not_structured():
    """仅含业务名词、无用户上下文的规则类问题 → 知识库（评估驱动修正）。"""
    assert detect_intents("快递一直不更新怎么办") == []
    assert detect_intents("怎么取消订单") == []
    assert detect_intents("商品坏了能不能维修") == []
    assert detect_intents("订单状态代码 shipped 是什么意思") == []


def test_catalog_question_is_product_intent():
    assert detect_intents("你们有什么商品") == ["product_info"]


def test_extract_order_no():
    assert extract_order_no("订单 SYN202610200001 发货了吗") == "SYN202610200001"
    assert extract_order_no("今天天气怎么样") is None


def test_extract_order_no_rejects_dashed_candidates():
    """政策编号/商品型号含连字符，不得被误判为订单号（评估驱动修正 v3）。"""
    assert extract_order_no("POLICY-2026-01 对应什么政策？") is None
    assert extract_order_no("商品型号 A100-X 和 A200-Pro 哪个更好？") is None
    assert detect_intents("POLICY-2026-01 对应什么政策？") == []
    assert detect_intents("商品型号 A100-X 和 A200-Pro 哪个更好？") == []
