from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from screener.brokers.base import BrokerClient
from screener.utils.logger import logger


class OHLCVStore:
    """종목별 일봉 캐시. 매일 신규 거래일분만 증분 조회해 API 호출을 최소화한다."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, code: str) -> Path:
        return self.cache_dir / f"{code}.parquet"

    def load(self, code: str) -> pd.DataFrame:
        path = self._path(code)
        if path.exists():
            return pd.read_parquet(path)
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    def update(self, broker: BrokerClient, code: str, lookback_days: int = 400) -> pd.DataFrame:
        existing = self.load(code)
        end = date.today()
        if existing.empty:
            start = end - timedelta(days=lookback_days)
        else:
            last_date = pd.to_datetime(existing["date"].max()).date()
            start = last_date + timedelta(days=1)
            if start > end:
                return existing

        candles = broker.get_daily_candles(code, start, end)
        if not candles:
            return existing

        new_rows = pd.DataFrame(
            [
                {
                    "date": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                }
                for c in candles
            ]
        )
        merged = (
            pd.concat([existing, new_rows], ignore_index=True)
            .drop_duplicates(subset="date")
            .sort_values("date")
            .reset_index(drop=True)
        )
        merged.to_parquet(self._path(code), index=False)
        return merged

    def bulk_update(self, broker: BrokerClient, codes: list[str], lookback_days: int = 400) -> dict[str, pd.DataFrame]:
        result = {}
        for code in codes:
            try:
                result[code] = self.update(broker, code, lookback_days)
            except Exception as exc:
                logger.warning(f"{code} 일봉 갱신 실패: {exc}")
        return result
