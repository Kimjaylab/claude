"""Step 2B of the spec: liquidity-sweep + RSI-divergence reversal entries
for TRENDING regimes, evaluated on the 15m timeframe.

Long: price sweeps below the prior swing low then closes back above it,
      with a bullish RSI divergence -> market long.
Short: price sweeps above the prior swing high, closes back below it with
       an upper-wick bearish candle, open interest is dropping, and RSI
       prints a bearish divergence -> market short.

Stop-loss is mechanically placed at the swept extreme (the wick that
triggered the setup); take-profit is exactly risk_reward_ratio * SL
distance away, per the spec's fixed R:R rule.
"""
from dataclasses import dataclass

import config
import indicators


@dataclass
class TrendSignal:
    symbol: str
    side: str  # "long" | "short"
    entry_price: float
    stop_price: float
    take_profit_price: float


def evaluate(client, risk_manager, symbol: str) -> TrendSignal | None:
    df_15m = client.fetch_ohlcv_df(symbol, config.TREND_SIGNAL_TIMEFRAME, limit=config.SWING_LOOKBACK_BARS + 30)
    if len(df_15m) < config.SWING_LOOKBACK_BARS + 5:
        return None

    last = df_15m.iloc[-1]
    entry_price = float(last["close"])

    if indicators.detect_bullish_sweep_and_divergence(df_15m, config.SWING_LOOKBACK_BARS):
        stop_price = float(last["low"])
        tp_price = risk_manager.take_profit_price(entry_price, stop_price, "long")
        return TrendSignal(symbol, "long", entry_price, stop_price, tp_price)

    oi_series = client.fetch_open_interest_history(
        symbol, timeframe="5m", limit=config.OI_DROP_LOOKBACK_BARS + 1
    )
    if indicators.detect_bearish_sweep_and_divergence(df_15m, oi_series, config.SWING_LOOKBACK_BARS):
        stop_price = float(last["high"])
        tp_price = risk_manager.take_profit_price(entry_price, stop_price, "short")
        return TrendSignal(symbol, "short", entry_price, stop_price, tp_price)

    return None


def execute(client, risk_manager, equity: float, signal: TrendSignal):
    qty = risk_manager.position_size(equity, signal.entry_price, signal.stop_price)
    if qty <= 0:
        return None

    client.set_leverage_and_margin(signal.symbol, risk_manager.leverage, risk_manager.margin_mode)

    entry_side = "buy" if signal.side == "long" else "sell"
    exit_side = "sell" if signal.side == "long" else "buy"

    client.market_order(signal.symbol, entry_side, qty)
    client.stop_market_order(signal.symbol, exit_side, qty, signal.stop_price)
    client.take_profit_market_order(signal.symbol, exit_side, qty, signal.take_profit_price)
    return qty
