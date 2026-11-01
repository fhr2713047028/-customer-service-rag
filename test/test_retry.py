"""重试策略单测（core/retry.py，阶段九 9.1.3~9.1.6）。"""
import httpx
import pytest

from app.core.retry import (
    is_retryable_exception,
    retry_call,
    retry_delay,
)


def _status_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://test")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_error_classification():
    assert is_retryable_exception(httpx.ConnectTimeout("超时")) is True
    assert is_retryable_exception(httpx.ConnectError("连接中断")) is True
    assert is_retryable_exception(_status_error(500)) is True
    assert is_retryable_exception(_status_error(429)) is True
    # 4xx：参数错误/权限不足，重试没有意义，权限不可能通过重试绕过
    assert is_retryable_exception(_status_error(400)) is False
    assert is_retryable_exception(_status_error(401)) is False
    assert is_retryable_exception(_status_error(403)) is False
    assert is_retryable_exception(ValueError("业务错误")) is False


def test_retry_delay_bounds():
    """指数退避 + 抖动：等待时间在 [base*2^attempt, base*2^attempt + base] 内。"""
    for attempt, lo in ((0, 1.0), (1, 2.0), (2, 4.0)):
        d = retry_delay(attempt, base_delay=1.0)
        assert lo <= d <= lo + 1.0


async def test_retry_call_retries_then_succeeds():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectTimeout("临时网络错误")
        return "ok"

    result = await retry_call(flaky, max_retries=2, base_delay=0.01)
    assert result == "ok"
    assert len(calls) == 3  # 首次 + 2 次重试


async def test_retry_call_no_retry_on_4xx():
    calls = []

    async def bad_request():
        calls.append(1)
        raise httpx.HTTPStatusError(
            "bad", request=httpx.Request("GET", "http://test"),
            response=httpx.Response(400, request=httpx.Request("GET", "http://test")),
        )

    with pytest.raises(httpx.HTTPStatusError):
        await retry_call(bad_request, max_retries=2, base_delay=0.01)
    assert len(calls) == 1  # 4xx 立即失败，不重试


async def test_retry_call_gives_up_after_max_retries():
    calls = []

    async def always_down():
        calls.append(1)
        raise httpx.ConnectTimeout("持续不可用")

    with pytest.raises(httpx.ConnectTimeout):
        await retry_call(always_down, max_retries=2, base_delay=0.01)
    assert len(calls) == 3  # 受控：最多 3 次尝试


async def test_retry_call_backoff_lower_bound():
    """退避等待有下界（指数部分），防止"打桩式"重试。"""
    import time

    calls = []

    async def flaky():
        calls.append(time.perf_counter())
        raise httpx.ConnectTimeout("x")

    with pytest.raises(httpx.ConnectTimeout):
        await retry_call(flaky, max_retries=2, base_delay=0.05)
    # 间隔应 ≥ 0.05s（第 1 次重试）与 ≥ 0.10s（第 2 次重试）
    assert calls[1] - calls[0] >= 0.05 - 1e-9
    assert calls[2] - calls[1] >= 0.10 - 1e-9
