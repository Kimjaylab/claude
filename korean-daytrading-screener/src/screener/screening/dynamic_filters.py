from screener.brokers.base import BrokerClient
from screener.screening.models import IntradaySnapshot, TechnicalSnapshot
from screener.utils.logger import logger


def build_intraday_snapshot(
    broker: BrokerClient,
    tech: TechnicalSnapshot,
    index_change_pct: float,
    disclosure_score: float = 0.0,
) -> IntradaySnapshot | None:
    try:
        quote = broker.get_quote(tech.code)
        book = broker.get_order_book(tech.code)
    except Exception as exc:
        logger.warning(f"{tech.code} 실시간 조회 실패: {exc}")
        return None

    return IntradaySnapshot(
        code=tech.code,
        current_price=quote.current_price,
        open_price=quote.open_price,
        prev_close=quote.prev_close,
        cumulative_volume=quote.volume,
        cumulative_value=quote.trading_value,
        buy_execution_ratio=quote.buy_execution_ratio,
        bid_ask_volume_ratio=book.bid_ask_volume_ratio,
        index_change_pct=index_change_pct,
        disclosure_score=disclosure_score,
    )


def passes_liquidity_gate(
    intraday: IntradaySnapshot,
    min_today_cumulative_value_krw: float,
) -> bool:
    return intraday.cumulative_value >= min_today_cumulative_value_krw


def build_dynamic_candidates(
    broker: BrokerClient,
    static_candidates: list[TechnicalSnapshot],
    index_change_by_market: dict[str, float],
    disclosure_scores: dict[str, float],
    min_today_cumulative_value_krw: float,
) -> list[tuple[TechnicalSnapshot, IntradaySnapshot]]:
    results = []
    for tech in static_candidates:
        intraday = build_intraday_snapshot(
            broker,
            tech,
            index_change_by_market.get(tech.market, 0.0),
            disclosure_scores.get(tech.code, 0.0),
        )
        if intraday and passes_liquidity_gate(intraday, min_today_cumulative_value_krw):
            results.append((tech, intraday))
    logger.info(f"동적 필터 통과: {len(results)}종목 (실시간 조회 대상 {len(static_candidates)}종목)")
    return results
