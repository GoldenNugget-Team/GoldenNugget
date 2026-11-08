"""Persistent restore progress driven by device-operation stage notifications."""
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.devicemanagement.device_capabilities import device_text
from src.gui.ios.feature_icons import FEATURE_ICONS
from src.gui.theme import ColorThemeManager, t, theme_pixmap
from src.gui.widgets import IOSCard

_STAGES = {
    "prepare": ("Preparing files", ":/icon/gear.svg"),
    "backup": ("Back up", ":/icon/hdd.svg"),
    "tweaks": ("Apply changes", ":/icon/toggles.svg"),
    "restore": ("Restore data", ":/icon/phone-download.svg"),
    "media": ("Restore photos & videos", ":/icon/photo.svg"),
    "setup": ("Set up & restart", ":/icon/phone-restart.svg"),
}
_CATEGORY_ICONS = {
    "backup": ":/icon/hdd.svg", "keychain": ":/icon/lock.svg",
    "authentication": ":/icon/lock.svg", "messages": ":/icon/chat.svg",
    "photos": ":/icon/photo.svg", "account": ":/icon/person.svg",
    "home": ":/icon/house.svg", "shortcuts": ":/icon/play-circle.svg",
    "wallpaper": ":/icon/wallpaper.svg", "settings": ":/icon/gear.svg",
    "restart": ":/icon/arrow-clockwise.svg",
}


def _tr(text):
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.translate("RestoreProgress", text)


