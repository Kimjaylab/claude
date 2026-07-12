from datetime import date, timedelta

import pandas as pd

from screener.backtest.models import Trade
from screener.brokers.base import BrokerClient
from screener.data.news_dart import DartClient
from screener.data.universe import UniverseFilter
from screener.screening.models import IntradaySnapshot
from screener.screening.risk import compute_risk_targets
from screener.screening.scoring import compute_score
from screener.screening.static_filters import (
    FIVE_MIN_SLICES,
    compute_technical_snapshot,
    passes_static_prefilter,
)
from screener.utils.logger import logger

MARKETS = ["KOSPI", "KOSDAQ"]


def build_backtest_universe(
    broker: BrokerClient, universe: UniverseFilter, settings: dict
) -> list[tuple[str, str, str]]:
    """라이브 유니버스 필터(시총/ETF/관리종목 등)를 통과하는 유동성 상위 종목을 한 번만 고정 선정한다.

    "거래대금 상위 N종목"을 그냥 쓰지 않고 실전 필터를 동일하게 적용하는 이유는,
    실전 시스템이 실제로 추천할 법한 중소형 단타주 성격을 백테스트 유니버스가
    반영하도록 하기 위함이다(대형주 위주 유니버스는 실전과 괴리가 커진다).
    """
    universe_size = settings["backtest"]["universe_size_per_market"]
    min_market_cap = settings["universe"]["min_market_cap_krw"]
    # 현재가 조회 API가 (주말 점검 등으로) 통째로 막혀 있으면 종목마다 재시도로 몇 시간을
    # 날리는 대신, 연속 실패가 임계치를 넘는 순간 시총 확인을 포기하고 나머지는
    # 유동성(거래대금순위) 기준만으로 통과시킨다.
    consecutive_failure_limit = 5

    result: list[tuple[str, str, str]] = []
    for market in MARKETS:
        # 순위 API 1개는 한 번에 30개 안팎만 반환해(페이지네이션 미구현) 3종류를 합쳐 폭을 넓힌다.
        candidates_by_code: dict[str, object] = {}
        for ranker in (broker.get_trading_value_rank, broker.get_volume_rank, broker.get_fluctuation_rank):
            try:
                for item in ranker(market, top_n=universe_size):
                    candidates_by_code[item.code] = item
            except Exception as exc:
                logger.warning(f"[{market}] {ranker.__name__} 조회 실패: {exc}")
        candidates = list(candidates_by_code.values())
        if not candidates:
            logger.warning(f"[{market}] 백테스트 유니버스 조회 실패: 순위 API 전부 실패")
            continue

        kept = 0
        skipped_cap_check = 0
        consecutive_failures = 0
        quote_api_down = False
        for item in candidates:
            if not universe.is_investable(item.code, item.name):
                continue

            if quote_api_down:
                result.append((item.code, item.name, market))
                kept += 1
                skipped_cap_check += 1
                continue

            try:
                quote = broker.get_quote(item.code)
                consecutive_failures = 0
            except Exception as exc:
                consecutive_failures += 1
                if consecutive_failures >= consecutive_failure_limit:
                    logger.warning(
                        f"[{market}] 현재가 조회 API가 응답하지 않아(연속 {consecutive_failures}회 실패) "
                        f"시총 확인을 생략하고 거래대금순위만으로 유니버스를 구성합니다: {exc}"
                    )
                    quote_api_down = True
                    result.append((item.code, item.name, market))
                    kept += 1
                    skipped_cap_check += 1
                continue

            if quote.market_cap < min_market_cap:
                continue
            result.append((item.code, item.name, market))
            kept += 1
        note = f" (시총 미확인 {skipped_cap_check}건 포함)" if skipped_cap_check else ""
        logger.info(f"[{market}] 백테스트 유니버스: {kept}/{len(candidates)}종목 통과{note}")
    return result


def _classify_regime(index_change_pct: float, settings: dict) -> str:
    regime_cfg = settings["market_regime"]
    backtest_cfg = settings["backtest"]
    if index_change_pct <= regime_cfg["crash_index_change_pct"]:
        return "하락장"
    if index_change_pct >= backtest_cfg["uptrend_index_change_pct"]:
        return "상승장"
    return "횡보장"


def _index_daily_change_by_date(candles) -> dict[str, float]:
    """지수 일봉에서 '시가 vs 전일종가' 등락률(%)을 날짜별로 계산 (09:05 시점 근사, 룩어헤드 없음)."""
    rows = sorted(candles, key=lambda c: c.timestamp)
    result = {}
    prev_close = None
    for c in rows:
        if prev_close is not None and prev_close > 0:
            result[c.timestamp] = (c.open / prev_close - 1) * 100
        prev_close = c.close
    return result


