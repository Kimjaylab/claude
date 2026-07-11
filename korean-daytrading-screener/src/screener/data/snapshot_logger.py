from datetime import date
from pathlib import Path

import pandas as pd

from screener.screening.models import Candidate
from screener.utils.logger import logger


def log_snapshot(candidates: list[Candidate], log_dir: Path, day: date | None = None) -> None:
    """그날 평가된 모든 후보(발송 여부 무관)를 기록한다.

    지금은 백테스트에 못 쓰지만(단일 시점), 매일 쌓이면 실제 09:00~09:05 시점의
    거래량/체결강도/점수 데이터가 축적되어 향후 룩어헤드 없는 진짜 분봉 기반
    백테스트가 가능해진다.
    """
    if not candidates:
        return
    day = day or date.today()
    log_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "date": day.isoformat(),
            "code": c.code,
            "name": c.name,
            "market": c.technical.market,
            "current_price": c.intraday.current_price,
            "prev_close": c.intraday.prev_close,
            "cumulative_volume": c.intraday.cumulative_volume,
            "cumulative_value": c.intraday.cumulative_value,
            "buy_execution_ratio": c.intraday.buy_execution_ratio,
            "bid_ask_volume_ratio": c.intraday.bid_ask_volume_ratio,
            "index_change_pct": c.intraday.index_change_pct,
            "score_total": c.score.total,
            "final_score": c.final_score,
            "entry": c.risk.entry_price,
            "stop_loss": c.risk.stop_loss,
            "target1": c.risk.target1,
            "target2": c.risk.target2,
        }
        for c in candidates
    ]
    path = log_dir / f"{day.isoformat()}.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    logger.info(f"당일 스냅샷 {len(rows)}건 저장: {path}")
