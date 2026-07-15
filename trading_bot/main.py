"""CLI 진입점.

사용 예:
  python -m trading_bot.main backtest --csv-dir ./data
  python -m trading_bot.main trade
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .config import load_config
from .data import load_csv
from .live import LiveTrader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def cmd_backtest(args: argparse.Namespace) -> None:
    cfg = load_config()
    csv_dir = Path(args.csv_dir)
    if not csv_dir.is_dir():
        print(f"CSV 디렉터리를 찾을 수 없습니다: {csv_dir}", file=sys.stderr)
        sys.exit(1)

    data_by_symbol: dict[str, pd.DataFrame] = {}
    for csv_path in sorted(csv_dir.glob("*.csv")):
        symbol = csv_path.stem.upper()
        data_by_symbol[symbol] = load_csv(str(csv_path))

    if not data_by_symbol:
        print(f"{csv_dir} 안에 CSV 파일이 없습니다 (파일명이 종목코드여야 합니다, 예: AAPL.csv).",
              file=sys.stderr)
        sys.exit(1)

    result = run_backtest(data_by_symbol, cfg.strategy, cfg.risk)
    print(result.summary())
    if args.output:
        result.to_dataframe().to_csv(args.output, index=False)
        print(f"거래내역 저장: {args.output}")


def cmd_trade(args: argparse.Namespace) -> None:
    cfg = load_config()
    trader = LiveTrader(cfg)
    if args.once:
        trader.run_once()
    else:
        trader.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="역매공파 스윙 자동매매 봇 (KIS API)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bt = sub.add_parser("backtest", help="과거 CSV 데이터로 전략 백테스트")
    p_bt.add_argument("--csv-dir", required=True, help="종목별 CSV가 있는 디렉터리 (파일명=종목코드.csv)")
    p_bt.add_argument("--output", help="거래내역을 저장할 CSV 경로")
    p_bt.set_defaults(func=cmd_backtest)

    p_trade = sub.add_parser("trade", help="자동매매 실행 (기본: 모의투자)")
    p_trade.add_argument("--once", action="store_true", help="루프 없이 1회만 실행")
    p_trade.set_defaults(func=cmd_trade)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
