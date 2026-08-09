"""Logging setup for monitor.log and errors.log with size rotation."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from config import LOG_DIR


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def setup_logging() -> tuple[logging.Logger, logging.Logger]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    monitor_logger = logging.getLogger("mt5_monitor")
    error_logger = logging.getLogger("mt5_monitor.errors")

    if monitor_logger.handlers:
        return monitor_logger, error_logger

    # Defaults: 5 MB per file, keep 3 backups => ~15 MB max per log type
    max_bytes = _env_int("LOG_MAX_MB", 5) * 1024 * 1024
    backup_count = _env_int("LOG_BACKUP_COUNT", 3)
    if max_bytes < 1024 * 1024:
        max_bytes = 1024 * 1024
    if backup_count < 1:
        backup_count = 1

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    monitor_handler = RotatingFileHandler(
        LOG_DIR / "monitor.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    monitor_handler.setFormatter(formatter)
    monitor_handler.setLevel(logging.INFO)

    error_handler = RotatingFileHandler(
        LOG_DIR / "errors.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
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

    monitor_logger.info(
        "Logging ready: rotate at %s MB, keep %s backups (logs/)",
        max_bytes // (1024 * 1024),
        backup_count,
    )

    return monitor_logger, error_logger


def log_error(error_logger: logging.Logger, message: str, exc: Exception | None = None) -> None:
    if exc:
        error_logger.error("%s: %s", message, exc)
    else:
        error_logger.error(message)
