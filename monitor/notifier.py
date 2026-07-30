"""Telegram notification delivery."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from monitor.mt5_client import ClosedTradeSnapshot, PositionSnapshot


class TelegramNotifier:
    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: str,
        chat_ids: tuple[str, ...] | list[str],
        logger: logging.Logger,
        error_logger: logging.Logger,
    ) -> None:
        self._bot_token = bot_token
        self._chat_ids = tuple(chat_ids)
        self._logger = logger
        self._error_logger = error_logger

    def send_message(self, text: str) -> bool:
        url = self.API_URL.format(token=self._bot_token)
        any_ok = False

        for chat_id in self._chat_ids:
            try:
                response = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                if not response.ok:
                    detail = response.text
                    try:
                        detail = response.json().get("description", response.text)
                    except ValueError:
                        pass
                    self._error_logger.error(
                        "Telegram send failed for chat %s: %s",
                        chat_id,
                        detail,
                    )
                    continue
                any_ok = True
            except requests.RequestException as exc:
                self._error_logger.error(
                    "Telegram send failed for chat %s "
                    "(check internet/DNS/firewall for api.telegram.org): %s",
                    chat_id,
                    exc,
                )

        return any_ok

    def send_trade_alert(
        self,
        account_label: str,
        account_login: int,
        position: PositionSnapshot,
    ) -> bool:
        timestamp = position.open_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        message = (
            "NEW TRADE OPENED\n"
            f"Account: {account_label} ({account_login})\n"
            f"Symbol: {position.symbol}\n"
            f"Type: {position.trade_type}\n"
            f"Volume: {position.volume}\n"
            f"Open Price: {position.open_price}\n"
            f"Ticket: {position.ticket}\n"
            f"Time: {timestamp}"
        )
        sent = self.send_message(message)
        if sent:
            self._logger.info(
                "Alert sent for ticket %s on %s (%s) to %s chat(s)",
                position.ticket,
                account_label,
                position.symbol,
                len(self._chat_ids),
            )
        return sent

    def send_trade_close_alert(
        self,
        account_label: str,
        account_login: int,
        trade: ClosedTradeSnapshot,
    ) -> bool:
        close_ts = trade.close_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        open_ts = trade.open_time.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        profit_sign = "+" if trade.profit >= 0 else ""
        message = (
            "TRADE CLOSED\n"
            f"Account: {account_label} ({account_login})\n"
            f"Symbol: {trade.symbol}\n"
            f"Type: {trade.trade_type}\n"
            f"Volume: {trade.volume}\n"
            f"Open Price: {trade.open_price}\n"
            f"Close Price: {trade.close_price}\n"
            f"Profit: {profit_sign}{trade.profit:.2f}\n"
            f"Ticket: {trade.ticket}\n"
            f"Opened: {open_ts}\n"
            f"Closed: {close_ts}"
        )
        sent = self.send_message(message)
        if sent:
            self._logger.info(
                "Close alert sent for ticket %s on %s (%s) profit=%s",
                trade.ticket,
                account_label,
                trade.symbol,
                trade.profit,
            )
        return sent

    def send_startup_message(self, account_labels: list[str]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        accounts = ", ".join(account_labels)
        self.send_message(
            f"MT5 Monitor started\n"
            f"Time: {now}\n"
            f"Watching: {accounts}\n"
            f"Alerts: trade open + trade close"
        )

    def send_test_message(self) -> bool:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return self.send_message(f"MT5 Monitor test OK\nTime: {now}")
