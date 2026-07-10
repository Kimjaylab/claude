"""주식현재가 체결(inquire-ccnl) API의 원본 JSON 응답을 확인하는 진단 스크립트.

inquire-price에는 체결강도 필드가 없다는 게 확인돼서, 체결강도/매수매도체결량이
실제로 어떤 필드명으로 오는지 이 API에서 확인한다.
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
        "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
        TR_ID["execution_detail"],
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
    )
    output = body.get("output") or body.get("output1") or body
    if isinstance(output, list):
        print(json.dumps(output[0], ensure_ascii=False, indent=2))
        print(f"... 총 {len(output)}건 중 첫 건만 표시")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
