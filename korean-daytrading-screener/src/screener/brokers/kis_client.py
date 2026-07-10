import json
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from screener.brokers.base import BrokerClient, Candle, OrderBook, Quote, RankingItem
from screener.utils.logger import logger
from screener.utils.retry import with_retry

# KIS Developers 엔드포인트/TR_ID. 공식 포털(apiportal.koreainvestment.com) 및
# GitHub(koreainvestment/open-trading-api) 기준으로 작성했으며, 실사용 전 최신 문서와
# 반드시 대조 확인할 것 (TR_ID는 공지 없이 변경되는 경우가 있음).
REAL_DOMAIN = "https://openapi.koreainvestment.com:9443"
PAPER_DOMAIN = "https://openapivts.koreainvestment.com:29443"

TR_ID = {
    "current_price": "FHKST01010100",
    "order_book": "FHKST01010200",
    "execution_detail": "FHKST01010300",  # 주식현재가 체결 - 체결강도 확인용
    "daily_chart": "FHKST03010100",
    "minute_chart": "FHKST03010200",
    "volume_rank": "FHPST01710000",
    "fluctuation_rank": "FHPST01700000",
    "trading_value_rank": "FHPST01710000",
    "holiday_check": "CTCA0903R",
}

MARKET_CODE = {"KOSPI": "0001", "KOSDAQ": "1001"}


