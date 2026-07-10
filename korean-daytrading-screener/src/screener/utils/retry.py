from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from screener.utils.logger import logger


def with_retry(exceptions: tuple[type[Exception], ...] = (Exception,), attempts: int = 3):
    """네트워크/API 호출용 재시도 데코레이터. 2s, 4s, 8s 간격으로 최대 attempts회 재시도."""

    return retry(
        retry=retry_if_exception_type(exceptions),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        before_sleep=lambda state: logger.warning(
            f"재시도 {state.attempt_number}/{attempts}: {state.outcome.exception()}"
        ),
        reraise=True,
    )
