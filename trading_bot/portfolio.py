"""보유 포지션 상태 관리 (익절 +5% / 손절 -5% 판단 포함)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .config import RiskConfig

logger = logging.getLogger(__name__)

ExitReason = Literal["take_profit", "stop_loss"]


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    entry_date: str

    def take_profit_price(self, cfg: RiskConfig) -> float:
        return self.entry_price * (1 + cfg.take_profit_pct)

    def stop_loss_price(self, cfg: RiskConfig) -> float:
        return self.entry_price * (1 + cfg.stop_loss_pct)

    def check_exit(self, current_price: float, cfg: RiskConfig) -> ExitReason | None:
        if current_price >= self.take_profit_price(cfg):
            return "take_profit"
        if current_price <= self.stop_loss_price(cfg):
            return "stop_loss"
        return None


class PortfolioState:
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.positions: dict[str, Position] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("상태 파일을 읽지 못했습니다: %s", self.state_file)
            return
        for symbol, pos in raw.get("positions", {}).items():
            self.positions[symbol] = Position(**pos)

    def save(self) -> None:
        data = {"positions": {sym: asdict(pos) for sym, pos in self.positions.items()}}
        self.state_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def open_position(self, symbol: str, qty: float, price: float, date: str) -> None:
        self.positions[symbol] = Position(symbol=symbol, qty=qty, entry_price=price, entry_date=date)
        self.save()

    def close_position(self, symbol: str) -> Position | None:
        pos = self.positions.pop(symbol, None)
        if pos is not None:
            self.save()
        return pos

    def can_open_new_position(self, cfg: RiskConfig) -> bool:
        return len(self.positions) < cfg.max_open_positions
