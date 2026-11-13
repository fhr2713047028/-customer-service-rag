"""查询改写（阶段十五）：检索前把口语化问题改写成检索友好查询。

- 改写结果只用于检索（embedding/关键词），**给模型生成的仍是用户原始问题**
  （改写不该改变用户意图，只优化召回）；
- 改写失败/输出为空 → 原样返回（软降级，绝不因改写失败而挂掉检索）。
"""
import logging

from app.llm.client import get_llm_client

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """你是检索查询改写模块。把用户口语化的问题改写为适合知识库检索的查询：
- 补充规范词与同义表达（如"买完不想要了能退吗" → "退货申请条件 七天无理由退货"）；
- 保留关键实体（型号、编号、专有名词）不丢失；
- 只输出改写后的查询文本，不要解释、不要引号、不要换行。"""


async def rewrite_query(question: str) -> str:
    """改写查询；任何失败返回原问题。"""
    try:
        client = get_llm_client()
        answer = await client.generate(REWRITE_SYSTEM_PROMPT, f"【用户问题】\n{question}", [])
        rewritten = answer.strip().strip('"“”').strip()
        return rewritten if rewritten else question
    except Exception:
        logger.exception("query rewrite failed, use original question")
        return question
