"""MT5 trade monitor — polls positions and sends Telegram alerts."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import defaultdict

from config import AccountConfig, Settings, load_settings
from monitor.logger_setup import log_error, setup_logging
from monitor.mt5_client import MT5Client, PositionSnapshot
from monitor.notifier import TelegramNotifier


class TradeMonitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger, self.error_logger = setup_logging()
        self.mt5 = MT5Client(
            default_terminal_path=settings.mt5_terminal_path,
            logger=self.logger,
            error_logger=self.error_logger,
        )
        self.notifier = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_ids=settings.telegram_chat_ids,
            logger=self.logger,
            error_logger=self.error_logger,
        )
        # login -> ticket -> last known open position
        self._known_positions: dict[int, dict[int, PositionSnapshot]] = defaultdict(dict)
        self._active_accounts: list[AccountConfig] = []
        self._running = True
        self._reconnect_delay = 5
        self._max_reconnect_delay = 60

    def stop(self) -> None:
        self._running = False

    def _ensure_connection(self, account: AccountConfig | None = None) -> bool:
        terminal_path = account.terminal_path if account else None
        if self.mt5.is_connected:
            return True

        self.logger.info("Attempting MT5 connection...")
        if self.mt5.connect(terminal_path):
            self._reconnect_delay = 5
            return True

        self.logger.warning(
            "Connection failed. Retrying in %s seconds.", self._reconnect_delay
        )
        time.sleep(self._reconnect_delay)
        self._reconnect_delay = min(
            self._reconnect_delay * 2, self._max_reconnect_delay
        )
        return False

    def _bootstrap_account(self, account: AccountConfig) -> bool:
        """Snapshot existing positions without alerting (first run only)."""
        if account.login in self._known_positions:
            return True

        if not self.mt5.login(account):
            return False

        positions = self.mt5.get_open_positions()
        self._known_positions[account.login] = {p.ticket: p for p in positions}
        self.logger.info(
            "Baseline for %s: %s open position(s)",
            account.label,
            len(positions),
        )
        return True

    def _detect_opened_and_closed(
        self,
        account: AccountConfig,
        positions: list[PositionSnapshot],
    ) -> tuple[list[PositionSnapshot], list[PositionSnapshot]]:
        known = self._known_positions[account.login]
        current = {p.ticket: p for p in positions}

        opened = [p for ticket, p in current.items() if ticket not in known]
        closed = [known[ticket] for ticket in known if ticket not in current]

        self._known_positions[account.login] = current
        return opened, closed

    def _poll_account(self, account: AccountConfig) -> None:
        if not self.mt5.login(account):
            return

        positions = self.mt5.get_open_positions()
        opened, closed = self._detect_opened_and_closed(account, positions)

        for position in opened:
            self.logger.info(
                "New trade detected on %s: ticket %s %s %s",
                account.label,
                position.ticket,
                position.trade_type,
                position.symbol,
            )
            self.notifier.send_trade_alert(account.label, account.login, position)

        for previous in closed:
            try:
                closed_trade = self.mt5.get_closed_trade(previous)
                self.logger.info(
                    "Trade closed on %s: ticket %s %s %s profit=%s",
                    account.label,
                    closed_trade.ticket,
                    closed_trade.trade_type,
                    closed_trade.symbol,
                    closed_trade.profit,
                )
                self.notifier.send_trade_close_alert(
                    account.label, account.login, closed_trade
                )
            except Exception as exc:
                self.error_logger.error(
                    "Failed to process closed trade ticket %s on %s: %s",
                    previous.ticket,
                    account.label,
                    exc,
                )

    def run(self) -> None:
        self.logger.info("MT5 Trade Monitor starting...")
        self.logger.info(
            "Poll interval: %ss | Accounts: %s",
            self.settings.poll_interval_seconds,
            len(self.settings.accounts),
        )

        first_account = self.settings.accounts[0]
        if not self._ensure_connection(first_account):
            self.error_logger.error("Could not connect to MT5 on startup.")
            sys.exit(1)

        ready_accounts: list[AccountConfig] = []
        for account in self.settings.accounts:
            if self._bootstrap_account(account):
                ready_accounts.append(account)
            else:
                self.error_logger.error(
                    "Skipping startup for %s (%s) — login failed.",
                    account.label,
                    account.login,
                )

        if not ready_accounts:
            self.error_logger.error(
                "No accounts logged in successfully. Fix credentials/server and retry."
            )
            self.mt5.disconnect()
            sys.exit(1)

        self._active_accounts = ready_accounts
        self.notifier.send_startup_message(
            [f"{a.label} ({a.login})" for a in ready_accounts]
        )

        poll_count = 0
        while self._running:
            for account in self._active_accounts:
                if not self._running:
                    break
                if not self._ensure_connection(account):
                    break
                self._poll_account(account)

            poll_count += 1
            if poll_count % 20 == 0:
                self.logger.info("Health check: monitor running normally.")

            time.sleep(self.settings.poll_interval_seconds)

        self.mt5.disconnect()
        self.logger.info("MT5 Trade Monitor stopped.")

    def run_test(self) -> int:
        """Verify MT5 + Telegram without entering the poll loop."""
        self.logger.info(
            "Running connection test for %s account(s)...",
            len(self.settings.accounts),
        )

        first_account = self.settings.accounts[0]
        if not self.mt5.connect(first_account.terminal_path):
            self.error_logger.error("MT5 connection test failed.")
            return 1

        for account in self.settings.accounts:
            if not self.mt5.login(account):
                self.error_logger.error(
                    "MT5 login test failed for %s (%s).",
                    account.label,
                    account.login,
                )
                self.mt5.disconnect()
                return 1

            positions = self.mt5.get_open_positions()
            self.logger.info(
                "Login OK. Open positions on %s (%s): %s",
                account.label,
                account.login,
                len(positions),
            )
            for pos in positions:
                self.logger.info(
                    "  ticket=%s %s %s vol=%s @ %s",
                    pos.ticket,
                    pos.trade_type,
                    pos.symbol,
                    pos.volume,
                    pos.open_price,
                )

        if not self.notifier.send_test_message():
            self.error_logger.error("Telegram test failed.")
            self.mt5.disconnect()
            return 1

        self.logger.info("Telegram test message sent.")
        self.mt5.disconnect()
        self.logger.info("All tests passed.")
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MT5 trade monitor with Telegram alerts")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test MT5 login and Telegram, then exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    monitor = TradeMonitor(settings)

    def handle_signal(signum: int, _frame: object) -> None:
        monitor.logger.info("Received signal %s, shutting down...", signum)
        monitor.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.test:
        sys.exit(monitor.run_test())

    try:
        monitor.run()
    except Exception as exc:
        log_error(monitor.error_logger, "Unhandled monitor error", exc)
        monitor.mt5.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    main()
