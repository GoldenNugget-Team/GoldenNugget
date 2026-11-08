"""Persistent, dismissible result shared by Home and Apply."""
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from awesomeui.liquid.controls import LiquidCard
from src.devicemanagement.device_capabilities import device_text
from src.gui.theme import ColorThemeManager, t, theme_pixmap


def result_text(success, error, reset_pages=None, preview=None):
    tr = lambda text: QCoreApplication.translate("Nugget", text)
    if not success:
        return (error or tr("Operation stopped before completion.")) + "\n\n" + tr(
            "Completion was not confirmed. Open the application log before retrying; follow any recovery instructions shown for your device.")
    lines = []
    if reset_pages is not None:
        lines.append(tr("Restored defaults for selected pages:"))
        lines.extend(tr(getattr(page, 'name', str(page))) for page in reset_pages)
    elif preview is not None:
        lines.append(tr("Settings included in the completed apply:"))
        entries = preview['entries']
        lines.extend(f"{tr(entry['section'])} — {tr(entry['title'])}" for entry in entries.values())
        if not entries:
            lines.append(tr("No plist settings selected."))
        if preview['queued']:
            lines.extend(["", tr("Packages included in the apply:")])
            lines.extend(f"{tr(section)} — {name}" for section, name in preview['queued'])
        skipped = preview['blocked'] + preview.get('skipped_packages', [])
        lines.extend(["", tr("Skipped: {0}").format(len(skipped))])
        lines.extend(tr(name) for name in preview['blocked'])
        lines.extend(preview.get('skipped_packages', []))
        if preview['forced']:
            lines.extend(["", tr("Services forced off by safety rules:"), *preview['forced']])
    else:
        lines.append(tr("Operation completed. A detailed selection summary is unavailable; see the application log."))
    lines.extend(["", tr("Next: check the result on your device. If you turned off Find My before applying, turn it back on after the operation is complete.")])
    return "\n".join(lines)


class OperationResultCard(LiquidCard):
    def __init__(self, open_logs, dismiss, parent=None):
        super().__init__(parent)
        self._success = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.title = QLabel(self)
        self.title.setTextFormat(Qt.PlainText)
        layout.setSpacing(12)
        layout.addWidget(self.title)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.PlainText)
        layout.addWidget(self.summary)
        self.find_my_reminder = QWidget(self)
        reminder_layout = QHBoxLayout(self.find_my_reminder)
        reminder_layout.setContentsMargins(12, 12, 12, 12)
        reminder_layout.setSpacing(12)
        self.find_my_icon = QLabel()
        self.find_my_icon.setFixedSize(40, 40)
        reminder_layout.addWidget(self.find_my_icon)
        reminder_text = QVBoxLayout()
        reminder_text.setSpacing(4)
        self.find_my_title = QLabel(QCoreApplication.translate("Nugget", "Turn Find My back on"))
        self.find_my_title.setWordWrap(True)
        reminder_text.addWidget(self.find_my_title)
        self.find_my_description = QLabel(QCoreApplication.translate("Nugget",
            "If you disabled Find My, re-enable it on your iPhone: Settings → your name → Find My → Find My iPhone."))
        self.find_my_description.setWordWrap(True)
        reminder_text.addWidget(self.find_my_description)
        reminder_layout.addLayout(reminder_text, 1)
        layout.addWidget(self.find_my_reminder)
        self.expand_btn = QPushButton(self)
        self.expand_btn.setCheckable(True)
        self.expand_btn.setMinimumHeight(44)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.toggled.connect(self._set_expanded)
        layout.addWidget(self.expand_btn)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        self.details.setMaximumHeight(220)
        layout.addWidget(self.details)
        self.log_details = QPlainTextEdit(self)
        self.log_details.setReadOnly(True)
        self.log_details.setMinimumHeight(160)
        self.log_details.setMaximumHeight(260)
        self.log_details.setAccessibleName(QCoreApplication.translate("Nugget", "Recent application log"))
        layout.addWidget(self.log_details)
        actions = QHBoxLayout()
        self.logs_btn = QPushButton(QCoreApplication.translate("Nugget", "Open application log"))
        self.logs_btn.clicked.connect(open_logs)
        self.close_btn = QPushButton(QCoreApplication.translate("Nugget", "Dismiss"))
        self.close_btn.setMinimumHeight(44)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(dismiss)
        actions.addWidget(self.logs_btn)
        actions.addStretch()
        actions.addWidget(self.close_btn)
        layout.addLayout(actions)
        self._set_expanded(False)
        self._retheme()
        self.hide()

    def show_result(self, success, text, is_reset=False, restart_required=False, device_model=""):
        self._success = success
        self.title.setText(QCoreApplication.translate("Nugget",
            "Defaults restored!" if success and is_reset else "Apply complete!" if success else "Operation failed or stopped"))
        self.summary.setText(QCoreApplication.translate("Nugget",
            ("Restart your iPhone to see the changes, then check the result." if restart_required else "Check the result on your iPhone. You can keep GoldenNugget open.")
            if success else
            "Completion was not confirmed. Expand details and logs before retrying; follow any recovery instructions shown."))
        self.summary.setText(device_text(self.summary.text(), device_model))
        self.find_my_description.setText(device_text(QCoreApplication.translate("Nugget",
            "If you disabled Find My, re-enable it on your iPhone: Settings → your name → Find My → Find My iPhone."), device_model))
        self.find_my_reminder.setVisible(success)
        self.details.setPlainText(text)
        self.expand_btn.setChecked(False)
        self._set_expanded(False)
        self._retheme()
        self.show()

    def _set_expanded(self, expanded):
        self.details.setVisible(expanded)
        self.log_details.setVisible(expanded)
        self.logs_btn.setVisible(expanded)
        self.expand_btn.setText(QCoreApplication.translate("Nugget",
            "Hide details and logs ▴" if expanded else "View details and logs ▾"))
        if expanded:
            from src.controllers.nugget_logger import get_log_tail
            self.log_details.setPlainText(get_log_tail() or QCoreApplication.translate(
                "Nugget", "No application log is available for this session."))
            self.log_details.verticalScrollBar().setValue(self.log_details.verticalScrollBar().maximum())

    def _retheme(self):
        super()._retheme()
        if not hasattr(self, 'title'):
            return
        self.title.setStyleSheet(t("process_status_green" if self._success else "process_status_red"))
        self.summary.setStyleSheet(t("home_subtitle"))
        colors = ColorThemeManager.instance().colors
        self.find_my_reminder.setStyleSheet(
            f"background: {colors.bg_tertiary}; border-radius: 12px;")
        self.find_my_title.setStyleSheet(f"color: {colors.text_primary}; font-size: 15px; font-weight: 600;")
        self.find_my_description.setStyleSheet(f"color: {colors.text_secondary}; font-size: 13px;")
        self.find_my_icon.setPixmap(theme_pixmap(":/icon/find-my.svg", colors.success, 40, self.devicePixelRatioF()))
        self.details.setStyleSheet(t("apply_preview_text"))
        self.log_details.setStyleSheet(t("apply_preview_text"))
        self.expand_btn.setStyleSheet(t("settings_action"))
        self.logs_btn.setStyleSheet(t("mini_button"))
        self.close_btn.setStyleSheet(t("mini_button"))
