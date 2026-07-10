import pandas as pd

from screener.screening.static_filters import compute_technical_snapshot, passes_static_prefilter


def _make_uptrend_df(days: int = 90) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    closes = [10_000 * (1 + 0.003) ** i for i in range(days)]
    return pd.DataFrame(
        {
            "date": [d.strftime("%Y%m%d") for d in dates],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * days,
        }
    )


def test_uptrend_stock_passes_prefilter():
    df = _make_uptrend_df()
    snap = compute_technical_snapshot("005930", "테스트", "KOSPI", df)
    assert snap is not None
    assert snap.ma5 > snap.ma20 > snap.ma60
    assert passes_static_prefilter(snap)


def test_insufficient_history_returns_none():
    df = _make_uptrend_df(days=30)
    snap = compute_technical_snapshot("005930", "테스트", "KOSPI", df)
    assert snap is None


def test_downtrend_stock_fails_prefilter():
    days = 90
    dates = pd.date_range("2026-01-01", periods=days, freq="D")
    closes = [10_000 * (1 - 0.003) ** i for i in range(days)]
    df = pd.DataFrame(
        {
            "date": [d.strftime("%Y%m%d") for d in dates],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * days,
        }
    )
    snap = compute_technical_snapshot("000660", "테스트2", "KOSPI", df)
    assert snap is not None
    assert not passes_static_prefilter(snap)
