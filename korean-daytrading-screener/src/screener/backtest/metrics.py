from dataclasses import dataclass, field

import pandas as pd

from screener.backtest.models import Trade


@dataclass
class PerformanceSummary:
    trade_count: int
    win_rate: float
    avg_return_pct: float          # 승리 거래 평균 수익률
    avg_loss_pct: float            # 패배 거래 평균 손실률
    profit_factor: float           # 총이익/총손실
    expectancy_pct: float          # 거래당 기대 수익률
    mdd_pct: float
    reliable: bool = True          # 표본이 min_trades_per_bucket 미만이면 False


@dataclass
class BacktestReport:
    overall: PerformanceSummary
    yearly: dict[str, PerformanceSummary] = field(default_factory=dict)
    by_regime: dict[str, PerformanceSummary] = field(default_factory=dict)
    by_score_bucket: dict[str, PerformanceSummary] = field(default_factory=dict)
    cagr_pct: float = 0.0
    sharpe: float = 0.0
    calmar: float = 0.0


def _summarize(returns: list[float], min_trades: int = 1) -> PerformanceSummary:
    if not returns:
        return PerformanceSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, reliable=False)

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / len(returns) * 100
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    total_win = sum(wins)
    total_loss = abs(sum(losses))
    profit_factor = (total_win / total_loss) if total_loss > 0 else float("inf") if total_win > 0 else 0.0
    expectancy = sum(returns) / len(returns)
    mdd = _max_drawdown_from_trade_sequence(returns)

    return PerformanceSummary(
        trade_count=len(returns),
        win_rate=win_rate,
        avg_return_pct=avg_win,
        avg_loss_pct=avg_loss,
        profit_factor=profit_factor,
        expectancy_pct=expectancy,
        mdd_pct=mdd,
        reliable=len(returns) >= min_trades,
    )


def _max_drawdown_from_trade_sequence(returns: list[float]) -> float:
    """거래를 순서대로 복리 체결했다고 가정한 단순 MDD (동시 보유/자본배분은 무시한 근사치)."""
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1 + r / 100
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak * 100
        mdd = min(mdd, drawdown)
    return mdd


def build_report(trades: list[Trade], score_field: str, min_score: float, settings: dict) -> BacktestReport:
    filtered = [t for t in trades if getattr(t, score_field) >= min_score]
    min_trades_per_bucket = settings["backtest"]["min_trades_per_bucket"]

    overall = _summarize([t.return_pct for t in filtered], min_trades_per_bucket)

    yearly: dict[str, PerformanceSummary] = {}
    for year, group in _group_by(filtered, lambda t: t.date[:4]).items():
        yearly[year] = _summarize([t.return_pct for t in group], min_trades_per_bucket)

    by_regime: dict[str, PerformanceSummary] = {}
    for regime, group in _group_by(filtered, lambda t: t.index_regime).items():
        by_regime[regime] = _summarize([t.return_pct for t in group], min_trades_per_bucket)

    by_bucket: dict[str, PerformanceSummary] = {}
    for bucket, group in _group_by(filtered, lambda t: _score_bucket_label(getattr(t, score_field))).items():
        by_bucket[bucket] = _summarize([t.return_pct for t in group], min_trades_per_bucket)

    cagr, sharpe, mdd_curve = _equity_curve_stats(filtered, settings)
    calmar = (cagr / abs(mdd_curve)) if mdd_curve < 0 else 0.0

    report = BacktestReport(
        overall=overall, yearly=yearly, by_regime=by_regime, by_score_bucket=by_bucket,
        cagr_pct=cagr, sharpe=sharpe, calmar=calmar,
    )
    report.overall.mdd_pct = mdd_curve  # 포트폴리오 단위 MDD로 덮어씀 (개별 거래 순차 MDD보다 현실적)
    return report


def _group_by(trades: list[Trade], key_fn) -> dict[str, list[Trade]]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(key_fn(t), []).append(t)
    return groups


def _score_bucket_label(score: float) -> str:
    lo = int(score // 10) * 10
    return f"{lo}~{lo + 9}"


def _equity_curve_stats(trades: list[Trade], settings: dict) -> tuple[float, float, float]:
    """일별로 그날 신호 중 상위 max_candidates만 균등비중 편입했다고 가정한 포트폴리오 곡선."""
    if not trades:
        return 0.0, 0.0, 0.0

    max_candidates = settings["notification"]["max_candidates"]
    df = pd.DataFrame([{"date": t.date, "score": t.score_reference, "return_pct": t.return_pct} for t in trades])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

    daily_returns = []
    for _, day_df in df.groupby("date"):
        top = day_df.sort_values("score", ascending=False).head(max_candidates)
        daily_returns.append(top["return_pct"].mean())

    dates = sorted(df["date"].unique())
    full_range = pd.bdate_range(dates[0], dates[-1])
    by_date = dict(zip(sorted(df["date"].unique()), daily_returns, strict=False))
    series = pd.Series([by_date.get(d, 0.0) for d in full_range], index=full_range)

    equity = (1 + series / 100).cumprod()
    total_days = max((full_range[-1] - full_range[0]).days, 1)
    cagr = (equity.iloc[-1] ** (365 / total_days) - 1) * 100 if equity.iloc[-1] > 0 else -100.0

    daily_std = series.std()
    sharpe = (series.mean() / daily_std * (252**0.5)) if daily_std > 0 else 0.0

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max * 100
    mdd = float(drawdown.min())

    return float(cagr), float(sharpe), mdd
