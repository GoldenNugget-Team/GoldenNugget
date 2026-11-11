"""Global crash handler for the GoldenNugget GUI.

Catches uncaught Python exceptions and surfaces them in a non-fatal dialog so
the user can either copy the details (with the recent session log) for a bug
report, open the log file, or dismiss it and keep working without losing the
current session.

Two entry points are hooked:

* ``sys.excepthook`` — for exceptions that escape the interpreter (outside the
  Qt event loop).
* ``QApplication.notify`` (via :class:`CrashHandlerApp`) — for exceptions
  raised inside Qt event handlers / slots, which PySide6 otherwise lets die
  silently after a printed traceback.
* ``threading.excepthook`` — for exceptions that escape a plain Python/worker
  thread. These CANNOT build a dialog: on macOS creating ``NSWindow`` (what a
  ``QWidget.show()/exec()`` does underneath) off the main thread raises
  ``NSInternalInconsistencyException`` and aborts the whole process. A crash
  reported from a worker thread is therefore logged in full and its dialog is
  posted to the GUI thread as a queued event (``postEvent`` is thread-safe);
  the app never restarts itself from a worker thread.

Apply/reset failures are routed through the same dialog: the worker threads
report them via :class:`ApplyAlertMessage`, and the main window opens
:func:`show_error_dialog` so the error is *parsed* exactly like a crash
(severity + likely cause + friendly text) and the same Copy/Report buttons are
available.

Use :func:`install_crash_handler` once at startup and
:class:`CrashHandlerApp` instead of a bare ``QApplication``.
"""

import logging
import os
import sys
import threading
import traceback
from typing import Callable, Optional
from urllib.parse import quote

from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEvent,
    QObject,
    QThread,
    QUrl,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)
from shiboken6 import isValid

from src.controllers.nugget_logger import get_log_path, get_log_tail
from src.exceptions.device_errors import is_connection_error, is_device_locked_error
from src.exceptions.nugget_exception import BackupDiskSpaceError

logger = logging.getLogger("GoldenNugget.crash")

ISSUES_URL = "https://github.com/GoldenNugget-Team/GoldenNugget/issues/new"


def _app_name() -> str:
    return QCoreApplication.applicationName() or "GoldenNugget"


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


