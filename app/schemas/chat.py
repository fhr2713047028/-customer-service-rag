"""对话请求/响应模型（api_design.md 4.2）。"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500, description="用户问题")
    conversation_id: str | None = Field(None, description="v1 单轮对话，字段预留")
    stream: bool = Field(False, description="v1 只做非流式")


class SourceOut(BaseModel):
    type: str  # order | product | kb
    doc_title: str | None = None
    chunk_id: int | None = None
    section: str | None = None
    score: float | None = None
    order_no: str | None = None


class ChatOut(BaseModel):
    answer: str
    # template（结构化模板）| generated（LLM 生成）| fallback（拒答/转人工）
    # | degraded（LLM 失败降级）| clarify（模糊问题澄清）
    answer_type: str
    # 处理路径（阶段八）：order_query | logistics_query | product_query
    #                    | kb_retrieval | combined | clarify
    route: str
    intents: list[str]
    sources: list[SourceOut]
    confidence: str  # high | low
