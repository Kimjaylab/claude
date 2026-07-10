from screener.config import load_screening_rules
from screener.screening.models import IntradaySnapshot, TechnicalSnapshot
from screener.screening.scoring import apply_regime_multiplier, compute_score


def _tech(**overrides) -> TechnicalSnapshot:
    base = dict(
        code="005930",
        name="테스트전자",
        market="KOSPI",
        prev_close=10_000,
        ma5=10_200,
        ma20=9_800,
        ma60=9_500,
        recent_high_20d=10_300,
        rsi14=60,
        atr_pct=3.0,
        three_day_return_pct=5.0,
        avg_5min_volume_20d=10_000,
    )
    base.update(overrides)
    return TechnicalSnapshot(**base)


def _intraday(**overrides) -> IntradaySnapshot:
    base = dict(
        code="005930",
        current_price=10_500,
        open_price=10_100,
        prev_close=10_000,
        cumulative_volume=50_000,
        cumulative_value=5_000_000_000,
        buy_execution_ratio=150,
        bid_ask_volume_ratio=1.5,
        index_change_pct=0.5,
        disclosure_score=0.0,
    )
    base.update(overrides)
    return IntradaySnapshot(**base)


def test_strong_candidate_scores_high():
    rules = load_screening_rules()
    tech = _tech()
    intraday = _intraday()
    breakdown, reasons = compute_score(tech, intraday, rules)
    assert breakdown.total > 50
    assert breakdown.volume_momentum > 0
    assert breakdown.breakout > 0
    assert len(reasons) > 0


def test_no_volume_surge_scores_low_on_volume():
    rules = load_screening_rules()
    tech = _tech()
    intraday = _intraday(cumulative_volume=5_000)  # 평상시 대비 0.5배 수준
    breakdown, _ = compute_score(tech, intraday, rules)
    assert breakdown.volume_momentum == 0


def test_overheated_stock_gets_penalized():
    rules = load_screening_rules()
    tech_normal = _tech(rsi14=60, three_day_return_pct=5)
    tech_overheated = _tech(rsi14=95, three_day_return_pct=40)
    intraday = _intraday()

    normal_score, _ = compute_score(tech_normal, intraday, rules)
    overheated_score, _ = compute_score(tech_overheated, intraday, rules)

    assert overheated_score.overheat_penalty < normal_score.overheat_penalty
    assert overheated_score.total < normal_score.total


def test_excessive_gap_is_penalized_hard():
    rules = load_screening_rules()
    tech = _tech()
    mild_gap = _intraday(open_price=10_200)   # +2% 갭
    huge_gap = _intraday(open_price=12_000)   # +20% 갭

    mild_score, _ = compute_score(tech, mild_gap, rules)
    huge_score, _ = compute_score(tech, huge_gap, rules)

    assert huge_score.gap_quality < 0
    assert huge_score.gap_quality < mild_score.gap_quality


def test_regime_multiplier_reduces_score_on_market_crash():
    settings_regime_cfg = {
        "crash_index_change_pct": -1.5,
        "crash_max_candidates": 3,
        "crash_score_multiplier": 0.75,
    }
    normal = apply_regime_multiplier(80, index_change_pct=0.3, regime_cfg=settings_regime_cfg)
    crashed = apply_regime_multiplier(80, index_change_pct=-2.0, regime_cfg=settings_regime_cfg)
    assert normal == 80
    assert crashed == 60
