"""Session logging — the single place that decides where logs go.

One rotating file handler is created on first use and attached to the root
logger *and* the ``GoldenNugget`` hierarchy (whose ``propagate=False`` in
``src/gui/logger.py`` would otherwise starve the file). The active path is
exposed so the crash handler can embed the recent tail into crash reports and
clipboard copies.

Paths (first match wins):
* ``GOLDENNUGGET_LOG_FILE`` env var (overrides everything, keeps working when
  the app is frozen with PyInstaller)
* a per-run timestamped file inside the OS AppData ``Logs`` dir, falling back
  to ``~/.nugget_logs`` when that is not writable.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

from src.utils.paths import app_data_dir

_active_log_path: str | None = None
_file_handler: logging.Handler | None = None

# Keep 6 x 16 MiB = 96 MiB max on disk per run (verbose DEBUG sessions can get
# chatty, and a rotated-away early line is exactly what a bug report needs).
_MAX_BYTES = 16 * 1024 * 1024
_BACKUP_COUNT = 6


def get_log_dir() -> str:
    app_data_path = str(app_data_dir())
    log_dir = os.path.join(app_data_path, "Logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.path.join(os.path.expanduser("~"), ".nugget_logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            pass
    return log_dir


def get_log_path() -> str:
    """Return the session log path, initializing on first call."""
    if _active_log_path:
        return _active_log_path
    env = os.environ.get("GOLDENNUGGET_LOG_FILE")
    if env:
        return env
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(get_log_dir(), f"nugget_{timestamp}.log")


def get_file_handler() -> logging.Handler:
    """Return the session file handler, creating it on first use."""
    if _file_handler is None:
        init_logging()
    return _file_handler


def _make_formatter(with_thread: bool = True) -> logging.Formatter:
    if with_thread:
        return logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(threadName)-12s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")


def init_logging() -> str:
    """Create the rotating file handler (idempotent) and return the path.

    Attaches to the root logger AND the ``GoldenNugget`` logger so nothing is
    lost whatever ``propagate`` flags exist downstream.
    """
    global _active_log_path, _file_handler
    if _file_handler is not None:
        return _active_log_path

    _active_log_path = get_log_path()
    try:
        os.makedirs(os.path.dirname(_active_log_path) or ".", exist_ok=True)
    except OSError:
        pass

    try:
        _file_handler = RotatingFileHandler(
            _active_log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
            encoding="utf-8")
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(_make_formatter())
    except Exception as e:  # never crash because logging failed
        print(f"[logger] file handler disabled: {e}", file=sys.stderr)
        _file_handler = logging.NullHandler()

    root = logging.getLogger()
    root.addHandler(_file_handler)

    gn = logging.getLogger("GoldenNugget")
    gn.addHandler(_file_handler)
    # Records headed for ``GoldenNugget`` are already handled here; without
    # this they would climb to the root handler and be written twice.
    gn.propagate = False

    logging.getLogger("pymobiledevice3").setLevel(logging.DEBUG)
    logging.getLogger("GoldenNugget").setLevel(logging.DEBUG)

    return _active_log_path


def get_log_tail(max_chars: int = 64 * 1024) -> str:
    """Return the tail of the active session log (head-truncated)."""
    path = get_log_path()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return ""
            start = max(0, size - max_chars)
            f.seek(start)
            text = f.read()
        if start > 0:
            # Drop the first (possibly partial) line so we start on a clean record.
            nl = text.find("\n")
            if nl != -1:
                text = text[nl + 1:]
        return text
    except Exception:
        return ""


def log_banner(logger_name: str = "GoldenNugget") -> None:
    """Log environment/version info at session start."""
    import platform
    try:
        from src.version import App_Version
        version = str(App_Version)
    except Exception:
        version = "unknown"
    logger = logging.getLogger(logger_name)
    logger.info("GoldenNugget %s | %s | Python %s | log=%s",
                version, platform.platform(), platform.python_version(), get_log_path())


def log_context(msg: str, **fields) -> None:
    """Log a context block (device, iOS, mode...) as a single readable line."""
    extra = " | ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, "", "unknown"))
    logger = logging.getLogger("GoldenNugget.context")
    if extra:
        logger.info("CONTEXT %s | %s", msg, extra)
    else:
        logger.info("CONTEXT %s", msg)