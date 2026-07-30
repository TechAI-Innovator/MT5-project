"""MetaTrader 5 connection and position polling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

from config import AccountConfig

DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
IPC_TIMEOUT_MS = 120_000


@dataclass(frozen=True)
class PositionSnapshot:
    ticket: int
    symbol: str
    trade_type: str
    volume: float
    open_price: float
    open_time: datetime


@dataclass(frozen=True)
class ClosedTradeSnapshot:
    ticket: int
    symbol: str
    trade_type: str
    volume: float
    open_price: float
    close_price: float
    profit: float
    open_time: datetime
    close_time: datetime
    commission: float = 0.0
    swap: float = 0.0


class MT5Client:
    def __init__(
        self,
        default_terminal_path: str | None,
        logger: logging.Logger,
        error_logger: logging.Logger,
    ) -> None:
        self._default_terminal_path = default_terminal_path
        self._logger = logger
        self._error_logger = error_logger
        self._initialized = False
        self._active_terminal_path: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._initialized and mt5.terminal_info() is not None

    def _resolve_terminal_path(self, terminal_path: str | None = None) -> str:
        chosen = terminal_path or self._default_terminal_path
        if chosen:
            return chosen.replace("\\", "/")

        if Path(DEFAULT_TERMINAL_PATH).exists():
            return DEFAULT_TERMINAL_PATH.replace("\\", "/")

        raise FileNotFoundError(
            "MT5 terminal not found. Set MT5_TERMINAL_PATH in .env to your "
            "terminal64.exe (e.g. broker-specific install path)."
        )

    def connect(self, terminal_path: str | None = None) -> bool:
        resolved_path = None
        try:
            resolved_path = self._resolve_terminal_path(terminal_path)
        except FileNotFoundError as exc:
            self._error_logger.error(str(exc))
            return False

        if (
            self._initialized
            and self._active_terminal_path == resolved_path
            and mt5.terminal_info() is not None
        ):
            return True

        mt5.shutdown()
        self._initialized = False
        self._active_terminal_path = None

        self._logger.info("Using MT5 terminal: %s", resolved_path)

        if not mt5.initialize(path=resolved_path, timeout=IPC_TIMEOUT_MS):
            error = mt5.last_error()
            self._error_logger.error("MT5 initialize failed: %s", error)
            if error[0] == -10005:
                self._log_ipc_timeout_help()
            return False

        self._initialized = True
        self._active_terminal_path = resolved_path
        info = mt5.terminal_info()
        if info:
            self._logger.info(
                "Connected to MT5 terminal: %s (build %s)",
                info.name,
                info.build,
            )
        return True

    def _log_ipc_timeout_help(self) -> None:
        help_text = (
            "IPC timeout (-10005): Python cannot reach the MT5 terminal. "
            "Fix in MT5: Tools -> Options -> Community -> enable "
            "'Python integration', then restart MT5. Also ensure MT5 is fully "
            "open (no login/update dialogs), only one terminal instance is "
            "running, and MT5 was not started as Administrator unless Python "
            "is too."
        )
        self._error_logger.error(help_text)
        self._logger.error(help_text)

    def disconnect(self) -> None:
        if self._initialized:
            mt5.shutdown()
            self._initialized = False
            self._active_terminal_path = None
            self._logger.info("Disconnected from MT5 terminal.")

    def login(self, account: AccountConfig) -> bool:
        if not self.connect(account.terminal_path):
            return False

        authorized = mt5.login(
            login=account.login,
            password=account.password,
            server=account.server,
        )
        if not authorized:
            error = mt5.last_error()
            self._error_logger.error(
                "MT5 login failed for %s (%s) on server '%s': %s",
                account.label,
                account.login,
                account.server,
                error,
            )
            return False

        self._logger.info(
            "Logged in to %s (%s) via %s",
            account.label,
            account.login,
            account.server,
        )
        return True

    def get_open_positions(self) -> list[PositionSnapshot]:
        raw_positions = mt5.positions_get()
        if raw_positions is None:
            error = mt5.last_error()
            if error[0] != 1:
                self._error_logger.error("positions_get failed: %s", error)
            return []

        snapshots: list[PositionSnapshot] = []
        for pos in raw_positions:
            trade_type = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            open_time = datetime.fromtimestamp(pos.time, tz=timezone.utc)
            snapshots.append(
                PositionSnapshot(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    trade_type=trade_type,
                    volume=pos.volume,
                    open_price=pos.price_open,
                    open_time=open_time,
                )
            )
        return snapshots

    def get_closed_trade(
        self,
        position: PositionSnapshot,
        lookback_days: int = 7,
    ) -> ClosedTradeSnapshot:
        """Build a closed-trade snapshot from deal history when possible."""
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=lookback_days)

        deals = mt5.history_deals_get(position=position.ticket)
        if deals is None or len(deals) == 0:
            # Fallback: scan recent history and match by position id
            deals = mt5.history_deals_get(date_from, now)
            if deals is None:
                self._error_logger.error(
                    "history_deals_get failed for ticket %s: %s",
                    position.ticket,
                    mt5.last_error(),
                )
                return self._fallback_closed_trade(position)
            deals = [d for d in deals if getattr(d, "position_id", 0) == position.ticket]

        if not deals:
            return self._fallback_closed_trade(position)

        close_price = position.open_price
        close_time = now
        profit = 0.0
        commission = 0.0
        swap = 0.0
        volume = position.volume

        for deal in deals:
            commission += float(deal.commission)
            swap += float(deal.swap)
            profit += float(deal.profit)
            if deal.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                close_price = float(deal.price)
                close_time = datetime.fromtimestamp(deal.time, tz=timezone.utc)
                volume = float(deal.volume)

        return ClosedTradeSnapshot(
            ticket=position.ticket,
            symbol=position.symbol,
            trade_type=position.trade_type,
            volume=volume,
            open_price=position.open_price,
            close_price=close_price,
            profit=profit,
            open_time=position.open_time,
            close_time=close_time,
            commission=commission,
            swap=swap,
        )

    def _fallback_closed_trade(self, position: PositionSnapshot) -> ClosedTradeSnapshot:
        now = datetime.now(timezone.utc)
        return ClosedTradeSnapshot(
            ticket=position.ticket,
            symbol=position.symbol,
            trade_type=position.trade_type,
            volume=position.volume,
            open_price=position.open_price,
            close_price=position.open_price,
            profit=0.0,
            open_time=position.open_time,
            close_time=now,
        )
