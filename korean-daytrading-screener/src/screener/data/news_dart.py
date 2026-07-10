import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

from screener.utils.logger import logger
from screener.utils.retry import with_retry

DART_BASE = "https://opendart.fss.or.kr/api"


@dataclass
class Disclosure:
    stock_code: str
    corp_name: str
    report_name: str
    receipt_date: str  # YYYYMMDD


class DartClient:
    """금융감독원 OpenDART 공시 조회. 무료 API 키 발급 필요(opendart.fss.or.kr)."""

    def __init__(self, api_key: str, cache_dir: Path):
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._stock_to_corp: dict[str, str] = {}

    def load_corp_codes(self, force_refresh: bool = False) -> None:
        cache_path = self.cache_dir / "CORPCODE.xml"
        if force_refresh or not cache_path.exists():
            self._download_corp_codes(cache_path)
        tree = ET.parse(cache_path)
        for item in tree.getroot().findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            corp_code = (item.findtext("corp_code") or "").strip()
            if stock_code:
                self._stock_to_corp[stock_code] = corp_code
        logger.info(f"DART 고유번호 매핑 로드: {len(self._stock_to_corp)}종목")

    @with_retry(exceptions=(requests.RequestException,))
    def _download_corp_codes(self, cache_path: Path) -> None:
        resp = requests.get(DART_BASE + "/corpCode.xml", params={"crtfc_key": self.api_key}, timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            cache_path.write_bytes(zf.read("CORPCODE.xml"))

    @with_retry(exceptions=(requests.RequestException,))
    def get_recent_disclosures(self, stock_code: str, days: int = 2) -> list[Disclosure]:
        corp_code = self._stock_to_corp.get(stock_code)
        if not corp_code:
            return []

        end = date.today()
        start = end - timedelta(days=days)
        resp = requests.get(
            DART_BASE + "/list.json",
            params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bgn_de": start.strftime("%Y%m%d"),
                "end_de": end.strftime("%Y%m%d"),
                "page_no": 1,
                "page_count": 20,
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") not in ("000", "013"):  # 013 = 조회된 데이터 없음
            logger.warning(f"DART 조회 오류 [{stock_code}]: {body.get('message')}")
            return []

        return [
            Disclosure(
                stock_code=stock_code,
                corp_name=row["corp_name"],
                report_name=row["report_nm"],
                receipt_date=row["rcept_dt"],
            )
            for row in body.get("list", [])
        ]

    def score_disclosures(self, disclosures: list[Disclosure], positive_keywords: list[str]) -> float:
        """일치하는 호재성 키워드 개수에 비례한 0~1 스코어."""
        if not disclosures:
            return 0.0
        hits = sum(
            1
            for d in disclosures
            for kw in positive_keywords
            if kw in d.report_name
        )
        return min(hits / 2, 1.0)
