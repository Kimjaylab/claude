import requests

from screener.screening.models import Candidate
from screener.utils.logger import logger
from screener.utils.retry import with_retry

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

GRADE_BY_SCORE = [(85, "S"), (75, "A"), (65, "B"), (0, "C")]


def _grade(total_score: float) -> str:
    for threshold, grade in GRADE_BY_SCORE:
        if total_score >= threshold:
            return grade
    return "C"


def format_candidate_message(c: Candidate) -> str:
    stock_change_pct = (c.intraday.current_price / c.intraday.prev_close - 1) * 100 if c.intraday.prev_close else 0.0
    volume_ratio = (
        c.intraday.cumulative_volume / c.technical.avg_5min_volume_20d
        if c.technical.avg_5min_volume_20d > 0
        else 0.0
    )
    reasons = " + ".join(c.reasons) if c.reasons else "복합 조건 충족"

    return (
        f"📈 {c.name} ({c.code})\n"
        f"현재가: {c.intraday.current_price:,.0f}원 ({stock_change_pct:+.1f}%)\n"
        f"거래량 증가율: 평상시比 {volume_ratio:.1f}배\n"
        f"거래대금: {c.intraday.cumulative_value / 1e8:,.1f}억원\n"
        f"추천 점수: {c.final_score:.0f}/100 (등급: {_grade(c.final_score)})\n"
        f"추천 이유: {reasons}\n"
        f"진입가: {c.risk.entry_price:,.0f}원\n"
        f"손절가: {c.risk.stop_loss:,.0f}원 "
        f"({(c.risk.stop_loss / c.risk.entry_price - 1) * 100:+.1f}%)\n"
        f"1차 목표가: {c.risk.target1:,.0f}원 "
        f"({(c.risk.target1 / c.risk.entry_price - 1) * 100:+.1f}%)\n"
        f"2차 목표가: {c.risk.target2:,.0f}원 "
        f"({(c.risk.target2 / c.risk.entry_price - 1) * 100:+.1f}%)\n"
        f"위험도: {c.risk.risk_grade} (ATR {c.technical.atr_pct:.1f}%)"
    )


def format_daily_report(candidates: list[Candidate], regime_note: str | None) -> str:
    today_header = "📊 오늘의 단타 후보 종목"
    if not candidates:
        body = "조건을 만족하는 후보가 없습니다. 오늘은 쉬어가는 것도 전략입니다."
        return f"{today_header}\n\n{body}" + (f"\n\n⚠️ {regime_note}" if regime_note else "")

    parts = [today_header]
    if regime_note:
        parts.append(f"⚠️ {regime_note}")
    parts.append("")
    for c in candidates:
        parts.append(format_candidate_message(c))
        parts.append("")
    return "\n".join(parts).strip()


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @with_retry(exceptions=(requests.RequestException,), attempts=4)
    def send(self, text: str) -> None:
        # 텔레그램 메시지는 4096자 제한이 있어 필요 시 분할 전송한다.
        for chunk in _split_message(text):
            resp = requests.post(
                TELEGRAM_API.format(token=self.bot_token),
                json={"chat_id": self.chat_id, "text": chunk},
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                raise RuntimeError(f"텔레그램 전송 실패: {body}")
        logger.info("텔레그램 발송 완료")


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current = [], []
    length = 0
    for block in text.split("\n\n"):
        if length + len(block) + 2 > limit:
            chunks.append("\n\n".join(current))
            current, length = [], 0
        current.append(block)
        length += len(block) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks
