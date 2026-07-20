"""Central configuration for the AI trading system.

All tunable constants from the trading spec live here so strategy code
never hardcodes a magic number.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Exchange credentials / mode -------------------------------------------------
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# "testnet" | "dry_run" | "live"
TRADING_MODE = os.getenv("TRADING_MODE", "dry_run").lower()
LIVE_TRADING_CONFIRMATION = os.getenv("LIVE_TRADING_CONFIRMATION", "")
LIVE_CONFIRMATION_PHRASE = "I_UNDERSTAND_THE_RISK"

# --- Market scanner ---------------------------------------------------------------
TOP_N_SYMBOLS = 30
QUOTE_ASSET = "USDT"
# Fallback safety net for tokenized-stock/commodity USDT perpetuals that
# Binance may list without a usable `underlyingType` field in the market
# metadata. Extend this if new non-crypto tickers show up in the scan logs
# ("Excluded N non-crypto USDT perpetual(s)...").
NON_CRYPTO_BASE_DENYLIST = {"XAU", "XAG", "MU"}
ADX_PERIOD = 14
ADX_TRENDING_THRESHOLD = 25
BB_PERIOD = 20
BB_STD_DEV = 2.0
# Bollinger bandwidth (as % of the middle band) below this is considered "squeezed".
BB_SQUEEZE_WIDTH_PCT = 4.0
REGIME_TIMEFRAMES = ["1h", "4h"]

# --- Grid strategy (ranging regime) -----------------------------------------------
GRID_BOX_LOOKBACK_DAYS = 3
GRID_LEVELS = 10
GRID_BOX_BREACH_PCT = 0.01  # 1% close-based breach triggers stop-loss + shutdown

# --- Trend strategy (trending regime) ---------------------------------------------
RSI_PERIOD = 14
TREND_SIGNAL_TIMEFRAME = "15m"
SWING_LOOKBACK_BARS = 20
OI_DROP_LOOKBACK_BARS = 4
OI_DROP_THRESHOLD_PCT = 3.0  # OI drop of >=3% flags "OI declining" for short setup

# --- Risk management ---------------------------------------------------------------
LEVERAGE = 5
MARGIN_MODE = "ISOLATED"
RISK_REWARD_RATIO = 2.0  # TP distance = RISK_REWARD_RATIO * SL distance
DAILY_LOSS_LIMIT_PCT = 0.03  # -3% of start-of-day equity halts trading
LOCKOUT_HOURS = 24
RISK_PER_TRADE_PCT = 0.01  # fraction of equity risked (SL distance) per trade

# Caps how many symbols can have capital deployed at the same time. Each
# concurrent slot gets equity / MAX_CONCURRENT_POSITIONS as its sizing
# budget, so the sum across every open grid + trend position stays bounded
# by LEVERAGE * equity account-wide -- not LEVERAGE * equity *per symbol*,
# which is what "5x leverage" is supposed to mean.
MAX_CONCURRENT_POSITIONS = 5

# --- Loop timing ---------------------------------------------------------------
SCAN_INTERVAL_SECONDS = 300

# --- Persistence -------------------------------------------------------------------
# Survives process restarts so a crash mid-lockout can't quietly re-arm the
# daily loss circuit breaker with a fresh baseline.
RISK_STATE_FILE = os.getenv("RISK_STATE_FILE", "state/risk_state.json")
