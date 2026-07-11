"""과거 데이터로 스크리닝 전략을 검증한다.

주의: look-ahead bias를 피하기 위해 "honest" 점수(당일 거래량 성분 제외)와
"reference" 점수(당일 전체 거래량을 09:05 근사치로 포함, 상한선 추정치)를 분리해서 보고한다.
reference 쪽 숫자를 실전 기대 성과로 오해하지 말 것 - 어디까지나 참고용 상한선이다.
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.backtest.engine import build_backtest_universe, run_backtest
from screener.backtest.metrics import BacktestReport, PerformanceSummary, build_report
from screener.brokers.kis_client import KISClient
from screener.config import PROJECT_ROOT, load_screening_rules, load_secrets, load_settings
from screener.data.news_dart import DartClient
from screener.data.universe import UniverseFilter
from screener.utils.logger import setup_logger


def main() -> None:
    settings = load_settings()
    rules = load_screening_rules()
    setup_logger(PROJECT_ROOT / "logs", settings["logging"]["level"], settings["logging"]["retention_days"])

    secrets = load_secrets()
    if not secrets.kis_app_key:
        print("KIS_APP_KEY가 .env에 없습니다.")
        return

    broker = KISClient(
        app_key=secrets.kis_app_key, app_secret=secrets.kis_app_secret,
        account_no=secrets.kis_account_no, env=secrets.kis_env,
        token_cache_path=PROJECT_ROOT / ".kis_token_cache.json",
    )

    dart_client = None
    if secrets.dart_api_key:
        dart_client = DartClient(secrets.dart_api_key, PROJECT_ROOT / "data" / "dart")
        try:
            dart_client.load_corp_codes()
        except Exception as exc:
            print(f"DART 초기화 실패, 공시 스코어 없이 진행: {exc!r}")
            dart_client = None

    universe_filter = UniverseFilter(PROJECT_ROOT / "data" / "universe")
    universe_filter.load()

    print("백테스트 유니버스 구성 중 (시총/ETF/관리종목 필터 적용) ...")
    universe = build_backtest_universe(broker, universe_filter, settings)
    print(f"유니버스: {len(universe)}종목\n")

    end = date.today()
    start = end - timedelta(days=365 * settings["backtest"]["lookback_years"])
    print(f"백테스트 기간: {start} ~ {end} (일봉 근사, 상세 가정은 README 참고)\n")

    trades = run_backtest(broker, dart_client, universe, start, end, settings, rules)
    if not trades:
        print("생성된 거래 신호가 없습니다.")
        return

    _save_trades_csv(trades, PROJECT_ROOT / "data" / "backtest_trades.csv")

    min_score = settings["notification"]["min_score_to_send"]
    for score_field, label in [("score_honest", "HONEST (룩어헤드 없음, 신뢰 가능)"), ("score_reference", "REFERENCE (거래량 포함, 상한선 참고용)")]:
        print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
        for split in ("in_sample", "out_of_sample"):
            split_trades = [t for t in trades if t.split == split]
            report = build_report(split_trades, score_field, min_score, settings)
            _print_report(f"[{split}]", report)


def _print_report(title: str, report: BacktestReport) -> None:
    print(f"\n--- {title} ---")
    _print_summary("전체", report.overall)
    print(f"  CAGR: {report.cagr_pct:.1f}%  Sharpe: {report.sharpe:.2f}  Calmar: {report.calmar:.2f}")

    print("  [연도별]")
    for year, s in sorted(report.yearly.items()):
        _print_summary(f"    {year}", s, indent=True)

    print("  [시장 국면별]")
    for regime, s in report.by_regime.items():
        _print_summary(f"    {regime}", s, indent=True)

    print("  [점수 구간별]")
    for bucket, s in sorted(report.by_score_bucket.items()):
        _print_summary(f"    {bucket}점", s, indent=True)


def _print_summary(label: str, s: PerformanceSummary, indent: bool = False) -> None:
    reliability = "" if s.reliable else " (표본 부족, 신뢰 불가)"
    print(
        f"{label}: {s.trade_count}건, 승률 {s.win_rate:.1f}%, 평균수익 {s.avg_return_pct:.2f}%, "
        f"평균손실 {s.avg_loss_pct:.2f}%, 손익비 {s.profit_factor:.2f}, 기대값 {s.expectancy_pct:.2f}%, "
        f"MDD {s.mdd_pct:.1f}%{reliability}"
    )


def _save_trades_csv(trades, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["date", "code", "name", "market", "entry", "exit", "exit_reason", "return_pct",
             "score_honest", "score_reference", "index_regime", "split"]
        )
        for t in trades:
            writer.writerow(
                [t.date, t.code, t.name, t.market, t.entry, t.exit, t.exit_reason, t.return_pct,
                 t.score_honest, t.score_reference, t.index_regime, t.split]
            )
    print(f"거래 로그 저장: {path}")


if __name__ == "__main__":
    main()
