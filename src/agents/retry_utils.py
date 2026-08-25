import asyncio
import logging
from typing import Any, Callable, Optional, Set, Tuple, Type

logger = logging.getLogger("compliance_workflow")

# Common transient network and API errors
TRANSIENT_ERROR_NAMES: Set[str] = {
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ServiceUnavailableError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "NetworkError",
    "RemoteDisconnected",
    "TimeoutError",
    "ConnectionResetError",
    "ConnectionRefusedError",
}

NON_RETRYABLE_ERROR_NAMES: Set[str] = {
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "BadRequestError",
    "ValidationError",
    "TypeError",
    "KeyError",
    "AttributeError",
}


def is_transient_error(exc: BaseException) -> bool:
    """
    Determines if an exception is likely transient (e.g. rate limit, connection drop, 5xx).
    """
    exc_type_name = type(exc).__name__

    if exc_type_name in NON_RETRYABLE_ERROR_NAMES:
        return False

    if exc_type_name in TRANSIENT_ERROR_NAMES:
        return True

    # Check for HTTP status codes if present on exception
    status_code = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status_code is not None:
        if status_code in (429, 500, 502, 503, 504):
            return True
        if status_code in (400, 401, 403, 404, 422):
            return False

    # Check exception messages for network / rate limit cues
    msg = str(exc).lower()
    transient_indicators = [
        "rate limit",
        "too many requests",
        "timeout",
        "connection reset",
        "connection closed",
        "service unavailable",
        "gateway timeout",
        "temporary failure",
        "503",
        "502",
        "504",
        "429",
    ]
    if any(ind in msg for ind in transient_indicators):
        return True

    return False


async def execute_with_retry(
    async_fn: Callable[..., Any],
    *args: Any,
    max_retries: Optional[int] = None,
    backoff_factor: Optional[float] = None,
    initial_delay: float = 0.5,
    **kwargs: Any
) -> Any:
    """
    Executes an async function with exponential backoff for transient errors.
    Non-transient errors (such as bad inputs, validation errors) are raised immediately.
    """
    from src.config import config

    retries_limit = max_retries if max_retries is not None else getattr(config, "max_retries", 3)
    backoff = backoff_factor if backoff_factor is not None else getattr(config, "retry_backoff_factor", 1.5)

    attempt = 0
    last_error: Optional[BaseException] = None

    while attempt <= retries_limit:
        try:
            return await async_fn(*args, **kwargs)
        except Exception as exc:
            attempt += 1
            last_error = exc

            if not is_transient_error(exc):
                logger.warning(f"[RETRY] Non-retryable exception '{type(exc).__name__}': {exc}. Raising immediately.")
                raise exc

            if attempt > retries_limit:
                logger.error(
                    f"[RETRY] All {retries_limit} retries failed for {getattr(async_fn, '__name__', 'operation')}. "
                    f"Last error ({type(exc).__name__}): {exc}"
                )
                raise exc

            delay = initial_delay * (backoff ** (attempt - 1))
            logger.warning(
                f"[RETRY] Transient failure ({type(exc).__name__}: {exc}) on attempt {attempt}/{retries_limit}. "
                f"Retrying in {delay:.2f}s..."
            )
            await asyncio.sleep(delay)

    if last_error:
        raise last_error
