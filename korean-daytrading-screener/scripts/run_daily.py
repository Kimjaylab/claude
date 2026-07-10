"""launchd/cron이 매일 08:55~09:00경 1회 호출하는 진입점.

내부적으로 설정된 send_time(기본 09:05)까지 대기했다가 텔레그램으로 발송한다.
파이프라인 자체가 실패하더라도 로그를 남기고 텔레그램으로 오류를 알린다.
"""

import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.brokers.kis_client import KISClient
from screener.brokers.mock_client import MockClient
from screener.config import PROJECT_ROOT, load_screening_rules, load_secrets, load_settings
from screener.data.market_calendar import is_trading_day
from screener.data.news_dart import DartClient
from screener.notify.telegram_bot import TelegramNotifier, format_daily_report
from screener.pipeline import run_pipeline
from screener.utils.logger import logger, setup_logger


def _wait_until(target_hhmm: str) -> None:
    target_h, target_m = map(int, target_hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    remaining = (target - now).total_seconds()
    if remaining > 0:
        logger.info(f"{target_hhmm} 발송까지 {remaining:.0f}초 대기")
        time.sleep(remaining)


def main() -> int:
    settings = load_settings()
    rules = load_screening_rules()
    setup_logger(PROJECT_ROOT / "logs", settings["logging"]["level"], settings["logging"]["retention_days"])

    secrets = load_secrets()
    notifier = TelegramNotifier(secrets.telegram_bot_token, secrets.telegram_chat_id)

    if secrets.kis_app_key and secrets.kis_app_secret:
        broker = KISClient(
            app_key=secrets.kis_app_key,
            app_secret=secrets.kis_app_secret,
            account_no=secrets.kis_account_no,
            account_product_cd=secrets.kis_account_product_cd,
            env=secrets.kis_env,
            token_cache_path=PROJECT_ROOT / ".kis_token_cache.json",
        )
    else:
        logger.warning("KIS 인증정보 없음 - MockClient로 실행 (개발/테스트 모드)")
        broker = MockClient()

    dart_client = None
    if secrets.dart_api_key:
        dart_client = DartClient(secrets.dart_api_key, PROJECT_ROOT / "data" / "dart")
        try:
            dart_client.load_corp_codes()
        except Exception as exc:
            logger.warning(f"DART 초기화 실패, 공시 스코어 없이 진행: {exc}")
            dart_client = None

    today = date.today()
    if not is_trading_day(today, broker):
        logger.info(f"{today} 휴장일 - 스크리닝을 건너뜁니다.")
        return 0

    try:
        candidates, regime_note = run_pipeline(broker, dart_client, settings, rules)
    except Exception:
        logger.exception("파이프라인 실행 중 오류 발생")
        try:
            notifier.send("⚠️ 단타 스크리너 실행 중 오류가 발생했습니다. 로그를 확인해주세요.")
        except Exception:
            logger.exception("오류 알림 전송도 실패")
        return 1

    _wait_until(settings["schedule"]["send_time"])

    try:
        notifier.send(format_daily_report(candidates, regime_note))
    except Exception:
        logger.exception("텔레그램 발송 최종 실패 (재시도 소진)")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
