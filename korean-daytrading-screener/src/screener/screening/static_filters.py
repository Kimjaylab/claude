import pandas as pd

from screener.screening.models import TechnicalSnapshot
from screener.utils.logger import logger

MINUTES_PER_TRADING_DAY = 390  # 09:00~15:30
FIVE_MIN_SLICES = MINUTES_PER_TRADING_DAY / 5


def _rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and pd.notna(rsi.iloc[-1]) else 50.0


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    last_close = close.iloc[-1]
    return float(atr / last_close * 100) if last_close else 0.0


def compute_technical_snapshot(
    code: str, name: str, market: str, df: pd.DataFrame, min_listed_days: int = 20
) -> TechnicalSnapshot | None:
    if len(df) < max(60, min_listed_days):
        return None  # 상장 초기 등, 이평선 신뢰 불가

    df = df.sort_values("date").reset_index(drop=True)
    closes = df["close"]

    ma5 = closes.rolling(5).mean().iloc[-1]
    ma20 = closes.rolling(20).mean().iloc[-1]
    ma60 = closes.rolling(60).mean().iloc[-1]
    recent_high_20d = df["high"].iloc[-21:-1].max()  # 오늘을 제외한 직전 20일 고점
    three_day_return_pct = (closes.iloc[-1] / closes.iloc[-4] - 1) * 100 if len(df) > 4 else 0.0

    # 분봉 히스토리는 별도 저장 없이는 확보가 어려워, 일평균 거래량을 5분 단위로
    # 균등 배분한 값을 "평상시 5분 거래량" 기준선으로 근사한다.
    avg_daily_volume_20d = df["volume"].iloc[-20:].mean()
    avg_5min_volume_20d = avg_daily_volume_20d / FIVE_MIN_SLICES

    return TechnicalSnapshot(
        code=code,
        name=name,
        market=market,
        prev_close=float(closes.iloc[-1]),
        ma5=float(ma5),
        ma20=float(ma20),
        ma60=float(ma60),
        recent_high_20d=float(recent_high_20d),
        rsi14=_rsi(closes),
        atr_pct=_atr_pct(df),
        three_day_return_pct=float(three_day_return_pct),
        avg_5min_volume_20d=float(avg_5min_volume_20d),
    )


def passes_static_prefilter(snap: TechnicalSnapshot) -> bool:
    """다음 단계(동적 스캔) 대상으로 남길지 결정하는 넓은 1차 컷.

    최종 점수 계산은 scoring.py에서 하며, 여기서는 후보군을 좁히는 역할만 한다.
    """
    trend_ok = snap.prev_close > snap.ma20
    near_breakout = snap.prev_close >= snap.recent_high_20d * 0.97  # 전고점 3% 이내 접근 또는 돌파
    return trend_ok and near_breakout


def build_static_candidates(
    ohlcv_by_code: dict[str, pd.DataFrame], names: dict[str, str], market: str, min_listed_days: int = 20
) -> list[TechnicalSnapshot]:
    snapshots = []
    for code, df in ohlcv_by_code.items():
        snap = compute_technical_snapshot(code, names.get(code, code), market, df, min_listed_days)
        if snap and passes_static_prefilter(snap):
            snapshots.append(snap)
    logger.info(f"[{market}] 정적 필터 통과: {len(snapshots)}종목")
    return snapshots
