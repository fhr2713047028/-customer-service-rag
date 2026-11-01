"""对话 API（核心 RAG 入口，api_design.md 4.2）。

- 需认证（订单类问题必须知道"你是谁"）；
- 单轮问答，conversation_id 预留；
- 每次请求写入 query_logs（请求日志/查询记录，database_design 3.8）。
"""
import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.metrics import RAG_DURATION
from app.models.query_log import QueryLog
from app.models.user import User
from app.schemas.chat import ChatOut, ChatRequest
from app.schemas.common import ApiResponse
from app.services import chat_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ApiResponse[ChatOut])
async def chat(
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = time.perf_counter()
    result = await chat_service.handle_chat(db, user, body.message)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    # RAG 请求总耗时指标（按处理路径与回答类型，阶段十指标清单）
    RAG_DURATION.labels(
        route=result.get("route", "unknown"), answer_type=result.get("answer_type", "unknown")
    ).observe((time.perf_counter() - start))

    # 请求日志：每次问答记录（database_design 3.8 query_logs 的用途）
    db.add(
        QueryLog(
            user_id=user.id,
            endpoint="/api/v1/chat",
            message=body.message[:500],
            intents=result["intents"],
            answer_type=result["answer_type"],
            latency_ms=latency_ms,
            http_status=200,
            request_id=getattr(request.state, "request_id", None),
        )
    )
    await db.commit()

    return ApiResponse(data=ChatOut(**result))
