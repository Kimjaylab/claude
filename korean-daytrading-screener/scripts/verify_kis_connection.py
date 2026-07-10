"""KIS Developers 실제 연동 확인용 스크립트.

.env에 KIS_APP_KEY/KIS_APP_SECRET/KIS_ENV=paper 를 채운 뒤 맥북에서 직접 실행한다.
브로커 어댑터가 구현한 모든 조회 기능을 한 번에 점검해, kis_client.py의 TR_ID/필드명이
실제 응답과 다른 부분이 있으면 여기서 바로 에러 메시지로 드러난다.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.brokers.kis_client import KISClient
from screener.config import PROJECT_ROOT, load_secrets

TEST_CODE = "005930"  # 삼성전자


def _step(label: str, fn) -> None:
    print(f"[{label}] ...")
    try:
        result = fn()
        print(f"      OK: {result}")
    except Exception as exc:
        print(f"      FAIL: {exc!r}")


def main() -> None:
    secrets = load_secrets()
    if not secrets.kis_app_key or not secrets.kis_app_secret:
        print("KIS_APP_KEY / KIS_APP_SECRET이 .env에 없습니다.")
        return

    client = KISClient(
        app_key=secrets.kis_app_key,
        app_secret=secrets.kis_app_secret,
        account_no=secrets.kis_account_no,
        env=secrets.kis_env,
        token_cache_path=PROJECT_ROOT / ".kis_token_cache.json",
    )

    print(f"[토큰] 발급 시도 (env={secrets.kis_env}) ...")
    try:
        token = client._ensure_token()
        print(f"      OK: {token[:15]}...")
    except Exception as exc:
        print(f"      FAIL: {exc!r}")
        return

    _step("현재가 조회", lambda: client.get_quote(TEST_CODE))
    _step("호가 조회", lambda: client.get_order_book(TEST_CODE))

    end = date.today()
    start = end - timedelta(days=30)
    _step("일봉 조회(최근 30일)", lambda: _summarize_candles(client.get_daily_candles(TEST_CODE, start, end)))
    _step("당일 분봉 조회", lambda: _summarize_candles(client.get_today_minute_candles(TEST_CODE)))

    _step("코스피 거래량순위", lambda: _summarize_rank(client.get_volume_rank("KOSPI", top_n=5)))
    _step("코스피 등락률순위", lambda: _summarize_rank(client.get_fluctuation_rank("KOSPI", top_n=5)))
    _step("코스피 거래대금순위", lambda: _summarize_rank(client.get_trading_value_rank("KOSPI", top_n=5)))
    _step("코스피 지수 등락률", lambda: client.get_index_change_pct("KOSPI"))
    _step("휴장일 여부(오늘)", lambda: client.is_market_holiday(date.today()))


def _summarize_candles(candles) -> str:
    if not candles:
        return "0건 (빈 응답)"
    last = candles[-1]
    return f"{len(candles)}건, 마지막: {last.timestamp} 종가={last.close:,.0f} 거래량={last.volume:,}"


def _summarize_rank(items) -> str:
    return " | ".join(f"{i.rank}.{i.name}({i.code})={i.value:,.1f}" for i in items)


if __name__ == "__main__":
    main()
