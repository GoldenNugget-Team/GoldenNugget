"""Bookmarks stay independent of tweak state; settings search preserves inputs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QElapsedTimer, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from src.controllers.favorites import TweakFavorites
from src.gui.ios.components import (
    IOSCollapsibleSection,
    IOSSearchEmpty,
    IOSSearchField,
    IOSSectionHeader,
)
from src.gui.ios.settings import IOSSettingsPage
from src.gui.ios.tweaks import IOSSectionContent
from src.tweaks.tweaks import tweaks


class FavoritesSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, self.tmp.name)
        self.addCleanup(lambda: QSettings.setDefaultFormat(QSettings.NativeFormat))
        store_path = str(Path(self.tmp.name) / 'favorites.ini')
        settings_patch = patch('src.controllers.favorites.Settings',
                               side_effect=lambda: QSettings(store_path, QSettings.IniFormat))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def wait_for_rows(self, page):
        if page._inner is None and not getattr(page, "_building", False):
            page.rebuild()
        deadline = QElapsedTimer()
        deadline.start()
        while getattr(page, '_building', False) and deadline.elapsed() < 10000:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(getattr(page, '_building', False))

    def test_bookmarks_persist_sync_and_respect_compatibility(self):
        manager = SimpleNamespace(data_singleton=SimpleNamespace(current_device=None),
                                  get_current_device_version=lambda: '27.0',
                                  get_current_device_model=lambda: 'iPhone17,3')
        window = SimpleNamespace(device_manager=manager)
        one, two = IOSSectionContent(window), IOSSectionContent(window)
        self.wait_for_rows(one)
        self.wait_for_rows(two)
        tid = next(tid for card, tid, *_ in one._search_rows if not card.isHidden())
        before = {tid: (t.enabled, repr(t.value)) for tid, t in tweaks.items()}
        one._favorite_buttons[tid].click()
        self.assertIn(tid.name, TweakFavorites().names())
        self.assertTrue(two._favorite_buttons[tid].isChecked())
        self.assertEqual(before, {tid: (t.enabled, repr(t.value)) for tid, t in tweaks.items()})
        one.filter_control.setCurrentIndex(2)
        self.assertEqual([tid for card, tid, *_ in one._search_rows if not card.isHidden()], [tid])
        one.rebuild()
        self.wait_for_rows(one)
        self.assertTrue(one._favorite_buttons[tid].isChecked())
        one._favorite_buttons[tid].click()
        self.assertFalse(two._favorite_buttons[tid].isChecked())
        self.assertFalse(one.search_empty.isHidden())
        one.close()
        two.close()
        one.deleteLater()
        two.deleteLater()
        self.app.processEvents()

    def test_search_matches_titles_and_sections_without_editing_values(self):
        page = QWidget()
        page.content_layout = QVBoxLayout(page)
        page.search = IOSSearchField()
        page.search_empty = IOSSearchEmpty()
        header = IOSSectionHeader('Backup')
        card = QWidget()
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel('Cache location'))
        value = QLineEdit('private user value')
        layout.addWidget(value)
        other_header = IOSSectionHeader('Appearance')
        other = QLabel('Accent color')
        for widget in (header, card, other_header, other):
            page.content_layout.addWidget(widget)
        IOSSettingsPage._index_search_rows(page)
        page.search.setText('cache')
        IOSSettingsPage._filter_settings(page)
        self.assertFalse(card.isHidden())
        self.assertTrue(other.isHidden())
        page.search.setText('backup')
        IOSSettingsPage._filter_settings(page)
        self.assertFalse(card.isHidden())
        page.search.setText('private user value')
        IOSSettingsPage._filter_settings(page)
        self.assertFalse(page.search_empty.isHidden())
        self.assertTrue(card.isHidden())
        page.search.clear()
        IOSSettingsPage._filter_settings(page)
        self.assertFalse(other.isHidden())
        self.assertEqual(value.text(), 'private user value')

    def test_advanced_search_temporarily_expands_and_filters_rows(self):
        page = QWidget()
        page.content_layout = QVBoxLayout(page)
        page.search = IOSSearchField()
        page.search_empty = IOSSearchEmpty()
        page._advanced_search_state = None
        advanced = IOSCollapsibleSection('Advanced', expanded=False)
        advanced.body_layout.addWidget(IOSSectionHeader('Backup options'))
        cache = QLabel('Encrypted backup')
        advanced.body_layout.addWidget(cache)
        advanced.body_layout.addWidget(IOSSectionHeader('Setup'))
        setup = QLabel('Supervision')
        advanced.body_layout.addWidget(setup)
        page.content_layout.addWidget(advanced)
        IOSSettingsPage._index_search_rows(page)
        page.search.setText('encrypted')
        IOSSettingsPage._filter_settings(page)
        self.assertTrue(advanced.expanded)
        self.assertFalse(cache.isHidden())
        self.assertTrue(setup.isHidden())
        page.search.clear()
        IOSSettingsPage._filter_settings(page)
        self.assertFalse(advanced.expanded)
        self.assertFalse(setup.isHidden())


if __name__ == '__main__':
    unittest.main()
