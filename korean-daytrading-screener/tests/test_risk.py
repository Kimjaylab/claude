from screener.config import load_screening_rules
from screener.screening.models import IntradaySnapshot, TechnicalSnapshot
from screener.screening.risk import compute_risk_targets


def test_risk_targets_ordering_and_grade():
    rules = load_screening_rules()
    tech = TechnicalSnapshot(
        code="005930", name="테스트", market="KOSPI", prev_close=10_000, ma5=10_100, ma20=9_900,
        ma60=9_700, recent_high_20d=10_300, rsi14=55, atr_pct=4.0, three_day_return_pct=3.0,
        avg_5min_volume_20d=10_000,
    )
    intraday = IntradaySnapshot(
        code="005930", current_price=10_500, open_price=10_100, prev_close=10_000,
        cumulative_volume=50_000, cumulative_value=5_000_000_000, buy_execution_ratio=150,
        bid_ask_volume_ratio=1.5, index_change_pct=0.5,
    )
    risk = compute_risk_targets(tech, intraday, rules)

    assert risk.stop_loss < risk.entry_price < risk.target1 < risk.target2
    assert risk.risk_grade == "중간"


def test_low_volatility_gets_low_risk_grade():
    rules = load_screening_rules()
    tech = TechnicalSnapshot(
        code="005930", name="테스트", market="KOSPI", prev_close=10_000, ma5=10_100, ma20=9_900,
        ma60=9_700, recent_high_20d=10_300, rsi14=55, atr_pct=1.5, three_day_return_pct=3.0,
        avg_5min_volume_20d=10_000,
    )
    intraday = IntradaySnapshot(
        code="005930", current_price=10_500, open_price=10_100, prev_close=10_000,
        cumulative_volume=50_000, cumulative_value=5_000_000_000, buy_execution_ratio=150,
        bid_ask_volume_ratio=1.5, index_change_pct=0.5,
    )
    risk = compute_risk_targets(tech, intraday, rules)
    assert risk.risk_grade == "낮음"
