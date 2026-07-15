"""자동 스크리닝 대상 종목(유니버스) 로딩.

기본 유니버스는 S&P 500 구성종목(약 503개, data/sp500_universe.csv)이다.
Nasdaq-100 구성종목은 대부분 S&P 500과 겹치므로 별도로 포함하지 않았다.

주의: symbol->exchange 매핑은 공개 데이터셋을 기반으로 자동 생성한 것이라
소수 종목은 거래소 코드가 틀릴 수 있다 (예: 상장폐지/이전 등으로 최신화 필요).
틀린 종목은 실행 시 API 오류로 스킵되고 로그에 남으니, 필요하면
data/sp500_universe.csv를 직접 수정하면 된다.
"""
from __future__ import annotations

import csv
from pathlib import Path

_DEFAULT_UNIVERSE_FILE = Path(__file__).parent / "data" / "sp500_universe.csv"


def load_universe(path: str | Path | None = None) -> list[tuple[str, str]]:
    """반환: [(symbol, exchange_code), ...]. exchange_code는 KIS EXCD 값(NAS/NYS 등)."""
    file_path = Path(path) if path else _DEFAULT_UNIVERSE_FILE
    if not file_path.exists():
        raise FileNotFoundError(f"유니버스 파일을 찾을 수 없습니다: {file_path}")

    pairs: list[tuple[str, str]] = []
    with file_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"].strip().upper()
            exchange = row["exchange"].strip().upper()
            if symbol:
                pairs.append((symbol, exchange))
    return pairs
