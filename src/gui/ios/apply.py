from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QProgressBar
)
import re

from src.gui.ios.components import (
    IOSSectionHeader, IOSCard, IOSPrimaryButton, IOSDangerButton)
from src.gui.theme import ColorThemeManager, t


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
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Apply Tweaks")))

        apply_card = IOSCard()
        apply_layout = QVBoxLayout(apply_card)
        apply_layout.setContentsMargins(16, 12, 16, 12)
        apply_layout.setSpacing(8)

        apply_desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Applies every enabled tweak to your device. The device reboots "
            "when done — remember to turn Find My back on afterwards."))
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
        content_layout.addWidget(apply_card)

        # --- Remove ---
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Remove Tweaks")))

        remove_card = IOSCard()
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
            "Nugget", "Remove Tweaks"))
        self.remove_btn.setToolTip(QCoreApplication.translate(
            "Nugget", "Restore the stock values for the selected tweak pages."))
        self.remove_btn.setAccessibleName(QCoreApplication.translate(
            "Nugget", "Remove selected tweaks"))
        self.remove_btn.clicked.connect(self.window.remove_tweaks_clicked)
        remove_layout.addWidget(self.remove_btn)
        content_layout.addWidget(remove_card)

        # --- Progress status ---
        content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Progress")))

        status_card = IOSCard()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 12, 16, 12)
        status_layout.setSpacing(0)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setAccessibleName(QCoreApplication.translate(
            "Nugget", "Operation status"))
        self.status_lbl.setStyleSheet(f"color: {c.text_primary}; font-size: 14px;")
        status_layout.addWidget(self.status_lbl)

        self.stage_labels = []
        self._stage_names = [
            QCoreApplication.translate("Nugget", "1. Prepare"),
            QCoreApplication.translate("Nugget", "2. Apply"),
            QCoreApplication.translate("Nugget", "3. Finish"),
        ]
        stages_layout = QHBoxLayout()
        stages_layout.setContentsMargins(0, 10, 0, 6)
        stages_layout.setSpacing(8)
        for stage in self._stage_names:
            label = QLabel(stage)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(t("home_subtitle"))
            label.hide()
            self.stage_labels.append(label)
            stages_layout.addWidget(label, 1)
        status_layout.addLayout(stages_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setAccessibleName(QCoreApplication.translate(
            "Nugget", "Operation progress"))
        self.progress_bar.setStyleSheet(t("dialog_progress_bar"))
        self.progress_bar.hide()
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 4, 0, 0)
        progress_row.setSpacing(10)
        progress_row.addWidget(self.progress_bar, 1)
        self.progress_value_lbl = QLabel("")
        self.progress_value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_value_lbl.setStyleSheet(t("home_subtitle"))
        self.progress_value_lbl.setMinimumWidth(42)
        self.progress_value_lbl.hide()
        progress_row.addWidget(self.progress_value_lbl)
        status_layout.addLayout(progress_row)
        self.progress_hint_lbl = QLabel(QCoreApplication.translate(
            "Nugget", "Keep your iPhone connected while this runs."))
        self.progress_hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_hint_lbl.setStyleSheet(t("home_subtitle"))
        self.progress_hint_lbl.hide()
        status_layout.addWidget(self.progress_hint_lbl)
        content_layout.addWidget(status_card)

        content_layout.addStretch()

    def set_status(self, text: str):
        text = text or ""
        self.status_lbl.setText(text)
        lowered = text.casefold()
        if any(word in lowered for word in ("error", "failed", "failure", "ошиб")):
            self.status_lbl.setStyleSheet(t("process_status_red"))
        elif any(word in lowered for word in ("success", "done", "complete", "готов")):
            self.status_lbl.setStyleSheet(t("process_status_green"))
        else:
            self.status_lbl.setStyleSheet(t("process_status_blue"))
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if match:
            percent = max(0, min(100, int(round(float(match.group(1))))))
            self.progress_bar.setValue(percent)
            self.progress_value_lbl.setText(f"{percent}%")
            self.progress_bar.show()
            self.progress_value_lbl.show()
            self.progress_hint_lbl.show()
        else:
            self.progress_bar.hide()
            self.progress_value_lbl.hide()
            self.progress_hint_lbl.hide()
        if text:
            progress = float(match.group(1)) if match else 100.0
            active = (0 if progress < 40 else 1 if progress < 90 else 2) if match else 3
            for index, label in enumerate(self.stage_labels):
                label.setText(
                    f"✓ {self._stage_names[index]}" if index < active
                    else self._stage_names[index])
                label.setStyleSheet(
                    t("process_status_blue") if index <= active
                    else t("home_subtitle"))
                label.show()
        else:
            for label in self.stage_labels:
                label.hide()

    def set_busy(self, busy: bool):
        self.apply_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.apply_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self.remove_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self.status_lbl.setStyleSheet(f"color: {c.text_primary}; font-size: 14px;")
        self.progress_bar.setStyleSheet(t("dialog_progress_bar"))
        self.progress_value_lbl.setStyleSheet(t("home_subtitle"))
        self.progress_hint_lbl.setStyleSheet(t("home_subtitle"))
        for label in self.stage_labels:
            label.setStyleSheet(t("home_subtitle"))
        if self.status_lbl.text():
            self.set_status(self.status_lbl.text())
