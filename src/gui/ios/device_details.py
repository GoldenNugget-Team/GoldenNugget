"""Compact device metrics beside the selected device preview."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from src.devicemanagement.storage_info import format_device_capacity
from src.gui.ios.components import _auto_retheme
from src.gui.theme import ColorThemeManager, t, theme_pixmap


class BatteryIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = None
        self.charging = False
        self.low_power = False
        self.setFixedSize(40, 20)

    def set_level(self, value, charging=False, low_power=False):
        self.level, self.charging, self.low_power = value, charging, low_power
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = ColorThemeManager.instance().colors
        body = QRectF(0, 2, 35, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.bg_tertiary))
        painter.drawRoundedRect(body, 5, 5)
        painter.fillRect(QRectF(36, 7, 2, 6), QColor(colors.text_secondary))
        if self.level is None:
            return
        color = colors.warning if self.low_power else colors.success if self.charging else colors.error if self.level <= 20 else colors.text_primary
        path = QPainterPath()
        path.addRoundedRect(body, 5, 5)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(0, 2, 35 * self.level / 100, 16), QColor(color))
        painter.restore()
        font = QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        label = str(round(self.level))
        painter.setPen(QColor(colors.text_primary))
        painter.drawText(body, Qt.AlignCenter, label)
        painter.save()
        painter.setClipRect(QRectF(0, 2, 35 * self.level / 100, 16))
        painter.setPen(QColor(colors.bg_primary))
        painter.drawText(body, Qt.AlignCenter, label)
        painter.restore()


class DeviceDetailsWidget(QWidget):
    selection_counts_changed = Signal(object, object)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        metrics = QHBoxLayout()
        metrics.setSpacing(5)
        self.storage_icon = QLabel()
        self.storage_icon.setFixedSize(13, 13)
        self.storage = QLabel()
        self.storage_bar = QProgressBar()
        self.storage_bar.setFixedSize(72, 6)
        self.storage_bar.setTextVisible(False)
        self.battery_icon = BatteryIndicator(self)
        self.battery = QLabel()
        metrics.addWidget(self.storage_icon)
        metrics.addWidget(self.storage)
        metrics.addWidget(self.storage_bar)
        self.battery_group = QWidget(self)
        battery_row = QHBoxLayout(self.battery_group)
        battery_row.setContentsMargins(7, 0, 7, 0)
        battery_row.setSpacing(5)
        battery_row.addWidget(self.battery, 0, Qt.AlignVCenter)
        battery_row.addWidget(self.battery_icon, 0, Qt.AlignVCenter)
        self.battery_group.setFixedHeight(26)
        self.battery_group.hide()
        metrics.addStretch()
        layout.addLayout(metrics)
        self.available_storage = QLabel(self)
        layout.addWidget(self.available_storage)
        self.available_storage.hide()
        self._retheme()
        _auto_retheme(self)

    def update_info(self):
        manager = self.window.device_manager
        udid = manager.get_current_device_udid()
        storage = getattr(self.window, "_storage_info", None)
        if storage and storage.get("udid") == udid and storage.get("total", 0) > 0:
            capacity = storage.get("capacity") or storage["total"]
            capacity_label = format_device_capacity(storage.get("capacity"))
            if capacity_label:
                self.storage.setText(self.tr("{0:.0f} GB used · {1}").format(max(0, capacity - storage["free"]) / 1_000_000_000, capacity_label))
            else:
                self.storage.setText(self.tr("{0:.0f} GB used").format(max(0, capacity - storage["free"]) / 1_000_000_000))
            self.storage_bar.setValue(min(100, max(0, round((storage["total"] - storage["free"]) * 100 / storage["total"]))))
            self.storage.setToolTip(self.tr("{0:.1f} GB available").format(storage["free"] / 1_000_000_000))
            self.available_storage.setText(self.storage.toolTip())
            self.available_storage.show()
        else:
            self.available_storage.hide()
            loading = udid in getattr(self.window.ios_home, "_storage_workers", {}) if hasattr(self.window, "ios_home") else False
            self.storage.setText(self.tr("Reading storage…") if loading else self.tr("Storage: —"))
            self.storage_bar.setValue(0)
            self.storage.setToolTip(self.tr("Storage information unavailable"))
        battery = getattr(self.window, "_battery_info", None)
        percent = battery.get("percent") if battery and battery.get("udid") == udid else None
        valid = isinstance(percent, (int, float)) and 0 <= percent <= 100
        self.battery_icon.set_level(percent if valid else None, bool(battery.get("charging")) if valid else False, battery.get("low_power") is True if valid else False)
        self.battery.setText(self.tr("Battery") if valid else self.tr("Battery: —"))
        self.battery.setToolTip(self.tr("Charging") if valid and battery.get("charging") else self.tr("Not charging") if valid else self.tr("Battery information unavailable"))

    def showEvent(self, event):
        super().showEvent(event)
        self.update_info()

    def _update_selection_counts(self):
        from src.gui.ios.compat import device_family, is_tweak_compatible
        from src.tweaks.hidden import (
            current_hidden_feature_names,
            current_hidden_tweak_names,
        )
        from src.tweaks.registry import SECTION_FEATURES, SPECS
        from src.tweaks.tweaks import TweakID, tweaks
        manager = self.window.device_manager
        model, version = manager.get_current_device_model(), manager.get_current_device_version()
        hidden, features = current_hidden_tweak_names(), current_hidden_feature_names()
        tweak_count = sum(1 for spec in SPECS if not spec.disabled
                          and spec.id.name not in hidden and SECTION_FEATURES.get(spec.section) not in features
                          and is_tweak_compatible(spec.id, version, device_family(model) == "iphone", model)
                          and spec.id in tweaks and tweaks[spec.id].enabled)
        daemons = tweaks.get(TweakID.Daemons)
        from src.tweaks.daemons_tweak import INTERFACE_KEYS, Daemon
        controls = [daemon for daemon in Daemon if all(key in INTERFACE_KEYS for key in daemon.value)]
        selected = daemons._filter_keys(daemons.value or {}) if daemons and daemons.enabled else {}
        daemon_count = sum(all(selected.get(key) is True for key in daemon.value) for daemon in controls)
        counts = {"tweaks": tweak_count, "daemons": daemon_count}
        totals = {"tweaks": sum(not spec.disabled for spec in SPECS), "daemons": len(controls)}
        self.selection_counts_changed.emit(counts, totals)

    def _retheme(self):
        colors = ColorThemeManager.instance().colors
        for label in (self.storage, self.battery, self.available_storage):
            label.setStyleSheet(f"color: {colors.text_secondary}; font-size: 13px; background: transparent; border: none;")
        self.storage_icon.setPixmap(theme_pixmap(":/icon/hdd.svg", colors.text_secondary, 13, self.devicePixelRatioF()))
        self.storage_bar.setStyleSheet(t("dialog_progress_bar"))
        self.battery_group.setStyleSheet(f"background: {colors.bg_secondary}; border-radius: 6px;")
        self.battery_icon.update()