def _simulate_exit(entry: float, target1: float, target2: float, stop: float, day_high: float, day_low: float, day_close: float, settings: dict) -> tuple[float, str]:
    cfg = settings["backtest"]
    # 저가가 손절가 이하이면, 목표가도 같이 닿았더라도 보수적으로 손절이 먼저 발생했다고 가정한다
    # (분봉이 없어 당일 고가/저가의 실제 도달 순서를 알 수 없기 때문).
    if day_low <= stop:
        return stop * (1 - cfg["stop_slippage_pct"] / 100), "stop"
    if day_high >= target2:
        return target2 * (1 - cfg["target_slippage_pct"] / 100), "target2"
    if day_high >= target1:
        return target1 * (1 - cfg["target_slippage_pct"] / 100), "target1"
    return day_close, "eod"


def run_backtest(
    broker: BrokerClient,
    dart_client: DartClient | None,
    universe: list[tuple[str, str, str]],
    start: date,
    end: date,
    settings: dict,
    rules: dict,
) -> list[Trade]:
    fetch_start = start - timedelta(days=180)  # 이평선/RSI 계산용 선행 데이터
    split_cutoff = start + (end - start) * (1 - settings["backtest"]["out_of_sample_ratio"])
    min_listed_days = settings["universe"]["min_listed_days"]
    round_trip_cost = settings["backtest"]["round_trip_cost_pct"]

    index_change_by_market: dict[str, dict[str, float]] = {}
    for market in MARKETS:
        try:
            candles = broker.get_index_daily_candles(market, fetch_start, end)
            index_change_by_market[market] = _index_daily_change_by_date(candles)
        except Exception as exc:
            logger.warning(f"[{market}] 지수 일봉 조회 실패, 상대강도/레짐 분류를 중립으로 대체: {exc}")
            index_change_by_market[market] = {}

    trades: list[Trade] = []
    for code, name, market in universe:
        try:
            candles = broker.get_daily_candles(code, fetch_start, end)
        except Exception as exc:
            logger.warning(f"{code} 일봉 조회 실패: {exc}")
            continue
        if len(candles) < 80:
            continue

        df = pd.DataFrame(
            [{"date": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles]
        ).sort_values("date").reset_index(drop=True)

        index_changes = index_change_by_market.get(market, {})

        for i in range(60, len(df)):
            day = df.iloc[i]
            day_date = pd.to_datetime(day["date"]).date()
            if day_date < start or day_date > end:
                continue

            hist = df.iloc[:i]
            tech = compute_technical_snapshot(code, name, market, hist, min_listed_days)
            if tech is None or not passes_static_prefilter(tech):
                continue

            index_change_pct = index_changes.get(day["date"], 0.0)
            disclosure_score = _historical_disclosure_score(dart_client, code, day_date, rules)

            entry = float(day["open"])

            # honest: 룩어헤드 성분(당일 거래량) 제외, reference: 당일 전체 거래량을 09:05 근사치로 포함(상한선 추정)
            honest_intraday = IntradaySnapshot(
                code=code, current_price=entry, open_price=entry, prev_close=tech.prev_close,
                cumulative_volume=0, cumulative_value=0, buy_execution_ratio=100.0,
                bid_ask_volume_ratio=1.0, index_change_pct=index_change_pct, disclosure_score=disclosure_score,
            )
            # compute_score의 volume_ratio = cumulative_volume / avg_5min_volume_20d 이므로,
            # 당일 전체 거래량을 5분 단위 기준선과 같은 스케일로 맞추기 위해 78(=390/5)로 나눈다.
            reference_intraday = IntradaySnapshot(
                code=code, current_price=entry, open_price=entry, prev_close=tech.prev_close,
                cumulative_volume=int(day["volume"] / FIVE_MIN_SLICES), cumulative_value=0,
                buy_execution_ratio=100.0, bid_ask_volume_ratio=1.0,
                index_change_pct=index_change_pct, disclosure_score=disclosure_score,
            )
            honest_score, _ = compute_score(tech, honest_intraday, rules)
            reference_score, _ = compute_score(tech, reference_intraday, rules)

            risk = compute_risk_targets(tech, reference_intraday, rules)
            exit_price, reason = _simulate_exit(
                entry, risk.target1, risk.target2, risk.stop_loss,
                float(day["high"]), float(day["low"]), float(day["close"]), settings,
            )
            return_pct = (exit_price / entry - 1) * 100 - round_trip_cost

            trades.append(
                Trade(
                    code=code, name=name, market=market, date=day["date"],
                    entry=entry, exit=exit_price, exit_reason=reason, return_pct=return_pct,
                    score_honest=honest_score.total, score_reference=reference_score.total,
                    index_regime=_classify_regime(index_change_pct, settings),
                    split="in_sample" if day_date < split_cutoff else "out_of_sample",
                )
            )

    logger.info(f"백테스트 완료: {len(trades)}건의 신호 생성")
    return trades


def _historical_disclosure_score(dart_client: DartClient | None, code: str, day_date: date, rules: dict) -> float:
    if dart_client is None:
        return 0.0
    try:
        # 당일 공시는 발표 시각을 알 수 없어 룩어헤드 위험이 있으므로 전일까지만 사용한다.
        cutoff = day_date - timedelta(days=1)
        disclosures = dart_client.get_recent_disclosures_as_of(code, cutoff, days=2)
        return dart_client.score_disclosures(disclosures, rules["weights"]["news_disclosure"]["positive_keywords"])
    except Exception:
        return 0.0
