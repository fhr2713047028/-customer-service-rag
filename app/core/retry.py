"""重试策略（阶段九 9.1.3~9.1.6）：有限重试 + 指数退避 + 随机抖动 + 错误分类。

原则（按 9.1 的错误分类要求）：
- 临时网络错误（超时/连接中断）→ 有限重试；
- 5xx / 429（服务端故障/限流）→ 有限重试，按退避等待，不无限重试；
- 4xx（请求参数错误、权限不足）→ **立即失败，重试没有意义**，
  权限不可能通过重试绕过；
- 副作用操作不自动重试 —— v1 只有查询端点，无副作用操作；
- 重试次数受控：默认最多 2 次重试（共 3 次尝试）。
"""
import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx

DEFAULT_MAX_RETRIES = 2
DEFAULT_BASE_DELAY = 1.0  # 秒

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def is_retryable_exception(exc: Exception) -> bool:
    """错误分类：是否值得重试。"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):  # 连接中断等临时网络错误
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return False


def retry_delay(attempt: int, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    """指数退避 + 随机抖动：base * 2^attempt + uniform(0, base)。

    - 指数部分保证等待下界可测试；
    - 抖动部分避免多个客户端同步重试造成"惊群"。
    """
    return base_delay * (2**attempt) + random.uniform(0, base_delay)


async def retry_call(
    fn: Callable[[], Awaitable],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    on_error: Callable[[Exception, int], None] | None = None,
):
    """执行 fn：可恢复错误按指数退避+抖动重试（最多 max_retries 次）；
    不可恢复错误（4xx 等）立即抛出。"""
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception as exc:
            if attempt >= max_retries or not is_retryable_exception(exc):
                raise
            if on_error is not None:
                on_error(exc, attempt)
            await asyncio.sleep(retry_delay(attempt, base_delay))
            attempt += 1
