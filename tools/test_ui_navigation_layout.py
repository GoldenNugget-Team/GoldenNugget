"""Offline regressions for compact tweak controls and window-local navigation."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QBoxLayout, QDialog, QLineEdit, QWidget

from src.gui.ios.apply import IOSApplyPage
from src.gui.ios.tweaks import IOSSectionContent
from src.gui.main_window_mixins import NavigationMixin


class NavigationWindow(QWidget, NavigationMixin):
    def __init__(self):
        super().__init__()
        self._go_back = Mock(return_value=True)


class UILayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_search_reflows_without_changing_selection(self):
        page = IOSSectionContent(SimpleNamespace())
        self.addCleanup(page.deleteLater)
        page.search.setText("wallpaper")
        # No generated tweak rows or device connection is needed for layout.
        page.filter_control.blockSignals(True)
        page.filter_control.setCurrentIndex(1)
        page.filter_control.blockSignals(False)
        for width, direction in ((1000, QBoxLayout.LeftToRight),
                                 (480, QBoxLayout.TopToBottom),
                                 (1000, QBoxLayout.LeftToRight)):
            page.resize(width, 600)
            page._fit_search_row()
            page.layout().activate()
            self.assertEqual(page._search_row.direction(), direction)
            self.assertEqual(page.search.text(), "wallpaper")
            self.assertEqual(page.filter_control.currentIndex(), 1)
            if direction == QBoxLayout.TopToBottom:
                self.assertGreater(page.filter_control.y(), page.search.geometry().bottom())
            self.assertGreaterEqual(page.search.width(), 240)

    def test_filter_width_controls_breakpoint(self):
        page = IOSSectionContent(SimpleNamespace())
        self.addCleanup(page.deleteLater)
        page.resize(1000, 600)
        # Simulate a translated control wider than the available inline space.
        page.filter_control.setMinimumWidth(800)
        page._fit_search_row()
        self.assertEqual(page._search_row.direction(), QBoxLayout.TopToBottom)

    def test_escape_stays_with_nonmodal_dialog_and_unrelated_window(self):
        window = NavigationWindow()
        self.addCleanup(window.deleteLater)
        editor = QLineEdit(window)
        dialog = QDialog(window)
        dialog_editor = QLineEdit(dialog)
        unrelated = QWidget()
        self.addCleanup(unrelated.deleteLater)
        escape = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        for target in (dialog, dialog_editor, unrelated):
            self.assertFalse(NavigationMixin.eventFilter(window, target, escape))
        window._go_back.assert_not_called()
        self.assertTrue(NavigationMixin.eventFilter(window, editor, escape))
        window._go_back.assert_called_once()

    def test_apply_secondary_buttons_keep_large_flexible_targets(self):
        window = Mock()
        page = IOSApplyPage(window)
        self.addCleanup(page.deleteLater)
        for button in (page.preview_btn, page.pause_btn):
            self.assertEqual(button.minimumHeight(), 44)
            self.assertGreater(button.maximumHeight(), 44)
        window.apply_tweaks_clicked.assert_not_called()
        window.remove_tweaks_clicked.assert_not_called()
        page.preview_btn.click()
        window.show_device_twin.assert_called_once()


if __name__ == "__main__":
    unittest.main()
