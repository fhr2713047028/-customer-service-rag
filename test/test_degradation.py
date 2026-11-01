"""降级边界测试（阶段九 9.3：DeepSeek 不可用时的明确降级边界）。"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import EmbeddingError, LLMError
from app.core.security import create_access_token
from app.main import app
from app.services import kb_answer


@pytest.fixture
async def token_and_user():
    from app.db.session import SessionFactory
    from app.models.user import User
    from sqlalchemy import select

    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.id == 1))).scalar_one_or_none()
    if user is None:
        pytest.skip("需要先运行种子数据")
    return create_access_token(user.id, user.is_admin)


def _client(token: str):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
        # 数据库宕机用例：Windows 上连接不可达端口可能"挂起"而非快速拒绝，
        # 应用在 asyncpg 2s 超时后返回 500；客户端超时需留足余量
        timeout=30.0,
    )


async def test_template_paths_unaffected_when_llm_down(
    db_available: bool, token_and_user, monkeypatch
):
    """LLM 不可用：商品/订单查询仍然正常执行（模板路径不经过 LLM）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    class DeadLLM:
        async def generate(self, *args, **kwargs):
            raise LLMError("模型不可用")

    monkeypatch.setattr(kb_answer, "get_llm_client", lambda: DeadLLM())

    async with _client(token_and_user) as client:
        resp = await client.post("/api/v1/chat", json={"message": "商品 蓝牙耳机 的价格是多少？"})
        assert resp.status_code == 200
        assert resp.json()["data"]["answer_type"] == "template"
        resp = await client.post("/api/v1/chat", json={"message": "我的订单发货了吗"})
        assert resp.status_code == 200
        assert resp.json()["data"]["answer_type"] == "template"


async def test_kb_question_degrades_to_retrieval_when_llm_down(
    db_available: bool, token_and_user, monkeypatch
):
    """LLM 不可用：知识问答降级为检索原文+来源（degraded），
    且绝不能把降级结果包装成完整 RAG 成功（answer_type != generated）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    class DeadLLM:
        async def generate(self, *args, **kwargs):
            raise LLMError("模型不可用")

    monkeypatch.setattr(kb_answer, "get_llm_client", lambda: DeadLLM())

    async with _client(token_and_user) as client:
        resp = await client.post("/api/v1/chat", json={"message": "退货需要什么条件"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_type"] == "degraded"
    assert data["answer_type"] != "generated"  # 不包装成完整 RAG 成功
    assert data["sources"]  # 带真实检索来源
    assert "检索" in data["answer"]


async def test_embedding_down_degrades_to_keyword_only(
    db_available: bool, token_and_user, monkeypatch
):
    """Embedding 失败：退化为关键词检索并明确标注（不伪造检索结果）。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    class DeadEmbedding:
        async def embed_texts(self, texts):
            raise EmbeddingError("向量服务不可用")

    monkeypatch.setattr(kb_answer, "get_embedding_client", lambda: DeadEmbedding())

    async with _client(token_and_user) as client:
        resp = await client.post("/api/v1/chat", json={"message": "退货需要什么条件"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["answer_type"] == "degraded"
    assert "关键词" in data["answer"]  # 明确标注检索方式
    assert data["sources"]  # 关键词检索的真实来源


async def test_embedding_down_and_no_keyword_hits_returns_502(
    db_available: bool, token_and_user, monkeypatch
):
    """Embedding 失败且关键词也无结果：如实报 502/50001，不伪装成"无依据"。"""
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")

    class DeadEmbedding:
        async def embed_texts(self, texts):
            raise EmbeddingError("向量服务不可用")

    monkeypatch.setattr(kb_answer, "get_embedding_client", lambda: DeadEmbedding())

    # 纯字母乱码：与语料零词元重叠，关键词路也必然无结果
    async with _client(token_and_user) as client:
        resp = await client.post("/api/v1/chat", json={"message": "qzxvnq weriou kjhgf zxcvb"})
    assert resp.status_code == 502
    assert resp.json()["code"] == 50001


async def test_db_down_returns_503_without_leaking_connection_info(
    db_available: bool, token_and_user, monkeypatch
):
    """数据库不可用：返回服务异常（503/50002），不泄露连接串/密码/主机名，
    不伪装成正常查询成功（api_design.md 错误码表：依赖服务不可用）。

    注入方式：会话工厂故障注入（真实 get_db 的封装逻辑捕获 OperationalError
    → DatabaseUnavailableError）。依赖阶段异常必须显式封装为 AppError，
    否则会被框架包装成 ExceptionGroup 逃逸（deps.py 注释有记录）。
    """
    if not db_available:
        pytest.skip("本机 5432 无 PostgreSQL")
    from sqlalchemy.exc import OperationalError

    from app.api import deps

    class DeadSession:
        async def get(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("database connection lost"))

        async def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("database connection lost"))

    class DeadFactory:
        async def __aenter__(self):
            return DeadSession()

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(deps, "SessionFactory", DeadFactory)

    async with _client(token_and_user) as client:
        resp = await client.post("/api/v1/chat", json={"message": "我的订单发货了吗"})

    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == 50002
    # 不泄露敏感连接信息与内部错误详情
    assert "rag_password" not in resp.text
    assert "postgresql" not in resp.text
    assert "connection lost" not in resp.text
