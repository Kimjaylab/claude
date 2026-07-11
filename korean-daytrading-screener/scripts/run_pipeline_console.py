"""전체 스크리닝 파이프라인을 실제 KIS API로 돌려서 콘솔에 결과를 출력한다.

텔레그램 설정이나 09:05 발송 대기 없이 지금 바로 결과를 확인하고 싶을 때 쓴다.
휴장일(주말 등)에는 "오늘 누적 거래대금" 게이트를 통과하는 종목이 없어
후보가 0개로 나오는 게 정상이다 - 그래도 각 단계가 에러 없이 도는지 확인할 수 있다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.brokers.kis_client import KISClient
from screener.config import PROJECT_ROOT, load_screening_rules, load_secrets, load_settings
from screener.data.news_dart import DartClient
from screener.notify.telegram_bot import format_daily_report
from screener.pipeline import run_pipeline
from screener.utils.logger import setup_logger


def main() -> None:
    settings = load_settings()
    rules = load_screening_rules()
    setup_logger(PROJECT_ROOT / "logs", settings["logging"]["level"], settings["logging"]["retention_days"])

    secrets = load_secrets()
    if not secrets.kis_app_key:
        print("KIS_APP_KEY가 .env에 없습니다.")
        return

    broker = KISClient(
        app_key=secrets.kis_app_key,
        app_secret=secrets.kis_app_secret,
        account_no=secrets.kis_account_no,
        env=secrets.kis_env,
        token_cache_path=PROJECT_ROOT / ".kis_token_cache.json",
    )

    dart_client = None
    if secrets.dart_api_key:
        dart_client = DartClient(secrets.dart_api_key, PROJECT_ROOT / "data" / "dart")
        try:
            dart_client.load_corp_codes()
        except Exception as exc:
            print(f"DART 초기화 실패, 공시 스코어 없이 진행: {exc!r}")
            dart_client = None

    print(f"파이프라인 실행 시작 (env={secrets.kis_env}) ...\n")
    candidates, regime_note = run_pipeline(broker, dart_client, settings, rules)
    print("\n===== 결과 =====")
    print(format_daily_report(candidates, regime_note))


if __name__ == "__main__":
    main()
