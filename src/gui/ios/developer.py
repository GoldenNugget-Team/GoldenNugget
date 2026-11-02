"""Local client tools for the home control bar."""
import ast
import logging
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from src.gui.widgets import (
    IOSSwitch, _auto_retheme,
)
from src.gui.theme import t


def _tr(text):
    return QCoreApplication.translate("Developer", text)


class DeveloperPanel(QWidget):
    _WATCH_INTERVAL_MS = 1000
    _SETTLE_SECONDS = 2.0
    _SOURCE_SUFFIXES = {'.py', '.svg', '.qss', '.qrc', '.ui'}

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self._packaged = bool(getattr(sys, 'frozen', False))
        self._root = Path(__file__).resolve().parents[3]
        self._snapshot = {}
        self._pending_python = set()
        self._changed_at = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        self.build_label = QLabel()
        self.build_label.hide()
        layout.addWidget(self.build_label)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.restart_button = QPushButton(_tr("Restart app"))
        self.restart_button.setMinimumHeight(32)
        self.restart_button.clicked.connect(lambda: self._restart())
        actions.addWidget(self.restart_button)
        self.reload_label = QLabel(_tr("Auto Reload (For changes)"))
        actions.addWidget(self.reload_label)
        enabled = not self._packaged and window.settings.value('developer_auto_reload', False, type=bool)
        self.reload_switch = IOSSwitch(enabled, self)
        self.reload_switch.setAccessibleName(_tr("Automatically restart after source changes"))
        self.reload_switch.setToolTip(_tr("Restart after local code or UI assets change. Waits for active device operations to finish."))
        self.reload_switch.setEnabled(not self._packaged)
        self.reload_label.setEnabled(not self._packaged)
        if self._packaged:
            self.reload_switch.setToolTip(_tr("Auto-reload is available when running from source."))
        self.reload_switch.toggled.connect(self._set_auto_reload)
        actions.addWidget(self.reload_switch)
        actions.addStretch()
        layout.addLayout(actions)
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(self._WATCH_INTERVAL_MS)
        self._watch_timer.timeout.connect(self._check_changes)
        if enabled:
            self._snapshot = self._source_snapshot()
            self._watch_timer.start()
        self._retheme()
        _auto_retheme(self)

    def _show_status(self, text):
        self.build_label.setText(text)
        self.build_label.show()

    def _set_auto_reload(self, enabled):
        enabled = enabled and not self._packaged
        self.window.settings.setValue('developer_auto_reload', enabled)
        self.window.settings.sync()
        self._changed_at = None
        self._pending_python.clear()
        self.build_label.clear()
        self.build_label.hide()
        if enabled:
            self._snapshot = self._source_snapshot()
            self._watch_timer.start()
        else:
            self._watch_timer.stop()
            self._snapshot.clear()

    def _source_snapshot(self):
        """``{path: (mtime_ns, size)}`` for every watched source file.

        ``os.walk`` + one ``stat`` per file: the previous version globbed with
        ``rglob('*')`` and then called ``stat()`` and ``is_file()`` on every
        entry, i.e. two syscalls per path, every watch tick.
        """
        snapshot = {}
        root = self._root
        try:
            stat_result = (root / 'main_app.py').stat()
            snapshot[str(root / 'main_app.py')] = (stat_result.st_mtime_ns, stat_result.st_size)
        except OSError:
            pass
        src = root / 'src'
        if not src.is_dir():
            return snapshot
        for directory, dirnames, filenames in os.walk(src):
            if '__pycache__' in dirnames:
                dirnames.remove('__pycache__')
            for name in filenames:
                if os.path.splitext(name)[1] not in self._SOURCE_SUFFIXES:
                    continue
                path = os.path.join(directory, name)
                try:
                    stat_result = os.stat(path)
                except OSError:
                    continue
                snapshot[path] = (stat_result.st_mtime_ns, stat_result.st_size)
        return snapshot

    def _check_changes(self):
        snapshot = self._source_snapshot()
        if snapshot != self._snapshot:
            self._pending_python.update(path for path, value in snapshot.items()
                                        if path.endswith('.py') and value != self._snapshot.get(path))
            self._snapshot = snapshot
            self._changed_at = time.monotonic()
            self._show_status(_tr("Changes detected…"))
            return
        if self._changed_at is None or time.monotonic() - self._changed_at < self._SETTLE_SECONDS:
            return
        if self._device_busy():
            self._show_status(_tr("Changes ready — waiting for the device operation"))
            return
        for name in self._pending_python:
            path = Path(name)
            if not path.exists():
                continue
            try:
                ast.parse(path.read_bytes(), filename=name)
            except (SyntaxError, OSError, ValueError):
                self._show_status(_tr("Waiting for valid Python changes…"))
                return
        self._restart(automatic=True)

    def _device_busy(self):
        window = self.window
        if getattr(window, 'apply_in_progress', False) or getattr(window, '_cache_restore_in_progress', False):
            return True
        workers = (
            getattr(window, 'worker_thread', None),
            getattr(window, '_cache_restore_thread', None),
            getattr(window, '_cache_update_thread', None),
            getattr(window, 'refresh_worker_thread', None),
            getattr(window.built_page('ios_passthemes'), '_worker', None),
            getattr(window.built_page('ios_settings'), '_reset_pairing_thread', None),
        )
        for worker in workers:
            try:
                if worker is not None and worker.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def _restart(self, automatic=False):
        if self._device_busy():
            self._show_status(_tr("Wait for the device operation before restarting"))
            return
        self.window.settings.sync()
        for handler in logging.getLogger().handlers:
            handler.flush()
        arguments = sys.argv[1:] if self._packaged else sys.argv
        try:
            os.execl(sys.executable, sys.executable, *arguments)
        except OSError as error:
            if automatic:
                self.reload_switch.setChecked(False)
                self._show_status(_tr("Auto-reload stopped: could not restart"))
                logging.getLogger('GoldenNugget.developer').exception('Auto-reload failed')
            else:
                QMessageBox.warning(self, _tr("Could not restart"), str(error))

    def _retheme(self):
        self.build_label.setStyleSheet(t("home_subtitle"))
        self.reload_label.setStyleSheet(t("home_subtitle"))
        self.restart_button.setStyleSheet(t("mini_button"))
