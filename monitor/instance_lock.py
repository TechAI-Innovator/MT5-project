"""Ensure only one monitor process runs at a time."""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
from pathlib import Path

from config import PROJECT_ROOT

LOCK_PATH = PROJECT_ROOT / "logs" / "monitor.lock"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        kwargs = {
            "text": True,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}"],
            **kwargs,
        )
        return str(pid) in output
    except (OSError, subprocess.SubprocessError):
        return False


def acquire_lock() -> bool:
    """Return True if this process owns the lock; False if another monitor is live."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            old_pid = -1

        if old_pid != os.getpid() and _pid_is_running(old_pid):
            print(
                f"Another MT5 monitor is already running (PID {old_pid}).\n"
                "Stop it before starting Task Scheduler, or run only one copy.\n"
                f"Lock file: {LOCK_PATH}",
                file=sys.stderr,
            )
            return False

    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(release_lock)
    return True


def release_lock() -> None:
    try:
        if LOCK_PATH.exists():
            current = LOCK_PATH.read_text(encoding="utf-8").strip()
            if current == str(os.getpid()):
                LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
