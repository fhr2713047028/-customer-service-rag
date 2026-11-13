"""查询改写单测（services/query_rewrite.py，阶段十五）。"""
from app.services.query_rewrite import rewrite_query


async def test_rewrite_returns_text(monkeypatch):
    class FakeLLM:
        async def generate(self, system, user, chunks):
            return "退货申请条件 七天无理由"

    import app.services.query_rewrite as module

    monkeypatch.setattr(module, "get_llm_client", lambda: FakeLLM())
    assert await rewrite_query("买完不想要了能退吗") == "退货申请条件 七天无理由"


async def test_rewrite_strips_quotes(monkeypatch):
    class FakeLLM:
        async def generate(self, system, user, chunks):
            return '"退货 条件"'

    import app.services.query_rewrite as module

    monkeypatch.setattr(module, "get_llm_client", lambda: FakeLLM())
    assert await rewrite_query("能退吗") == "退货 条件"


async def test_rewrite_failure_returns_original(monkeypatch):
    class BrokenLLM:
        async def generate(self, system, user, chunks):
            raise RuntimeError("模型不可用")

    import app.services.query_rewrite as module

    monkeypatch.setattr(module, "get_llm_client", lambda: BrokenLLM())
    assert await rewrite_query("退货需要什么条件") == "退货需要什么条件"
