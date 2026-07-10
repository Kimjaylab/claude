from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class Quote:
    code: str
    name: str
    current_price: float
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    volume: int                    # 당일 누적 거래량
    trading_value: float           # 당일 누적 거래대금(원)
    market_cap: float
    buy_execution_ratio: float     # 체결강도 (매수체결량/매도체결량 * 100)


@dataclass
class OrderBook:
    code: str
    bid_prices: list[float]
    bid_volumes: list[int]
    ask_prices: list[float]
    ask_volumes: list[int]

    @property
    def bid_ask_volume_ratio(self) -> float:
        total_bid = sum(self.bid_volumes)
        total_ask = sum(self.ask_volumes)
        return total_bid / total_ask if total_ask else float("inf")


@dataclass
class Candle:
    timestamp: str        # 일봉: YYYYMMDD, 분봉: YYYYMMDDHHMM
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class RankingItem:
    code: str
    name: str
    rank: int
    value: float           # 순위 기준이 되는 값(거래량, 등락률 등)


class BrokerClient(ABC):
    """증권사 API 어댑터 인터페이스.

    구현체를 교체해도 상위 스크리닝 로직이 영향받지 않도록
    모든 조회 결과를 브로커 중립적인 dataclass로 반환한다.
    """

    @abstractmethod
    def is_ready(self) -> bool: ...

    @abstractmethod
    def get_quote(self, code: str) -> Quote: ...

    @abstractmethod
    def get_order_book(self, code: str) -> OrderBook: ...

    @abstractmethod
    def get_daily_candles(self, code: str, start: date, end: date) -> list[Candle]: ...

    @abstractmethod
    def get_today_minute_candles(self, code: str) -> list[Candle]: ...

    @abstractmethod
    def get_volume_rank(self, market: str, top_n: int = 100) -> list[RankingItem]: ...

    @abstractmethod
    def get_fluctuation_rank(self, market: str, top_n: int = 100) -> list[RankingItem]: ...

    @abstractmethod
    def get_trading_value_rank(self, market: str, top_n: int = 100) -> list[RankingItem]: ...

    @abstractmethod
    def get_index_change_pct(self, market: str) -> float:
        """market: 'KOSPI' | 'KOSDAQ' 의 당일 등락률(%)"""
        ...

    @abstractmethod
    def is_market_holiday(self, day: date) -> bool: ...
