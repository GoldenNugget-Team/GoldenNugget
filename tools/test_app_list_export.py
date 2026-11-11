#!/usr/bin/env python3
"""Offline test for the "Apps on iPhone" export dialog (no device needed).

Locks in:
  1. FetchAppsThread._fetch maps the InstallationProxy raw dict into
     ``[{bundle_id, display_name, version}]`` sorted by display name, with
     sensible fallbacks for apps that have no display name.
  2. The JSON payload the dialog exports matches that selection and round-trips.

The InstallationProxy service and ``lockdown_session`` are mocked, so the
test never opens a device connection. Run: python tools/test_app_list_export.py
"""
import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.dialogs.app_list_dialog import FetchAppsThread

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


# --- mock the device session + InstallationProxy -----------------------------
class _FakeInstallationProxy:
    def __init__(self, lockdown=None, **kwargs):
        self._raw = kwargs.pop("raw", RAW)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_apps(self, application_type="Any", calculate_sizes=False):
        check("get_apps asked for Any application type", application_type == "Any")
        check("get_apps asked not to calculate sizes", calculate_sizes is False)
        return self._raw


RAW = {
    # has a display name + version
    "com.instagram.instagram": {
        "CFBundleDisplayName": "Instagram",
        "CFBundleVersion": "289.0",
        "CFBundleName": "Instagram",
    },
    # no display name -> must fall back to CFBundleName
    "com.apple.mobilesafari": {
        "CFBundleName": "Safari",
        "CFBundleVersion": "604.1",
    },
    # no display name and no CFBundleName -> bundle id itself
    "com.example.weird": {
        "CFBundleVersion": "1.0",
    },
    # entry without a bundle id (malformed) -> must be dropped
    "": {"CFBundleDisplayName": "Ghost"},
}


_entered = {"count": 0}


class _FakeSession:
    async def __aenter__(self):
        return object()  # lockdown client

    async def __aexit__(self, *exc):
        return False


def _fake_session_factory(_udid=None, **_kw):
    return _FakeSession()


async def _run_fetch(thread):
    # Stub the async context manager + service used by _fetch.
    src = "src.devicemanagement.session"
    lockdown_module = types.ModuleType(src)
    lockdown_module.lockdown_session = _fake_session_factory

    # prevent real device session from being reached
    sys.modules[src] = lockdown_module
    return await thread._fetch()


async def main():
    # Replace the real InstallationProxy import path with the fake.
    sys.modules["pymobiledevice3.services.installation_proxy"] = None  # not hit

    # Patch the inner import so the thread pulls our fake service instead.
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pymobiledevice3.services.installation_proxy":
            mod_ = types.ModuleType(name)
            mod_.InstallationProxyService = _FakeInstallationProxy
            return mod_
        return real_import(name, *args, **kwargs)

    import builtins
    builtins.__import__ = fake_import
    try:
        thread = FetchAppsThread.__new__(FetchAppsThread)
        thread.udid = "UDIDTEST"
        apps = await _run_fetch(thread)
    finally:
        builtins.__import__ = real_import

    check("all three named apps mapped", len(apps) == 3)
    check("sorted by display name", [a["display_name"] for a in apps] ==
          ["com.example.weird", "Instagram", "Safari"])
    instagram = next(a for a in apps if a["bundle_id"] == "com.instagram.instagram")
    check("display name kept", instagram["display_name"] == "Instagram")
    check("version kept", instagram["version"] == "289.0")
    safari = next(a for a in apps if a["bundle_id"] == "com.apple.mobilesafari")
    check("CFBundleName fallback", safari["display_name"] == "Safari")
    weird = next(a for a in apps if a["bundle_id"] == "com.example.weird")
    check("bundle-id fallback", weird["display_name"] == "com.example.weird")

    # JSON export payload matches the fetched list and round-trips.
    payload = [
        {"bundle_id": a["bundle_id"], "display_name": a["display_name"],
         "version": a["version"]}
        for a in apps
    ]
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    restored = json.loads(blob)
    check("JSON round-trips", restored == payload)

    # --- widget-level flow: filter + selection, offscreen -------------------
    from PySide6.QtWidgets import QApplication

    from src.gui.dialogs.app_list_dialog import AppListExportDialog

    app = QApplication.instance() or QApplication([])  # noqa: F841 -- keeps the QApplication alive

    class _FakeManager:
        def get_current_device_udid(self):
            return None  # no device -> dialog shows the no-device message

    class _FakeWindow:
        device_manager = _FakeManager()

    dlg = AppListExportDialog(_FakeWindow())
    dlg._on_done(apps)  # simulate the fetch completing
    check("no-device path then populated", dlg.list_widget.count() == 3)
    check("export button enabled after data", dlg.export_btn.isEnabled())

    dlg.filter_input.setText("instagram")
    # The search is debounced; hidden rows remain allocated so their icons and
    # item objects can be reused when the query changes.
    dlg._apply_filter()
    visible = lambda: [dlg.list_widget.item(i) for i in range(dlg.list_widget.count())
                       if not dlg.list_widget.item(i).isHidden()]
    check("filter narrows list", len(visible()) == 1)
    dlg._on_current_changed(dlg.list_widget.currentItem(), None)
    sel = dlg.selected_app()
    check("selection carries the app dict",
          sel is not None and sel["bundle_id"] == "com.instagram.instagram")

    dlg.filter_input.setText("zzz-nothing")
    dlg._apply_filter()
    check("no-match filter empties the list", len(visible()) == 0)
    dlg.filter_input.setText("")

    print(f"ALL APP-LIST CHECKS PASSED ({PASS} checks)", flush=True)


asyncio.run(main())