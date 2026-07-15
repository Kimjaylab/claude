"""환경변수 기반 설정 로더."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_list(name: str, default: list[str]) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [s.strip().upper() for s in val.split(",") if s.strip()]


@dataclass
class KISConfig:
    app_key: str = field(default_factory=lambda: os.getenv("KIS_APP_KEY", ""))
    app_secret: str = field(default_factory=lambda: os.getenv("KIS_APP_SECRET", ""))
    account_no: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_NO", ""))
    account_product_cd: str = field(
        default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CD", "01")
    )
    # "paper" (모의투자) 또는 "real" (실전투자)
    mode: str = field(default_factory=lambda: os.getenv("KIS_MODE", "paper").lower())


@dataclass
class StrategyConfig:
    """역매공파 전략 파라미터. 모두 백테스트로 검증 후 조정할 것."""

    ma_short: int = int(os.getenv("STRAT_MA_SHORT", "112"))
    ma_mid: int = int(os.getenv("STRAT_MA_MID", "224"))
    ma_long: int = int(os.getenv("STRAT_MA_LONG", "448"))

    # 매집봉: 최근 N일 거래량 평균 대비 배율, 하락바닥 룩백 구간
    accumulation_lookback_days: int = int(os.getenv("STRAT_ACC_LOOKBACK", "60"))
    accumulation_volume_multiplier: float = float(os.getenv("STRAT_ACC_VOL_MULT", "2.0"))
    accumulation_wick_ratio: float = float(os.getenv("STRAT_ACC_WICK_RATIO", "0.3"))

    # 공구리: 매집봉 이후 저가 이탈 허용치, 확인 기간
    base_building_min_days: int = int(os.getenv("STRAT_BASE_MIN_DAYS", "5"))
    base_building_max_days: int = int(os.getenv("STRAT_BASE_MAX_DAYS", "20"))
    base_building_break_tolerance: float = float(os.getenv("STRAT_BASE_TOLERANCE", "0.03"))

    # 볼린저밴드(파란 점선) 스퀴즈 판단
    bb_window: int = int(os.getenv("STRAT_BB_WINDOW", "20"))
    bb_num_std: float = float(os.getenv("STRAT_BB_STD", "2.0"))
    bb_squeeze_lookback: int = int(os.getenv("STRAT_BB_SQUEEZE_LOOKBACK", "60"))
    bb_squeeze_percentile: float = float(os.getenv("STRAT_BB_SQUEEZE_PCTL", "0.25"))

    # 112일선 근접 판단 허용 오차
    ma_short_proximity_pct: float = float(os.getenv("STRAT_MA_SHORT_PROXIMITY", "0.03"))

    # 역배열 상태가 최소 며칠 이상 유지되어야 유효한 셋업으로 인정
    min_reverse_array_days: int = int(os.getenv("STRAT_MIN_REVERSE_DAYS", "20"))


@dataclass
class RiskConfig:
    take_profit_pct: float = float(os.getenv("RISK_TAKE_PROFIT_PCT", "0.05"))
    stop_loss_pct: float = float(os.getenv("RISK_STOP_LOSS_PCT", "-0.05"))
    # 종목 1개당 총자산 대비 최대 배분 비율
    max_position_pct: float = float(os.getenv("RISK_MAX_POSITION_PCT", "0.2"))
    max_open_positions: int = int(os.getenv("RISK_MAX_OPEN_POSITIONS", "5"))


@dataclass
class AppConfig:
    kis: KISConfig = field(default_factory=KISConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    watchlist: list[str] = field(
        default_factory=lambda: _get_list("WATCHLIST", ["AAPL", "MSFT", "NVDA"])
    )
    exchange: str = field(default_factory=lambda: os.getenv("EXCHANGE", "NAS"))
    poll_interval_sec: int = int(os.getenv("POLL_INTERVAL_SEC", "300"))
    state_file: str = os.getenv("STATE_FILE", "trading_bot_state.json")
    # 실전투자 안전장치: 명시적으로 "yes" 로 설정해야 실거래 주문 전송
    confirm_real_trading: bool = _get_bool("CONFIRM_REAL_TRADING", False)


def load_config() -> AppConfig:
    return AppConfig()
