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
import hashlib
import json
import os
import time

from PySide6.QtCore import QCoreApplication, QSize, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.gui.theme import ColorThemeManager, t, theme_icon
from src.gui.widgets import IOSSearchField
from src.utils.paths import cache_dir


class FetchAppsThread(QThread):
    """Pull the installed-app list from the device on a background thread."""

    done = Signal(object)   # list[dict] sorted by display name
    failed = Signal(str)
    icon_ready = Signal(str, bytes)

    def __init__(self, udid: str, parent=None):
        super().__init__(parent)
        self.udid = udid

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            apps = loop.run_until_complete(self._fetch())
            self.done.emit(apps)
            loop.run_until_complete(self._fetch_icons(apps))
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _fetch(self) -> list[dict]:
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        from src.devicemanagement.session import lockdown_session
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

    async def _fetch_icons(self, apps):
        from contextlib import AsyncExitStack

        from pymobiledevice3.services.springboard import SpringBoardServicesService

        from src.devicemanagement.session import lockdown_session
        cache = cache_dir() / "AppIcons" / hashlib.sha256(self.udid.encode()).hexdigest()
        try:
            cache.mkdir(parents=True, exist_ok=True)
        except OSError:
            cache = None
        pending = []
        for app in apps:
            key = f"{app['bundle_id']}:{app.get('version', '')}"
            path = cache / (hashlib.sha256(key.encode()).hexdigest() + '.png') if cache else None
            try:
                st = path.stat() if path is not None else None
                if st is not None and 0 < st.st_size <= 1024 * 1024 and time.time() - st.st_mtime < 86400:
                    data = path.read_bytes()
                    if data.startswith(b'\x89PNG\r\n\x1a\n'):
                        self.icon_ready.emit(app['bundle_id'], data)
                        continue
            except OSError:
                pass
            pending.append((app, path))
        if not pending or self.isInterruptionRequested():
            return
        try:
            async with lockdown_session(self.udid) as lockdown, AsyncExitStack() as stack:
                services = [await stack.enter_async_context(SpringBoardServicesService(lockdown))]
                if len(pending) > 12:
                    try:
                        services.append(await stack.enter_async_context(SpringBoardServicesService(lockdown)))
                    except Exception:
                        pass  # Devices limiting service count still work sequentially.
                queue = iter(pending)
                async def fetch(service):
                    for app, path in queue:
                        if self.isInterruptionRequested():
                            return
                        try:
                            data = await asyncio.wait_for(service.get_icon_pngdata(app['bundle_id']), 5)
                        except Exception:
                            continue
                        if data:
                            self.icon_ready.emit(app['bundle_id'], data)
                            try:
                                # Atomic cache writes: another dialog may use the same key.
                                from src.utils.payload import install_payload
                                if path is not None:
                                    install_payload(data, path)
                            except OSError:
                                pass
                await asyncio.gather(*(fetch(service) for service in services))
        except Exception:
            return


class AppListExportDialog(QDialog):
    """Searchable picker of the apps installed on the connected iPhone.

    ``selected_app()`` returns the last highlighted app (or the one double-
    clicked), so the page can open a prefilled Add Icon Theme dialog.
    """

    def __init__(self, window, parent=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.window = window
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Apps on iPhone"))
        self.setModal(True)
        self.resize(640, 660)
        self._apps: list[dict] = []
        self._apps_by_id = {}
        self._app_items = {}
        self._icons = {}
        self._thread = None
        self._selected: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(QCoreApplication.translate("Nugget", "Apps on iPhone"), self)
        title.setObjectName('appListTitle')
        layout.addWidget(title)
        self.status_lbl = QLabel(QCoreApplication.translate("Nugget", "Loading installed apps..."), self)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        self.filter_input = IOSSearchField(self)
        self.filter_input.setPlaceholderText(QCoreApplication.translate("Nugget", "Filter by name or bundle id..."))
        self.filter_input.connect_filter(self._apply_filter)
        self.filter_input.setVisible(False)
        layout.addWidget(self.filter_input)

        self.list_widget = QListWidget(self)
        self.list_widget.setIconSize(QSize(52, 52))
        self.list_widget.setSpacing(6)
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
        close_btn.setObjectName("appListClose")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        for button in self.findChildren(QPushButton):
            button.setMinimumHeight(46)
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
        self._thread = FetchAppsThread(udid, parent=QCoreApplication.instance())
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._fetch_finished)
        self._thread.icon_ready.connect(self._on_icon)
        self._thread.done.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_done(self, apps: list[dict]):
        selected = self.list_widget.currentItem()
        selected_id = selected.app['bundle_id'] if selected is not None else None
        self.list_widget.clear()
        self._app_items.clear()
        self._apps = apps
        self.status_lbl.setText(QCoreApplication.translate("Nugget", 
            "{0} apps installed on the iPhone.").format(len(apps)))
        self.filter_input.setVisible(True)
        self.list_widget.setVisible(True)
        self.export_btn.setEnabled(bool(apps))
        self._apply_filter()
        if selected_id in self._app_items:
            item = self._app_items[selected_id]
            if not item.isHidden():
                self.list_widget.setCurrentItem(item)

    def _on_failed(self, error: str):
        self.status_lbl.setText(QCoreApplication.translate("Nugget", 
            "Could not read the app list.\n\n{0}").format(error))

    def _apply_filter(self):
        needle = self.filter_input.text().strip().casefold()
        if len(self._app_items) != len(self._apps):
            self.list_widget.clear()
            self._app_items.clear()
            self._apps_by_id = {app['bundle_id']: app for app in self._apps}
            fallback = theme_icon(":/icon/app-indicator.svg", ColorThemeManager.instance().colors.text_secondary)
            for app in self._apps:
                item = QListWidgetItem(f"{app['display_name']}\n{app['bundle_id']}")
                item.setSizeHint(QSize(0, 76))
                item.app = app
                item.setIcon(self._icons.get(app['bundle_id'], fallback))
                self.list_widget.addItem(item)
                self._app_items[app['bundle_id']] = item
        selected = self.list_widget.currentItem()
        first = None
        self.list_widget.setUpdatesEnabled(False)
        try:
            for app in self._apps:
                item = self._app_items[app['bundle_id']]
                visible = not needle or needle in f"{app['display_name']} {app['bundle_id']}".casefold()
                item.setHidden(not visible)
                if visible and first is None:
                    first = item
            if selected is None or selected.isHidden():
                self.list_widget.setCurrentItem(first)
        finally:
            self.list_widget.setUpdatesEnabled(True)

    def _on_current_changed(self, current, _previous):
        self._selected = None
        self.add_btn.setEnabled(current is not None)
        if current is not None:
            self._selected = current.app

    def _fetch_finished(self):
        self._thread = None

    def _on_icon(self, bundle_id, data):
        app = self._apps_by_id.get(bundle_id)
        if app is not None:
            app['icon_data'] = data
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        icon = QIcon(pixmap)
        self._icons[bundle_id] = icon
        item = self._app_items.get(bundle_id)
        if item is not None:
            item.setIcon(icon)

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

    def done(self, result):
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
        super().done(result)

    def _retheme(self):
        self.setStyleSheet(t("app_list_dialog"))
