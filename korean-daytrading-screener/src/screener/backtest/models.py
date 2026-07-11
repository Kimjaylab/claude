from dataclasses import dataclass


@dataclass
class Trade:
    code: str
    name: str
    market: str
    date: str  # YYYYMMDD
    entry: float
    exit: float
    exit_reason: str  # "target1" | "target2" | "stop" | "eod"
    return_pct: float  # 비용/슬리피지 반영 후 최종 수익률(%)
    score_honest: float  # look-ahead 없는 성분만으로 계산한 점수
    score_reference: float  # 당일 전체 거래량을 09:05 근사치로 포함한 참고용 점수(상한선 추정)
    index_regime: str  # "상승장" | "횡보장" | "하락장"
    split: str  # "in_sample" | "out_of_sample"
