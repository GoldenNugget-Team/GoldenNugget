"""Inline, cancellable Find My wait for the active restore worker."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from awesomeui.liquid.controls import LiquidCard
from src.devicemanagement.device_capabilities import device_text
from src.gui.theme import ColorThemeManager, t, theme_pixmap


class FindMyWarningCard(LiquidCard):
    def __init__(self, window, parent=None):
        self._content_ready = False
        super().__init__(parent)
        self.window = window
        self._control = None
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(12)
        self.icon = QLabel(self)
        self.icon.setFixedSize(30, 30)
        row.addWidget(self.icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(5)
        self.title = QLabel(self.tr("Turn off Find My to continue"), self)
        self.title.setWordWrap(True)
        text.addWidget(self.title)
        self.description = QLabel(self)
        self.description.setWordWrap(True)
        text.addWidget(self.description)
        self.check_status = QLabel(self)
        text.addWidget(self.check_status)
        row.addLayout(text, 1)
        self.cancel_button = QPushButton(self.tr("Cancel apply"), self)
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.clicked.connect(self._cancel)
        row.addWidget(self.cancel_button, 0, Qt.AlignVCenter)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._sync)
        self._content_ready = True
        self._retheme()
        self.hide()

    def set_busy(self, busy):
        if busy:
            self._timer.start()
        else:
            self._timer.stop()
        self._sync() if busy else self.hide()

    def _sync(self):
        cache_restore = getattr(self.window, "_cache_restore_in_progress", False)
        worker = getattr(self.window, "_cache_restore_thread" if cache_restore else "worker_thread", None)
        control = getattr(worker, "find_my_wait", None)
        active, checking, cancelled = control.snapshot() if control else (False, False, False)
        self._control = control
        self.setVisible(active)
        if not active:
            return
        self.description.setText(device_text(self.tr(
            "On your iPhone, open Settings → your name → Find My → Find My iPhone and turn it off. "
            "Keep it connected and unlocked. GoldenNugget will retry automatically. "
            "Cancelling stops this restore; your protective backup stays on this computer."),
            self.window.device_manager.get_current_device_model()))
        self.check_status.setText(self.tr("Cancelling…") if cancelled else
                                  self.tr("Checking device…") if checking else self.tr("Waiting for Find My to be turned off…"))
        self.cancel_button.setText(self.tr("Cancel restore") if cache_restore else self.tr("Cancel apply"))
        self.cancel_button.setEnabled(not checking and not cancelled)
        for page in (self.window.ios_apply, self.window.ios_home):
            page.progress_card.time_row.hide()
            page.progress_card.eta.clear()

    def _cancel(self):
        if self._control is not None:
            self._control.cancel()
            self._sync()

    def _retheme(self):
        super()._retheme()
        if not self._content_ready:
            return
        colors = ColorThemeManager.instance().colors
        self.icon.setPixmap(theme_pixmap(":/icon/find-my.svg", colors.warning, 30, self.devicePixelRatioF()))
        self.title.setStyleSheet(f"color:{colors.warning}; font-size:16px; font-weight:600; background:transparent; border:none;")
        self.description.setStyleSheet(f"color:{colors.text_primary}; font-size:13px; background:transparent; border:none;")
        self.check_status.setStyleSheet(f"color:{colors.text_secondary}; font-size:12px; background:transparent; border:none;")
        self.cancel_button.setStyleSheet(t("mini_button"))
