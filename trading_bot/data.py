"""과거 OHLCV 데이터 로딩 유틸리티."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

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


def _cache_path(cache_dir: str, symbol: str) -> Path:
    # 일부 종목코드는 "BRK/B" 처럼 경로 구분자로 오인될 문자를 포함하므로 파일명에 안전하게 치환한다.
    safe_symbol = symbol.replace("/", "-").replace("\\", "-")
    return Path(cache_dir) / f"{safe_symbol}.csv"


def update_history_cache(client: KISClient, symbol: str, exchange: str, cache_dir: str,
                          full_lookback_days: int = 500, max_rows: int = 800) -> pd.DataFrame:
    """종목별 로컬 캐시를 증분 갱신한다.

    수백~수천 종목을 매일 스캔할 때 KIS의 초당 호출 제한 때문에 매번 전체 과거 데이터를
    다시 받으면 시간이 너무 오래 걸린다. 캐시가 있으면 마지막 저장일 이후 데이터만
    1회 호출로 받아오고, 캐시가 없으면(최초 실행) 전체 lookback을 페이지네이션으로 받는다.
    """
    path = _cache_path(cache_dir, symbol)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    if path.exists():
        cached = pd.read_csv(path, dtype={"date": str})
        if not cached.empty:
            new_rows = client.get_daily_price(symbol, exchange=exchange, count=30)
            if new_rows:
                new_df = pd.DataFrame(new_rows).rename(columns=_COLUMN_MAP)
                keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in new_df.columns]
                new_df = new_df[keep]
                for col in ["open", "high", "low", "close", "volume"]:
                    if col in new_df.columns:
                        new_df[col] = pd.to_numeric(new_df[col], errors="coerce")
                new_df["date"] = pd.to_datetime(new_df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
                combined = pd.concat([cached, new_df], ignore_index=True)
            else:
                combined = cached
            combined = combined.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
            if len(combined) > max_rows:
                combined = combined.iloc[-max_rows:].reset_index(drop=True)
            combined.to_csv(path, index=False)
            return combined

    combined = fetch_kis_daily_history(client, symbol, exchange, lookback_days=full_lookback_days)
    if not combined.empty:
        combined.to_csv(path, index=False)
    return combined
