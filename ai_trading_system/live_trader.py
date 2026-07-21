"""Main loop tying the scanner, both strategies, risk manager, and exchange
client together for testnet/dry-run/live execution.

This has been exercised with the synthetic-data simulation in backtester.py
and with the DryRunBroker fill-matching logic, but NOT against a live or
funded testnet Binance account (this environment's network policy blocks
reaching Binance's API). Run it in "dry_run" mode first, then "testnet",
and watch it for at least a few full days before ever considering "live".
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import config
import regime_scanner
from exchange_client import ExchangeClient
from risk_manager import RiskManager
from strategies import trend_strategy
from strategies.grid_strategy import GridStrategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live_trader")


class LiveTrader:
    def __init__(self, mode: str | None = None):
        self.client = ExchangeClient(mode)
        self.risk_manager = RiskManager()
        self.grids: dict[str, GridStrategy] = {}
        self.trend_active: set[str] = set()

        equity = self.client.fetch_equity()
        restored = self.risk_manager.load()
        if restored:
            log.info(
                "Restored risk state from disk: day_start_equity=%s locked_until=%s",
                self.risk_manager.day_start_equity, self.risk_manager.locked_until,
            )
        else:
            self.risk_manager.start_new_day(equity)
        log.info("Started in mode=%s equity=%.2f", self.client.mode, equity)

    def _flatten_everything(self):
        self.client.close_all_positions()
        for symbol, grid in list(self.grids.items()):
            grid.shutdown(self.client)
        self.grids.clear()
        self.trend_active.clear()

    def _process_dry_run_fills(self):
        """dry_run mode never talks to a real exchange, so nothing else
        fills the resting limit/stop/take-profit orders sitting in
        DryRunBroker.open_orders. Without this, grid limit orders and
        trend stop-loss/take-profit orders would just sit there forever.
        Uses the latest traded price as a stand-in for the bar's high/low,
        so a level can be missed if price wicks through and back between
        polling cycles -- fine for watching the strategy logic behave
        sensibly, not a substitute for testnet/live fills.
        """
        if self.client.mode != "dry_run":
            return
        broker = self.client.dry_run_broker
        active_symbols = set(self.grids) | set(self.trend_active)
        for symbol in active_symbols:
            if not broker.open_orders.get(symbol):
                continue
            last_price = self.client.fetch_last_price(symbol)
            balance_before = broker.balance_usdt
            broker.check_fills(symbol, last_price, high=last_price, low=last_price)
            pnl = broker.balance_usdt - balance_before
            if pnl != 0:
                log.info("%s dry-run fill, realized pnl=%+.4f", symbol, pnl)

    def run_once(self):
        now = datetime.now(timezone.utc)
        equity = self.client.fetch_equity()

        if self.risk_manager.check_daily_loss_limit(equity, now):
            log.warning("DAILY LOSS LIMIT HIT: %s", self.risk_manager.lock_reason)
            self._flatten_everything()
            return

        if self.risk_manager.is_locked(now):
            log.info("Locked out until %s, skipping cycle.", self.risk_manager.locked_until)
            return

        self._process_dry_run_fills()

        readings = regime_scanner.scan_market(self.client, config.TOP_N_SYMBOLS)
        readings_by_symbol = {r.symbol: r for r in readings}

        # Manage existing grids first: breach check + rebalance, or tear
        # down if the symbol is no longer ranging.
        for symbol, grid in list(self.grids.items()):
            reading = readings_by_symbol.get(symbol)
            last_price = self.client.fetch_last_price(symbol)
            if grid.is_box_breached(last_price):
                log.warning("%s box breached at %.6f, stopping grid.", symbol, last_price)
                grid.shutdown(self.client)
                del self.grids[symbol]
                continue
            grid.rebalance(self.client, last_price)

        # Manage existing trend positions: drop from active set once the
        # position has actually closed (stop-loss or take-profit filled).
        for symbol in list(self.trend_active):
            positions = self.client.fetch_positions(symbol)
            has_open = any(
                (p.amount if hasattr(p, "amount") else float(p.get("contracts") or 0)) != 0
                for p in positions
            )
            if not has_open:
                self.trend_active.discard(symbol)

        # Each concurrently-open symbol only gets an equal slice of total
        # equity to size against, so account-wide leverage stays bounded at
        # LEVERAGE * equity no matter how many symbols the scanner flags in
        # the same cycle. Without this, N simultaneous grids/positions would
        # each be sized off the FULL equity, stacking to ~N * LEVERAGE.
        per_symbol_budget = equity / config.MAX_CONCURRENT_POSITIONS

        for reading in readings:
            symbol = reading.symbol
            if symbol in self.grids or symbol in self.trend_active:
                continue

            active_count = len(self.grids) + len(self.trend_active)
            if active_count >= config.MAX_CONCURRENT_POSITIONS:
                log.info(
                    "Max concurrent positions (%d) reached, skipping %s this cycle.",
                    config.MAX_CONCURRENT_POSITIONS, symbol,
                )
                break

            if reading.regime == "ranging":
                grid = GridStrategy(symbol)
                try:
                    grid.setup(self.client, self.risk_manager, per_symbol_budget)
                except Exception:
                    log.exception("Failed to set up grid for %s", symbol)
                    continue
                self.grids[symbol] = grid
                log.info("Grid started for %s: box [%.6f, %.6f]", symbol, grid.box_low, grid.box_high)

            elif reading.regime == "trending":
                try:
                    signal = trend_strategy.evaluate(self.client, self.risk_manager, symbol)
                except Exception:
                    log.exception("Failed to evaluate trend signal for %s", symbol)
                    continue
                if signal:
                    qty = trend_strategy.execute(self.client, self.risk_manager, per_symbol_budget, signal)
                    if qty:
                        self.trend_active.add(symbol)
                        log.info(
                            "%s %s entry=%.6f sl=%.6f tp=%.6f qty=%.6f",
                            symbol, signal.side, signal.entry_price,
                            signal.stop_price, signal.take_profit_price, qty,
                        )

        equity_now = self.client.fetch_equity()
        day_start = self.risk_manager.day_start_equity or equity_now
        day_pnl = equity_now - day_start
        day_pnl_pct = (day_pnl / day_start * 100) if day_start else 0.0
        log.info(
            "Cycle summary: equity=%.2f day_pnl=%+.2f (%+.2f%%) open_grids=%d open_trend=%d",
            equity_now, day_pnl, day_pnl_pct, len(self.grids), len(self.trend_active),
        )

    def run_forever(self):
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Unhandled error in trading cycle")
            time.sleep(config.SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    LiveTrader().run_forever()