class KISClient(BrokerClient):
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        account_product_cd: str = "01",
        env: str = "paper",
        token_cache_path: Path | None = None,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.account_product_cd = account_product_cd
        self.domain = PAPER_DOMAIN if env == "paper" else REAL_DOMAIN
        self.custtype = "P"
        self.token_cache_path = token_cache_path or Path(".kis_token_cache.json")
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._session = requests.Session()

    def is_ready(self) -> bool:
        try:
            self._ensure_token()
            return True
        except Exception as exc:
            logger.error(f"KIS 인증 실패: {exc}")
            return False

    # ---- 인증 ----

    def _ensure_token(self) -> str:
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        cached = self._load_cached_token()
        if cached:
            self._access_token, self._token_expires_at = cached
            return self._access_token

        self._issue_token()
        return self._access_token

    def _load_cached_token(self) -> tuple[str, datetime] | None:
        if not self.token_cache_path.exists():
            return None
        try:
            payload = json.loads(self.token_cache_path.read_text())
            expires_at = datetime.fromisoformat(payload["expires_at"])
            if datetime.now() < expires_at - timedelta(minutes=5):
                return payload["access_token"], expires_at
        except Exception:
            return None
        return None

    @with_retry(exceptions=(requests.RequestException,))
    def _issue_token(self) -> None:
        # KIS는 access_token 재발급을 짧은 간격으로 반복하면 거부하므로 파일 캐시가 필수.
        resp = self._session.post(
            f"{self.domain}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        self._access_token = body["access_token"]
        expires_in = int(body.get("expires_in", 86400))
        self._token_expires_at = datetime.now() + timedelta(seconds=expires_in)
        self.token_cache_path.write_text(
            json.dumps(
                {
                    "access_token": self._access_token,
                    "expires_at": self._token_expires_at.isoformat(),
                }
            )
        )

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._ensure_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": self.custtype,
        }

    @with_retry(exceptions=(requests.RequestException,))
    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        resp = self._session.get(
            f"{self.domain}{path}", headers=self._headers(tr_id), params=params, timeout=10
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            raise RuntimeError(f"KIS API 오류 [{tr_id}]: {body.get('msg1')}")
        return body

    # ---- 시세 조회 ----

    def get_quote(self, code: str) -> Quote:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            TR_ID["current_price"],
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        d = body["output"]
        return Quote(
            code=code,
            name=d.get("hts_kor_isnm", ""),
            current_price=float(d["stck_prpr"]),
            prev_close=float(d["stck_sdpr"]),
            open_price=float(d["stck_oprc"]),
            high_price=float(d["stck_hgpr"]),
            low_price=float(d["stck_lwpr"]),
            volume=int(d["acml_vol"]),
            trading_value=float(d["acml_tr_pbmn"]),
            market_cap=float(d.get("hts_avls", 0)) * 100_000_000,
            buy_execution_ratio=self._get_execution_strength(code),
        )

    def _get_execution_strength(self, code: str) -> float:
        # inquire-price에는 체결강도 필드가 없어 별도 API(체결 내역)에서 가져온다.
        # tday_rltv: 당일 누적 매수/매도 체결강도(100 기준, >100이면 매수세 우위).
        try:
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
                TR_ID["execution_detail"],
                {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            )
            rows = body.get("output") or []
            return float(rows[0]["tday_rltv"]) if rows else 100.0
        except Exception as exc:
            logger.warning(f"{code} 체결강도 조회 실패, 중립값(100)으로 대체: {exc}")
            return 100.0

    def get_order_book(self, code: str) -> OrderBook:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            TR_ID["order_book"],
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        d = body["output1"]
        bid_prices = [float(d[f"bidp{i}"]) for i in range(1, 11)]
        bid_volumes = [int(d[f"bidp_rsqn{i}"]) for i in range(1, 11)]
        ask_prices = [float(d[f"askp{i}"]) for i in range(1, 11)]
        ask_volumes = [int(d[f"askp_rsqn{i}"]) for i in range(1, 11)]
        return OrderBook(code, bid_prices, bid_volumes, ask_prices, ask_volumes)

    def get_daily_candles(self, code: str, start: date, end: date) -> list[Candle]:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            TR_ID["daily_chart"],
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        return [
            Candle(
                timestamp=row["stck_bsop_date"],
                open=float(row["stck_oprc"]),
                high=float(row["stck_hgpr"]),
                low=float(row["stck_lwpr"]),
                close=float(row["stck_clpr"]),
                volume=int(row["acml_vol"]),
            )
            for row in body["output2"]
        ]

    def get_today_minute_candles(self, code: str) -> list[Candle]:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            TR_ID["minute_chart"],
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": "090000",
                "FID_PW_DATA_INCU_YN": "Y",
                "FID_ETC_CLS_CODE": "",
            },
        )
        return [
            Candle(
                timestamp=row["stck_cntg_hour"],
                open=float(row["stck_oprc"]),
                high=float(row["stck_hgpr"]),
                low=float(row["stck_lwpr"]),
                close=float(row["stck_prpr"]),
                volume=int(row["cntg_vol"]),
            )
            for row in body["output2"]
        ]

    # ---- 순위분석 (전종목 벌크 스캔용) ----

    def get_volume_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            TR_ID["volume_rank"],
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": MARKET_CODE[market],
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
            },
        )
        return [
            RankingItem(code=row["mksc_shrn_iscd"], name=row["hts_kor_isnm"], rank=i + 1, value=float(row["acml_vol"]))
            for i, row in enumerate(body["output"][:top_n])
        ]

    def get_fluctuation_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        body = self._get(
            "/uapi/domestic-stock/v1/ranking/fluctuation",
            TR_ID["fluctuation_rank"],
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20170",
                "FID_INPUT_ISCD": MARKET_CODE[market],
                "FID_RANK_SORT_CLS_CODE": "0",
                "FID_INPUT_CNT_1": "0",
                "FID_PRC_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "0",
                "FID_TRGT_EXLS_CLS_CODE": "0",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_TRGT_CLS_CODE_2": "",
            },
        )
        return [
            RankingItem(
                code=row["stck_shrn_iscd"],
                name=row["hts_kor_isnm"],
                rank=i + 1,
                value=float(row["prdy_ctrt"]),
            )
            for i, row in enumerate(body["output"][:top_n])
        ]

    def get_trading_value_rank(self, market: str, top_n: int = 100) -> list[RankingItem]:
        # 거래량순위 API가 거래대금(acml_tr_pbmn) 필드도 함께 반환하므로 재사용 후 재정렬한다.
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            TR_ID["trading_value_rank"],
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": MARKET_CODE[market],
                "FID_DIV_CLS_CODE": "1",
                "FID_BLNG_CLS_CODE": "0",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
            },
        )
        rows = sorted(body["output"], key=lambda r: float(r["acml_tr_pbmn"]), reverse=True)
        return [
            RankingItem(code=row["mksc_shrn_iscd"], name=row["hts_kor_isnm"], rank=i + 1, value=float(row["acml_tr_pbmn"]))
            for i, row in enumerate(rows[:top_n])
        ]

    # 실제 응답에서 등락률 필드명이 확인되지 않아, 후보 필드명 중 존재하는 것을 사용한다.
    _INDEX_CHANGE_FIELD_CANDIDATES = ("prdy_ctrt", "bstp_nmix_prdy_ctrt", "prdy_vrss_ctrt")

    def get_index_change_pct(self, market: str) -> float:
        code = "0001" if market == "KOSPI" else "1001"
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-index-price",
            "FHPUP02100000",
            {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code},
        )
        output = body["output"]
        for field in self._INDEX_CHANGE_FIELD_CANDIDATES:
            if field in output:
                return float(output[field])
        raise KeyError(
            f"지수 등락률 필드를 찾지 못함. 실제 응답 필드: {list(output.keys())}"
        )

    def is_market_holiday(self, day: date) -> bool:
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/chk-holiday",
            TR_ID["holiday_check"],
            {"BASS_DT": day.strftime("%Y%m%d"), "CTX_AREA_NK": "", "CTX_AREA_FK": ""},
        )
        rows = body.get("output", [])
        today_row = next((r for r in rows if r["bass_dt"] == day.strftime("%Y%m%d")), None)
        return bool(today_row) and today_row.get("opnd_yn") == "N"
