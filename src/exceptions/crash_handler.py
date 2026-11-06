"""Global crash handling — parsing and reporting, deliberately Qt-free.

This module owns everything about an uncaught exception that does not need a
widget: the classification used for the friendly text, the GitHub issue body /
clipboard report builders, the startup banner, the native-crash dump and the
``sys.excepthook`` / ``sys.unraisablehook`` installation.

The presentation lives in :mod:`src.gui.crash_ui`, which installs itself as the
**presenter** through :func:`set_presenter` at startup. Until that happens (a
CLI run, or an exception before the window exists) the handler degrades to
printing on stderr, so an error is never silently lost.

Two entry points are hooked at runtime:

* ``sys.excepthook`` — for exceptions that escape the interpreter (outside the
  Qt event loop).
* ``QApplication.notify`` — installed by the GUI presenter
  (:class:`src.gui.crash_ui.CrashHandlerApp`) for exceptions raised inside Qt
  event handlers / slots, which PySide6 otherwise lets die silently.
* ``threading.excepthook`` — for exceptions that escape a plain Python/worker
  thread. These MUST NOT build a dialog off the GUI thread: on macOS creating
  ``NSWindow`` (what a ``QWidget.show()/exec()`` does underneath) off the main
  thread raises ``NSInternalInconsistencyException`` and aborts the whole
  process. A crash reported from a worker thread is therefore logged in full
  (with the thread name) and its dialog is marshalled to the GUI thread by the
  presenter (``src.gui.crash_ui`` posts a ``_CrashEvent`` — ``postEvent`` is
  thread-safe); the app never restarts itself from a worker thread.

Apply/reset failures are routed through the same presenter: the worker threads
report them via :class:`ApplyAlertMessage`, and the main window asks
:func:`show_error_dialog` (GUI module) to present them with the same
Copy/Report buttons.
"""

import sys
import traceback
import logging
import os
import threading
from typing import Callable, Optional
from urllib.parse import quote

from src.utils.i18n import QT_TRANSLATE_NOOP
from src.controllers.nugget_logger import get_log_path, get_log_tail
from src.exceptions.device_errors import is_connection_error, is_device_locked_error
from src.exceptions.nugget_exception import BackupDiskSpaceError
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError

logger = logging.getLogger("GoldenNugget.crash")

ISSUES_URL = "https://github.com/awesomenull-dev/GoldenNugget/issues/new"


# --------------------------------------------------------------------------- #
# Presenter hook (the GUI registers itself here)
# --------------------------------------------------------------------------- #

# ``presenter(summary, traceback_text, info, backup_path, on_restore)``.
# Kept as a module global so the GUI can plug in without this module importing
# Qt. ``None`` means "no user interface available" (CLI / very early startup).
_presenter: Optional[Callable[..., None]] = None


def set_presenter(presenter: Optional[Callable[..., None]]) -> None:
    """Install (or clear) the function that shows errors to the user."""
    global _presenter
    _presenter = presenter


def has_presenter() -> bool:
    return _presenter is not None


def _app_name() -> str:
    return "GoldenNugget"


def _format_error(exc_type, exc_value, exc_tb) -> str:
    """Return ``(short_summary, full_traceback)`` for the given exception."""
    try:
        summary = f"{exc_type.__name__}: {exc_value}"
    except Exception:
        summary = f"{exc_type.__name__}"
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    return summary, tb


