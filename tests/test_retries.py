import asyncio
import pytest
from src.agents.retry_utils import execute_with_retry, is_transient_error


class MockRateLimitError(Exception):
    pass


class MockAuthError(Exception):
    pass


def test_is_transient_error():
    assert is_transient_error(MockRateLimitError("Rate limit exceeded")) is True
    assert is_transient_error(TimeoutError("Connection timed out")) is True
    assert is_transient_error(ConnectionResetError("Connection reset by peer")) is True
    assert is_transient_error(ValueError("Bad parameter value")) is False
    assert is_transient_error(KeyError("missing_key")) is False
    assert is_transient_error(TypeError("unsupported operand")) is False


def test_retry_transient_success_on_second_attempt():
    attempts = 0

    async def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MockRateLimitError("Rate limit exceeded 429")
        return "SUCCESS_RESULT"

    async def _run():
        result = await execute_with_retry(
            flaky_operation,
            max_retries=3,
            initial_delay=0.01,
            backoff_factor=1.0
        )
        assert result == "SUCCESS_RESULT"
        assert attempts == 2

    asyncio.run(_run())


def test_retry_all_retries_fail():
    attempts = 0

    async def failing_operation():
        nonlocal attempts
        attempts += 1
        raise TimeoutError("Network timeout")

    async def _run():
        nonlocal attempts
        with pytest.raises(TimeoutError) as exc_info:
            await execute_with_retry(
                failing_operation,
                max_retries=3,
                initial_delay=0.01,
                backoff_factor=1.0
            )
        # Initial try (attempt 1) + 3 retries (attempts 2, 3, 4) = 4 calls
        assert attempts == 4
        assert "Network timeout" in str(exc_info.value)

    asyncio.run(_run())


def test_non_transient_error_aborts_immediately():
    attempts = 0

    async def permanent_error_operation():
        nonlocal attempts
        attempts += 1
        raise ValueError("Invalid schema formatting")

    async def _run():
        nonlocal attempts
        with pytest.raises(ValueError) as exc_info:
            await execute_with_retry(
                permanent_error_operation,
                max_retries=3,
                initial_delay=0.01,
                backoff_factor=1.0
            )
        # Must fail immediately on attempt 1 without retries
        assert attempts == 1
        assert "Invalid schema formatting" in str(exc_info.value)

    asyncio.run(_run())
