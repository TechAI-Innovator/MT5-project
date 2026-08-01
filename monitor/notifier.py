"""Telegram notification delivery with Seen acknowledgements."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from monitor.mt5_client import ClosedTradeSnapshot, PositionSnapshot


@dataclass
class PendingOpenAlert:
    key: str
    ticket: int
    account_login: int
    account_label: str
    text: str
    first_sent_at: float
    last_sent_at: float
    reminder_count: int = 0
    acknowledged: bool = False
    message_refs: list[tuple[str, int]] = field(default_factory=list)


class TelegramNotifier:
    API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(
        self,
        bot_token: str,
        chat_ids: tuple[str, ...] | list[str],
        logger: logging.Logger,
        error_logger: logging.Logger,
        ack_remind_seconds: float = 30,
        ack_max_reminders: int = 5,
    ) -> None:
        self._bot_token = bot_token
        self._chat_ids = tuple(chat_ids)
        self._logger = logger
        self._error_logger = error_logger
        self._ack_remind_seconds = ack_remind_seconds
        self._ack_max_reminders = ack_max_reminders
        self._pending: dict[str, PendingOpenAlert] = {}
        self._update_offset: int | None = None

    def _url(self, method: str) -> str:
        return self.API_BASE.format(token=self._bot_token, method=method)

    def _post(self, method: str, payload: dict) -> dict | None:
        try:
            response = requests.post(self._url(method), json=payload, timeout=15)
            data = response.json()
            if not response.ok or not data.get("ok"):
                detail = data.get("description", response.text)
                self._error_logger.error("Telegram %s failed: %s", method, detail)
                return None
            return data.get("result")
        except (requests.RequestException, ValueError) as exc:
            self._error_logger.error("Telegram %s failed: %s", method, exc)
            return None

    def send_message(
        self,
        text: str,
        reply_markup: dict | None = None,
    ) -> list[tuple[str, int]]:
        refs: list[tuple[str, int]] = []
        for chat_id in self._chat_ids:
            payload: dict = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            result = self._post("sendMessage", payload)
            if result and "message_id" in result:
                refs.append((str(chat_id), int(result["message_id"])))
        return refs

    @staticmethod
    def _ack_keyboard(alert_key: str) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "✅ Seen", "callback_data": f"ack:{alert_key}"}]
            ]
        }

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
            f"Time: {timestamp}\n"
            "\nTap ✅ Seen when you have read this."
        )
        alert_key = f"{account_login}-{position.ticket}"
        refs = self.send_message(message, reply_markup=self._ack_keyboard(alert_key))
        if not refs:
            return False

        now = time.time()
        self._pending[alert_key] = PendingOpenAlert(
            key=alert_key,
            ticket=position.ticket,
            account_login=account_login,
            account_label=account_label,
            text=message,
            first_sent_at=now,
            last_sent_at=now,
            message_refs=refs,
        )
        self._logger.info(
            "Alert sent for ticket %s on %s (%s); waiting for Seen ack",
            position.ticket,
            account_label,
            position.symbol,
        )
        return True

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
        refs = self.send_message(message)
        if refs:
            self._logger.info(
                "Close alert sent for ticket %s on %s (%s) profit=%s",
                trade.ticket,
                account_label,
                trade.symbol,
                trade.profit,
            )
            # Drop any pending open-ack for this ticket
            self._pending.pop(f"{account_login}-{trade.ticket}", None)
            return True
        return False

    def send_startup_message(self, account_labels: list[str]) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        accounts = ", ".join(account_labels)
        self.send_message(
            f"MT5 Monitor started\n"
            f"Time: {now}\n"
            f"Accounts: {len(account_labels)}\n"
            f"Watching: {accounts}\n"
            f"Alerts: open + close\n"
            f"Open-alert Seen remind: every {int(self._ack_remind_seconds)}s"
        )

    def send_test_message(self) -> bool:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        refs = self.send_message(
            f"MT5 Monitor test OK\nTime: {now}\nTap Seen to test acknowledgements.",
            reply_markup=self._ack_keyboard("test-0"),
        )
        return bool(refs)

    def process_acknowledgements(self) -> None:
        """Poll Telegram for Seen button presses."""
        payload: dict = {"timeout": 0, "allowed_updates": ["callback_query"]}
        if self._update_offset is not None:
            payload["offset"] = self._update_offset

        result = self._post("getUpdates", payload)
        if not result:
            return

        for update in result:
            update_id = int(update["update_id"])
            self._update_offset = update_id + 1
            callback = update.get("callback_query")
            if not callback:
                continue
            self._handle_callback(callback)

    def _handle_callback(self, callback: dict) -> None:
        data = str(callback.get("data", ""))
        callback_id = callback.get("id")
        from_user = callback.get("from") or {}
        username = (
            from_user.get("username")
            or from_user.get("first_name")
            or str(from_user.get("id", "user"))
        )

        if not data.startswith("ack:"):
            if callback_id:
                self._post(
                    "answerCallbackQuery",
                    {"callback_query_id": callback_id, "text": "Unknown action"},
                )
            return

        alert_key = data[4:]
        if alert_key == "test-0":
            if callback_id:
                self._post(
                    "answerCallbackQuery",
                    {"callback_query_id": callback_id, "text": "Seen test OK"},
                )
            message = callback.get("message") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            message_id = message.get("message_id")
            if chat_id is not None and message_id is not None:
                self._post(
                    "editMessageReplyMarkup",
                    {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
                )
                self._post(
                    "editMessageText",
                    {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": f"MT5 Monitor test OK\nAcknowledged by @{username}",
                    },
                )
            return

        alert = self._pending.get(alert_key)
        if callback_id:
            self._post(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": "Marked as Seen" if alert and not alert.acknowledged else "Already seen / expired",
                },
            )

        if not alert or alert.acknowledged:
            return

        alert.acknowledged = True
        ack_line = f"\n\n✅ Seen by @{username}"
        for chat_id, message_id in alert.message_refs:
            self._post(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": alert.text + ack_line,
                },
            )
        self._logger.info(
            "Open alert acknowledged for ticket %s by %s",
            alert.ticket,
            username,
        )
        self._pending.pop(alert_key, None)

    def remind_unacknowledged(self) -> None:
        """Resend open alerts that were not Seen within ACK_REMIND_SECONDS."""
        now = time.time()
        for alert in list(self._pending.values()):
            if alert.acknowledged:
                continue
            if alert.reminder_count >= self._ack_max_reminders:
                continue
            if now - alert.last_sent_at < self._ack_remind_seconds:
                continue

            reminder_no = alert.reminder_count + 1
            reminder_text = (
                f"REMINDER ({reminder_no}/{self._ack_max_reminders}) — still not Seen\n"
                f"{alert.text}"
            )
            refs = self.send_message(
                reminder_text,
                reply_markup=self._ack_keyboard(alert.key),
            )
            if refs:
                alert.reminder_count = reminder_no
                alert.last_sent_at = now
                alert.message_refs = refs
                self._logger.warning(
                    "Resent open alert for ticket %s (reminder %s)",
                    alert.ticket,
                    reminder_no,
                )
