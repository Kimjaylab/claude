"""Step 2A of the spec: neutral futures grid for RANGING regimes.

Box = high/low of the last GRID_BOX_LOOKBACK_DAYS days. We lay resting buy
limit orders below the current price and resting sell limit orders above
it, spread evenly across the box. Every fill is meant to be closed by an
order one grid step in the opposite direction (classic grid bot), which
`GridStrategy.rebalance` re-establishes.

If a bar closes more than GRID_BOX_BREACH_PCT outside the box, the whole
grid is torn down and every position is flattened with a market order --
this is the "칼손절" (hard stop) rule from the spec.
"""
from dataclasses import dataclass, field

import config


def compute_box(df_1h) -> tuple[float, float]:
    lookback_bars = config.GRID_BOX_LOOKBACK_DAYS * 24
    window = df_1h.iloc[-lookback_bars:]
    return float(window["high"].max()), float(window["low"].min())


@dataclass
class GridStrategy:
    symbol: str
    box_high: float = 0.0
    box_low: float = 0.0
    levels: list[float] = field(default_factory=list)
    order_amount: float = 0.0
    active: bool = False

    def setup(self, client, risk_manager, equity: float):
        df_1h = client.fetch_ohlcv_df(self.symbol, "1h", limit=config.GRID_BOX_LOOKBACK_DAYS * 24 + 5)
        self.box_high, self.box_low = compute_box(df_1h)

        step = (self.box_high - self.box_low) / config.GRID_LEVELS
        self.levels = [self.box_low + step * i for i in range(config.GRID_LEVELS + 1)]

        notional_per_level = (equity * risk_manager.leverage) / config.GRID_LEVELS
        last_price = client.fetch_last_price(self.symbol)
        self.order_amount = notional_per_level / last_price

        client.set_leverage_and_margin(self.symbol, risk_manager.leverage, risk_manager.margin_mode)
        client.cancel_all_orders(self.symbol)

        for level in self.levels:
            if level < last_price:
                client.limit_order(self.symbol, "buy", self.order_amount, level)
            elif level > last_price:
                client.limit_order(self.symbol, "sell", self.order_amount, level)

        self.active = True

    def is_box_breached(self, close_price: float) -> bool:
        upper_breach = close_price > self.box_high * (1 + config.GRID_BOX_BREACH_PCT)
        lower_breach = close_price < self.box_low * (1 - config.GRID_BOX_BREACH_PCT)
        return upper_breach or lower_breach

    def shutdown(self, client):
        client.close_all_positions(self.symbol)
        client.cancel_all_orders(self.symbol)
        self.active = False

    def rebalance(self, client, last_price: float):
        """Re-quote any grid level that no longer has a resting order (i.e.
        it was filled), placing the opposite-side order one step up/down so
        the filled unit has a take-profit resting for it.
        """
        if self.mode_is_dry_run(client):
            open_prices = {o["price"] for o in client.dry_run_broker.open_orders.get(self.symbol, [])}
        else:
            try:
                open_orders = client.exchange.fetch_open_orders(self.symbol)
            except Exception:
                return
            open_prices = {float(o["price"]) for o in open_orders if o.get("price")}

        for level in self.levels:
            if any(abs(level - p) < 1e-9 for p in open_prices):
                continue
            if level < last_price:
                client.limit_order(self.symbol, "buy", self.order_amount, level)
            elif level > last_price:
                client.limit_order(self.symbol, "sell", self.order_amount, level)

    @staticmethod
    def mode_is_dry_run(client) -> bool:
        return client.mode == "dry_run"
