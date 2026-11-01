"""LLM 客户端封装（阶段七）：provider 可配置（mock / openai 兼容协议）。

- 所有模型调用集中在本模块 —— 业务接口不直接写模型调用代码（7.1 要求）；
- 模型名 / Base URL / API Key 全部走环境变量（config.py）；
- **mock**（默认）：确定性模板生成 —— 严格从检索上下文构造回答与引用，
  无上下文即拒答。机制上保证"有依据才答、引用真实存在"，用于离线开发
  与管线测试；**不代表真实 DeepSeek 生成质量**（预算 0 元策略）；
- **openai**：DeepSeek（AsyncOpenAI，SDK 内建重试 + 显式超时）。
  失败抛 LLMError，由调用方降级（返回检索原文+来源）。

接口约定：generate(system_prompt, user_prompt, context_chunks) -> str
- context_chunks 与 user_prompt 中的检索上下文一致（mock 需要结构化数据构造引用；
  真实客户端只使用 prompts，chunks 参数为空列表亦可）。
"""
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.core.errors import LLMError
from app.core.metrics import LLM_DURATION, LLM_ERRORS, observe
from app.core.tracing import trace

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "暂时无法确认您的问题答案，建议联系人工客服获取帮助。"


class MockLLMClient:
    """确定性模板生成（仅管线测试，标注 mock）。"""

    provider = "mock"

    @trace("llm.generate", "llm")
    async def generate(self, system_prompt: str, user_prompt: str, context_chunks: list) -> str:
        async with observe(LLM_DURATION.labels(provider=self.provider)):
            if not context_chunks:
                return REFUSAL_TEXT
            first = context_chunks[0]
            summary = first.content if len(first.content) <= 60 else first.content[:60] + "……"
            citations = "；".join(
                f"[{i}]《{c.document.title}》{c.chunk_meta.get('section', '')}"
                for i, c in enumerate(context_chunks, start=1)
            )
            return f"根据平台规则，{summary}\n\n参考来源：{citations}"


class OpenAICompatibleLLMClient:
    """OpenAI 兼容协议客户端（DeepSeek）：SDK 内建重试，超时显式配置。"""

    provider = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        http_client=None,  # 故障注入测试用：注入带 MockTransport 的 httpx 客户端
    ):
        self.model = model
        # max_retries 是客户端级配置（openai SDK 3.x）：超时/5xx/429 指数退避重试，4xx 不重试
        # SDK 自带退避+抖动；错误分类（4xx 不重试）由 SDK 内部处理
        self.client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2,
            http_client=http_client,
        )

    @trace("llm.generate", "llm")
    async def generate(self, system_prompt: str, user_prompt: str, context_chunks: list) -> str:
        try:
            async with observe(LLM_DURATION.labels(provider=self.provider)):
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                return resp.choices[0].message.content or ""
        except Exception as exc:  # 超时/网络/上游错误统一转为业务错误，由调用方降级
            LLM_ERRORS.labels(provider=self.provider, error_class=exc.__class__.__name__).inc()
            logger.error("llm call failed: %s: %s", exc.__class__.__name__, exc)
            raise LLMError(f"模型调用失败: {exc.__class__.__name__}")


_client = None


def get_llm_client():
    """按配置选择 provider；openai 缺密钥时快速失败（与 embedding 客户端同一策略）。"""
    global _client
    if _client is not None:
        return _client

    if settings.llm_provider == "mock":
        _client = MockLLMClient()
    elif settings.llm_provider == "openai":
        if not settings.llm_api_key:
            raise LLMError("LLM_PROVIDER=openai 但 LLM_API_KEY 为空")
        _client = OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    else:
        raise LLMError(f"未知 LLM_PROVIDER: {settings.llm_provider}")

    logger.info(
        "llm client ready provider=%s model=%s",
        _client.provider,
        settings.llm_model if _client.provider == "openai" else "mock-template",
    )
    return _client
