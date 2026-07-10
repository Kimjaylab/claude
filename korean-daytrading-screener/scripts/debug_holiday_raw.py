"""휴장일조회 API가 계속 500을 반환하는 원인을 확인하기 위해 원본 에러 본문을 그대로 찍는다.

kis_client._get()은 raise_for_status()가 먼저 걸려서 에러 본문을 볼 수 없으므로
여기서는 requests를 직접 써서 상태코드와 무관하게 응답 본문을 출력한다.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests

from screener.brokers.kis_client import KISClient
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
    token = client._ensure_token()

    resp = requests.get(
        f"{client.domain}/uapi/domestic-stock/v1/quotations/chk-holiday",
        headers={
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": client.app_key,
            "appsecret": client.app_secret,
            "tr_id": "CTCA0903R",
            "custtype": "P",
        },
        params={"BASS_DT": date.today().strftime("%Y%m%d"), "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        timeout=10,
    )
    print("status_code:", resp.status_code)
    print("body:", resp.text)


if __name__ == "__main__":
    main()
