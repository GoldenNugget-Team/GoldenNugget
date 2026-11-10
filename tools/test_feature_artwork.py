#!/usr/bin/env python3
"""Home artwork sizing and refresh regressions, without device access."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PySide6.QtGui import QBitmap, QRegion
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QToolButton

import src.gui.widgets  # Configure the host theme adapter.
from src.gui.ios.feature_icons import FEATURE_ICONS
from src.gui.ios.home import IOSHomePage

APP = QApplication.instance() or QApplication([])


class FeatureArtwork(unittest.TestCase):
    def test_icon_artist_credit_avatar_and_link(self):
        from src.gui.credits import CREDITS
        from src.gui.ios.support_panel import SupportPanel
        credit = next(entry for entry in CREDITS if entry[1] == 'mekabrine')
        entry = SupportPanel._credit(*credit)
        avatar = entry.findChild(QToolButton)
        self.assertIsNotNone(avatar)
        self.assertFalse(avatar.icon().isNull())
        with patch('src.gui.ios.support_panel.QDesktopServices.openUrl') as open_url:
            avatar.click()
        self.assertEqual(open_url.call_args.args[0].toString(),
                         'https://discord.com/users/1196529222617923660')

    def test_translation_credit_groups_avatars_under_one_heading(self):
        from PySide6.QtWidgets import QPushButton

        from src.gui.ios.support_panel import SupportPanel
        with patch('src.gui.ios.support_panel.ContributorMedia.instance') as media:
            panel = SupportPanel()
            panel._load_translation_contributors(True)
            ready = media.return_value.contributors.call_args.args[1]
            ready(['awesomenull-dev', 'kik4311', 'Wind0ws11Aero'], True)
        self.assertEqual(panel._translation_grid.count(), 3)
        headings = [button for button in panel.findChildren(QPushButton)
                    if button.text() == 'Translations']
        self.assertEqual(len(headings), 1)
        self.assertTrue(panel._translation_status.isHidden())

    def test_contributor_name_uses_theme_button_instead_of_html_link(self):
        from PySide6.QtWidgets import QPushButton

        from src.gui.ios.support_panel import SupportPanel
        with patch('src.gui.ios.support_panel.ContributorMedia.instance'):
            entry = SupportPanel._credit('Wallpaper Website', 'SerStars',
                                         'https://cowabun.ga/wallpapers')
        name = entry.findChild(QPushButton, 'supportCreditLink')
        self.assertEqual(name.text(), 'SerStars')
        self.assertIn('supportCreditLink', entry.styleSheet())

    def test_passcode_artwork_uses_requested_size(self):
        home = SimpleNamespace(_c=SimpleNamespace(text_primary='#ffffff'),
                               devicePixelRatioF=lambda: 1)
        label = QLabel()
        label.setFixedSize(140, 128)
        IOSHomePage._paint_tile_icon(home, label, FEATURE_ICONS['Passcode Theme'])
        bounds = QRegion(QBitmap.fromImage(label.pixmap().toImage().createAlphaMask())).boundingRect()
        self.assertGreaterEqual(bounds.height(), 124)
        self.assertLessEqual(abs(bounds.center().x() - label.rect().center().x()), 1)

    def test_device_refresh_reuses_tile_renderer(self):
        icon, title, caption = QLabel(), QLabel(), QLabel()
        resource = FEATURE_ICONS['Passcode Theme']
        renderer = Mock()
        home = SimpleNamespace(
            window=SimpleNamespace(device_manager=Mock()),
            passcode_theme_card=QFrame(),
            _tiles=[(icon, resource, title, caption)],
            _c=SimpleNamespace(text_secondary='#aaaaaa', text_primary='#ffffff', text_disabled='#666666'),
            _paint_tile_icon=renderer)
        with patch('src.gui.ios.home.current_passcode_theme_reason', return_value=None):
            IOSHomePage.update_passcode_support(home)
        renderer.assert_called_once_with(icon, resource)


if __name__ == '__main__':
    unittest.main()
