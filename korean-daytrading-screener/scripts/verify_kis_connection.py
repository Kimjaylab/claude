"""KIS Developers 실제 연동 확인용 스크립트.

.env에 KIS_APP_KEY/KIS_APP_SECRET/KIS_ENV=paper 를 채운 뒤 맥북에서 직접 실행한다.
토큰 발급 -> 삼성전자 현재가 조회 -> 거래량순위 조회 순으로 확인하며,
kis_client.py의 TR_ID/필드명이 실제 응답과 다르면 여기서 바로 에러 메시지로 드러난다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.brokers.kis_client import KISClient
from screener.config import PROJECT_ROOT, load_secrets


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

    print(f"[1/3] 토큰 발급 시도 (env={secrets.kis_env}) ...")
    try:
        token = client._ensure_token()
        print(f"      OK: {token[:15]}...")
    except Exception as exc:
        print(f"      FAIL: {exc!r}")
        return

    print("[2/3] 삼성전자(005930) 현재가 조회 ...")
    try:
        quote = client.get_quote("005930")
        print(f"      OK: {quote}")
    except Exception as exc:
        print(f"      FAIL: {exc!r}")

    print("[3/3] 코스피 거래량순위 조회 ...")
    try:
        items = client.get_volume_rank("KOSPI", top_n=5)
        for item in items:
            print(f"      {item.rank}. {item.name}({item.code}) - {item.value:,.0f}")
    except Exception as exc:
        print(f"      FAIL: {exc!r}")


if __name__ == "__main__":
    main()
