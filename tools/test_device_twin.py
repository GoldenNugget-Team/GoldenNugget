"""Offline digital-twin regressions: what is drawn for a selection (no device)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import resources_rc  # noqa: F401

from src.controllers.preset_manager import PresetManager
from src.gui.ios.device_twin import DeviceTwinView, build_state

ON = {'enabled': True, 'value': True}


def render(state, size=QSize(700, 760)):
    view = DeviceTwinView(state)
    view.resize(size)
    image = QImage(size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0))
    view.render(image)
    return image


class TwinState(unittest.TestCase):
    def test_search_button_replacement_respects_ios_version(self):
        old = {'SBHideSearchAffordance': {'enabled': True, 'value': False}}
        new = {'SBHomeScreenShowsSearchButton': {'enabled': True, 'value': False}}
        self.assertFalse(build_state(old, '27.0.1', 'iPhone17,1').search_button)
        self.assertTrue(build_state(old, '27.1', 'iPhone17,1').search_button)
        self.assertTrue(build_state(new, '27.0.1', 'iPhone17,1').search_button)
        self.assertFalse(build_state(new, '27.1', 'iPhone17,1').search_button)
        self.assertFalse(build_state(new, '27.2', 'iPhone17,1').search_button)

    def test_stock_selection_draws_nothing_special(self):
        state = build_state({}, '26.2', 'iPhone15,3')
        self.assertEqual((state.cutout, state.home_button), ('island', False))
        self.assertTrue(state.glass_dock and state.glass_clock and state.glass_icons)
        self.assertTrue(state.search_button and state.seconds_hand)
        self.assertEqual((state.shown, state.not_shown), ([], 0))

    def test_hardware_shapes(self):
        self.assertEqual(build_state({}, '26.2', 'iPhone12,1').cutout, 'notch')
        se = build_state({}, '26.2', 'iPhone14,6')
        self.assertEqual((se.cutout, se.home_button), ('none', True))
        self.assertEqual(build_state({}, '', '').cutout, 'island', 'unknown device uses the common shape')

    def test_island_tweak_only_where_there_is_an_island(self):
        island = build_state({'HideDICompletely': ON}, '26.2', 'iPhone15,3')
        self.assertEqual(island.cutout, 'none')
        self.assertEqual(len(island.shown), 1)
        notch = build_state({'HideDICompletely': ON}, '26.2', 'iPhone12,1')
        self.assertEqual(notch.cutout, 'notch')
        self.assertEqual(notch.shown, [], 'an incompatible tweak changes nothing')

    def test_visual_flags_and_hidden_count(self):
        data = {'NoLiquidDock': ON, 'NoLiquidClock': ON, 'UseFlatIconsEverywhere': ON,
                'SBHideSearchAffordance': {'enabled': True, 'value': False},
                'DisableSecondsHand': ON, 'RTL': ON,
                'LockScreenFootnote': {'enabled': True, 'value': 'Call me'},
                'SBShowSupervisionTextOnLockScreen': ON,
                'Daemons': {'enabled': True, 'value': {'com.apple.tipsd': True}},
                'AppStoreDebug': ON, 'SBBuildNumber': {'enabled': False}}
        state = build_state(data, '26.2', 'iPhone15,3')
        self.assertFalse(state.glass_dock or state.glass_clock or state.glass_icons)
        self.assertFalse(state.search_button or state.seconds_hand)
        self.assertTrue(state.rtl and state.supervised)
        self.assertEqual(state.footnote, 'Call me')
        self.assertEqual(len(state.shown), 8)
        self.assertEqual(state.not_shown, 2)
        self.assertEqual(state.build_label, '')

    def test_build_number_replaces_home_screen_time(self):
        self.assertEqual(build_state({'SBBuildNumber': ON}, '26.2', 'iPhone15,3', build='23C55').build_label, '23C55')

    def test_status_bar_comes_from_the_override_data(self):
        from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
        tweak = StatusBarTweak()
        tweak.enabled = True
        tweak.set_carrier_override('Nugget Mobile')
        entry = PresetManager.__new__(PresetManager)._serialize_tweak(tweak)
        state = build_state({'StatusBar': entry}, '26.2', 'iPhone15,3')
        self.assertEqual(state.status.carrier, 'Nugget Mobile')
        self.assertEqual(len(state.shown), 1)
        empty = PresetManager.__new__(PresetManager)._serialize_tweak(StatusBarTweak())
        empty['enabled'] = True
        self.assertEqual(build_state({'StatusBar': empty}, '26.2', 'iPhone15,3').shown, [],
                         'switched on without overrides looks stock')

    def test_icon_themes_and_wallpaper(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        icon = str(Path(tmp.name) / 'icon.png')
        image = QImage(60, 60, QImage.Format.Format_ARGB32)
        image.fill(QColor('#FF00FF'))
        image.save(icon)
        data = {'IconThemes': {'enabled': False, 'themes': [
            {'bundle_id': 'a', 'display_name': 'Mine', 'icon_path': icon},
            {'bundle_id': 'b', 'display_name': '', 'icon_path': icon}]}}
        state = build_state(data, '26.2', 'iPhone15,3', wallpaper=icon)
        self.assertEqual([(app.name, app.show_label) for app in state.themed], [('Mine', True), ('', False)])
        self.assertEqual(len(state.shown), 2)
        drawn = render(state)
        magenta = sum(drawn.pixelColor(x, y) == QColor('#FF00FF')
                      for x in range(0, drawn.width(), 7) for y in range(0, drawn.height(), 7))
        self.assertGreater(magenta, 100, 'wallpaper and themed icons are drawn')

    def test_stock_icons_from_the_device_cache(self):
        from unittest import mock

        from src.controllers import device_icons
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(device_icons, 'cache_dir', return_value=tmp.name):
            self.assertEqual(device_icons.cached_icons('UDID', '27.0'), {})
            image = QImage(60, 60, QImage.Format.Format_ARGB32)
            image.fill(QColor('#00FFFF'))
            image.save(str(Path(tmp.name) / 'com.apple.mobilephone.png'))
            icons = device_icons.cached_icons('UDID', '27.0')
        self.assertEqual(list(icons), ['Phone'])
        state = build_state({}, '27.0', 'iPhone17,1')
        plain = render(state)
        state.stock_icons = icons
        drawn = render(state)
        cyan = sum(drawn.pixelColor(x, y) == QColor('#00FFFF')
                   for x in range(0, drawn.width(), 3) for y in range(0, drawn.height(), 3))
        self.assertGreater(cyan, 10, 'the cached Phone icon replaces the drawn one')
        self.assertNotEqual(plain, drawn)


class TwinPainting(unittest.TestCase):
    def test_every_shape_renders_and_flags_change_pixels(self):
        for model in ('iPhone15,3', 'iPhone12,1', 'iPhone14,6'):
            render(build_state({}, '26.2', model))
        glass = render(build_state({}, '26.2', 'iPhone15,3'))
        solid = render(build_state({'NoLiquidDock': ON, 'SBHideSearchAffordance': ON}, '26.2', 'iPhone15,3'))
        self.assertNotEqual(glass, solid)

    def test_dialog_legend(self):
        from src.gui.dialogs.device_twin import DeviceTwinDialog, legend_text
        state = build_state({'NoLiquidDock': ON, 'AppStoreDebug': ON}, '26.2', 'iPhone15,3')
        text = legend_text(state)
        self.assertIn('Solid Dock', text)
        self.assertIn('1 more tweak', text)
        self.assertIn('not a screenshot', text)
        self.assertIn('None of the selected', legend_text(build_state({})))
        dialog = DeviceTwinDialog(state, 'Mine')
        self.assertEqual(dialog.windowTitle(), 'Mine')


if __name__ == '__main__':
    unittest.main()
