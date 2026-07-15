"""자동매매 실행 루프 (모의투자 기본값 / 실전투자는 명시적 동의 필요)."""
from __future__ import annotations

import logging
import time
from datetime import datetime

from .config import AppConfig
from .data import fetch_kis_daily_history
from .kis_client import KISClient
from .portfolio import PortfolioState
from .strategy import generate_signal, prepare_indicators

logger = logging.getLogger(__name__)


class LiveTrader:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        if cfg.kis.mode == "real" and not cfg.confirm_real_trading:
            raise RuntimeError(
                "실전투자 모드입니다. 실수 방지를 위해 CONFIRM_REAL_TRADING=yes 를 "
                ".env에 명시적으로 설정해야 주문이 전송됩니다. 먼저 모의투자(paper)로 충분히 "
                "검증하는 것을 권장합니다."
            )
        self.client = KISClient(
            app_key=cfg.kis.app_key,
            app_secret=cfg.kis.app_secret,
            account_no=cfg.kis.account_no,
            account_product_cd=cfg.kis.account_product_cd,
            mode=cfg.kis.mode,
        )
        self.portfolio = PortfolioState(cfg.state_file)
        self._last_signal_check_date: str | None = None

    def _position_size(self, price: float, cash_available: float) -> int:
        budget = cash_available * self.cfg.risk.max_position_pct
        qty = int(budget // price)
        return max(qty, 0)

    def _manage_open_positions(self) -> None:
        for symbol in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions[symbol]
            try:
                quote = self.client.get_current_price(symbol, exchange=self.cfg.exchange)
                current_price = float(quote.get("last", 0) or quote.get("base", 0))
            except Exception:
                logger.exception("%s 현재가 조회 실패", symbol)
                continue
            if current_price <= 0:
                continue

            exit_reason = pos.check_exit(current_price, self.cfg.risk)
            if exit_reason is None:
                continue

            logger.info("%s 청산 신호: %s (진입가=%.2f, 현재가=%.2f)",
                        symbol, exit_reason, pos.entry_price, current_price)
            try:
                self.client.place_order(symbol, "sell", pos.qty, current_price, exchange=self.cfg.exchange)
                self.portfolio.close_position(symbol)
            except Exception:
                logger.exception("%s 매도 주문 실패", symbol)

    def _scan_for_entries(self) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if self._last_signal_check_date == today:
            return  # 일봉 기준 신호는 하루 한 번만 평가

        for symbol in self.cfg.watchlist:
            if self.portfolio.has_position(symbol):
                continue
            if not self.portfolio.can_open_new_position(self.cfg.risk):
                logger.info("최대 보유 종목 수 도달, 신규 진입 스킵")
                break
            try:
                df = fetch_kis_daily_history(self.client, symbol, self.cfg.exchange,
                                              lookback_days=self.cfg.strategy.ma_long + 30)
                if df.empty:
                    continue
                df = prepare_indicators(df, self.cfg.strategy)
                signal = generate_signal(df, len(df) - 1, self.cfg.strategy)
            except Exception:
                logger.exception("%s 신호 계산 실패", symbol)
                continue

            if not signal.buy:
                logger.debug("%s 매수신호 없음: %s", symbol, signal.reasons)
                continue

            logger.info("%s 매수신호 발생: %s", symbol, signal.reasons)
            try:
                balance = self.client.get_balance(exchange=self.cfg.exchange)
                cash = self._extract_cash(balance)
                price = float(df.iloc[-1]["close"])
                qty = self._position_size(price, cash)
                if qty <= 0:
                    logger.warning("%s 매수 가능 수량이 0입니다 (잔고 부족)", symbol)
                    continue
                self.client.place_order(symbol, "buy", qty, price, exchange=self.cfg.exchange)
                self.portfolio.open_position(symbol, qty, price, today)
            except Exception:
                logger.exception("%s 매수 주문 실패", symbol)

        self._last_signal_check_date = today

    @staticmethod
    def _extract_cash(balance: dict) -> float:
        summary = balance.get("summary") or []
        if not summary:
            return 0.0
        row = summary[0]
        for key in ("frcr_dncl_amt_2", "frcr_dncl_amt1", "ovrs_ord_psbl_amt"):
            if key in row:
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    continue
        return 0.0

    def run_once(self) -> None:
        self._manage_open_positions()
        self._scan_for_entries()

    def run_forever(self) -> None:
        logger.info("자동매매 루프 시작 (mode=%s, 관심종목=%s, 주기=%ss)",
                    self.cfg.kis.mode, self.cfg.watchlist, self.cfg.poll_interval_sec)
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("매매 루프 실행 중 오류 발생")
            time.sleep(self.cfg.poll_interval_sec)
