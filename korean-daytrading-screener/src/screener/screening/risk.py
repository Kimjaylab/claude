from screener.screening.models import IntradaySnapshot, RiskTargets, TechnicalSnapshot


def compute_risk_targets(tech: TechnicalSnapshot, intraday: IntradaySnapshot, rules: dict) -> RiskTargets:
    cfg = rules["targets"]
    grade_cfg = rules["risk_grade"]

    entry_price = intraday.current_price
    risk_amount = entry_price * (tech.atr_pct / 100) * cfg["stop_loss_atr_multiple"]
    stop_loss = max(entry_price - risk_amount, 0.0)
    target1 = entry_price + risk_amount * cfg["target1_risk_reward"]
    target2 = entry_price + risk_amount * cfg["target2_risk_reward"]

    if tech.atr_pct <= grade_cfg["low_atr_pct"]:
        risk_grade = "낮음"
    elif tech.atr_pct <= grade_cfg["medium_atr_pct"]:
        risk_grade = "중간"
    else:
        risk_grade = "높음"

    return RiskTargets(
        entry_price=round(entry_price, 0),
        stop_loss=round(stop_loss, 0),
        target1=round(target1, 0),
        target2=round(target2, 0),
        risk_grade=risk_grade,
    )
