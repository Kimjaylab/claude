"""한국투자증권(KIS Developers) 해외주식 REST API 클라이언트.

주의: TR ID/엔드포인트는 KIS 공식 GitHub(koreainvestment/open-trading-api)와
apiportal.koreainvestment.com 문서를 기준으로 작성했습니다. KIS가 문서를
개정할 수 있으므로 실거래 투입 전 반드시 최신 공식 문서와 대조 확인하세요.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"

# 해외주식 매수/매도 TR ID (실전). 모의투자는 앞에 V를 붙인다.
TR_ORDER_BUY_REAL = "TTTT1002U"
TR_ORDER_SELL_REAL = "TTTT1006U"

TR_BALANCE_REAL = "TTTS3012R"

# 시세 조회 TR (실전/모의 공통)
TR_CURRENT_PRICE = "HHDFS00000300"
TR_DAILY_PRICE = "HHDFS76240000"

_TOKEN_CACHE_FILE = Path(".kis_token_cache.json")

# "초당 거래건수를 초과하였습니다" - TR별 초당 호출 제한 초과 시 KIS가 내려주는 코드.
# 모의투자 계좌는 이 제한이 더 엄격해서, 요청 간 최소 간격을 둬도 종종 발생할 수 있다.
# 발생 시 예외를 바로 던지지 않고 지수 백오프로 재시도한다.
_RATE_LIMIT_CODE = "EGW00201"


class KISAPIError(RuntimeError):
    pass


@dataclass
class Position:
    symbol: str
    qty: float
    avg_price: float


class KISClient:
    def __init__(self, app_key: str, app_secret: str, account_no: str,
                 account_product_cd: str = "01", mode: str = "paper",
                 request_interval_sec: float = 1.05):
        if not app_key or not app_secret or not account_no:
            raise ValueError("KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO가 설정되어야 합니다.")
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.account_product_cd = account_product_cd
        self.mode = mode
        self.base_url = PAPER_BASE_URL if mode == "paper" else REAL_BASE_URL
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._session = requests.Session()
        # KIS는 TR별로 초당 호출 횟수를 제한한다(모의투자가 더 엄격함, EGW00201 오류로 거절됨).
        # 매 API 호출 전에 최소 간격을 강제해 "초당 거래건수를 초과하였습니다" 오류를 방지한다.
        self._request_interval_sec = request_interval_sec
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        wait = self._request_interval_sec - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _send(self, method: str, url: str, *, headers: dict[str, str] | None = None,
              params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None,
              max_retries: int = 5) -> requests.Response:
        """요청 간 최소 간격을 강제하고, 초당 호출 제한(EGW00201) 발생 시 지수 백오프로 재시도한다."""
        resp: requests.Response | None = None
        for attempt in range(max_retries + 1):
            self._throttle()
            resp = self._session.request(method, url, headers=headers, params=params,
                                          json=json_body, timeout=10)
            if resp.status_code == 200:
                return resp
            if _RATE_LIMIT_CODE in resp.text and attempt < max_retries:
                wait = min(1.5 * (2 ** attempt), 20.0)
                logger.warning("KIS 초당 호출 제한(EGW00201) 감지, %.1f초 후 재시도 (%d/%d)",
                               wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            raise KISAPIError(f"HTTP {resp.status_code}: {resp.text}")
        raise KISAPIError(f"재시도 횟수 초과: {resp.text if resp is not None else ''}")

    # ------------------------------------------------------------------
    # 인증
    # ------------------------------------------------------------------
    def _load_cached_token(self) -> bool:
        if not _TOKEN_CACHE_FILE.exists():
            return False
        try:
            data = json.loads(_TOKEN_CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        if data.get("mode") != self.mode or data.get("app_key") != self.app_key:
            return False
        if data.get("expires_at", 0) - 60 <= time.time():
            return False
        self._access_token = data["access_token"]
        self._token_expires_at = data["expires_at"]
        return True

    def _save_token_cache(self) -> None:
        _TOKEN_CACHE_FILE.write_text(json.dumps({
            "mode": self.mode,
            "app_key": self.app_key,
            "access_token": self._access_token,
            "expires_at": self._token_expires_at,
        }))

    def get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        if not force_refresh and self._load_cached_token():
            return self._access_token  # type: ignore[return-value]

        # KIS는 접근토큰 발급 빈도를 제한한다 (분당/일당 제한). 불필요한 재발급을 피할 것.
        resp = self._send(
            "POST", f"{self.base_url}/oauth2/tokenP",
            json_body={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
        )
        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = time.time() + expires_in
        self._save_token_cache()
        return self._access_token

    def _get_hashkey(self, body: dict[str, Any]) -> str:
        resp = self._send(
            "POST", f"{self.base_url}/uapi/hashkey",
            headers={
                "content-type": "application/json",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
            json_body=body,
        )
        return resp.json()["HASH"]

    def _headers(self, tr_id: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if extra:
            headers.update(extra)
        return headers

    def _tr_id(self, real_tr_id: str) -> str:
        return real_tr_id if self.mode == "real" else "V" + real_tr_id[1:]

    # ------------------------------------------------------------------
    # 시세 조회
    # ------------------------------------------------------------------
    def get_daily_price(self, symbol: str, exchange: str = "NAS",
                         period: str = "0", count: int = 100,
                         base_date: str = "") -> list[dict[str, Any]]:
        """해외주식 기간별시세(일봉). period: 0=일, 1=주, 2=월.

        base_date(YYYYMMDD)를 지정하면 해당 날짜를 기준으로 그 이전 데이터를 조회한다
        (과거 데이터 페이지네이션용).
        """
        resp = self._send(
            "GET", f"{self.base_url}/uapi/overseas-price/v1/quotations/dailyprice",
            headers=self._headers(TR_DAILY_PRICE),
            params={
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": symbol,
                "GUBN": period,
                "BYMD": base_date,
                "MODP": "0",
            },
        )
        data = resp.json()
        rows = data.get("output2", [])
        return rows[:count]

    def get_current_price(self, symbol: str, exchange: str = "NAS") -> dict[str, Any]:
        resp = self._send(
            "GET", f"{self.base_url}/uapi/overseas-price/v1/quotations/price-detail",
            headers=self._headers(TR_CURRENT_PRICE),
            params={"AUTH": "", "EXCD": exchange, "SYMB": symbol},
        )
        return resp.json().get("output", {})

    # ------------------------------------------------------------------
    # 잔고/주문
    # ------------------------------------------------------------------
    def get_balance(self, exchange: str = "NAS", currency: str = "USD") -> dict[str, Any]:
        resp = self._send(
            "GET", f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-balance",
            headers=self._headers(self._tr_id(TR_BALANCE_REAL)),
            params={
                "CANO": self.account_no,
                "ACNT_PRDT_CD": self.account_product_cd,
                "OVRS_EXCG_CD": exchange,
                "TR_CRCY_CD": currency,
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )
        data = resp.json()
        return {"holdings": data.get("output1", []), "summary": data.get("output2", [])}

    def place_order(self, symbol: str, side: str, qty: int, price: float,
                     exchange: str = "NAS", order_division: str = "00") -> dict[str, Any]:
        """side: 'buy' 또는 'sell'. price<=0 이면 시장가로 취급하지 않음 (해외주식은 지정가 위주)."""
        if side not in ("buy", "sell"):
            raise ValueError("side는 'buy' 또는 'sell' 이어야 합니다.")
        tr_id = self._tr_id(TR_ORDER_BUY_REAL if side == "buy" else TR_ORDER_SELL_REAL)

        body = {
            "CANO": self.account_no,
            "ACNT_PRDT_CD": self.account_product_cd,
            "OVRS_EXCG_CD": exchange,
            "PDNO": symbol,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": order_division,
        }
        hashkey = self._get_hashkey(body)
        resp = self._send(
            "POST", f"{self.base_url}/uapi/overseas-stock/v1/trading/order",
            headers=self._headers(tr_id, extra={"hashkey": hashkey}),
            json_body=body,
        )
        result = resp.json()
        if result.get("rt_cd") != "0":
            raise KISAPIError(f"주문 실패: {result}")
        logger.info("주문 전송(%s, mode=%s): %s x%s @ %.2f -> %s",
                     side, self.mode, symbol, qty, price, result.get("output"))
        return result
