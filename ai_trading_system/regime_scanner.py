"""Step 1 of the spec: classify each of the top-N symbols as RANGING or
TRENDING using ADX + Bollinger Band width on the 1h and 4h timeframes.

RANGING: ADX < 25 on either timeframe, OR Bollinger Bands are squeezed
         (bandwidth below config.BB_SQUEEZE_WIDTH_PCT).
TRENDING: ADX >= 25 on both timeframes AND bands are expanding (not
          squeezed) with above-average volume on the breakout bar.
Anything that is neither cleanly ranging nor cleanly trending is skipped
for this cycle rather than forced into a strategy.
"""
from dataclasses import dataclass

import config
import indicators
from exchange_client import ExchangeClient


@dataclass
class RegimeReading:
    symbol: str
    regime: str  # "ranging" | "trending" | "unclear"
    adx_1h: float
    adx_4h: float
    bb_width_1h: float
    volume_ratio: float


def _volume_ratio(df, lookback: int = 20) -> float:
    avg_vol = df["volume"].iloc[-(lookback + 1):-1].mean()
    if not avg_vol:
        return 1.0
    return float(df["volume"].iloc[-1] / avg_vol)


def classify_regime(client: ExchangeClient, symbol: str) -> RegimeReading | None:
    try:
        df_1h = client.fetch_ohlcv_df(symbol, "1h", limit=100)
        df_4h = client.fetch_ohlcv_df(symbol, "4h", limit=100)
    except Exception:
        return None

    if len(df_1h) < config.ADX_PERIOD * 2 or len(df_4h) < config.ADX_PERIOD * 2:
        return None

    adx_1h = indicators.adx(df_1h, config.ADX_PERIOD).iloc[-1]
    adx_4h = indicators.adx(df_4h, config.ADX_PERIOD).iloc[-1]
    _, _, _, bb_width_1h = indicators.bollinger_bands(df_1h, config.BB_PERIOD, config.BB_STD_DEV)
    bb_width_1h_last = bb_width_1h.iloc[-1]
    vol_ratio = _volume_ratio(df_1h)

    is_ranging = (
        adx_1h < config.ADX_TRENDING_THRESHOLD
        or bb_width_1h_last < config.BB_SQUEEZE_WIDTH_PCT
    )
    is_trending = (
        adx_1h >= config.ADX_TRENDING_THRESHOLD
        and adx_4h >= config.ADX_TRENDING_THRESHOLD
        and bb_width_1h_last >= config.BB_SQUEEZE_WIDTH_PCT
        and vol_ratio >= 1.2
    )

    if is_trending:
        regime = "trending"
    elif is_ranging:
        regime = "ranging"
    else:
        regime = "unclear"

    return RegimeReading(
        symbol=symbol,
        regime=regime,
        adx_1h=float(adx_1h),
        adx_4h=float(adx_4h),
        bb_width_1h=float(bb_width_1h_last),
        volume_ratio=vol_ratio,
    )


def scan_market(client: ExchangeClient, top_n: int = config.TOP_N_SYMBOLS) -> list[RegimeReading]:
    symbols = client.fetch_top_symbols(top_n)
    readings = []
    for symbol in symbols:
        reading = classify_regime(client, symbol)
        if reading is not None:
            readings.append(reading)
    return readings
