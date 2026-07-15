"""'역매공파' 스윙 전략 (주식단테 기법 재구성).

전략 구성요소 (사용자 설명 기반):
  1. 역배열: 장기 이평선(112/224/448일)이 짧은 기간일수록 아래에 위치 (하락 추세 구조)
  2. 매집봉: 바닥권에서 평균 대비 거래량이 급증하며 아래꼬리를 남기는 캔들 (세력 매집 추정)
  3. 공구리: 매집봉 이후 저가가 견고하게 지지되는 바닥 다지기 구간
  4. 파란 점선(볼린저밴드) 에너지 응축: 밴드 폭이 좁아지며 변동성 확대 에너지가 쌓인 상태
  5. 112일선 근접: 단기 반등으로 주가가 112일선 부근까지 회복

주의: 원 기법은 정성적 설명(영상/블로그)에 기반하므로, 아래 판단 규칙은 이를 정량화한
근사치입니다. 실거래 투입 전 반드시 백테스트로 파라미터(trading_bot/config.py의
StrategyConfig)를 검증하세요.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import StrategyConfig
from .indicators import add_bollinger_bands, add_moving_averages, add_volume_average


@dataclass
class Signal:
    buy: bool
    index: int
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def prepare_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    df = df.copy()
    df = add_moving_averages(df, [cfg.ma_short, cfg.ma_mid, cfg.ma_long])
    df = add_bollinger_bands(df, window=cfg.bb_window, num_std=cfg.bb_num_std)
    df = add_volume_average(df, window=cfg.bb_window)
    return df


def _is_reverse_array(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    short = f"ma{cfg.ma_short}"
    mid = f"ma{cfg.ma_mid}"
    long = f"ma{cfg.ma_long}"
    window = df.iloc[max(0, i - cfg.min_reverse_array_days + 1): i + 1]
    if window[[short, mid, long]].isna().any().any():
        return False
    return bool((window[short] < window[mid]).all() and (window[mid] < window[long]).all())


def _find_accumulation_candle(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> int | None:
    """i 시점 이전 lookback 구간에서 매집봉 후보(거래량 급증 + 아래꼬리)를 최근 것부터 탐색."""
    start = max(0, i - cfg.accumulation_lookback_days)
    window = df.iloc[start:i + 1]
    if window.empty:
        return None
    rolling_low = window["low"].min()
    candidates = []
    for idx in window.index:
        row = df.loc[idx]
        vol_ma = row.get(f"vol_ma{cfg.bb_window}")
        if pd.isna(vol_ma) or vol_ma <= 0:
            continue
        if row["volume"] < vol_ma * cfg.accumulation_volume_multiplier:
            continue
        candle_range = row["high"] - row["low"]
        if candle_range <= 0:
            continue
        lower_wick = min(row["open"], row["close"]) - row["low"]
        wick_ratio = lower_wick / candle_range
        if wick_ratio < cfg.accumulation_wick_ratio:
            continue
        # 바닥권 근접: 해당 구간 최저가 대비 일정 범위 이내
        if row["low"] > rolling_low * (1 + cfg.base_building_break_tolerance):
            continue
        candidates.append(idx)
    if not candidates:
        return None
    return candidates[-1]


def _check_base_building(df: pd.DataFrame, acc_idx: int, i: int, cfg: StrategyConfig) -> bool:
    days_since = i - acc_idx
    if days_since < cfg.base_building_min_days or days_since > cfg.base_building_max_days:
        return False
    acc_low = df.loc[acc_idx, "low"]
    after = df.iloc[acc_idx + 1: i + 1]
    if after.empty:
        return False
    min_low_after = after["low"].min()
    return bool(min_low_after >= acc_low * (1 - cfg.base_building_break_tolerance))


def _check_bollinger_energy(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    start = max(0, i - cfg.bb_squeeze_lookback)
    window = df["bb_width"].iloc[start:i + 1].dropna()
    if window.empty or pd.isna(df.loc[i, "bb_width"]):
        return False
    threshold = window.quantile(cfg.bb_squeeze_percentile)
    return bool(df.loc[i, "bb_width"] <= threshold)


def _check_ma_short_proximity(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> bool:
    short_ma = df.loc[i, f"ma{cfg.ma_short}"]
    close = df.loc[i, "close"]
    if pd.isna(short_ma) or short_ma <= 0:
        return False
    return bool(abs(close - short_ma) / short_ma <= cfg.ma_short_proximity_pct)


def generate_signal(df: pd.DataFrame, i: int, cfg: StrategyConfig) -> Signal:
    reasons: list[str] = []
    details: dict = {}

    if not _is_reverse_array(df, i, cfg):
        return Signal(buy=False, index=i, reasons=["역배열 아님"])
    reasons.append("역배열 확인")

    acc_idx = _find_accumulation_candle(df, i, cfg)
    if acc_idx is None:
        return Signal(buy=False, index=i, reasons=reasons + ["매집봉 미발견"])
    reasons.append(f"매집봉 발견(idx={acc_idx})")
    details["accumulation_index"] = acc_idx

    if not _check_base_building(df, acc_idx, i, cfg):
        return Signal(buy=False, index=i, reasons=reasons + ["공구리(바닥다지기) 조건 불충족"])
    reasons.append("공구리 확인")

    if not _check_bollinger_energy(df, i, cfg):
        return Signal(buy=False, index=i, reasons=reasons + ["볼린저밴드 에너지 응축 조건 불충족"])
    reasons.append("볼린저밴드 스퀴즈(에너지 응축) 확인")

    if not _check_ma_short_proximity(df, i, cfg):
        return Signal(buy=False, index=i, reasons=reasons + [f"{cfg.ma_short}일선 근접 조건 불충족"])
    reasons.append(f"{cfg.ma_short}일선 근접 확인")

    return Signal(buy=True, index=i, reasons=reasons, details=details)
