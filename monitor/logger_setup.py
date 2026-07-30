"""Logging setup for monitor.log and errors.log."""

from __future__ import annotations

import logging
from pathlib import Path

from config import LOG_DIR


def setup_logging() -> tuple[logging.Logger, logging.Logger]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    monitor_logger = logging.getLogger("mt5_monitor")
    error_logger = logging.getLogger("mt5_monitor.errors")

    if monitor_logger.handlers:
        return monitor_logger, error_logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    monitor_handler = logging.FileHandler(LOG_DIR / "monitor.log", encoding="utf-8")
    monitor_handler.setFormatter(formatter)
    monitor_handler.setLevel(logging.INFO)

    error_handler = logging.FileHandler(LOG_DIR / "errors.log", encoding="utf-8")
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    monitor_logger.setLevel(logging.INFO)
    monitor_logger.addHandler(monitor_handler)
    monitor_logger.addHandler(console_handler)

    error_logger.setLevel(logging.ERROR)
    error_logger.propagate = False
    error_logger.addHandler(error_handler)
    error_logger.addHandler(console_handler)

    return monitor_logger, error_logger


def log_error(error_logger: logging.Logger, message: str, exc: Exception | None = None) -> None:
    if exc:
        error_logger.error("%s: %s", message, exc)
    else:
        error_logger.error(message)
