"""이동평균/볼린저밴드 등 보조지표 계산."""
from __future__ import annotations

import pandas as pd


def add_moving_averages(df: pd.DataFrame, windows: list[int], price_col: str = "close") -> pd.DataFrame:
    for w in windows:
        df[f"ma{w}"] = df[price_col].rolling(window=w, min_periods=w).mean()
    return df


def add_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2.0,
                         price_col: str = "close") -> pd.DataFrame:
    mid = df[price_col].rolling(window=window, min_periods=window).mean()
    std = df[price_col].rolling(window=window, min_periods=window).std()
    df["bb_mid"] = mid
    df["bb_upper"] = mid + num_std * std
    df["bb_lower"] = mid - num_std * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    return df


def add_volume_average(df: pd.DataFrame, window: int = 20, volume_col: str = "volume") -> pd.DataFrame:
    df[f"vol_ma{window}"] = df[volume_col].rolling(window=window, min_periods=window).mean()
    return df
