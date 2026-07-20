"""Thin wrapper around ccxt's Binance USDS-M futures client.

Three modes, selected by config.TRADING_MODE:

- "dry_run"  Pulls real public market data (no API key needed) but never
             sends an order to Binance. Fills are simulated locally by
             DryRunBroker. This is the default and the safest way to run
             the live_trader loop continuously.
- "testnet"  Talks to Binance Futures Testnet with real orders using
             testnet API keys. Real order-placement code paths, fake money.
- "live"     Talks to real Binance with real funds. Refuses to start unless
             LIVE_TRADING_CONFIRMATION exactly matches the confirmation
             phrase in config.py, as an extra guardrail against running
             this by accident.

Order-placement code for "testnet"/"live" follows Binance's documented
USDS-M futures order types (STOP_MARKET / TAKE_PROFIT_MARKET, reduceOnly)
via ccxt's binanceusdm pass-through. It has been exercised against public
endpoints and the dry-run simulator in this repo, but NOT against a funded
testnet or live account -- validate on testnet before ever using "live".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import ccxt
import pandas as pd

import config


class LiveTradingNotConfirmedError(RuntimeError):
    pass


@dataclass
class SimPosition:
    side: str  # "long" | "short"
    amount: float
    entry_price: float


@dataclass
class DryRunBroker:
    """Local paper-trading simulator: real prices, fake fills/balance."""

    balance_usdt: float = 10_000.0
    positions: dict[str, SimPosition] = field(default_factory=dict)
    open_orders: dict[str, list[dict]] = field(default_factory=dict)
    _next_order_id: int = 1

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        params = params or {}
        order_id = str(self._next_order_id)
        self._next_order_id += 1
        order = {
            "id": order_id,
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "amount": amount,
            "price": price,
            "stopPrice": params.get("stopPrice"),
            "reduceOnly": params.get("reduceOnly", False),
            "status": "open",
        }
        if order_type == "market":
            self._fill(order, fill_price=price)
            order["status"] = "closed"
        else:
            self.open_orders.setdefault(symbol, []).append(order)
        return order

    def _fill(self, order: dict, fill_price: float):
        symbol = order["symbol"]
        side = order["side"]
        amount = order["amount"]
        pos = self.positions.get(symbol)

        signed = amount if side == "buy" else -amount
        if pos is None:
            self.positions[symbol] = SimPosition(
                side="long" if signed > 0 else "short",
                amount=abs(signed),
                entry_price=fill_price,
            )
            return

        pos_signed = pos.amount if pos.side == "long" else -pos.amount
        new_signed = pos_signed + signed

        if pos.side == "long" and side == "sell" or pos.side == "short" and side == "buy":
            closing_amount = min(abs(signed), pos.amount)
            pnl_per_unit = (fill_price - pos.entry_price) if pos.side == "long" else (pos.entry_price - fill_price)
            self.balance_usdt += pnl_per_unit * closing_amount

        if abs(new_signed) < 1e-12:
            del self.positions[symbol]
        else:
            self.positions[symbol] = SimPosition(
                side="long" if new_signed > 0 else "short",
                amount=abs(new_signed),
                entry_price=fill_price,
            )

    def check_fills(self, symbol: str, last_price: float, high: float, low: float):
        """Call once per new bar with that bar's OHLC extremes to see if any
        resting limit/stop orders would have been triggered.
        """
        still_open = []
        for order in self.open_orders.get(symbol, []):
            triggered = False
            fill_price = order.get("price") or order.get("stopPrice")

            if order["type"] == "limit":
                if order["side"] == "buy" and low <= order["price"]:
                    triggered = True
                elif order["side"] == "sell" and high >= order["price"]:
                    triggered = True
            elif order["type"] in ("stop_market", "take_profit_market"):
                sp = order["stopPrice"]
                if order["side"] == "sell" and low <= sp:
                    triggered, fill_price = True, sp
                elif order["side"] == "buy" and high >= sp:
                    triggered, fill_price = True, sp

            if triggered:
                self._fill(order, fill_price)
                order["status"] = "closed"
            else:
                still_open.append(order)
        self.open_orders[symbol] = still_open

    def cancel_all(self, symbol: str):
        self.open_orders[symbol] = []

    def equity(self, mark_prices: dict[str, float]) -> float:
        unrealized = 0.0
        for sym, pos in self.positions.items():
            mark = mark_prices.get(sym, pos.entry_price)
            diff = (mark - pos.entry_price) if pos.side == "long" else (pos.entry_price - mark)
            unrealized += diff * pos.amount
        return self.balance_usdt + unrealized


class ExchangeClient:
    def __init__(self, mode: str | None = None):
        self.mode = (mode or config.TRADING_MODE).lower()
        if self.mode not in ("dry_run", "testnet", "live"):
            raise ValueError(f"Unknown TRADING_MODE: {self.mode!r}")

        if self.mode == "live" and config.LIVE_TRADING_CONFIRMATION != config.LIVE_CONFIRMATION_PHRASE:
            raise LiveTradingNotConfirmedError(
                "Refusing to start in live mode: set LIVE_TRADING_CONFIRMATION="
                f"{config.LIVE_CONFIRMATION_PHRASE!r} in your .env after you have "
                "validated the strategy on testnet."
            )

        self.exchange = ccxt.binanceusdm(
            {
                "apiKey": config.BINANCE_API_KEY,
                "secret": config.BINANCE_API_SECRET,
                "enableRateLimit": True,
            }
        )
        if self.mode == "testnet":
            self.exchange.set_sandbox_mode(True)

        self.dry_run_broker = DryRunBroker() if self.mode == "dry_run" else None

    # --- market data (works in every mode, uses public endpoints) -------------------
    def fetch_top_symbols(self, n: int = config.TOP_N_SYMBOLS) -> list[str]:
        """Top-N USDT-margined perpetuals by 24h quote volume, restricted to
        actual cryptocurrencies. Binance's USDS-M futures now also lists
        tokenized-stock and commodity perpetuals (e.g. gold/silver, single
        stocks) under the same USDT-quoted swap markets; those are excluded
        here since the strategies/risk model in this repo were built for
        crypto volatility, not equities or metals.
        """
        markets = self.exchange.load_markets()
        tickers = self.exchange.fetch_tickers()

        usdt_perp = []
        excluded = []
        for m in markets.values():
            if not (m.get("swap") and m.get("quote") == config.QUOTE_ASSET and m.get("active")):
                continue
            underlying_type = (m.get("info") or {}).get("underlyingType")
            if underlying_type and underlying_type != "COIN":
                excluded.append(m["symbol"])
                continue
            if m.get("base") in config.NON_CRYPTO_BASE_DENYLIST:
                excluded.append(m["symbol"])
                continue
            usdt_perp.append(m["symbol"])

        if excluded:
            logging.getLogger("exchange_client").info(
                "Excluded %d non-crypto USDT perpetual(s) from the scan: %s",
                len(excluded), ", ".join(sorted(excluded)),
            )

        ranked = sorted(
            usdt_perp,
            key=lambda s: tickers.get(s, {}).get("quoteVolume") or 0,
            reverse=True,
        )
        return ranked[:n]

    def fetch_ohlcv_df(self, symbol: str, timeframe: str, limit: int = 200, since: int | None = None) -> pd.DataFrame:
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, since=since)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.set_index("timestamp")

    def fetch_open_interest_history(self, symbol: str, timeframe: str = "5m", limit: int = 30) -> pd.Series | None:
        try:
            raw = self.exchange.fetch_open_interest_history(symbol, timeframe=timeframe, limit=limit)
        except Exception:
            return None
        if not raw:
            return None
        idx = [pd.to_datetime(r["timestamp"], unit="ms", utc=True) for r in raw]
        vals = [r["openInterestAmount"] for r in raw]
        return pd.Series(vals, index=idx)

    def fetch_last_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(symbol)["last"])

    # --- account / positions ---------------------------------------------------------
    def fetch_equity(self) -> float:
        if self.mode == "dry_run":
            marks = {s: self.fetch_last_price(s) for s in self.dry_run_broker.positions}
            return self.dry_run_broker.equity(marks)
        balance = self.exchange.fetch_balance()
        return float(balance["USDT"]["total"])

    def set_leverage_and_margin(self, symbol: str, leverage: int, margin_mode: str):
        if self.mode == "dry_run":
            return
        try:
            self.exchange.set_margin_mode(margin_mode.lower(), symbol)
        except ccxt.ExchangeError:
            pass  # already set to this mode
        self.exchange.set_leverage(leverage, symbol)

    # --- order placement ---------------------------------------------------------------
    def market_order(self, symbol: str, side: str, amount: float, reduce_only: bool = False):
        params = {"reduceOnly": reduce_only}
        if self.mode == "dry_run":
            price = self.fetch_last_price(symbol)
            return self.dry_run_broker.create_order(symbol, "market", side, amount, price, params)
        return self.exchange.create_order(symbol, "market", side, amount, None, params)

    def limit_order(self, symbol: str, side: str, amount: float, price: float, reduce_only: bool = False):
        params = {"reduceOnly": reduce_only}
        if self.mode == "dry_run":
            return self.dry_run_broker.create_order(symbol, "limit", side, amount, price, params)
        return self.exchange.create_order(symbol, "limit", side, amount, price, params)

    def stop_market_order(self, symbol: str, side: str, amount: float, stop_price: float):
        params = {"stopPrice": stop_price, "reduceOnly": True}
        if self.mode == "dry_run":
            return self.dry_run_broker.create_order(symbol, "stop_market", side, amount, None, params)
        return self.exchange.create_order(symbol, "STOP_MARKET", side, amount, None, params)

    def take_profit_market_order(self, symbol: str, side: str, amount: float, stop_price: float):
        params = {"stopPrice": stop_price, "reduceOnly": True}
        if self.mode == "dry_run":
            return self.dry_run_broker.create_order(symbol, "take_profit_market", side, amount, None, params)
        return self.exchange.create_order(symbol, "TAKE_PROFIT_MARKET", side, amount, None, params)

    def cancel_all_orders(self, symbol: str):
        if self.mode == "dry_run":
            self.dry_run_broker.cancel_all(symbol)
            return
        self.exchange.cancel_all_orders(symbol)

    def fetch_positions(self, symbol: str | None = None):
        if self.mode == "dry_run":
            if symbol:
                pos = self.dry_run_broker.positions.get(symbol)
                return [pos] if pos else []
            return list(self.dry_run_broker.positions.values())
        return self.exchange.fetch_positions([symbol] if symbol else None)

    def close_all_positions(self, symbol: str | None = None):
        """Flush every open position with a reduce-only market order. Used
        by the daily-loss circuit breaker and the grid box-breach stop.
        """
        if self.mode == "dry_run":
            symbols = [symbol] if symbol else list(self.dry_run_broker.positions.keys())
            for sym in symbols:
                pos = self.dry_run_broker.positions.get(sym)
                if not pos:
                    continue
                close_side = "sell" if pos.side == "long" else "buy"
                self.market_order(sym, close_side, pos.amount, reduce_only=True)
                self.cancel_all_orders(sym)
            return

        positions = self.fetch_positions(symbol)
        for pos in positions:
            amount = float(pos.get("contracts") or 0)
            if amount == 0:
                continue
            close_side = "sell" if pos.get("side") == "long" else "buy"
            self.market_order(pos["symbol"], close_side, amount, reduce_only=True)
            self.cancel_all_orders(pos["symbol"])
