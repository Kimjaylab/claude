"""inquire-price API의 원본 JSON 응답 전체를 찍어서 실제 필드명을 확인하는 진단용 스크립트.

체결강도(buy_execution_ratio) 계산에 쓰는 필드명이 맞는지 등을 확인할 때 사용한다.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screener.brokers.kis_client import TR_ID, KISClient
from screener.config import PROJECT_ROOT, load_secrets


def main() -> None:
    secrets = load_secrets()
    client = KISClient(
        app_key=secrets.kis_app_key,
        app_secret=secrets.kis_app_secret,
        account_no=secrets.kis_account_no,
        env=secrets.kis_env,
        token_cache_path=PROJECT_ROOT / ".kis_token_cache.json",
    )
    body = client._get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        TR_ID["current_price"],
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
    )
    print(json.dumps(body["output"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
