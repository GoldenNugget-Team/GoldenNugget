"""First-run previews use actual Home and never persist preview choices."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication, QDialog
from src.gui.theme import ColorThemeManager
from src.gui.interface_picker import InterfacePickerDialog, _interface_preview

from settings_sandbox import SettingsSandbox

APP = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont(str(ROOT / 'src/qt/fonts/InterVariable.ttf'))
APP.setFont(QFont('Inter Variable'))


class FirstRunTests(unittest.TestCase):
    def test_actual_home_previews_selection_and_state_restoration(self):
        from src.gui.translator import Translator
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as directory, \
                SettingsSandbox(Path(directory)) as make_settings:
            settings = make_settings('settings')
            previous = ColorThemeManager._inst
            ColorThemeManager._inst = ColorThemeManager()
            manager = DeviceManager()
            manager.pref_manager.settings = settings
            try:
                with patch.object(MainWindow, 'refresh_devices'), \
                     patch.object(MainWindow, '_load_last_preset'), \
                     patch.object(MainWindow, '_register_tweak_autosave'), \
                     patch('src.gui.main_window.DeviceMonitorThread.start'), \
                     patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=directory):
                    window = MainWindow(manager, Translator(APP, settings))
                try:
                    window.show()
                    APP.processEvents()
                    window.set_sidebar_enabled(True)
                    window.set_ios_page(4, animate=False)
                    original = {key: settings.value(key) for key in settings.allKeys()}
                    widgets = (window.ui.sidebar, window.bottom_navigation,
                               window.ios_home.cards_grid, window.ios_home.apply_btn, window.ios_nav)
                    visibility = [widget.isHidden() for widget in widgets]
                    root = window.centralWidget()
                    original_size = root.size()
                    grab = root.grab
                    capture_count = 0

                    def check_layout_before_capture():
                        nonlocal capture_count
                        capture_count += 1
                        self.assertEqual((root.width(), root.height()), (1440, 960))
                        home = window.ios_home
                        if not home.cards_grid.isHidden():
                            # Regression: the old snapshot caught the header mid-reflow,
                            # pushing feature tiles beneath the bottom navigation.
                            header_bottom = max(home._branding.geometry().bottom(),
                                                home._device_area.geometry().bottom())
                            self.assertGreater(home.cards_grid.geometry().top(), header_bottom)
                            self.assertLess(home.cards_grid.mapTo(root, home.cards_grid.rect().bottomLeft()).y(),
                                            window.bottom_navigation.geometry().top())
                        return grab()

                    with patch.object(root, 'grab', side_effect=check_layout_before_capture):
                        modern = _interface_preview(window, 'modern')
                        sidebar = _interface_preview(window, 'sidebar')
                    self.assertEqual(capture_count, 2)
                    self.assertEqual(root.size(), original_size)
                    self.assertFalse(modern.isNull())
                    self.assertFalse(sidebar.isNull())
                    self.assertNotEqual(modern.toImage(), sidebar.toImage())
                    self.assertEqual(window.ios_pages.currentIndex(), 4)
                    self.assertEqual([widget.isHidden() for widget in widgets], visibility)
                    self.assertEqual({key: settings.value(key) for key in settings.allKeys()}, original)
                    APP.processEvents()
                    self.assertEqual(root.size(), original_size)
                    self.assertEqual(window.ios_pages.currentIndex(), 4)
                    self.assertEqual([widget.isHidden() for widget in widgets], visibility)
                    window.set_ios_page(0, animate=False)
                    dialog = InterfacePickerDialog(window)
                    self.assertIsNone(dialog.choice)
                    self.assertTrue(dialog._ios_frame.isChecked())
                    self.assertFalse(dialog._classic_frame.isChecked())
                    self.assertEqual(dialog._recommended.text(), 'Recommended')
                    self.assertTrue(all(not label.pixmap().isNull() for label in dialog._art.values()))
                    dialog._classic_frame.click()
                    self.assertIsNone(dialog.choice)
                    self.assertEqual(dialog._selected, 'classic')
                    dialog._ios_frame.click()
                    dialog.show()
                    APP.processEvents()
                    self.assertTrue(dialog.rect().contains(dialog._continue.geometry()))
                    self.assertGreaterEqual(dialog._ios_frame.height(), 330)
                    for art in dialog._art.values():
                        self.assertTrue(art.parentWidget().rect().contains(art.geometry()))
                    if os.environ.get('GOLDENNUGGET_FIRST_RUN_SCREENSHOT'):
                        dialog.grab().save(os.environ['GOLDENNUGGET_FIRST_RUN_SCREENSHOT'])
                    ColorThemeManager.instance().set_accent('purple')
                    APP.processEvents()
                    self.assertTrue(dialog._ios_frame.isChecked())
                    self.assertIsNone(dialog.choice)
                    dialog._continue.click()
                    self.assertEqual(dialog.result(), QDialog.Accepted)
                    self.assertEqual(dialog.choice, 'ios')
                    dialog.deleteLater()
                finally:
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            finally:
                ColorThemeManager._inst = previous


if __name__ == '__main__':
    unittest.main()
