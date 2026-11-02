"""iOS pages are reserved at startup and constructed on first access.

Building all fifteen pages up front cost ~0.5 s of the startup path even
though only the home page is on screen. Each other page now reserves its
stack slot (so the numeric page indices stay stable) and is built when
something asks for it.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from src.gui.theme import ColorThemeManager

from settings_sandbox import SettingsSandbox

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
        from src.gui.translator import Translator
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
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
        settings_page = window.built_page("ios_settings")
        self.assertIsNotNone(settings_page)
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


if __name__ == '__main__':
    unittest.main()
