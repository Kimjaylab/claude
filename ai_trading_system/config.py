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

# --- Loop timing ---------------------------------------------------------------
SCAN_INTERVAL_SECONDS = 300