class RestoreProgressCard(IOSCard):
    def __init__(self, parent=None, *, compact=False):
        super().__init__(parent)
        self._compact = compact
        self._device_model = ""
        self._stage = "prepare"
        self._category = ""
        self._seen = set()
        self._completed = set()
        self._skipped = set()
        self._steps = {}
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(400)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._flush_status)
        self._pending_status = ""
        self._combined_restore = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)
        header = QHBoxLayout()
        header.setSpacing(12)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(36, 36)
        header.addWidget(self.status_icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.phase_label = QLabel(self._tr("Preparing files"))
        self.phase_label.setObjectName("restorePhase")
        text.addWidget(self.phase_label)
        self.status_label = QLabel()
        self.status_label.setObjectName("restoreStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        text.addWidget(self.status_label)
        header.addLayout(text, 1)
        layout.addLayout(header)
        self.timeline = QWidget()
        self.timeline_layout = QHBoxLayout(self.timeline)
        self.timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_layout.setSpacing(8)
        layout.addWidget(self.timeline)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setAccessibleName(self._tr("Device-reported progress"))
        progress_row.addWidget(self.bar, 1)
        self.value = QLabel(self._tr("Waiting…"))
        self.value.setObjectName("restorePercent")
        self.value.setMinimumWidth(64)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.value)
        layout.addLayout(progress_row)
        self.time_row = QWidget()
        time_layout = QHBoxLayout(self.time_row)
        time_layout.setContentsMargins(0, 0, 0, 0)
        time_layout.setSpacing(8)
        self.timer_icon = QLabel()
        self.timer_icon.setFixedSize(22, 22)
        time_layout.addWidget(self.timer_icon)
        self.eta = QLabel()
        self.eta.setObjectName("restoreTime")
        time_layout.addWidget(self.eta)
        time_layout.addStretch()
        layout.addWidget(self.time_row)
        warning = QWidget()
        warning.setObjectName("restoreConnection")
        warning_layout = QHBoxLayout(warning)
        warning_layout.setContentsMargins(16, 14, 16, 14)
        warning_layout.setSpacing(12)
        self.connection_icon = QLabel()
        self.connection_icon.setObjectName("restoreConnectionIcon")
        self.connection_icon.setFixedSize(32, 32)
        self.connection_icon.setAlignment(Qt.AlignCenter)
        warning_layout.addWidget(self.connection_icon, 0, Qt.AlignVCenter)
        warning_text = QVBoxLayout()
        warning_text.setSpacing(3)
        self.hint = QLabel(self._tr("Do not disconnect your iPhone"))
        self.hint.setObjectName("restoreWarning")
        self.hint.setWordWrap(True)
        warning_text.addWidget(self.hint)
        detail = QLabel(self._tr("Keep the USB cable connected until GoldenNugget confirms the restore is complete."))
        self.connection_detail = detail
        detail.setObjectName("restoreConnectionDetail")
        detail.setWordWrap(True)
        warning_text.addWidget(detail)
        warning_layout.addLayout(warning_text, 1)
        layout.addWidget(warning)
        if compact:
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(10)
            self.timeline.hide()
            warning.hide()
        self.start(False)
        self.hide()

    def _tr(self, text):
        return device_text(_tr(text), self._device_model)

    def start(self, protective, finalization=True, device_model=""):
        self._device_model = device_model
        self.hint.setText(self._tr("Do not disconnect your iPhone"))
        self.connection_detail.setText(self._tr("Keep the USB cable connected until GoldenNugget confirms the restore is complete."))
        self._status_timer.stop()
        self._pending_status = ""
        self._stage, self._category = "prepare", ""
        self._combined_restore = False
        self._seen.clear()
        self._completed.clear()
        self._skipped.clear()
        while self.timeline_layout.count():
            old_step = self.timeline_layout.takeAt(0).widget()
            old_step.hide()
            old_step.deleteLater()
        self._steps.clear()
        stages = ["backup", "tweaks", "restore"] if protective else ["tweaks"]
        if protective and finalization:
            stages.append("setup")
        for key in stages:
            self._add_step(key, self.timeline_layout.count())
        self.bar.setRange(0, 0)
        self.value.setText(self._tr("Waiting…"))
        self.status_label.setText(self._tr("Waiting for the operation to start."))
        self.eta.clear()
        self.time_row.hide()
        self._retheme()

    def _add_step(self, key, index):
        step = QWidget()
        step.setObjectName("restoreStep")
        step.setMinimumWidth(0)
        step.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        step_layout = QVBoxLayout(step)
        step_layout.setContentsMargins(10, 10, 10, 10)
        step_layout.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(24, 24)
        step_layout.addWidget(icon, 0, Qt.AlignHCenter)
        label = QLabel(self._tr(_STAGES[key][0]))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        label.setObjectName("restoreStepTitle")
        step_layout.addWidget(label)
        self._steps[key] = (step, icon, label)
        self.timeline_layout.insertWidget(index, step, 1)

    def set_stage(self, stage, category=""):
        if stage not in _STAGES:
            return
        if category == "skipped":
            if stage not in self._steps:
                index = self.timeline_layout.indexOf(self._steps["setup"][0]) if "setup" in self._steps else self.timeline_layout.count()
                self._add_step(stage, index)
            self._skipped.add(stage)
            self._completed.discard(stage)
            self._refresh_stage()
            return
        self._skipped.discard(stage)
        if stage not in self._steps and stage != "prepare":
            self._add_step(stage, self.timeline_layout.count())
        if stage != self._stage and self._stage in self._seen and self._stage not in self._skipped:
            self._completed.add(self._stage)
        if stage == "restore" and "tweaks" not in self._seen and "tweaks" in self._steps:
            self._combined_restore = True
            self._steps["tweaks"][0].hide()
        if category == "media_pending" and "media" not in self._steps:
            index = self.timeline_layout.indexOf(self._steps["setup"][0]) if "setup" in self._steps else self.timeline_layout.count()
            self._add_step("media", index)
        changed = stage != self._stage
        if changed:
            self.eta.clear()
            self.time_row.hide()
            self._flush_status()
            self._status_timer.stop()
            self._pending_status = ""
            self.bar.setRange(0, 0)
            self.value.setText(self._tr("Waiting…"))
        self._stage, self._category = stage, category
        self._seen.add(stage)
        if category in {"restart", "waiting", "authentication"}:
            self.eta.clear()
            self.time_row.hide()
            self.bar.setRange(0, 0)
            self.value.setText(self._tr("Waiting…"))
        if changed or stage != "backup":
            self._refresh_stage()
        self.show()

    def set_status(self, text):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if match:
            if self._category == "authentication":
                self._category = ""
                self._refresh_stage()
            percent = max(0, min(100, round(float(match.group(1)))))
            self.bar.setRange(0, 100)
            self.bar.setValue(percent)
            self.value.setText(f"{percent}%")
        lines = text.splitlines()
        eta = next((line for line in lines if "Time Left:" in line), "")
        if eta or match or not self.eta.text():
            self.eta.setText(eta or self._tr("Time Left: Finishing this stage…" if match and float(match.group(1)) >= 100 else "Time Left: Calculating…"))
        self.eta.setToolTip(self._tr("Estimate for the current transfer only. Setup and restart can take additional time."))
        self.time_row.setVisible(self._stage in {"backup", "restore", "media"} and self._category not in {"restart", "waiting", "authentication"})
        body = [line for line in lines if line != eta and line.strip() != "DO NOT UNPLUG"]
        self._pending_status = re.sub(r"\s*\(\d+(?:\.\d+)?%\)", "", "\n".join(body))
        if self._stage != "backup" or self._category == "authentication" or "Low computer storage:" in text:
            self._status_timer.stop()
            self._flush_status()
        elif not self._status_timer.isActive():
            self._flush_status()
            self._status_timer.start()
        self.show()

    def _flush_status(self):
        if self._pending_status and self.status_label.text() != self._pending_status:
            self.status_label.setText(self._pending_status)

    def _retheme(self):
        super()._retheme()
        if not hasattr(self, "bar"):
            return
        compact_style = ("QLabel#restorePhase { font-size: 15px; font-weight: 600; } "
                         "QLabel#restoreStatus { font-size: 12px; } "
                         "QLabel#restorePercent { font-size: 17px; font-weight: 600; } "
                         "QLabel#restoreTime { font-size: 13px; font-weight: 600; }") if self._compact else ""
        self.setStyleSheet(self.styleSheet() + t("restore_progress") + compact_style)
        self.bar.setStyleSheet(t("dialog_progress_bar"))
        self.timer_icon.setPixmap(theme_pixmap(
            ":/icon/clock.svg", ColorThemeManager.instance().colors.accent,
            22, self.devicePixelRatioF()))
        self.connection_icon.setPixmap(theme_pixmap(
            ":/icon/restore-warning.svg", ColorThemeManager.instance().colors.warning,
            28, self.devicePixelRatioF()))
        self._refresh_stage()

    def _refresh_stage(self):
        colors = ColorThemeManager.instance().colors
        title = "Restarting iPhone" if self._category == "restart" else _STAGES[self._stage][0]
        if self._stage == "backup":
            title = "Backing up"
        if self._combined_restore and self._stage == "restore" and self._category not in {"restart", "waiting", "authentication"}:
            title = "Restore data & apply changes"
        if "media" in self._steps and self._stage in {"restore", "media"} and self._category not in {"restart", "waiting", "authentication"}:
            title = self._tr("{0} — stage {1} of 2").format(self._tr(title), 1 if self._stage == "restore" else 2)
        if self._category == "authentication":
            title = "Unlock your iPhone"
        self.phase_label.setText(self._tr(title))
        icon = ":/icon/lock.svg" if self._category == "authentication" else _STAGES["backup"][1] if self._stage == "backup" else _CATEGORY_ICONS.get(self._category, _STAGES[self._stage][1])
        artwork = {"tweaks": "Tweaks", "wallpaper": "PosterBoard", "statusbar": "Status Bar",
                   "daemons": "Daemons", "icons": "Icon Themes"}.get(
            self._category, "Tweaks" if self._stage == "tweaks" else None)
        if artwork and self._category != "authentication":
            ratio = self.devicePixelRatioF()
            pixmap = QPixmap(FEATURE_ICONS[artwork]).scaled(
                round(32 * ratio), round(32 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            self.status_icon.setPixmap(pixmap)
        else:
            self.status_icon.setPixmap(theme_pixmap(icon, colors.accent, 32, self.devicePixelRatioF()))
        for key, (step, icon, label) in self._steps.items():
            state = "skipped" if key in self._skipped else "active" if key == self._stage else "complete" if key in self._completed else "pending"
            if step.property("state") != state:
                step.setProperty("state", state)
                step.style().unpolish(step)
                step.style().polish(step)
            resource = ":/icon/check-circle.svg" if state == "complete" else _STAGES[key][1]
            color = colors.accent if state == "active" else colors.success if state == "complete" else colors.text_secondary
            icon.setPixmap(theme_pixmap(resource, color, 24, self.devicePixelRatioF()))
            label.setText(self._tr("Restore data & changes") if key == "restore" and self._combined_restore else self._tr(_STAGES[key][0]))
            if state == "skipped":
                label.setText(self._tr("{0} — skipped").format(self._tr(_STAGES[key][0])))
