import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from screener.utils.logger import logger
from screener.utils.retry import with_retry

# KIS Developers가 공식 예제에서 안내하는 종목마스터 배포 URL.
# 고정폭 텍스트 포맷이며, 그룹코드 컬럼 위치는 배포처 갱신 시 바뀔 수 있으므로
# 최신 KIS 샘플(examples_user/domestic_stock)의 마스터 파서와 대조 확인 필요.
MASTER_URLS = {
    "KOSPI": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
    "KOSDAQ": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
}

# 그룹코드 기준 제외 대상 (ETF/ETN/투자회사/리츠/스팩 등 개별주 단타 전략과 무관한 상품)
EXCLUDED_GROUP_CODES = {"EF", "EN", "MF", "RT", "IF", "SC", "SW", "SR", "JD"}

# 마스터 파일 파싱이 실패하거나 그룹코드가 애매할 때를 대비한 이름 기반 보조 필터.
ETF_ETN_NAME_HINTS = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL", "ACE", "KOSEF",
    "KINDEX", "TIMEFOLIO", "WOORI", "마이다스", "ETN", "ETF",
)


@dataclass
class StockMeta:
    code: str
    name: str
    market: str
    is_etf_etn: bool
    is_preferred: bool
    is_management_issue: bool
    listed_date: str | None = None


class UniverseFilter:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._meta: dict[str, StockMeta] = {}

    def load(self, force_refresh: bool = False) -> None:
        for market, url in MASTER_URLS.items():
            cache_path = self.cache_dir / f"{market.lower()}_code.mst"
            try:
                if force_refresh or not cache_path.exists():
                    self._download_master(url, cache_path)
                self._parse_master(cache_path, market)
            except Exception as exc:
                # 마스터 서버 장애 시에도 전체 파이프라인이 죽지 않도록 이름 기반
                # 휴리스틱(is_investable)만으로 계속 진행한다.
                logger.warning(f"{market} 종목마스터 로드 실패, 이름 기반 필터로 폴백: {exc}")
        logger.info(f"종목마스터 로드 완료: {len(self._meta)}종목")

    @with_retry(exceptions=(requests.RequestException,))
    def _download_master(self, url: str, cache_path: Path) -> None:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            inner_name = zf.namelist()[0]
            cache_path.write_bytes(zf.read(inner_name))

    def _parse_master(self, cache_path: Path, market: str) -> None:
        # 고정폭 레코드: 앞부분 종목코드(9)+한글명 가변 이후 그룹코드 등 속성 컬럼이 이어진다.
        # 정확한 오프셋은 배포 버전에 따라 미세 조정이 필요할 수 있어, 아래는 공개된
        # KIS 샘플 파서 기준 근사치이며 실사용 전 실제 파일로 검증할 것.
        try:
            with open(cache_path, encoding="cp949", errors="ignore") as f:
                for line in f:
                    if len(line) < 30:
                        continue
                    code = line[0:9].strip()
                    rest = line[9:]
                    name = rest[:40].strip() if len(rest) >= 40 else rest.strip()
                    group_code = rest[40:42].strip() if len(rest) >= 42 else ""
                    is_preferred = name.endswith("우") or name.endswith("우B") or name.endswith("우A")
                    is_management = "관리" in group_code or group_code == "MG"
                    self._meta[code] = StockMeta(
                        code=code,
                        name=name,
                        market=market,
                        is_etf_etn=group_code in EXCLUDED_GROUP_CODES
                        or any(hint in name.upper() for hint in ETF_ETN_NAME_HINTS),
                        is_preferred=is_preferred,
                        is_management_issue=is_management,
                    )
        except Exception as exc:
            logger.warning(f"{market} 마스터 파싱 실패, 이름 기반 필터로 폴백: {exc}")

    def is_investable(self, code: str, name: str = "") -> bool:
        """마스터 정보가 있으면 그룹코드 기준으로, 없으면 이름 휴리스틱으로 판단."""
        meta = self._meta.get(code)
        if meta is None:
            return not any(hint in name.upper() for hint in ETF_ETN_NAME_HINTS) and not name.rstrip().endswith(
                ("우", "우B", "우A")
            )
        return not (meta.is_etf_etn or meta.is_preferred or meta.is_management_issue)

    def get_meta(self, code: str) -> StockMeta | None:
        return self._meta.get(code)