class CrashDialog(QDialog):
    """Modal dialog showing a friendly error summary with 'Report on GitHub',
    'Copy Error', 'Open Log' and 'Continue' buttons.

    ``backup_path`` / ``on_restore`` make the dialog usable for apply failures
    where a protective backup is still on disk and can be restored.
    """

    def __init__(self, parent: Optional[QObject] = None,
                 summary: str = "", traceback_text: str = "", info: Optional[dict] = None,
                 backup_path: Optional[str] = None,
                 on_restore: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "{0} - Detected an Error").format(_app_name()))
        self.setModal(True)
        self.resize(640, 480)

        self._traceback_text = traceback_text
        self._backup_path = backup_path
        self._on_restore = on_restore
        info = info or _classify(Exception, Exception())
        self._info = info

        layout = QVBoxLayout(self)

        heading = QLabel(QCoreApplication.translate("Nugget", 
            "GoldenNugget detected an error. Here's what we know - report it to "
            "us or copy the details (with the session log) before restarting."))
        heading.setWordWrap(True)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(heading)

        severity_label = QLabel(QCoreApplication.translate("Nugget", "Severity: {0}").format(
            QCoreApplication.translate("Nugget", info['severity'])))
        severity_label.setWordWrap(True)
        layout.addWidget(severity_label)

        fault_label = QLabel(QCoreApplication.translate("Nugget", "Likely cause: {0}").format(
            QCoreApplication.translate("Nugget", info['fault'])))
        fault_label.setWordWrap(True)
        layout.addWidget(fault_label)

        friendly_label = QLabel(QCoreApplication.translate("Nugget", info['friendly']))
        friendly_label.setWordWrap(True)
        friendly_label.setStyleSheet("color: #007AFF; font-style: italic;")
        layout.addWidget(friendly_label)

        self._searchable = QPlainTextEdit()
        self._searchable.setReadOnly(True)
        self._searchable.setPlainText(summary)
        self._searchable.setMaximumHeight(64)
        layout.addWidget(self._searchable)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlainText(traceback_text)
        self._details.setPlaceholderText(QCoreApplication.translate("Nugget", "No technical details available."))
        layout.addWidget(self._details, 1)

        log_path_label = QLabel(QCoreApplication.translate("Nugget", "Log: {0}").format(get_log_path()))
        log_path_label.setWordWrap(True)
        log_path_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(log_path_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        if self._backup_path:
            restore_btn = QPushButton(QCoreApplication.translate("Nugget", "Restore data from backup"))
            restore_btn.setToolTip(QCoreApplication.translate("Nugget", 
                "Restore the protective backup from the failed apply to avoid "
                "data loss."))
            restore_btn.clicked.connect(self._restore)
            buttons.addWidget(restore_btn)

        report_btn = QPushButton(QCoreApplication.translate("Nugget", "Report on GitHub"))
        report_btn.setToolTip(QCoreApplication.translate("Nugget", 
            "Copies the error details + session log and opens the issue "
            "tracker in your browser with a pre-filled report."))
        report_btn.clicked.connect(lambda: self._report(info, summary, traceback_text))
        buttons.addWidget(report_btn)

        copy_btn = QPushButton(QCoreApplication.translate("Nugget", "Copy Error"))
        copy_btn.setToolTip(QCoreApplication.translate("Nugget", "Copies the full error report + session log to the clipboard."))
        copy_btn.clicked.connect(self._copy)
        buttons.addWidget(copy_btn)

        open_log_btn = QPushButton(QCoreApplication.translate("Nugget", "Open Log"))
        open_log_btn.setToolTip(QCoreApplication.translate("Nugget", "Opens the session log file in your preferred text editor."))
        open_log_btn.clicked.connect(self._open_log)
        buttons.addWidget(open_log_btn)

        continue_btn = QPushButton(QCoreApplication.translate("Nugget", "Restart App"))
        continue_btn.setToolTip(QCoreApplication.translate("Nugget", "Close the error report and relaunch GoldenNugget."))
        continue_btn.setDefault(True)
        continue_btn.clicked.connect(self.accept)
        buttons.addWidget(continue_btn)

        layout.addLayout(buttons)

    def _copy(self):
        QApplication.clipboard().setText(_full_report(self._info, self._searchable.toPlainText(),
                                                       self._traceback_text))

    def _open_log(self):
        path = get_log_path()
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _report(self, info: dict, summary: str, traceback_text: str):
        QApplication.clipboard().setText(_full_report(info, summary, traceback_text))
        url = _build_issues_url(info, summary, traceback_text)
        QDesktopServices.openUrl(QUrl(url))

    def _restore(self):
        cb = self._on_restore
        self.accept()
        if cb is not None:
            cb()

    def exec(self) -> int:
        return super().exec()


# Dialogs currently on screen. Keeping a strong reference here means the cyclic
# collector can never be the one that frees the wrapper while the C++ widget is
# still alive (see ``_exec_dialog_on_gui_thread``).
_live_dialogs: list = []


def _exec_dialog_on_gui_thread(dialog: CrashDialog) -> "int | None":
    """``exec()`` a crash dialog and destroy its C++ object on the GUI thread.

    Every button in :class:`CrashDialog` is connected to a lambda/bound method
    that captures ``self``, so the Python wrapper sits in a reference cycle. If
    that cycle is left to the cyclic GC, it is collected by whichever thread
    happens to trigger a collection — and during an apply that is ApplyThread.
    Shiboken then destroys the QDialog off the GUI thread, which tears down its
    children and delivers their events while the main thread is still
    dispatching for the same widget; the result is a SIGSEGV inside
    ``PySide::getWrapperForQObject``.

    So: pin the wrapper for the lifetime of the modal loop, then delete the C++
    side here (``deleteLater`` is processed by the GUI thread) and drop the pin.
    Whatever GC does with the leftover cycle afterwards is harmless because the
    wrapper is already invalidated.
    """
    _live_dialogs.append(dialog)
    result = None
    try:
        result = dialog.exec()
    finally:
        try:
            dialog.deleteLater()
        finally:
            try:
                _live_dialogs.remove(dialog)
            except ValueError:
                pass
    return result


def show_error_dialog(summary: str, traceback_text: str, info: Optional[dict] = None,
                      backup_path: Optional[str] = None,
                      on_restore: Optional[Callable[[], None]] = None) -> bool:
    """Show the crash/error dialog on the main thread, if a QApplication exists.

    Also used for apply/reset failures so they get parsed and reported exactly
    like uncaught exceptions.

    Returns True only when the user accepted the dialog (the "Restart App" /
    restore buttons); every other dismissal answers False, so the caller can
    exit instead of force-relaunching. Off-GUI-thread requests are posted as a
    ``_CrashEvent`` and the answer is unknown — treated as False.
    """
    app = QApplication.instance()
    if app is None:
        print(f"ERROR: {summary}\n{traceback_text}", file=sys.stderr)
        return False
    if not _on_gui_thread():
        _queue_crash_dialog_on_gui_thread(app, summary, traceback_text, info,
                                          backup_path, on_restore)
        return False
    dialog = CrashDialog(summary=summary, traceback_text=traceback_text,
                         info=info, backup_path=backup_path, on_restore=on_restore)
    return _exec_dialog_on_gui_thread(dialog) == dialog.Accepted


# Core presenter for the crash dialog (src/gui wiring injects it; tests may
# inject a fake). None → the built-in dialog/print path below.
_presenter = None


def set_presenter(fn) -> None:
    global _presenter
    _presenter = fn


def _show_crash_dialog(summary: str, traceback_text: str, exc_type=None, exc_value=None):
    """Show the crash dialog on the main thread, if a QApplication exists.

    Returns True only when the user asked to restart (see show_error_dialog).
    """
    info = _classify(exc_type, exc_value) if exc_type is not None else None
    if _presenter is not None:
        return _presenter(summary, traceback_text, info) is True
    app = QApplication.instance()
    if app is None:
        # No application yet — fall back to printing so nothing is lost.
        print(f"CRASH: {summary}\n{traceback_text}", file=sys.stderr)
        return False
    if not _on_gui_thread():
        # A worker thread reported this crash. Building a QWidget here would
        # instantiate NSWindow off the main thread (macOS: instant process
        # abort), so post it to the GUI thread instead and continue this
        # thread — the session must be allowed to keep running.
        _queue_crash_dialog_on_gui_thread(app, summary, traceback_text, info)
        return False
    return show_error_dialog(summary, traceback_text, info)


def _on_gui_thread() -> bool:
    """True when widgets/dialogs may be created on the current thread."""
    app = QApplication.instance()
    if app is None:
        return threading.current_thread() is threading.main_thread()
    return QThread.currentThread() is app.thread()


class _CrashEvent(QEvent):
    """Queued "show the crash dialog" request, posted from worker threads.

    ``QApplication.postEvent`` is thread-safe, and the GUI thread processes it
    inside :meth:`CrashHandlerApp.event` — the only cross-thread-safe way to
    marshal widget creation without a helper QObject whose affinity would
    depend on which thread created it first.
    """

    _TYPE = None

    @classmethod
    def qt_type(cls) -> int:
        if cls._TYPE is None:
            cls._TYPE = QEvent.registerEventType()
        return cls._TYPE

    def __init__(self, summary: str, traceback_text: str, info: Optional[dict],
                 backup_path: Optional[str] = None,
                 on_restore: Optional[Callable[[], None]] = None):
        super().__init__(QEvent.Type(self.qt_type()))
        self.summary = summary
        self.traceback_text = traceback_text
        self.info = info
        self.backup_path = backup_path
        self.on_restore = on_restore


def _queue_crash_dialog_on_gui_thread(app, summary: str, traceback_text: str,
                                      info: Optional[dict],
                                      backup_path: Optional[str] = None,
                                      on_restore: Optional[Callable[[], None]] = None) -> None:
    print(f"CRASH: {summary}\n{traceback_text}", file=sys.stderr)
    if isinstance(app, CrashHandlerApp):
        QApplication.postEvent(app, _CrashEvent(summary, traceback_text, info,
                                                backup_path, on_restore))
    else:
        # A plain QApplication never sees our event type; the log (written by
        # _handle_crash above) and stderr are the survivor of record.
        pass


def _restart_app():
    """Relaunch GoldenNugget from the crash handler so the session keeps
    working after an unexpected error. Uses the same args the process was
    started with."""
    from src.utils.restart import restart_app
    restart_app()


def _handle_crash(exc_type, exc_value, exc_tb):
    summary, tb = _format_error(exc_type, exc_value, exc_tb)
    if exc_type is not KeyboardInterrupt:
        logger.error("Uncaught exception (thread=%s): %s\n%s",
                     threading.current_thread().name, summary, tb)
    if not _on_gui_thread():
        # A worker thread crashed. NEVER create the dialog (or os.execv!) on
        # this thread: instantiating NSWindow off the main thread aborts the
        # whole process (NSInternalInconsistencyException), which is exactly
        # what a "widget built from a slot running on the emitter thread"
        # does. _show_crash_dialog posts the report to the GUI thread and this
        # thread keeps running — the session is not lost.
        _show_crash_dialog(summary, tb, exc_type, exc_value)
        return
    try:
        wants_restart = _show_crash_dialog(summary, tb, exc_type, exc_value)
    except Exception:
        # Never let the crash handler itself crash the app. Do NOT restart:
        # a crash before the window exists would loop dialog -> execv forever.
        # Returning lets the interpreter exit normally; the user relaunches.
        print(f"CRASH: {summary}\n{tb}", file=sys.stderr)
        return
    if wants_restart:
        _restart_app()
    # Anything else: the dialog is dismissed and the uncaught exception lets
    # the process exit normally (excepthook) or the event loop keeps running
    # (notify-guard path) — a startup crash can no longer loop forever.


def _excepthook(exc_type, exc_value, exc_tb):
    # Only swallow ordinary exceptions; KeyboardInterrupt should still exit.
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
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


class CrashHandlerApp(QApplication):
    """QApplication subclass that routes Qt event-handler exceptions to the
    crash handler instead of silently printing and dropping them."""

    def event(self, event: QEvent) -> bool:
        if _CrashEvent._TYPE is not None and event.type() == QEvent.Type(_CrashEvent._TYPE) \
                and isinstance(event, _CrashEvent):
            # A worker thread posted a crash report: build the dialog here, on
            # the GUI thread, where NSWindow instantiation is legal.
            try:
                dialog = CrashDialog(summary=event.summary,
                                     traceback_text=event.traceback_text,
                                     info=event.info,
                                     backup_path=event.backup_path,
                                     on_restore=event.on_restore)
                _exec_dialog_on_gui_thread(dialog)
            except Exception:
                print(f"CRASH: {event.summary}\n{event.traceback_text}",
                      file=sys.stderr)
            return True
        return super().event(event)

    def notify(self, receiver: QObject, event: QEvent) -> bool:
        if receiver is not None and not isValid(receiver):
            logger.debug("Discarding queued event for a deleted Qt receiver")
            return False
        try:
            return super().notify(receiver, event)
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            if _is_dead_object_event(exc_value, exc_tb):
                logger.warning("Dropped %s event: %s", event.type(), exc_value)
                return False
            _handle_crash(exc_type, exc_value, exc_tb)
            return False
        except Exception:
            if receiver is not None and not isValid(receiver):
                logger.warning("Qt receiver was deleted during event delivery; discarding its event", exc_info=True)
                return False
            exc_type, exc_value, exc_tb = sys.exc_info()
            _handle_crash(exc_type, exc_value, exc_tb)
            return False


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
        from src.version import App_Build, App_Version
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


_qt_last_message = ["", 0]


def _qt_message_handler(msg_type, context, message):
    """Forward Qt framework messages (qWarning/qCritical/qFatal, including the
    QFont diagnostics and any crash forewarning) into the session log and, for
    warnings+, duplicate them on stderr exactly like Qt's default handler."""
    try:
        from PySide6.QtCore import QtMsgType
        level = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }.get(msg_type, logging.WARNING)
        if message == _qt_last_message[0]:
            _qt_last_message[1] += 1
            return
        last, count = _qt_last_message
        if count > 1:
            logger.log(level, "[Qt] %s (x%d)", last, count)
        _qt_last_message[0] = message
        _qt_last_message[1] = 1
        logger.log(level, "[Qt] %s", message)
        if level >= logging.WARNING:
            print(message, file=sys.stderr)
    except Exception:
        pass


def _install_qt_message_handler():
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass


def install_crash_handler():
    """Install the global uncaught-exception handler.

    Call once before ``QApplication`` is created. The dialog is only shown once
    an application instance exists; exceptions raised before then are logged
    and printed. Native crashes (which never raise a Python exception) are
    captured into a dedicated backtrace dump instead.
    """
    print_startup_banner()
    _install_faulthandler()
    _install_qt_message_handler()
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
