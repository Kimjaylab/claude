from screener.notify.telegram_bot import format_daily_report
from screener.screening.models import Candidate, IntradaySnapshot, RiskTargets, ScoreBreakdown, TechnicalSnapshot


def _candidate(score_total: float) -> Candidate:
    tech = TechnicalSnapshot(
        code="005930", name="테스트전자", market="KOSPI", prev_close=10_000, ma5=10_200, ma20=9_800,
        ma60=9_500, recent_high_20d=10_300, rsi14=60, atr_pct=3.0, three_day_return_pct=5.0,
        avg_5min_volume_20d=10_000,
    )
    intraday = IntradaySnapshot(
        code="005930", current_price=10_500, open_price=10_100, prev_close=10_000,
        cumulative_volume=50_000, cumulative_value=5_000_000_000, buy_execution_ratio=150,
        bid_ask_volume_ratio=1.5, index_change_pct=0.5,
    )
    score = ScoreBreakdown(volume_momentum=score_total)
    risk = RiskTargets(entry_price=10_500, stop_loss=10_200, target1=10_900, target2=11_300, risk_grade="중간")
    return Candidate(technical=tech, intraday=intraday, score=score, risk=risk, reasons=["거래량 급증"])


def test_report_lists_candidates_sorted_by_score():
    report = format_daily_report([_candidate(90), _candidate(70)], regime_note=None)
    assert "테스트전자" in report
    assert "90/100" in report or "S" in report


def test_empty_report_has_friendly_message():
    report = format_daily_report([], regime_note=None)
    assert "후보가 없습니다" in report


def test_regime_note_is_included():
    report = format_daily_report([], regime_note="시장 약세")
    assert "시장 약세" in report
