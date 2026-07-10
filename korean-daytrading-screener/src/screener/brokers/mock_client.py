import random
from datetime import date, timedelta

from screener.brokers.base import BrokerClient, Candle, OrderBook, Quote, RankingItem


class MockClient(BrokerClient):
    """API 키 없이 화면/스코어링 로직을 개발·테스트하기 위한 더미 브로커.

    결정론적 결과가 필요하면 seed를 고정한다.
    """

    def __init__(self, seed: int = 42, universe: list[tuple[str, str]] | None = None):
        self._rng = random.Random(seed)
        self.universe = universe or [
            (f"{100000 + i:06d}", f"테스트종목{i}") for i in range(50)
        ]

    def is_ready(self) -> bool:
        return True

    def get_quote(self, code: str) -> Quote:
        base = self._rng.uniform(5_000, 80_000)
        prev_close = base
        change = self._rng.uniform(-0.03, 0.15)
        current = prev_close * (1 + change)
        return Quote(
            code=code,
            name=dict(self.universe).get(code, code),
            current_price=round(current, 0),
            prev_close=round(prev_close, 0),
            open_price=round(prev_close * (1 + self._rng.uniform(-0.01, 0.05)), 0),
            high_price=round(current * 1.02, 0),
            low_price=round(prev_close * 0.98, 0),
            volume=self._rng.randint(100_000, 5_000_000),
            trading_value=self._rng.uniform(3e8, 5e10),
            market_cap=self._rng.uniform(5e10, 2e12),
            buy_execution_ratio=self._rng.uniform(60, 180),
        )

    def get_order_book(self, code: str) -> OrderBook:
        mid = self._rng.uniform(5_000, 80_000)
        tick = mid * 0.001
        return OrderBook(
            code=code,
            bid_prices=[mid - tick * i for i in range(1, 11)],
            bid_volumes=[self._rng.randint(100, 5000) for _ in range(10)],
            ask_prices=[mid + tick * i for i in range(1, 11)],
            ask_volumes=[self._rng.randint(100, 5000) for _ in range(10)],
        )

    def get_daily_candles(self, code: str, start: date, end: date) -> list[Candle]:
        candles = []
        price = self._rng.uniform(5_000, 80_000)
        current = start
        while current <= end:
            if current.weekday() < 5:
                o = price
                c = price * (1 + self._rng.uniform(-0.03, 0.03))
                h = max(o, c) * (1 + self._rng.uniform(0, 0.01))
                lo = min(o, c) * (1 - self._rng.uniform(0, 0.01))
                candles.append(
                    Candle(current.strftime("%Y%m%d"), o, h, lo, c, self._rng.randint(50_000, 2_000_000))
                )
                price = c
            current += timedelta(days=1)
        return candles

    def get_today_minute_candles(self, code: str) -> list[Candle]:
        candles = []
        price = self._rng.uniform(5_000, 80_000)
        for m in range(5):
            o = price
            c = price * (1 + self._rng.uniform(-0.01, 0.02))
            candles.append(
                Candle(f"0900{m:02d}", o, max(o, c), min(o, c), c, self._rng.randint(1_000, 100_000))
            )
            price = c
        return candles

    def get_volume_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        items = [
            RankingItem(code, name, i + 1, self._rng.uniform(1e6, 5e7))
            for i, (code, name) in enumerate(self.universe[:top_n])
        ]
        return sorted(items, key=lambda x: x.value, reverse=True)

    def get_fluctuation_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        items = [
            RankingItem(code, name, i + 1, self._rng.uniform(-10, 25))
            for i, (code, name) in enumerate(self.universe[:top_n])
        ]
        return sorted(items, key=lambda x: x.value, reverse=True)

    def get_trading_value_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        items = [
            RankingItem(code, name, i + 1, self._rng.uniform(1e9, 8e10))
            for i, (code, name) in enumerate(self.universe[:top_n])
        ]
        return sorted(items, key=lambda x: x.value, reverse=True)

    def get_index_change_pct(self, market: str) -> float:
        return self._rng.uniform(-1.0, 1.0)

    def is_market_holiday(self, day: date) -> bool:
        return day.weekday() >= 5
