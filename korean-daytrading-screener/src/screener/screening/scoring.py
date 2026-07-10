from screener.screening.models import IntradaySnapshot, ScoreBreakdown, TechnicalSnapshot


def _score_volume_momentum(ratio: float, cfg: dict) -> float:
    lo, hi, max_pts = cfg["ideal_ratio_min"], cfg["ideal_ratio_max"], cfg["max_points"]
    if ratio <= 1:
        return 0.0
    if ratio < lo:
        return max_pts * (ratio - 1) / (lo - 1)
    if ratio <= hi:
        return float(max_pts)
    penalty = (ratio - hi) * cfg["over_ratio_penalty_per_x"]
    return max(0.0, max_pts - penalty)


def _score_trend(current_price: float, ma5: float, ma20: float, ma60: float, max_pts: float) -> float:
    conditions = [current_price > ma5, ma5 > ma20, ma20 > ma60]
    return max_pts * sum(conditions) / len(conditions)


def _score_breakout(current_price: float, recent_high_20d: float, volume_ratio: float, cfg: dict) -> float:
    if recent_high_20d <= 0:
        return 0.0
    base_max = cfg["max_points"] - cfg["volume_confirmation_bonus"]
    ratio_to_high = current_price / recent_high_20d
    if ratio_to_high < 0.97:
        base = 0.0
    elif ratio_to_high < 1.0:
        proximity = (ratio_to_high - 0.97) / 0.03
        base = base_max * 0.5 * proximity
    else:
        excess = min((ratio_to_high - 1.0) * 100, 5.0) / 5.0
        base = base_max * (0.5 + 0.5 * excess)
    bonus = cfg["volume_confirmation_bonus"] if (ratio_to_high >= 1.0 and volume_ratio >= 3.0) else 0.0
    return base + bonus


def _score_execution(buy_execution_ratio: float, bid_ask_volume_ratio: float, max_pts: float) -> float:
    exec_component = min(max((buy_execution_ratio - 100) / 100, 0.0), 1.0)
    bid_component = min(max((bid_ask_volume_ratio - 1) / 1, 0.0), 1.0)
    return max_pts * (0.6 * exec_component + 0.4 * bid_component)


def _score_relative_strength(stock_change_pct: float, index_change_pct: float, max_pts: float) -> float:
    rs = stock_change_pct - index_change_pct
    return max_pts * min(max(rs / 5.0, 0.0), 1.0)


def _score_gap(gap_pct: float, cfg: dict) -> float:
    if gap_pct <= cfg["sweet_spot_max_pct"]:
        return float(cfg["max_points"])
    if gap_pct <= cfg["half_score_max_pct"]:
        return cfg["max_points"] * 0.5
    if gap_pct <= cfg["hard_cut_pct"]:
        return 0.0
    return float(cfg["excessive_gap_penalty"])


def _score_news(disclosure_score: float, max_pts: float) -> float:
    return disclosure_score * max_pts


def _score_overheat(rsi14: float, three_day_return_pct: float, cfg: dict) -> float:
    max_penalty = abs(cfg["max_points"])
    penalty = 0.0
    if rsi14 > cfg["rsi_threshold"]:
        penalty += (rsi14 - cfg["rsi_threshold"]) / 20 * max_penalty
    if three_day_return_pct > cfg["three_day_return_threshold_pct"]:
        penalty += (three_day_return_pct - cfg["three_day_return_threshold_pct"]) / 25 * max_penalty
    return -min(penalty, max_penalty)


def compute_score(tech: TechnicalSnapshot, intraday: IntradaySnapshot, rules: dict) -> tuple[ScoreBreakdown, list[str]]:
    w = rules["weights"]
    volume_ratio = (
        intraday.cumulative_volume / tech.avg_5min_volume_20d if tech.avg_5min_volume_20d > 0 else 0.0
    )
    stock_change_pct = (intraday.current_price / intraday.prev_close - 1) * 100 if intraday.prev_close else 0.0
    gap_pct = (intraday.open_price / intraday.prev_close - 1) * 100 if intraday.prev_close else 0.0

    breakdown = ScoreBreakdown(
        volume_momentum=_score_volume_momentum(volume_ratio, w["volume_momentum"]),
        trend_alignment=_score_trend(intraday.current_price, tech.ma5, tech.ma20, tech.ma60, w["trend_alignment"]["max_points"]),
        breakout=_score_breakout(intraday.current_price, tech.recent_high_20d, volume_ratio, w["breakout"]),
        execution_strength=_score_execution(
            intraday.buy_execution_ratio, intraday.bid_ask_volume_ratio, w["execution_strength"]["max_points"]
        ),
        relative_strength=_score_relative_strength(
            stock_change_pct, intraday.index_change_pct, w["relative_strength"]["max_points"]
        ),
        gap_quality=_score_gap(gap_pct, w["gap_quality"]),
        news_disclosure=_score_news(intraday.disclosure_score, w["news_disclosure"]["max_points"]),
        overheat_penalty=_score_overheat(tech.rsi14, tech.three_day_return_pct, w["overheat_penalty"]),
    )

    reasons = _build_reasons(breakdown, volume_ratio, tech, intraday)
    return breakdown, reasons


def _build_reasons(
    b: ScoreBreakdown, volume_ratio: float, tech: TechnicalSnapshot, intraday: IntradaySnapshot
) -> list[str]:
    reasons = []
    if b.volume_momentum >= 15:
        reasons.append(f"거래량 {volume_ratio:.1f}배 급증")
    if b.breakout >= 12:
        reasons.append("20일 신고가 돌파(거래량 동반)" if intraday.current_price >= tech.recent_high_20d else "전고점 근접")
    if b.trend_alignment >= 10:
        reasons.append("이동평균 정배열(5>20>60일선)")
    if b.execution_strength >= 10:
        reasons.append(f"매수체결강도 우위({intraday.buy_execution_ratio:.0f})")
    if b.relative_strength >= 6:
        reasons.append("시장 대비 상대강도 우수")
    if b.news_disclosure >= 5:
        reasons.append("호재성 공시 감지")
    if b.overheat_penalty <= -5:
        reasons.append("단기 과열 주의(감점 반영)")
    return reasons


def apply_regime_multiplier(score_total: float, index_change_pct: float, regime_cfg: dict) -> float:
    if index_change_pct <= regime_cfg["crash_index_change_pct"]:
        return score_total * regime_cfg["crash_score_multiplier"]
    return score_total
