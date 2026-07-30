"""Load monitor configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
MAX_ACCOUNTS = 5


@dataclass(frozen=True)
class AccountConfig:
    label: str
    login: int
    password: str
    server: str
    terminal_path: str | None = None


@dataclass(frozen=True)
class Settings:
    poll_interval_seconds: float
    telegram_bot_token: str
    telegram_chat_ids: tuple[str, ...]
    mt5_terminal_path: str | None
    accounts: tuple[AccountConfig, ...]


def load_settings(env_path: Path | None = None) -> Settings:
    load_dotenv(env_path or PROJECT_ROOT / ".env")

    accounts: list[AccountConfig] = []
    for index in range(1, MAX_ACCOUNTS + 1):
        login_raw = os.getenv(f"MT5_LOGIN_{index}", "").strip()
        if not login_raw:
            continue

        password = os.getenv(f"MT5_PASSWORD_{index}", "").strip()
        server = os.getenv(f"MT5_SERVER_{index}", "").strip()
        label = os.getenv(f"MT5_ACCOUNT_LABEL_{index}", f"Account {index}").strip()
        account_terminal = os.getenv(f"MT5_TERMINAL_PATH_{index}", "").strip() or None

        if not password or not server:
            raise ValueError(
                f"MT5_PASSWORD_{index} and MT5_SERVER_{index} are required "
                f"when MT5_LOGIN_{index} is set."
            )

        accounts.append(
            AccountConfig(
                label=label,
                login=int(login_raw),
                password=password,
                server=server,
                terminal_path=account_terminal,
            )
        )

    if not accounts:
        raise ValueError(
            "No MT5 accounts configured. Set MT5_LOGIN_1, MT5_PASSWORD_1, "
            "and MT5_SERVER_1 in .env (see .env.example)."
        )

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    chat_ids = tuple(
        part.strip() for part in chat_ids_raw.replace(";", ",").split(",") if part.strip()
    )
    if not bot_token or not chat_ids:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required in .env. "
            "For multiple people, set TELEGRAM_CHAT_ID=id1,id2"
        )

    poll_raw = os.getenv("POLL_INTERVAL_SECONDS", "3").strip()
    poll_interval = float(poll_raw)
    if poll_interval < 1 or poll_interval > 5:
        raise ValueError("POLL_INTERVAL_SECONDS must be between 1 and 5.")

    terminal_path = os.getenv("MT5_TERMINAL_PATH", "").strip() or None

    return Settings(
        poll_interval_seconds=poll_interval,
        telegram_bot_token=bot_token,
        telegram_chat_ids=chat_ids,
        mt5_terminal_path=terminal_path,
        accounts=tuple(accounts),
    )