def _classify(exc_type, exc_value) -> dict:
    """Turn a caught exception into user-friendly metadata.

    Returns a dict with ``severity`` (Fatal/Serious/Moderate/Minor), ``fault``
    (approximate attribution) and ``friendly`` (a plain-language description).
    """
    try:
        name = getattr(exc_type, "__name__", "Error") or "Error"
    except Exception:
        name = "Error"
    msg = ""
    try:
        msg = str(exc_value)
    except Exception:
        pass
    try:
        module = getattr(exc_type, "__module__", "") or ""
    except Exception:
        module = ""

    # Defaults
    severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Serious"), QT_TRANSLATE_NOOP("Nugget", "Unknown"), f"An error occurred ({name})."

    # --- Device locked ---
    if is_device_locked_error(exc_value):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Moderate"), QT_TRANSLATE_NOOP("Nugget", "Your device"), \
            QT_TRANSLATE_NOOP("Nugget", "Your device is locked. Unlock it and keep it awake, then try again.")
    elif issubclass(exc_type, (BackupDiskSpaceError, NotEnoughDiskSpaceError)):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Moderate"), QT_TRANSLATE_NOOP("Nugget", "Your computer's storage"), \
            (msg or QT_TRANSLATE_NOOP("Nugget", "The backup drive does not have enough free disk space. "
             "Free space or choose another backup location in Settings."))
    # --- File / OS / user-data issues (subclasses of OSError, so they MUST be
    # checked before the generic connection/OSError branch below). ---
    elif issubclass(exc_type, FileNotFoundError):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Minor"), QT_TRANSLATE_NOOP("Nugget", "Your files or setup"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget couldn't find a file or folder it needed.")
    elif issubclass(exc_type, PermissionError):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Minor"), QT_TRANSLATE_NOOP("Nugget", "Your files or setup"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget didn't have permission to access a file or folder.")
    elif issubclass(exc_type, FileExistsError):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Minor"), QT_TRANSLATE_NOOP("Nugget", "Your files or setup"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget tried to create something that already exists.")
    elif issubclass(exc_type, (IsADirectoryError, NotADirectoryError)):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Minor"), QT_TRANSLATE_NOOP("Nugget", "Your files or setup"), \
            QT_TRANSLATE_NOOP("Nugget", "A file path was used as a folder (or a folder as a file).")
    # --- Device / connection ---
    elif is_connection_error(exc_value) or "terminated" in msg.lower():
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Moderate"), QT_TRANSLATE_NOOP("Nugget", "Your device or connection"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget couldn't communicate with your device.")
    # --- Out of memory ---
    elif issubclass(exc_type, MemoryError):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Fatal"), QT_TRANSLATE_NOOP("Nugget", "Your computer"), \
            QT_TRANSLATE_NOOP("Nugget", "Your computer ran out of memory. Close some programs and try again.")
    # --- App logic / programming errors ---
    elif name == "NuggetException" or module.startswith("src."):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Serious"), QT_TRANSLATE_NOOP("Nugget", "The app (GoldenNugget)"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget hit an internal problem.")
    elif issubclass(exc_type, (TypeError, ValueError, KeyError, IndexError,
                               AttributeError, ImportError, NameError, OSError)):
        severity, fault, friendly = QT_TRANSLATE_NOOP("Nugget", "Serious"), QT_TRANSLATE_NOOP("Nugget", "The app (GoldenNugget)"), \
            QT_TRANSLATE_NOOP("Nugget", "GoldenNugget hit an internal problem.")

    return {
        "severity": severity,
        "fault": fault,
        "friendly": friendly,
        "type_name": name,
    }


