"""Ordered GUI bootstrap steps; backend preloading never constructs Qt widgets."""
from dataclasses import dataclass
import os
import sys


@dataclass
class BackendPreload:
    done: object
    errors: list

    def wait(self):
        self.done.wait()
        if self.errors:
            raise self.errors[0]


def preload_backend():
    # Preload the device-manager module (pymobiledevice3 and its service deps
    # are the single most expensive import in the app) on a worker thread so it
    # races with the GUI setup below instead of blocking startup. If it is still
    # running or failed, the main-thread import later behaves exactly as it did
    # before — waiting on the module lock or re-raising the error on the main
    # thread. Qt objects are only ever created on the main thread.
    import threading
    _dm_preload_error: list = []
    _dm_preload_done = threading.Event()

    def _preload_device_manager():
        try:
            # Import ONLY the pure-Python pymobiledevice3 backend here. A Qt
            # import on a non-main thread would leak QThreadStorage entries
            # that Qt complains about at exit, so nothing here may pull in
            # widgets — ``src.devicemanagement`` is Qt-free by rule (see
            # tools/test_backend_qt_free.py), and the pmd3 services (the
            # single most expensive part) are already in sys.modules.
            from pymobiledevice3 import usbmux, ca  # noqa: F401
            from pymobiledevice3.lockdown import create_using_usbmux  # noqa: F401
            from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service  # noqa: F401
            from pymobiledevice3.services.mobile_config import MobileConfigService  # noqa: F401
            from pymobiledevice3.services.diagnostics import DiagnosticsService  # noqa: F401
            from pymobiledevice3.services.installation_proxy import InstallationProxyService  # noqa: F401
            import pymobiledevice3.service_connection  # noqa: F401
            import pymobiledevice3.exceptions  # noqa: F401
        except BaseException as e:  # surfaced on the main thread below
            _dm_preload_error.append(e)
        finally:
            _dm_preload_done.set()

    threading.Thread(target=_preload_device_manager, name="device-manager-preload", daemon=True).start()

    return BackendPreload(_dm_preload_done, _dm_preload_error)


def configure_appearance(app, bundle_root):
    # Fusion style is required for a custom QPalette to take effect on all
    # platforms (native styles ignore palette tweaks).  The palette is now
    # managed by ColorThemeManager so it can switch between dark/light.
    app.setStyle("Fusion")

    from src.gui.theme import ColorThemeManager, FONT_FAMILY
    _color_theme = ColorThemeManager.instance()
    # Pins the colour scheme too, so the OS light/dark setting never leaks in.
    _color_theme.apply_to_app(app)

    # Register the bundled Inter variable font and make it the single UI font
    # on every platform. Both the dev tree and the PyInstaller bundle
    # (_MEIPASS) ship it at src/qt/fonts/...; the platform default size is
    # kept and weights/italics come from the variable font.
    from PySide6.QtGui import QFontDatabase
    _fonts_root = os.path.join(
        getattr(sys, "_MEIPASS", bundle_root),
        "src", "qt", "fonts",
    )
    for _font_file in ("InterVariable.ttf", "InterVariable-Italic.ttf"):
        _font_path = os.path.join(_fonts_root, _font_file)
        if QFontDatabase.addApplicationFont(_font_path) == -1:
            print(f"[init] WARNING: bundled font not registered: {_font_path}", flush=True)
    _app_font = app.font()
    _app_font.setFamily(FONT_FAMILY)
    app.setFont(_app_font)
    print(f"[init] Font: {FONT_FAMILY} on all platforms", flush=True)

    print(f"[init] Qt style: {app.style().objectName()}")



def restore_selected_preset(settings, logger):
    # Restore the preset that was loaded right before the app restarted (pages
    # read the tweak state only once on startup, so the preset must be applied
    # before the window is created). The marker is cleared once applied.
    last_loaded_preset = settings.value("last_loaded_preset", "", type=str)
    if last_loaded_preset:
        try:
            from src.controllers.preset_manager import PresetManager
            if PresetManager().load_preset(last_loaded_preset):
                logger.info("Restored preset: %s", last_loaded_preset)
        except Exception as e:
            logger.error("Failed to restore preset '%s': %s", last_loaded_preset, e)
        finally:
            settings.setValue("last_loaded_preset", "")
            settings.sync()
