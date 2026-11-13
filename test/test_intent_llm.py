"""LLM 意图路由单测（services/intent_llm.py，阶段十五）。"""
from app.services.intent_llm import parse_router_output, detect_route_llm


def test_parse_plain_json():
    assert parse_router_output('{"route": "kb", "intents": [], "combined": false, "order_no": null}') == {
        "route": "kb", "intents": [], "combined": False, "order_no": None,
    }


def test_parse_json_with_code_fence():
    text = '```json\n{"route": "structured", "intents": ["order_status"], "combined": true, "order_no": "SYN001"}\n```'
    data = parse_router_output(text)
    assert data["route"] == "structured"
    assert data["order_no"] == "SYN001"


def test_parse_json_with_extra_text():
    text = '好的，分析如下：{"route": "kb", "intents": [], "combined": false, "order_no": null} 希望有帮助'
    data = parse_router_output(text)
    assert data["route"] == "kb"


def test_parse_invalid_returns_none():
    assert parse_router_output("抱歉我无法回答") is None
    assert parse_router_output("") is None
    assert parse_router_output('{"intents": []}') is None  # 缺 route 字段


async def test_detect_route_llm_returns_parsed(monkeypatch):
    class FakeLLM:
        async def generate(self, system, user, chunks):
            return '{"route": "kb", "intents": [], "combined": false, "order_no": null}'

    import app.services.intent_llm as module

    monkeypatch.setattr(module, "get_llm_client", lambda: FakeLLM())
    data = await detect_route_llm("退货需要什么条件")
    assert data["route"] == "kb"


async def test_detect_route_llm_failure_returns_none(monkeypatch):
    class BrokenLLM:
        async def generate(self, system, user, chunks):
            raise RuntimeError("模型不可用")

    import app.services.intent_llm as module

    monkeypatch.setattr(module, "get_llm_client", lambda: BrokenLLM())
    assert await detect_route_llm("退货需要什么条件") is None
