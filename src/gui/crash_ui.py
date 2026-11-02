"""Qt presentation for uncaught exceptions (the GUI half of the crash handler).

:mod:`src.exceptions.crash_handler` owns the classification, the report text
builders and ``sys.excepthook``; this module owns the widgets and the Qt event
plumbing:

* :class:`CrashHandlerApp` — ``QApplication`` subclass whose ``notify`` routes
  slot exceptions to the crash dialog instead of letting PySide print and drop
  them.
* :class:`CrashDialog` — the friendly, non-fatal error report with Copy / Open
  Log / Report on GitHub / Restart.
* :func:`show_error_dialog` — used for uncaught exceptions *and* apply/reset
  failures (through ``ApplyAlertMessage``), so both are parsed the same way.
* :func:`install_crash_handler` — installs the Qt-free handler first, then this
  module registers itself as its presenter, so any error after this point gets
  a dialog.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable, Optional

from shiboken6 import isValid

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from src.controllers.nugget_logger import get_log_path
from src.exceptions import crash_handler as core
from src.exceptions.crash_handler import (
    _app_name,
    _build_issues_url,
    _classify,
    _full_report,
    _handle_crash,
    _is_dead_object_event,
)

logger = logging.getLogger("GoldenNugget.crash")

__all__ = [
    "CrashDialog",
    "CrashHandlerApp",
    "install_crash_handler",
    "install_notify_guard",
    "report_error",
    "show_error_dialog",
    "_classify",
    "_is_dead_object_event",
]


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


def _exec_dialog_on_gui_thread(dialog: CrashDialog) -> None:
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
    try:
        dialog.exec()
    finally:
        try:
            dialog.deleteLater()
        finally:
            try:
                _live_dialogs.remove(dialog)
            except ValueError:
                pass


def show_error_dialog(summary: str, traceback_text: str, info: Optional[dict] = None,
                      backup_path: Optional[str] = None,
                      on_restore: Optional[Callable[[], None]] = None):
    """Show the crash/error dialog on the main thread, if a QApplication exists.

    Also used for apply/reset failures so they get parsed and reported exactly
    like uncaught exceptions.
    """
    app = QApplication.instance()
    if app is None:
        print(f"ERROR: {summary}\n{traceback_text}", file=sys.stderr)
        return
    dialog = CrashDialog(summary=summary, traceback_text=traceback_text,
                         info=info, backup_path=backup_path, on_restore=on_restore)
    _exec_dialog_on_gui_thread(dialog)


def report_error(summary: str, traceback_text: str, info: Optional[dict] = None,
                 backup_path: Optional[str] = None,
                 on_restore: Optional[Callable[[], None]] = None) -> None:
    """Presenter registered with :mod:`src.exceptions.crash_handler`.

    Matches the core presenter signature; the extra ``backup_path`` /
    ``on_restore`` arguments are only supplied by explicit callers.
    """
    show_error_dialog(summary, traceback_text, info,
                      backup_path=backup_path, on_restore=on_restore)


class CrashHandlerApp(QApplication):
    """QApplication subclass that routes Qt event-handler exceptions to the
    crash handler instead of silently printing and dropping them.

    The ``notify`` override is attached by :func:`install_notify_guard` once the
    startup UI exists. A Python override runs for *every* Qt event — startup
    delivers >100k of them, which cost ~0.4 s of pure virtual-dispatch overhead
    while the pages were being built. Until the guard is installed, PySide
    still reports slot exceptions through ``sys.excepthook`` (verified on 6.12),
    so nothing is lost.
    """


def _guarded_notify(self, receiver: QObject, event: QEvent) -> bool:
    if receiver is not None and not isValid(receiver):
        logger.debug("Discarding queued event for a deleted Qt receiver")
        return False
    try:
        return super(CrashHandlerApp, self).notify(receiver, event)
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


def install_notify_guard(app=None) -> bool:
    """Start routing Qt event-handler exceptions to the crash dialog.

    Call once the startup UI is built (right before ``app.exec()``). Returns
    True when the guard was installed by this call.
    """
    app = app if app is not None else QApplication.instance()
    if not isinstance(app, CrashHandlerApp):
        return False
    if getattr(app, "_notify_guard_installed", False):
        return False
    type(app).notify = _guarded_notify
    app._notify_guard_installed = True
    return True


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
    """Install the global crash handling for a GUI session.

    Runs the Qt-free part from :mod:`src.exceptions.crash_handler`, registers
    this module's dialog as its presenter, and installs the Qt message handler.
    Call once before the application object is created.
    """
    core.install_crash_handler()
    core.set_presenter(report_error)
    _install_qt_message_handler()