def _log_tail_for_report() -> str:
    """Recent session log tail, bounded, with a header line."""
    try:
        tail = get_log_tail(64 * 1024).rstrip("\n")
        if not tail:
            return ""
        return f"\n\n--- Recent session log ({get_log_path()}) ---\n{tail}"
    except Exception:
        return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[- (2 * limit) // 3:]
    return f"{head}\n... [log truncated ...]\n{tail}"


def _build_issue_body(info: dict, summary: str, traceback_text: str,
                      include_log: bool = True) -> str:
    """Assemble the text pasted into the prefilled GitHub issue."""
    try:
        from src.version import App_Version
        version = str(App_Version)
    except Exception:
        version = "unknown"
    body = (
        "## GoldenNugget Error Report\n\n"
        f"**App version:** {version}\n"
        f"**Severity:** {info['severity']}\n"
        f"**Likely cause:** {info['fault']}\n\n"
        f"**What went wrong:**\n{info['friendly']}\n\n"
        f"**Error:** `{summary}`\n\n"
        "<details><summary>Technical details</summary>\n\n"
        "```\n" + _truncate(traceback_text, 16 * 1024) + "\n```\n\n"
        "</details>\n\n"
    )
    if include_log:
        log_tail = _log_tail_for_report()
        if log_tail:
            body += ("<details><summary>Session log</summary>\n\n"
                     "```\n" + _truncate(log_tail, 24 * 1024) +
                     "\n```\n\n</details>\n\n")
    body += "<!-- Please add any steps you took before this error appeared. -->"
    return body


def _build_issues_url(info: dict, summary: str, traceback_text: str) -> str:
    title = f"Error: {info['severity']} - {info['friendly']}"
    body = _build_issue_body(info, summary, traceback_text, include_log=True)
    return f"{ISSUES_URL}?title={quote(title)}&body={quote(body)}"


def _full_report(info: dict, summary: str, traceback_text: str) -> str:
    """The complete clipboard payload: report + traceback + session log."""
    report = _build_issue_body(info, summary, traceback_text, include_log=True)
    return report.replace("<!-- Please add any steps you took before this error appeared. -->",
                          "").rstrip()


def _restart_app():
    """Relaunch GoldenNugget from the crash handler so the session keeps
    working after an unexpected error. Uses the same args the process was
    started with; falls back to a plain re-exec if anything fails.

    Main-thread only — ``os.execv`` replaces the process and running it from a
    worker thread is undefined; :func:`_handle_crash` never calls this after a
    worker-thread crash.
    """
    try:
        if getattr(sys, "frozen", False):
            # PyInstaller: sys.argv[0] is already the exe path.
            target = sys.argv if len(sys.argv) > 1 else [sys.executable]
            os.execv(sys.executable, target)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        try:
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception:
            pass


def _show_crash_dialog(summary: str, traceback_text: str, exc_type=None, exc_value=None):
    """Hand a crash to the GUI presenter, or print it when there is none."""
    info = _classify(exc_type, exc_value) if exc_type is not None else None
    if _presenter is None:
        # No user interface yet — fall back to printing so nothing is lost.
        print(f"CRASH: {summary}\n{traceback_text}", file=sys.stderr)
        return
    _presenter(summary, traceback_text, info)


def _on_main_thread() -> bool:
    """Qt-free stand-in for ``src.gui.crash_ui._on_gui_thread``.

    The GUI thread IS the main thread here (``QApplication`` is created on
    it), so "may we restart the process" can be answered without importing
    Qt. The authoritative widget-affinity check lives in the GUI presenter.
    """
    return threading.current_thread() is threading.main_thread()


def _handle_crash(exc_type, exc_value, exc_tb):
    summary, tb = _format_error(exc_type, exc_value, exc_tb)
    if exc_type is not KeyboardInterrupt:
        logger.error("Uncaught exception (thread=%s): %s\n%s",
                     threading.current_thread().name, summary, tb)
    if not _on_main_thread():
        # A worker thread crashed. NEVER restart the process here (os.execv is
        # main-thread only) and never let a widget be built: the presenter
        # (src.gui.crash_ui) posts its dialog to the GUI thread instead. This
        # thread keeps running — the session is not lost.
        _show_crash_dialog(summary, tb, exc_type, exc_value)
        return
    try:
        _show_crash_dialog(summary, tb, exc_type, exc_value)
    except Exception:
        # Never let the crash handler itself crash the app.
        print(f"CRASH: {summary}\n{tb}", file=sys.stderr)
        _restart_app()
        return
    _restart_app()


def _excepthook(exc_type, exc_value, exc_tb):
    # Only swallow ordinary exceptions; KeyboardInterrupt should still exit.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    # Qt raises this while converting an already-deleted receiver for a Python
    # event filter; there is no handler frame, so nothing can act on it. The
    # guarded notify() drops it per event — this covers the window before
    # install_notify_guard() runs (startup) where PySide reports it here.
    if _is_dead_object_event(exc_value, exc_tb):
        logger.debug("Dropped event for a deleted Qt object: %s", exc_value)
        return
    _handle_crash(exc_type, exc_value, exc_tb)


def _is_dead_object_event(exc_value, exc_tb) -> bool:
    """True when Qt delivered an event to an object whose Python wrapper is
    already gone, usually while windows are torn down on close. PySide raises
    while converting that object for a Python event filter, before any of our
    code runs, so the traceback has no frame past ``notify``. Nothing can
    handle such an event; errors raised inside our own handlers have deeper
    frames and still reach the crash dialog."""
    return ("already deleted" in str(exc_value)
            and exc_tb is not None and exc_tb.tb_next is None)


def _detect_desktop() -> str:
    """Detect the current desktop environment."""
    if sys.platform == "linux":
        de = (os.environ.get("XDG_CURRENT_DESKTOP")
              or os.environ.get("XDG_SESSION_DESKTOP")
              or os.environ.get("DESKTOP_SESSION")
              or "unknown")
        session_type = os.environ.get("XDG_SESSION_TYPE") or "unknown"
        return f"{de} ({session_type})"
    elif sys.platform == "darwin":
        return "AppKit"
    elif sys.platform == "win32":
        return "Win32"
    else:
        return sys.platform


def print_startup_banner() -> None:
    """Print a startup info banner to the terminal."""
    try:
        from src.version import App_Version, App_Build
        version_str = str(App_Version)
        beta_build = int(App_Build)
    except Exception:
        version_str = "unknown"
        beta_build = 0

    if beta_build > 0:
        version_str += f" (beta {beta_build})"

    frozen = getattr(sys, "frozen", False)
    run_env = "PyInstaller" if frozen else "generic"

    desktop = _detect_desktop()

    is_release = "yes" if (frozen and beta_build == 0) else "no"
    is_beta = "yes" if beta_build > 0 else "no"

    # Only reliable in the official GitHub Actions workspace;
    # always "yes" locally or on other repos.
    off_build = "no" if os.environ.get("GITHUB_ACTIONS") else "yes"

    print(f"GoldenNugget {version_str}")
    print(f"Running on: {sys.platform} ({run_env})")
    print(f"Desktop: {desktop}")
    print(f"IsRelease?: {is_release}")
    print(f"IsBeta?: {is_beta}")
    print(f"Off-Build?: {off_build}")


def _install_faulthandler():
    """Route native crashes (segfault / stack overflow / fatal abort) to a
    dedicated dump file. Python exceptions are handled by the crash dialog, but
    a native fault kills the process before the interpreter can react - this
    captures whatever stack is left so the bug can be diagnosed."""
    try:
        import faulthandler
        from src.controllers.nugget_logger import get_log_dir
        dump_path = os.path.join(get_log_dir(), "nugget_crash_backtrace.log")
        dump_file = open(dump_path, "ab", buffering=0)
        faulthandler.enable(all_threads=True, file=dump_file)
        print(f"[init] Native-crash backtraces -> {dump_path}", file=sys.stderr)
    except Exception:
        pass


def install_crash_handler():
    """Install the global uncaught-exception handler (Qt-free part).

    Call once before the window is created. Errors are printed until a GUI
    presenter is registered through :func:`set_presenter`. Native crashes
    (which never raise a Python exception) are captured into a dedicated
    backtrace dump instead.
    """
    print_startup_banner()
    _install_faulthandler()
    sys.excepthook = _excepthook
    # Plain Python threads (queue workers, asyncio.ToThread helpers, ...)
    # route uncaught exceptions through threading.excepthook, which by default
    # only prints. Route them into the same handler so the report reaches the
    # log AND a dialog can be shown — on the GUI thread via _handle_crash's
    # worker-thread path (never building widgets off the main thread).
    try:
        def _threading_excepthook(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
                return
            _handle_crash(args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = _threading_excepthook
    except Exception:
        pass
    # Sys.unraisablehook catches errors in __del__ / finalizers, which would
    # otherwise be reported to stderr and might quietly abort cleanup.
    try:
        import warnings

        def _unraisable(unraisable):
            summary = f"{unraisable.exc_type.__name__}: {unraisable.exc_value}"
            warnings.warn(
                f"Unraisable exception in GoldenNugget: {summary}",
                RuntimeWarning,
                stacklevel=2,
            )

        sys.unraisablehook = _unraisable
    except Exception:
        pass
