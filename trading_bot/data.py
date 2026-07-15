"""과거 OHLCV 데이터 로딩 유틸리티."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from .kis_client import KISClient

logger = logging.getLogger(__name__)

_COLUMN_MAP = {
    # KIS dailyprice(HHDFS76240000) 응답 필드명 -> 표준 컬럼명
    # 실제 응답 필드명은 반드시 apiportal.koreainvestment.com 문서로 재확인할 것.
    "xymd": "date",
    "clos": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "tvol": "volume",
}


def load_csv(path: str) -> pd.DataFrame:
    """columns: date, open, high, low, close, volume (date 오름차순)."""
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def fetch_kis_daily_history(client: KISClient, symbol: str, exchange: str,
                             lookback_days: int = 500) -> pd.DataFrame:
    """KIS 기간별시세 API를 여러 번 호출해 lookback_days 만큼의 일봉 데이터를 수집.

    한 번 호출당 최대 약 100건까지만 반환되므로 BYMD 커서를 뒤로 이동시키며 반복 조회한다.
    """
    all_rows: list[dict] = []
    base_date = ""
    remaining = lookback_days

    while remaining > 0:
        rows = client.get_daily_price(symbol, exchange=exchange, count=100, base_date=base_date)
        if not rows:
            break
        all_rows.extend(rows)
        remaining -= len(rows)
        if len(rows) < 100:
            break
        oldest = rows[-1]
        try:
            oldest_date = datetime.strptime(oldest.get("xymd", ""), "%Y%m%d")
        except ValueError:
            break
        base_date = (oldest_date - timedelta(days=1)).strftime("%Y%m%d")

    if not all_rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows)
    df = df.rename(columns=_COLUMN_MAP)
    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df
