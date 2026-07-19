"""Historical simulation of both strategies, with the same risk-management
rules as live trading. Uses only Binance's public market-data endpoints --
no API key required -- so this is safe to run before ever touching a real
or testnet account.

Both strategies are driven through DryRunBroker (see exchange_client.py)
so fills, position netting, and realized P&L use the exact same matching
logic as dry-run live trading. The only difference is that here we feed it
historical OHLCV bar-by-bar instead of polling the live market.

Limitation: Binance's open-interest history endpoint only retains ~30 days,
so the short-side OI-decline confirmation is skipped for older bars; the
backtest note this in its summary rather than silently pretending it was
checked.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import ccxt
import pandas as pd

import config
import indicators
from exchange_client import DryRunBroker
from risk_manager import RiskManager
from strategies.grid_strategy import compute_box


def fetch_history(exchange: ccxt.Exchange, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
    ms_per_bar = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
    all_rows = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1][0]
        next_since = last_ts + ms_per_bar
        if next_since <= since or len(batch) < 1000:
            since = next_since
            if len(batch) < 1000:
                break
        else:
            since = next_since
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def _regime_at(df_1h: pd.DataFrame, ts) -> str:
    hist = df_1h[df_1h.index <= ts]
    if len(hist) < config.ADX_PERIOD * 2:
        return "unclear"
    adx_val = indicators.adx(hist, config.ADX_PERIOD).iloc[-1]
    _, _, _, bb_width = indicators.bollinger_bands(hist, config.BB_PERIOD, config.BB_STD_DEV)
    bb_width_last = bb_width.iloc[-1]
    if pd.isna(adx_val) or pd.isna(bb_width_last):
        return "unclear"
    if adx_val < config.ADX_TRENDING_THRESHOLD or bb_width_last < config.BB_SQUEEZE_WIDTH_PCT:
        return "ranging"
    if adx_val >= config.ADX_TRENDING_THRESHOLD and bb_width_last >= config.BB_SQUEEZE_WIDTH_PCT:
        return "trending"
    return "unclear"


@dataclass
class GridBacktestState:
    box_high: float
    box_low: float
    levels: list[float]
    order_amount: float
    active: bool = True


@dataclass
class BacktestResult:
    symbol: str
    equity_curve: list[tuple]
    trades: list[dict]
    starting_equity: float
    ending_equity: float

    @property
    def total_return_pct(self) -> float:
        return (self.ending_equity - self.starting_equity) / self.starting_equity * 100

    @property
    def max_drawdown_pct(self) -> float:
        peak = self.starting_equity
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100)
        return max_dd

    @property
    def win_rate_pct(self) -> float:
        closed = [t for t in self.trades if t["pnl"] is not None]
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t["pnl"] > 0)
        return wins / len(closed) * 100


def _rebalance_grid(broker: DryRunBroker, symbol: str, state: GridBacktestState, last_price: float, order_amount: float):
    open_prices = {round(o["price"], 8) for o in broker.open_orders.get(symbol, [])}
    for level in state.levels:
        if round(level, 8) in open_prices:
            continue
        if level < last_price:
            broker.create_order(symbol, "limit", "buy", order_amount, level)
        elif level > last_price:
            broker.create_order(symbol, "limit", "sell", order_amount, level)


def run_backtest(symbol: str, days: int = 60, starting_equity: float = 10_000.0) -> BacktestResult:
    exchange = ccxt.binanceusdm({"enableRateLimit": True})
    df_15m = fetch_history(exchange, symbol, config.TREND_SIGNAL_TIMEFRAME, days)
    df_1h = fetch_history(exchange, symbol, "1h", days)
    return simulate(symbol, df_15m, df_1h, starting_equity)


def simulate(symbol: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame, starting_equity: float = 10_000.0) -> BacktestResult:
    """Pure bar-driven simulation loop, independent of where the OHLCV data
    came from. Split out from run_backtest so it can be exercised with
    synthetic data (e.g. in tests) without a network call.
    """
    broker = DryRunBroker(balance_usdt=starting_equity)
    risk_manager = RiskManager()
    risk_manager.start_new_day(starting_equity, df_15m.index[0])

    grid_state: GridBacktestState | None = None
    trend_stop_tp: dict | None = None  # {"entry": .., "side": ..}
    equity_curve = []
    trades = []
    warmup = config.SWING_LOOKBACK_BARS + 30

    for i in range(warmup, len(df_15m)):
        bar = df_15m.iloc[i]
        ts = df_15m.index[i]
        window_15m = df_15m.iloc[: i + 1]
        mark_prices = {symbol: float(bar["close"])}
        equity = broker.equity(mark_prices)

        if risk_manager.check_daily_loss_limit(equity, ts):
            for sym, pos in list(broker.positions.items()):
                close_side = "sell" if pos.side == "long" else "buy"
                broker.create_order(sym, "market", close_side, pos.amount, float(bar["close"]))
            broker.cancel_all(symbol)
            grid_state = None
            trend_stop_tp = None
            equity_curve.append((ts, broker.equity(mark_prices)))
            continue

        if risk_manager.is_locked(ts):
            equity_curve.append((ts, equity))
            continue

        regime = _regime_at(df_1h, ts)
        has_position = symbol in broker.positions
        has_open_orders = bool(broker.open_orders.get(symbol))

        # --- trend strategy: only enter when completely flat ---
        if regime == "trending" and not has_position and not has_open_orders and grid_state is None:
            entry_price = float(bar["close"])
            signal_side = None
            stop_price = None
            if indicators.detect_bullish_sweep_and_divergence(window_15m, config.SWING_LOOKBACK_BARS):
                signal_side, stop_price = "long", float(bar["low"])
            elif indicators.detect_bearish_sweep_and_divergence(window_15m, None, config.SWING_LOOKBACK_BARS):
                signal_side, stop_price = "short", float(bar["high"])

            if signal_side:
                tp_price = risk_manager.take_profit_price(entry_price, stop_price, signal_side)
                qty = risk_manager.position_size(equity, entry_price, stop_price)
                if qty > 0:
                    entry_side = "buy" if signal_side == "long" else "sell"
                    exit_side = "sell" if signal_side == "long" else "buy"
                    broker.create_order(symbol, "market", entry_side, qty, entry_price)
                    broker.create_order(symbol, "stop_market", exit_side, qty, None, {"stopPrice": stop_price})
                    broker.create_order(symbol, "take_profit_market", exit_side, qty, None, {"stopPrice": tp_price})
                    trend_stop_tp = {"entry": entry_price, "side": signal_side}
                    trades.append({"ts": ts, "symbol": symbol, "type": "trend_entry", "side": signal_side, "price": entry_price, "pnl": None})

        # --- grid strategy: set up when ranging and flat ---
        elif regime == "ranging" and not has_position and not has_open_orders and grid_state is None:
            box_high, box_low = compute_box(df_1h[df_1h.index <= ts])
            if box_high > box_low:
                step = (box_high - box_low) / config.GRID_LEVELS
                levels = [box_low + step * k for k in range(config.GRID_LEVELS + 1)]
                notional_per_level = (equity * risk_manager.leverage) / config.GRID_LEVELS
                order_amount = notional_per_level / float(bar["close"])
                grid_state = GridBacktestState(box_high, box_low, levels, order_amount)
                _rebalance_grid(broker, symbol, grid_state, float(bar["close"]), order_amount)

        # --- manage active grid ---
        if grid_state is not None:
            close_price = float(bar["close"])
            breached = (
                close_price > grid_state.box_high * (1 + config.GRID_BOX_BREACH_PCT)
                or close_price < grid_state.box_low * (1 - config.GRID_BOX_BREACH_PCT)
            )
            if breached:
                for sym, pos in list(broker.positions.items()):
                    close_side = "sell" if pos.side == "long" else "buy"
                    pnl_before = broker.balance_usdt
                    broker.create_order(sym, "market", close_side, pos.amount, close_price)
                    trades.append({"ts": ts, "symbol": sym, "type": "grid_stop_loss", "side": close_side, "price": close_price, "pnl": broker.balance_usdt - pnl_before})
                broker.cancel_all(symbol)
                grid_state = None
            else:
                pre_balance = broker.balance_usdt
                broker.check_fills(symbol, close_price, float(bar["high"]), float(bar["low"]))
                if broker.balance_usdt != pre_balance:
                    trades.append({"ts": ts, "symbol": symbol, "type": "grid_fill", "side": None, "price": close_price, "pnl": broker.balance_usdt - pre_balance})
                _rebalance_grid(broker, symbol, grid_state, close_price, grid_state.order_amount)

        # --- manage active trend position (SL/TP) ---
        if trend_stop_tp is not None:
            pre_balance = broker.balance_usdt
            broker.check_fills(symbol, float(bar["close"]), float(bar["high"]), float(bar["low"]))
            if symbol not in broker.positions:
                trades.append({"ts": ts, "symbol": symbol, "type": "trend_exit", "side": trend_stop_tp["side"], "price": float(bar["close"]), "pnl": broker.balance_usdt - pre_balance})
                trend_stop_tp = None
                broker.cancel_all(symbol)

        equity_curve.append((ts, broker.equity({symbol: float(bar["close"])})))

    ending_equity = equity_curve[-1][1] if equity_curve else starting_equity
    return BacktestResult(symbol, equity_curve, trades, starting_equity, ending_equity)


def run_backtest_suite(symbols: list[str], days: int = 60) -> list[BacktestResult]:
    return [run_backtest(sym, days) for sym in symbols]
