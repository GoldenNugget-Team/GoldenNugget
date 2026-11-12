"""iOS pages are reserved at startup and constructed on first access.

Building all fifteen pages up front cost ~0.5 s of the startup path even
though only the home page is on screen. Each other page now reserves its
stack slot (so the numeric page indices stay stable) and is built when
something asks for it.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget
from settings_sandbox import SettingsSandbox

from src.gui.theme import ColorThemeManager

APP = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont(str(ROOT / 'src/qt/fonts/InterVariable.ttf'))
APP.setFont(QFont('Inter Variable'))

RESERVED = {
    1: "ios_tweaks", 2: "ios_posterboard", 3: "ios_daemons", 4: "ios_settings",
    5: "ios_statusbar", 6: "ios_apply", 7: "ios_springboard", 8: "ios_internal",
    9: "ios_liquidglass", 10: "ios_iconthemes", 11: "ios_passthemes",
    12: "ios_presets", 13: "ios_catalog", 14: "ios_templates",
}


class LazyPages(unittest.TestCase):
    def build_window(self):
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
        from src.gui.translator import Translator
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        sandbox = SettingsSandbox(Path(directory))
        make_settings = sandbox.__enter__()
        self.addCleanup(sandbox.__exit__, None, None, None)
        settings = make_settings('settings')
        previous = ColorThemeManager._inst
        ColorThemeManager._inst = ColorThemeManager()
        self.addCleanup(lambda: setattr(ColorThemeManager, '_inst', previous))
        manager = DeviceManager()
        manager.pref_manager.settings = settings
        with patch.object(MainWindow, 'refresh_devices'), \
             patch.object(MainWindow, '_load_last_preset'), \
             patch.object(MainWindow, '_register_tweak_autosave'), \
             patch('src.gui.main_window.DeviceMonitorThread.start'), \
             patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=directory):
            window = MainWindow(manager, Translator(APP, settings))
        self.addCleanup(window.deleteLater)
        return window

    def test_only_home_is_built_at_startup(self):
        window = self.build_window()
        self.assertIsNotNone(window.built_page("ios_home"))
        for name in RESERVED.values():
            self.assertIsNone(window.built_page(name),
                              f"{name} was built during startup")
        self.assertEqual(window.ios_pages.count(), len(RESERVED) + 1)
        for index in RESERVED:
            self.assertIsInstance(window.ios_pages.widget(index), QWidget)
            self.assertNotIn(type(window.ios_pages.widget(index)).__name__,
                             ('IOSSettingsPage', 'IOSHomePage'))

    def test_navigation_builds_the_page_in_its_reserved_slot(self):
        window = self.build_window()
        window.set_ios_page(4, animate=False)
        # The first open shows the reserved loading screen and queues the
        # build; pump the timer until it completes (bounded, no hidden waits).
        deadline = time.monotonic() + 5
        while window.built_page("ios_settings") is None:
            self.assertLess(time.monotonic(), deadline,
                            "deferred first-open build never completed")
            QApplication.processEvents()
        settings_page = window.built_page("ios_settings")
        self.assertIs(window.ios_pages.widget(4), settings_page)
        self.assertIs(window.ios_pages.currentWidget(), settings_page)

    def test_attribute_access_builds_in_place_and_keeps_indices(self):
        window = self.build_window()
        page = window.ios_tweaks
        self.assertIs(window.built_page("ios_tweaks"), page)
        self.assertIs(window.ios_pages.widget(1), page)
        self.assertIsNot(window.ios_pages.widget(2), page)
        # Already built: later accesses return the same widget, not a rebuild.
        self.assertIs(window.ios_tweaks, page)

    def test_built_page_probe_does_not_construct(self):
        window = self.build_window()
        self.assertIsNone(window.built_page("ios_catalog"))
        self.assertIn("ios_catalog", window._lazy_pages)

    def test_nav_right_actions_resolve_lazily(self):
        window = self.build_window()
        label, action = window._nav_right_actions[2]
        self.assertTrue(label)
        self.assertTrue(callable(action))
        # Merely registering the action must not build the page.
        self.assertIsNone(window.built_page("ios_posterboard"))

    def test_failed_build_keeps_the_page_retryable(self):
        # A failed first build used to pop the reservation and never restore
        # it, so every later access died with a bare AttributeError
        # ("'MainWindow' object has no attribute 'ios_presets'").
        window = self.build_window()
        from unittest.mock import Mock

        def broken():
            raise RuntimeError("simulated construction failure")

        with patch.dict(window._lazy_pages, {"ios_presets": (12, broken)}):
            with self.assertRaisesRegex(RuntimeError, "simulated construction failure"):
                window.ios_presets
            self.assertIn("ios_presets", window._lazy_pages,
                          "a failed build must not lose the reservation")

        from src.gui.ios.presets import IOSPresetsPage
        with patch.dict(window._lazy_pages, {"ios_presets": (12, lambda: IOSPresetsPage(window))}):
            page = window.ios_presets
        self.assertIsNotNone(window.built_page("ios_presets"))
        self.assertIs(window.ios_pages.widget(12), page)
        self.assertIsInstance(page, IOSPresetsPage)

    def test_catalog_panel_uses_the_shared_preset_manager(self):
        # catalog.ensure_panel must not reach into window.ios_presets: from a
        # showEvent that built a whole other page (and crashed when the lazy
        # reservation was missing). The window already owns a PresetManager.
        from unittest.mock import Mock

        from PySide6.QtWidgets import QWidget

        from src.gui.ios import catalog as catalog_module

        window = self.build_window()
        with patch.object(catalog_module, "CatalogDialog", Mock(return_value=QWidget())) as dialog, \
                patch.object(catalog_module, "_device_context", return_value=("", "", False)):
            page = catalog_module.IOSCatalogPage(window)
            page.ensure_panel()
        dialog.assert_called_once()
        self.assertIs(dialog.call_args.args[0], window.preset_manager)
        self.assertIsNone(window.built_page("ios_presets"),
                          "ensure_panel must not build the presets page")
        self.assertIsNone(window.built_page("ios_catalog"))


if __name__ == '__main__':
    unittest.main()
