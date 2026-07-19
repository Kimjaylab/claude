"""CLI entry point.

  python main.py backtest --symbols BTC/USDT:USDT ETH/USDT:USDT --days 60
  python main.py run --mode dry_run
  python main.py run --mode testnet
  python main.py run --mode live      # requires LIVE_TRADING_CONFIRMATION in .env
"""
import argparse
import sys

import config


def cmd_backtest(args):
    from backtester import run_backtest

    for symbol in args.symbols:
        print(f"\n=== Backtesting {symbol} over {args.days}d ===")
        result = run_backtest(symbol, days=args.days, starting_equity=args.equity)
        print(f"  start equity   : {result.starting_equity:,.2f}")
        print(f"  end equity     : {result.ending_equity:,.2f}")
        print(f"  total return   : {result.total_return_pct:+.2f}%")
        print(f"  max drawdown   : {result.max_drawdown_pct:.2f}%")
        print(f"  win rate       : {result.win_rate_pct:.1f}%")
        print(f"  trade events   : {len(result.trades)}")


def cmd_run(args):
    from live_trader import LiveTrader

    trader = LiveTrader(mode=args.mode)
    trader.run_forever()


def main():
    parser = argparse.ArgumentParser(description="AI trading system")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run a historical simulation (no API key needed)")
    bt.add_argument("--symbols", nargs="+", default=["BTC/USDT:USDT", "ETH/USDT:USDT"])
    bt.add_argument("--days", type=int, default=60)
    bt.add_argument("--equity", type=float, default=10_000.0)
    bt.set_defaults(func=cmd_backtest)

    run = sub.add_parser("run", help="Run the live/testnet/dry-run trading loop")
    run.add_argument("--mode", choices=["dry_run", "testnet", "live"], default=config.TRADING_MODE)
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
