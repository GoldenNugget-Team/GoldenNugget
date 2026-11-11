"""Offline checks for the Status Bar page's live preview."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QRectF, QTime
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from src.gui.ios.statusbar_preview import (
    MAX_BARS,
    MAX_WIFI_BARS,
    StatusBarPreview,
    paint_status_bar,
    preview_state,
)
from src.tweaks.status_bar.status_setter import StatusBarItem

APP = QApplication.instance() or QApplication([])
NOON = QTime(12, 0)


class FakeStatusBar:
    """Only the getters preview_state reads; unset ones report 'not overridden'."""

    def __init__(self, enabled=True, hidden=(), **values):
        self.enabled = enabled
        self._values = values
        self._hidden = set(hidden)

    def __getattr__(self, name):
        for prefix, key in (('is_', '_overridden'), ('get_', '_override')):
            if name.startswith(prefix) and name.endswith(key):
                field = name[len(prefix):-len(key)]
                if prefix == 'is_':
                    return lambda: field in self._values
                return lambda: self._values[field]
        raise AttributeError(name)

    def is_item_overridden(self, item):
        return item in self._hidden

    def get_item_override(self, item):
        return 0 if item in self._hidden else 1


class PreviewState(unittest.TestCase):
    FULL = dict(carrier='GoldenNugget', primary_service_badge='P', gsm_signal_strength_bars=2,
                secondary_carrier='Beeline', time='4:20', battery_capacity=15,
                battery_detail='42%', wifi_signal_strength_bars=1)

    def test_master_switch_off_shows_stock(self):
        state = preview_state(FakeStatusBar(enabled=False, **self.FULL), ios27=False, now=NOON)
        self.assertNotEqual(state.carrier, 'GoldenNugget')
        self.assertEqual((state.time, state.bars, state.wifi_bars, state.battery), ('12:00', MAX_BARS, MAX_WIFI_BARS, 100))
        self.assertIsNone(state.secondary_bars)

    def test_ios26_applies_every_override(self):
        state = preview_state(FakeStatusBar(**self.FULL), ios27=False, now=NOON)
        self.assertEqual(state.carrier, 'GoldenNugget')
        self.assertEqual(state.primary_badge, 'P')
        self.assertEqual(state.bars, 2)
        self.assertEqual(state.secondary_carrier, 'Beeline')
        self.assertEqual(state.secondary_bars, MAX_BARS)
        self.assertEqual((state.time, state.battery, state.battery_detail, state.wifi_bars), ('4:20', 15, '42%', 1))

    def test_ios27_keeps_only_the_cellular_entry(self):
        state = preview_state(FakeStatusBar(hidden={StatusBarItem.MainBatteryStatusBarItem}, **self.FULL),
                              ios27=True, now=NOON)
        self.assertEqual((state.carrier, state.primary_badge, state.bars), ('GoldenNugget', 'P', 2))
        self.assertEqual((state.time, state.battery, state.battery_detail, state.wifi_bars),
                         ('12:00', 100, '', MAX_WIFI_BARS))

    def test_ios27_name_only_keeps_stock_preview_bars(self):
        # An unset bar count is omitted; retain the stock preview placeholder.
        state = preview_state(FakeStatusBar(carrier='GoldenNugget'), ios27=True, now=NOON)
        self.assertEqual((state.carrier, state.bars), ('GoldenNugget', MAX_BARS))
        self.assertIsNone(state.secondary_bars)

    def test_values_are_clamped_and_hidden_icons_drop_out(self):
        state = preview_state(FakeStatusBar(
            gsm_signal_strength_bars=9, wifi_signal_strength_bars=-3, battery_capacity=250,
            hidden={StatusBarItem.CellularDataNetworkStatusBarItem, StatusBarItem.CellularServiceStatusBarItem}),
            ios27=False, now=NOON)
        self.assertEqual(state.bars, MAX_BARS)
        self.assertEqual(state.battery, 100)
        self.assertIsNone(state.wifi_bars)
        self.assertFalse(state.show_cellular)

    def test_preview_widget_api_remains_available(self):
        widget = StatusBarPreview()
        widget.resize(960, widget.heightForWidth(960))
        state = preview_state(FakeStatusBar(**self.FULL), ios27=False, now=NOON)
        widget.set_state(state)
        self.assertEqual(widget.state(), state)
        self.assertFalse(widget.grab().isNull())
        self.assertGreater(widget.heightForWidth(960), widget.heightForWidth(400))
        widget.deleteLater()

    def test_device_status_renderer_paints_every_state(self):
        for width in (393, 600, 960):
            for manager in (FakeStatusBar(enabled=False), FakeStatusBar(**self.FULL),
                            FakeStatusBar(carrier='x' * 200, primary_service_badge='', gsm_signal_strength_bars=0,
                                          hidden={StatusBarItem.MainBatteryStatusBarItem})):
                state = preview_state(manager, ios27=False, now=NOON)
                for lock_screen in (False, True):
                    image = QImage(width, 200, QImage.Format_ARGB32)
                    image.fill(QColor('#202020'))
                    before = image.copy()
                    painter = QPainter(image)
                    paint_status_bar(painter, QRectF(0, 0, width, 200), state, lock_screen)
                    painter.end()
                    self.assertNotEqual(image, before)


if __name__ == '__main__':
    unittest.main()
