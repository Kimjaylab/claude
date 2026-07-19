"""Technical indicators and pattern detectors used by both strategies.

All functions take/return pandas objects indexed the same way as the input
OHLCV DataFrame (columns: open, high, low, close, volume) so they can be
assigned straight back onto it.
"""
import numpy as np
import pandas as pd


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (used by ADX/RSI/ATR)."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def average_true_range(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return wilder_smooth(tr, period)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder's original formulation)."""
    high, low = df["high"], df["low"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    atr = average_true_range(df, period)
    plus_di = 100 * wilder_smooth(plus_dm, period) / atr
    minus_di = 100 * wilder_smooth(minus_dm, period) / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return wilder_smooth(dx, period)


def bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0):
    """Returns (mid, upper, lower, bandwidth_pct)."""
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=0)
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    bandwidth_pct = (upper - lower) / mid * 100
    return mid, upper, lower, bandwidth_pct


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def swing_low(df: pd.DataFrame, lookback: int, exclude_last: int = 1) -> float:
    """Lowest low over the lookback window, excluding the most recent bar(s)."""
    window = df["low"].iloc[-(lookback + exclude_last):-exclude_last]
    return float(window.min())


def swing_high(df: pd.DataFrame, lookback: int, exclude_last: int = 1) -> float:
    window = df["high"].iloc[-(lookback + exclude_last):-exclude_last]
    return float(window.max())


def detect_bullish_sweep_and_divergence(df: pd.DataFrame, lookback: int = 20) -> bool:
    """Long setup: price sweeps below the prior swing low then the 15m candle
    closes back above it, while RSI prints a higher low than at the prior low
    (bullish divergence). Evaluated on the most recently *closed* bar.
    """
    if len(df) < lookback + 3:
        return False

    prior_low_level = swing_low(df, lookback, exclude_last=1)
    last = df.iloc[-1]

    swept_below = last["low"] < prior_low_level
    closed_back_above = last["close"] > prior_low_level
    if not (swept_below and closed_back_above):
        return False

    rsi_series = rsi(df, 14)
    prior_low_idx = df["low"].iloc[-(lookback + 1):-1].idxmin()
    prior_low_rsi = rsi_series.loc[prior_low_idx]
    current_rsi = rsi_series.iloc[-1]

    # Price made a lower low (last["low"] < prior_low_level) but RSI made a
    # higher low -> classic bullish divergence.
    return bool(current_rsi > prior_low_rsi)


def detect_bearish_sweep_and_divergence(
    df: pd.DataFrame, oi_series: pd.Series | None = None, lookback: int = 20
) -> bool:
    """Short setup: price sweeps above the prior swing high but closes back
    below it with an upper-wick bearish candle, RSI prints a lower high
    (bearish divergence), and open interest is falling (longs trapped).
    """
    if len(df) < lookback + 3:
        return False

    prior_high_level = swing_high(df, lookback, exclude_last=1)
    last = df.iloc[-1]

    swept_above = last["high"] > prior_high_level
    closed_back_below = last["close"] < prior_high_level
    is_bearish_candle = last["close"] < last["open"]
    upper_wick = last["high"] - max(last["close"], last["open"])
    body = abs(last["close"] - last["open"])
    has_upper_wick = upper_wick > body

    if not (swept_above and closed_back_below and is_bearish_candle and has_upper_wick):
        return False

    rsi_series = rsi(df, 14)
    prior_high_idx = df["high"].iloc[-(lookback + 1):-1].idxmax()
    prior_high_rsi = rsi_series.loc[prior_high_idx]
    current_rsi = rsi_series.iloc[-1]
    bearish_divergence = current_rsi < prior_high_rsi
    if not bearish_divergence:
        return False

    if oi_series is not None and len(oi_series) >= 2:
        recent_oi = oi_series.iloc[-4:] if len(oi_series) >= 4 else oi_series
        oi_change_pct = (recent_oi.iloc[-1] - recent_oi.iloc[0]) / recent_oi.iloc[0] * 100
        if oi_change_pct > -3.0:
            # OI isn't actually declining -> spec requires OI 급감(sharp drop)
            return False

    return True
