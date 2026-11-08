from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.gui.theme import ColorThemeManager, t
from src.gui.widgets import (
    IOSCard,
    IOSDangerButton,
    IOSPrimaryButton,
    IOSSectionHeader,
)


class IOSApplyPage(QWidget):
    """Apply / Remove tweaks — rebuilt from the classic Apply page using the
    iOS-style components."""
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        c = ColorThemeManager.instance().colors
        scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self._scroll = scroll
        content = QWidget()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 32)
        content_layout.setSpacing(8)

        # --- Apply ---
        self.apply_header = IOSSectionHeader(QCoreApplication.translate("Nugget", "Apply Tweaks"))
        content_layout.addWidget(self.apply_header)

        self.apply_card = apply_card = IOSCard()
        apply_layout = QVBoxLayout(apply_card)
        apply_layout.setContentsMargins(16, 12, 16, 12)
        apply_layout.setSpacing(8)

        apply_desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Applies every enabled tweak to your device. The device reboots "
            "when done. If you turn Find My off for this apply, turn it back "
            "on afterwards."))
        apply_desc.setWordWrap(True)
        apply_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self.apply_desc = apply_desc
        apply_layout.addWidget(apply_desc)

        self.apply_btn = IOSPrimaryButton(QCoreApplication.translate(
            "Nugget", "Apply Tweaks"))
        self.apply_btn.setToolTip(QCoreApplication.translate(
            "Nugget", "Apply all enabled tweaks and restart the device."))
        self.apply_btn.setAccessibleName(QCoreApplication.translate(
            "Nugget", "Apply enabled tweaks"))
        self.apply_btn.clicked.connect(self.window.apply_tweaks_clicked)
        apply_layout.addWidget(self.apply_btn)
        self.preview_btn = QPushButton(QCoreApplication.translate(
            "DeviceTwin", "Preview on iPhone"))
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.setMinimumHeight(44)
        self.preview_btn.setToolTip(QCoreApplication.translate(
            "DeviceTwin", "See the Lock Screen and Home Screen with the selected tweaks before applying."))
        self.preview_btn.clicked.connect(self.window.show_device_twin)
        apply_layout.addWidget(self.preview_btn)
        self.preview_btn.setStyleSheet(t("mini_button"))
        content_layout.addWidget(apply_card)

        # --- Remove ---
        self.remove_header = IOSSectionHeader(QCoreApplication.translate("Nugget", "Restore Defaults"))
        content_layout.addWidget(self.remove_header)

        self.remove_card = remove_card = IOSCard()
        remove_layout = QVBoxLayout(remove_card)
        remove_layout.setContentsMargins(16, 12, 16, 12)
        remove_layout.setSpacing(8)

        remove_desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Restores the original values for the tweak pages you pick."))
        remove_desc.setWordWrap(True)
        remove_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self.remove_desc = remove_desc
        remove_layout.addWidget(remove_desc)

        self.remove_btn = IOSDangerButton(QCoreApplication.translate(
            "Nugget", "Restore Defaults"))
        self.remove_btn.setToolTip(QCoreApplication.translate(
            "Nugget", "Restore the stock values for the selected tweak pages."))
        self.remove_btn.setAccessibleName(QCoreApplication.translate(
            "Nugget", "Restore defaults for selected sections"))
        self.remove_btn.clicked.connect(self.window.remove_tweaks_clicked)
        remove_layout.addWidget(self.remove_btn)
        content_layout.addWidget(remove_card)

        from src.gui.ios.restore_progress import RestoreProgressCard
        self.progress_card = RestoreProgressCard(self)
        self._busy = False
        self.status_lbl = self.progress_card.status_label
        self.progress_bar = self.progress_card.bar
        content_layout.addWidget(self.progress_card)
        from src.gui.ios.find_my_warning import FindMyWarningCard
        self.find_my_warning = FindMyWarningCard(self.window, self)
        content_layout.addWidget(self.find_my_warning)
        self.pause_btn = QPushButton(self.tr("Pause photo transfer"))
        self.pause_btn.setMinimumHeight(44)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.pause_btn.hide()
        content_layout.addWidget(self.pause_btn)
        self._pause_timer = QTimer(self)
        self._pause_timer.setInterval(150)
        self._pause_timer.timeout.connect(self._update_pause_control)

        from src.gui.ios.operation_result import OperationResultCard
        self.result_card = OperationResultCard(
            self.window.ios_home.open_logs, self.window.dismiss_operation_result)
        content_layout.addWidget(self.result_card)

        content_layout.addStretch()

    def _pause_control(self):
        return getattr(getattr(self.window, "worker_thread", None), "pause_control", None)

    def _toggle_pause(self):
        control = self._pause_control()
        if control is None:
            return
        if control.state == "paused":
            control.resume()
        elif control.state == "available":
            from src.gui.dialogs.confirmation import ask_confirmation
            if ask_confirmation(self, self.tr("Pause photo transfer?"),
                self.tr("Are you sure you want to pause? Active transfers will finish first. Keep your device connected until you resume and restoration completes."),
                self.tr("Pause transfer")):
                control.request_pause()
        self._update_pause_control()

    def _update_pause_control(self):
        worker = getattr(self.window, "worker_thread", None)
        find_my = getattr(worker, "find_my_wait", None)
        if find_my is not None and find_my.snapshot()[0]:
            self.pause_btn.hide()
            return
        control = self._pause_control()
        state = control.state if control else "unavailable"
        media = state in {"available", "paused", "pending", "resuming"}
        self.pause_btn.setVisible(self._busy and media)
        self.pause_btn.setEnabled(state in {"available", "paused"})
        text = {"paused": "Resume photo transfer", "pending": "Pausing after active transfers…", "resuming": "Resuming…"}.get(state, "Pause photo transfer")
        self.pause_btn.setText(self.tr(text))
        self.pause_btn.setToolTip(self.tr("Photo transfer can pause between files. Active data restoration and reboots cannot be paused."))
        if state in {"pending", "paused", "resuming"}:
            self.progress_card.time_row.hide()
            self.progress_card.eta.clear()
            if state == "paused":
                self.progress_card.status_label.setText(self.tr("Paused. Keep your device connected and select Resume to continue."))

    def set_status(self, text: str):
        if text:
            self.progress_card.set_status(text)
        elif not self._busy:
            self.progress_card.hide()

    def set_stage(self, stage, category=""):
        self.progress_card.set_stage(stage, category)

    def set_status_only(self, enabled: bool):
        self._status_only = enabled
        for widget in (self.apply_header, self.apply_card, self.remove_header, self.remove_card):
            widget.setVisible(not enabled and not self._busy)

    def set_busy(self, busy: bool):
        if busy and not self._busy:
            protective = self.window.device_manager.get_current_device_partially_supported()
            preferences = self.window.device_manager.pref_manager
            self.progress_card.start(protective,
                                     preferences.auto_reboot or preferences.skip_setup,
                                     self.window.device_manager.get_current_device_model())
            self.progress_card.show()
        self._busy = busy
        self.find_my_warning.set_busy(busy)
        for widget in (self.apply_header, self.apply_card, self.remove_header, self.remove_card):
            widget.setVisible(not busy and not getattr(self, '_status_only', False))
        if busy:
            self._pause_timer.start()
        else:
            self._pause_timer.stop()
        self._update_pause_control()
        connected = bool(self.window.device_manager.get_current_device_udid())
        self.apply_btn.setEnabled(not busy and connected)
        self.remove_btn.setEnabled(not busy and connected)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.preview_btn.setStyleSheet(t("mini_button"))
        self.apply_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        self.remove_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        self.pause_btn.setStyleSheet(t("mini_button"))
        self.progress_card._retheme()
