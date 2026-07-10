from datetime import date

from screener.brokers.base import BrokerClient
from screener.utils.logger import logger

# 브로커 API 조회가 실패할 경우를 대비한 최소 폴백(공휴일만, 임시휴장은 반영 안 됨).
# 매년 초 갱신 필요.
KNOWN_HOLIDAYS_FALLBACK = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02", "2026-05-05", "2026-05-24",
    "2026-05-25", "2026-06-06", "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03",
    "2026-10-09", "2026-12-25",
}


def is_trading_day(target: date, broker: BrokerClient) -> bool:
    if target.weekday() >= 5:
        return False
    try:
        return not broker.is_market_holiday(target)
    except Exception as exc:
        logger.warning(f"휴장일 API 조회 실패, 폴백 캘린더 사용: {exc}")
        return target.isoformat() not in KNOWN_HOLIDAYS_FALLBACK
