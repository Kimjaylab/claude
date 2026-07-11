import pytest

from screener.backtest.engine import _classify_regime, _index_daily_change_by_date, _simulate_exit
from screener.brokers.base import Candle
from screener.config import load_settings


def test_simulate_exit_stop_takes_priority_when_both_touched():
    settings = load_settings()
    exit_price, reason = _simulate_exit(
        entry=100, target1=110, target2=120, stop=90,
        day_high=125, day_low=85, day_close=105, settings=settings,
    )
    assert reason == "stop"
    assert exit_price < 90  # 슬리피지 반영으로 손절가보다 더 나쁨


def test_simulate_exit_target2_when_only_targets_touched():
    settings = load_settings()
    exit_price, reason = _simulate_exit(
        entry=100, target1=110, target2=120, stop=90,
        day_high=122, day_low=95, day_close=115, settings=settings,
    )
    assert reason == "target2"
    assert exit_price < 120


def test_simulate_exit_eod_when_nothing_touched():
    settings = load_settings()
    exit_price, reason = _simulate_exit(
        entry=100, target1=110, target2=120, stop=90,
        day_high=105, day_low=98, day_close=103, settings=settings,
    )
    assert reason == "eod"
    assert exit_price == 103


def test_classify_regime():
    settings = load_settings()
    assert _classify_regime(-2.0, settings) == "하락장"
    assert _classify_regime(1.0, settings) == "상승장"
    assert _classify_regime(0.1, settings) == "횡보장"


def test_index_daily_change_uses_open_vs_prev_close_no_lookahead():
    candles = [
        Candle("20260101", open=100, high=101, low=99, close=100, volume=1000),
        Candle("20260102", open=103, high=104, low=102, close=102, volume=1000),
    ]
    changes = _index_daily_change_by_date(candles)
    # 첫날은 전일 종가가 없어 등락률 계산 불가(제외), 둘째날은 전일(첫날) 종가 100 대비 시가 103
    assert "20260101" not in changes
    assert changes["20260102"] == pytest.approx(3.0)
