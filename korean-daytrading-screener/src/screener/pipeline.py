
from screener.brokers.base import BrokerClient
from screener.config import PROJECT_ROOT
from screener.data.news_dart import DartClient
from screener.data.ohlcv_store import OHLCVStore
from screener.data.universe import UniverseFilter
from screener.screening.dynamic_filters import build_dynamic_candidates
from screener.screening.models import Candidate
from screener.screening.risk import compute_risk_targets
from screener.screening.scoring import apply_regime_multiplier, compute_score
from screener.screening.static_filters import build_static_candidates
from screener.utils.logger import logger

MARKETS = ["KOSPI", "KOSDAQ"]


def collect_universe_candidates(broker: BrokerClient, universe: UniverseFilter, top_n: int = 150) -> dict[str, list]:
    """순위분석 API로 시장별 후보군을 압축한다 (전종목 개별 조회를 피하기 위함)."""
    by_market: dict[str, dict[str, str]] = {}
    for market in MARKETS:
        codes: dict[str, str] = {}
        for ranker in (broker.get_volume_rank, broker.get_fluctuation_rank, broker.get_trading_value_rank):
            try:
                for item in ranker(market, top_n=top_n):
                    if universe.is_investable(item.code, item.name):
                        codes[item.code] = item.name
            except Exception as exc:
                logger.warning(f"[{market}] 순위 API 조회 실패({ranker.__name__}): {exc}")
        by_market[market] = codes
        logger.info(f"[{market}] 순위분석 압축 후보: {len(codes)}종목")
    return by_market


def run_pipeline(
    broker: BrokerClient,
    dart_client: DartClient | None,
    settings: dict,
    rules: dict,
) -> tuple[list[Candidate], str | None]:
    universe = UniverseFilter(PROJECT_ROOT / "data" / "universe")
    universe.load()

    ohlcv_store = OHLCVStore(PROJECT_ROOT / "data" / "ohlcv")
    candidates_by_market = collect_universe_candidates(broker, universe)

    index_change_by_market = {}
    for market in MARKETS:
        try:
            index_change_by_market[market] = broker.get_index_change_pct(market)
        except Exception as exc:
            logger.warning(f"{market} 지수 조회 실패: {exc}")
            index_change_by_market[market] = 0.0

    all_candidates: list[Candidate] = []
    for market, codes_names in candidates_by_market.items():
        if not codes_names:
            continue
        ohlcv = ohlcv_store.bulk_update(broker, list(codes_names.keys()))
        static_snaps = build_static_candidates(
            ohlcv, codes_names, market, settings["universe"]["min_listed_days"]
        )

        disclosure_scores = {}
        if dart_client:
            for snap in static_snaps:
                try:
                    disclosures = dart_client.get_recent_disclosures(snap.code)
                    disclosure_scores[snap.code] = dart_client.score_disclosures(
                        disclosures, rules["weights"]["news_disclosure"]["positive_keywords"]
                    )
                except Exception as exc:
                    logger.warning(f"{snap.code} 공시 조회 실패: {exc}")

        dynamic_pairs = build_dynamic_candidates(
            broker,
            static_snaps,
            index_change_by_market,
            disclosure_scores,
            settings["universe"]["min_today_cumulative_value_krw"],
        )

        for tech, intraday in dynamic_pairs:
            breakdown, reasons = compute_score(tech, intraday, rules)
            adjusted_total = apply_regime_multiplier(
                breakdown.total, intraday.index_change_pct, settings["market_regime"]
            )
            risk = compute_risk_targets(tech, intraday, rules)
            candidate = Candidate(
                technical=tech,
                intraday=intraday,
                score=breakdown,
                risk=risk,
                reasons=reasons,
                adjusted_total=adjusted_total,
            )
            all_candidates.append(candidate)

    regime_note = _build_regime_note(index_change_by_market, settings["market_regime"])
    max_candidates = settings["market_regime"]["crash_max_candidates"] if regime_note else settings["notification"]["max_candidates"]

    filtered = [c for c in all_candidates if c.final_score >= settings["notification"]["min_score_to_send"]]
    filtered.sort(key=lambda c: c.final_score, reverse=True)
    return filtered[:max_candidates], regime_note


def _build_regime_note(index_change_by_market: dict[str, float], regime_cfg: dict) -> str | None:
    crashed = [m for m, chg in index_change_by_market.items() if chg <= regime_cfg["crash_index_change_pct"]]
    if not crashed:
        return None
    details = ", ".join(f"{m} {index_change_by_market[m]:+.1f}%" for m in crashed)
    return f"시장 약세({details}) - 발송 종목 수를 축소하고 점수에 페널티를 적용했습니다."
