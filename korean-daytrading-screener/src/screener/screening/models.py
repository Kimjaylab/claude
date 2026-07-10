from dataclasses import dataclass, field


@dataclass
class TechnicalSnapshot:
    """08:30~08:50 정적 필터 단계에서 전일 종가 기준으로 계산되는 값들."""

    code: str
    name: str
    market: str
    prev_close: float
    ma5: float
    ma20: float
    ma60: float
    recent_high_20d: float
    rsi14: float
    atr_pct: float                 # 최근 14일 ATR / 종가 * 100
    three_day_return_pct: float
    avg_5min_volume_20d: float      # 최근 20거래일의 "09:00~09:05" 평균 거래량 (동적 필터 기준값)


@dataclass
class IntradaySnapshot:
    """09:00~09:05 동적 필터 단계에서 당일 실시간 데이터로 계산되는 값들."""

    code: str
    current_price: float
    open_price: float
    prev_close: float
    cumulative_volume: int
    cumulative_value: float
    buy_execution_ratio: float
    bid_ask_volume_ratio: float
    index_change_pct: float
    disclosure_score: float = 0.0   # 0~1, DartClient.score_disclosures 결과


@dataclass
class ScoreBreakdown:
    volume_momentum: float = 0.0
    trend_alignment: float = 0.0
    breakout: float = 0.0
    execution_strength: float = 0.0
    relative_strength: float = 0.0
    gap_quality: float = 0.0
    news_disclosure: float = 0.0
    overheat_penalty: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.volume_momentum
            + self.trend_alignment
            + self.breakout
            + self.execution_strength
            + self.relative_strength
            + self.gap_quality
            + self.news_disclosure
            + self.overheat_penalty
        )


@dataclass
class RiskTargets:
    entry_price: float
    stop_loss: float
    target1: float
    target2: float
    risk_grade: str        # "낮음" | "중간" | "높음"


@dataclass
class Candidate:
    technical: TechnicalSnapshot
    intraday: IntradaySnapshot
    score: ScoreBreakdown
    risk: RiskTargets
    reasons: list[str] = field(default_factory=list)
    adjusted_total: float | None = None  # 시장레짐 배수 적용 후 최종 점수 (None이면 score.total과 동일)

    @property
    def code(self) -> str:
        return self.technical.code

    @property
    def name(self) -> str:
        return self.technical.name

    @property
    def final_score(self) -> float:
        return self.adjusted_total if self.adjusted_total is not None else self.score.total
