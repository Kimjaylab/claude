"""Risk management: leverage/margin enforcement, fixed R:R sizing, and the
daily loss circuit breaker that locks the system out for 24h.

This module never talks to the exchange directly -- it only makes
decisions. The caller (live_trader.py / backtester.py) is responsible for
actually closing positions and cancelling orders when told to.

For unattended 24/7 operation, the daily-loss lockout state is persisted
to disk (see save()/load()) so that a crash-and-restart (systemd, Docker,
a VPS reboot) can't silently reset a lockout that was protecting the
account -- otherwise a process that keeps crashing after the -3% limit is
hit would just keep re-arming itself with a fresh baseline every restart.
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config


@dataclass
class RiskManager:
    leverage: int = config.LEVERAGE
    margin_mode: str = config.MARGIN_MODE
    risk_reward_ratio: float = config.RISK_REWARD_RATIO
    daily_loss_limit_pct: float = config.DAILY_LOSS_LIMIT_PCT
    risk_per_trade_pct: float = config.RISK_PER_TRADE_PCT

    day_start_equity: float | None = None
    day_start_at: datetime | None = None
    locked_until: datetime | None = None
    lock_reason: str = ""

    def __post_init__(self):
        if self.leverage > 5:
            raise ValueError("Spec caps leverage at 5x isolated margin.")
        if self.margin_mode != "ISOLATED":
            raise ValueError("Spec requires ISOLATED margin mode only.")

    # --- daily loss circuit breaker ------------------------------------------------
    def start_new_day(self, equity: float, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        self.day_start_equity = equity
        self.day_start_at = now
        self.save()

    def _maybe_roll_day(self, now: datetime):
        if self.day_start_at is None:
            return
        if now - self.day_start_at >= timedelta(hours=24) and self.locked_until is None:
            # A full day passed without hitting the limit; roll the baseline
            # forward so a slow multi-day drawdown doesn't false-trigger.
            self.day_start_at = now
            self.save()

    def is_locked(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.locked_until is None:
            return False
        if now >= self.locked_until:
            self.locked_until = None
            self.lock_reason = ""
            self.save()
            return False
        return True

    def check_daily_loss_limit(self, current_equity: float, now: datetime | None = None) -> bool:
        """Returns True if the -3% daily loss limit was just breached (i.e.
        the caller must flatten all positions and freeze order placement).
        """
        now = now or datetime.now(timezone.utc)
        if self.day_start_equity is None:
            self.start_new_day(current_equity, now)
            return False

        self._maybe_roll_day(now)

        drawdown_pct = (self.day_start_equity - current_equity) / self.day_start_equity
        if drawdown_pct >= self.daily_loss_limit_pct and not self.is_locked(now):
            self.locked_until = now + timedelta(hours=config.LOCKOUT_HOURS)
            self.lock_reason = (
                f"Daily loss limit hit: -{drawdown_pct * 100:.2f}% "
                f"(limit -{self.daily_loss_limit_pct * 100:.0f}%). "
                f"Locked until {self.locked_until.isoformat()}."
            )
            self.save()
            return True
        return False

    # --- position sizing / fixed R:R ------------------------------------------------
    def position_size(self, equity: float, entry_price: float, stop_price: float) -> float:
        """Quantity (in base asset) such that a stop-out risks exactly
        risk_per_trade_pct of equity, respecting max leverage-bound notional.
        """
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return 0.0
        risk_amount = equity * self.risk_per_trade_pct
        qty = risk_amount / stop_distance

        max_notional = equity * self.leverage
        qty = min(qty, max_notional / entry_price)
        return max(qty, 0.0)

    def take_profit_price(self, entry_price: float, stop_price: float, side: str) -> float:
        """TP distance is exactly risk_reward_ratio * SL distance, per spec."""
        stop_distance = abs(entry_price - stop_price)
        tp_distance = stop_distance * self.risk_reward_ratio
        if side == "long":
            return entry_price + tp_distance
        if side == "short":
            return entry_price - tp_distance
        raise ValueError(f"side must be 'long' or 'short', got {side!r}")

    # --- persistence (survive process restarts) --------------------------------------
    def save(self, path: str | None = None):
        path = path or config.RISK_STATE_FILE
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        state = {
            "day_start_equity": self.day_start_equity,
            "day_start_at": self.day_start_at.isoformat() if self.day_start_at else None,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "lock_reason": self.lock_reason,
        }
        Path(path).write_text(json.dumps(state))

    def load(self, path: str | None = None) -> bool:
        """Restore previously saved state in-place. Returns True if a state
        file was found and loaded, False if there was nothing to restore.
        """
        path = path or config.RISK_STATE_FILE
        p = Path(path)
        if not p.exists():
            return False
        state = json.loads(p.read_text())
        self.day_start_equity = state.get("day_start_equity")
        self.day_start_at = (
            datetime.fromisoformat(state["day_start_at"]) if state.get("day_start_at") else None
        )
        self.locked_until = (
            datetime.fromisoformat(state["locked_until"]) if state.get("locked_until") else None
        )
        self.lock_reason = state.get("lock_reason", "")
        return True
