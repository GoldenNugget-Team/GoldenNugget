"""Installed-app list from a connected iPhone, for the Icon Themes page.

Queries the device's InstallationProxy for every installed app and shows it
in a searchable picker so a bundle id never has to be hand-typed. Two ways
to use the result:

  * pick an app -> the page opens the "Add Icon Theme" dialog pre-filled
    with that app's bundle id + display name;
  * "Export JSON..." -> writes the whole list
    ``[{bundle_id, display_name, version}]`` to a file the user chooses.

All device I/O runs on a background ``QThread`` so the UI stays responsive
while the lockdown service is queried.
"""

from __future__ import annotations

import asyncio
import json
import os

from PySide6.QtCore import QCoreApplication, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QFileDialog, QMessageBox,
)

from src.gui.theme import ColorThemeManager

_NUGGET = "Nugget"


class FetchAppsThread(QThread):
    """Pull the installed-app list from the device on a background thread."""

    done = Signal(object)   # list[dict] sorted by display name
    failed = Signal(str)

    def __init__(self, udid: str, parent=None):
        super().__init__(parent)
        self.udid = udid

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            apps = loop.run_until_complete(self._fetch())
            self.done.emit(apps)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _fetch(self) -> list[dict]:
        from src.devicemanagement.session import lockdown_session
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
        async with lockdown_session(self.udid) as lockdown:
            async with InstallationProxyService(lockdown=lockdown) as ip:
                raw = await ip.get_apps(application_type="Any", calculate_sizes=False)
        apps = []
        for bundle_id, info in (raw or {}).items():
            if not bundle_id:
                continue
            name = (info.get("CFBundleDisplayName")
                    or info.get("CFBundleName") or bundle_id)
            apps.append({
                "bundle_id": bundle_id,
                "display_name": name,
                "version": info.get("CFBundleVersion", ""),
            })
        apps.sort(key=lambda a: a["display_name"].lower())
        return apps


class AppListExportDialog(QDialog):
    """Searchable picker of the apps installed on the connected iPhone.

    ``selected_app()`` returns the last highlighted app (or the one double-
    clicked), so the page can open a prefilled Add Icon Theme dialog.
    """

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Apps on iPhone"))
        self.setModal(True)
        self.resize(520, 560)
        self._apps: list[dict] = []
        self._thread = None
        self._selected: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.status_lbl = QLabel(QCoreApplication.translate("Nugget", "Loading installed apps..."), self)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText(QCoreApplication.translate("Nugget", "Filter by name or bundle id..."))
        self.filter_input.textChanged.connect(self._apply_filter)
        self.filter_input.setVisible(False)
        layout.addWidget(self.filter_input)

        self.list_widget = QListWidget(self)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._add_selected())
        self.list_widget.setVisible(False)
        layout.addWidget(self.list_widget, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.export_btn = QPushButton(QCoreApplication.translate("Nugget", "Export JSON..."), self)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_json)
        btns.addWidget(self.export_btn)
        btns.addStretch()
        self.add_btn = QPushButton(QCoreApplication.translate("Nugget", "Add Icon for Selected"), self)
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add_selected)
        btns.addWidget(self.add_btn)
        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"), self)
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        self._btn_box = btns
        layout.addLayout(btns)

        self._retheme()
        self._start_fetch()

    def _start_fetch(self):
        udid = None
        try:
            udid = self.window.device_manager.get_current_device_udid()
        except Exception:
            udid = None
        if not udid:
            self.status_lbl.setText(QCoreApplication.translate("Nugget", 
                "No iPhone connected. Connect and unlock the device, then try again."))
            return
        self._thread = FetchAppsThread(udid, parent=self)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_done(self, apps: list[dict]):
        self._apps = apps
        self._thread = None
        self.status_lbl.setText(QCoreApplication.translate("Nugget", 
            "{0} apps installed on the iPhone.").format(len(apps)))
        self.filter_input.setVisible(True)
        self.list_widget.setVisible(True)
        self.export_btn.setEnabled(bool(apps))
        self._apply_filter()

    def _on_failed(self, error: str):
        self._thread = None
        self.status_lbl.setText(QCoreApplication.translate("Nugget", 
            "Could not read the app list.\n\n{0}").format(error))

    def _apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        self.list_widget.clear()
        for app in self._apps:
            hay = f"{app['display_name']} {app['bundle_id']}".lower()
            if needle and needle not in hay:
                continue
            item = QListWidgetItem(
                f"{app['display_name']}\n{app['bundle_id']}")
            item.app = app
            self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _on_current_changed(self, current, _previous):
        self.add_btn.setEnabled(current is not None)
        if current is not None:
            self._selected = current.app

    def _add_selected(self):
        app = self._selected
        if not app:
            item = self.list_widget.currentItem()
            if item is not None:
                app = getattr(item, "app", None)
            if not app:
                return
        self._selected = app
        self.accept()

    def selected_app(self) -> dict | None:
        return self._selected

    def _export_json(self):
        default_name = "installed_apps.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("Nugget", "Export App List"),
            os.path.join(os.path.expanduser("~"), default_name),
            "JSON files (*.json)")
        if not path:
            return
        payload = [
            {
                "bundle_id": app["bundle_id"],
                "display_name": app["display_name"],
                "version": app["version"],
            }
            for app in self._apps
        ]
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Warning"), QCoreApplication.translate("Nugget", "Could not write the file:\n{0}").format(e))
            return
        self.status_lbl.setText(QCoreApplication.translate("Nugget", 
            "Exported {0} apps to:\n{1}").format(len(payload), path))

    def reject(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(5000)
        self._thread = None
        super().reject()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; font-size: 14px; }}
            QLineEdit {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 14px;
                padding: 10px 12px;
            }}
            QListWidget {{
                background-color: {c.bg_secondary};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 14px;
                padding: 6px;
            }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
            QListWidget::item:selected {{ background-color: {c.accent}; color: {c.text_inverse}; }}
            QPushButton {{
                background-color: {c.accent};
                border: none;
                border-radius: 10px;
                color: {c.text_inverse};
                font-size: 14px;
                font-weight: 600;
                padding: 10px 16px;
            }}
            QPushButton:hover {{ background-color: {c.accent_hover}; }}
            QPushButton:disabled {{ background-color: {c.scrollbar}; color: {c.text_disabled}; }}
        """)
        for i in range(self._btn_box.count()):
            w = self._btn_box.itemAt(i).widget()
            if isinstance(w, QPushButton) and w.text() == QCoreApplication.translate("Nugget", "Close"):
                w.setStyleSheet(
                    f"background-color: {c.surface_hover}; color: {c.text_primary};")