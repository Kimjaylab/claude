"""역매공파 전략 백테스트 엔진.

실거래 전에 반드시 이 모듈로 과거 데이터를 검증하세요.
데이터는 KIS API의 해외주식 기간별시세를 사용하거나, 별도 CSV
(columns: date, open, high, low, close, volume)를 로드해 사용할 수 있습니다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from .config import RiskConfig, StrategyConfig
from .strategy import generate_signal, prepare_indicators

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    return_pct: float


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.return_pct > 0)
        return wins / len(self.trades)

    @property
    def avg_return_pct(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.return_pct for t in self.trades) / len(self.trades)

    @property
    def cumulative_return_pct(self) -> float:
        cum = 1.0
        for t in self.trades:
            cum *= (1 + t.return_pct)
        return cum - 1.0

    def summary(self) -> str:
        return (
            f"거래횟수={self.total_trades}, 승률={self.win_rate:.1%}, "
            f"평균수익률={self.avg_return_pct:.2%}, 누적수익률={self.cumulative_return_pct:.2%}"
        )

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


def backtest_symbol(df: pd.DataFrame, symbol: str, strat_cfg: StrategyConfig,
                     risk_cfg: RiskConfig) -> list[Trade]:
    """df: date 오름차순 정렬된 OHLCV 데이터프레임 (컬럼: date, open, high, low, close, volume)."""
    df = df.reset_index(drop=True)
    df = prepare_indicators(df, strat_cfg)

    trades: list[Trade] = []
    in_position = False
    entry_price = 0.0
    entry_date = ""

    min_history = max(strat_cfg.ma_long, strat_cfg.bb_squeeze_lookback) + 1

    for i in range(min_history, len(df)):
        row = df.iloc[i]

        if in_position:
            tp_price = entry_price * (1 + risk_cfg.take_profit_pct)
            sl_price = entry_price * (1 + risk_cfg.stop_loss_pct)
            # 손절을 먼저 체크 (동일 봉에서 둘 다 충족 시 보수적으로 처리)
            if row["low"] <= sl_price:
                trades.append(Trade(symbol, entry_date, entry_price, row["date"], sl_price,
                                     "stop_loss", (sl_price - entry_price) / entry_price))
                in_position = False
            elif row["high"] >= tp_price:
                trades.append(Trade(symbol, entry_date, entry_price, row["date"], tp_price,
                                     "take_profit", (tp_price - entry_price) / entry_price))
                in_position = False
            continue

        signal = generate_signal(df, i, strat_cfg)
        if signal.buy:
            in_position = True
            entry_price = float(row["close"])
            entry_date = row["date"]

    return trades


def run_backtest(data_by_symbol: dict[str, pd.DataFrame], strat_cfg: StrategyConfig,
                  risk_cfg: RiskConfig) -> BacktestResult:
    result = BacktestResult()
    for symbol, df in data_by_symbol.items():
        try:
            trades = backtest_symbol(df, symbol, strat_cfg, risk_cfg)
        except Exception:
            logger.exception("종목 %s 백테스트 중 오류", symbol)
            continue
        result.trades.extend(trades)
    result.trades.sort(key=lambda t: t.entry_date)
    return result
