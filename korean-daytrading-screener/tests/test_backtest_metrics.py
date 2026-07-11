from screener.backtest.metrics import _score_bucket_label, _summarize, build_report
from screener.backtest.models import Trade
from screener.config import load_settings


def _trade(date="20240101", return_pct=1.0, score_honest=70, score_reference=75, regime="횡보장", split="in_sample") -> Trade:
    return Trade(
        code="005930", name="테스트", market="KOSPI", date=date, entry=10000, exit=10100,
        exit_reason="eod", return_pct=return_pct, score_honest=score_honest, score_reference=score_reference,
        index_regime=regime, split=split,
    )


def test_summarize_win_rate_and_expectancy():
    s = _summarize([2.0, 2.0, -1.0, -1.0])
    assert s.trade_count == 4
    assert s.win_rate == 50.0
    assert s.avg_return_pct == 2.0
    assert s.avg_loss_pct == -1.0
    assert s.profit_factor == 2.0  # 총이익 4 / 총손실 2
    assert s.expectancy_pct == 0.5


def test_summarize_empty_returns_zero_and_unreliable():
    s = _summarize([])
    assert s.trade_count == 0
    assert s.reliable is False


def test_score_bucket_label():
    assert _score_bucket_label(72) == "70~79"
    assert _score_bucket_label(100) == "100~109"
    assert _score_bucket_label(-5) == "-10~-1"


def test_build_report_filters_by_min_score_and_splits_regime():
    settings = load_settings()
    trades = [
        _trade(return_pct=3.0, score_honest=80, regime="상승장"),
        _trade(return_pct=-2.0, score_honest=80, regime="하락장"),
        _trade(return_pct=1.0, score_honest=30, regime="횡보장"),  # min_score 미달로 제외되어야 함
    ]
    report = build_report(trades, score_field="score_honest", min_score=65, settings=settings)
    assert report.overall.trade_count == 2
    assert "상승장" in report.by_regime
    assert "하락장" in report.by_regime
    assert "횡보장" not in report.by_regime


def test_build_report_marks_small_buckets_unreliable():
    settings = load_settings()
    trades = [_trade(score_honest=90) for _ in range(3)]  # min_trades_per_bucket(10) 미만
    report = build_report(trades, score_field="score_honest", min_score=0, settings=settings)
    assert report.overall.reliable is False
