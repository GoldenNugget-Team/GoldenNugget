"""Offline accent persistence, contrast and live-widget regressions.

The app ships a single dark palette (``DARK``); only the accent is a user
choice, so these tests cover the accent lifecycle instead of a light/dark switch.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QPalette, QColor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel
from src.gui.theme import ColorThemeManager, DARK, ACCENT_PRESETS, STYLES, t

from settings_sandbox import SettingsSandbox

APP = QApplication.instance() or QApplication([])
APP.setStyle('Fusion')


def contrast(first, second):
    def luminance(hex_color):
        values = [int(hex_color[pos:pos + 2], 16) / 255 for pos in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(values, (.2126, .7152, .0722)))
    dark, light = sorted((luminance(first), luminance(second)))
    return (light + .05) / (dark + .05)


class Themes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sandbox = SettingsSandbox(Path(self.tmp.name))
        self.make_settings = self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__, None, None, None)
        self.settings = self.make_settings('settings')
        self.old_manager = ColorThemeManager._inst
        self.old_palette = APP.palette()
        self.manager = ColorThemeManager()
        ColorThemeManager._inst = self.manager
        self.addCleanup(self.restore)

    def restore(self):
        ColorThemeManager._inst = self.old_manager
        APP.setPalette(self.old_palette)

    def test_accent_persists_and_does_not_change_the_base_palette(self):
        self.assertEqual(self.manager.accent_name, 'blue')
        self.assertEqual(self.manager.colors.bg_primary, DARK.bg_primary)
        self.manager.set_accent('yellow')
        restored = ColorThemeManager()
        self.assertEqual(restored.accent_name, 'yellow')
        self.assertEqual(restored.colors.accent, ACCENT_PRESETS['yellow'][0])
        self.assertEqual(restored.colors.bg_primary, DARK.bg_primary)

    def test_os_colour_scheme_is_always_pinned_dark(self):
        from PySide6.QtCore import QObject, Qt, Signal

        class Hints(QObject):
            colorSchemeChanged = Signal(object)

            def __init__(self):
                super().__init__()
                self.scheme = None

            def setColorScheme(self, scheme):
                self.scheme = scheme

        class App:
            def __init__(self):
                self.hints = Hints()
                self.palette = None

            def styleHints(self):
                return self.hints

            def setPalette(self, palette):
                self.palette = palette

        app = App()
        self.manager.apply_to_app(app)
        self.assertEqual(app.hints.scheme, Qt.ColorScheme.Dark, 'dark is pinned')
        # The OS (or anything else) switches to light: dark is re-asserted.
        app.hints.scheme = Qt.ColorScheme.Light
        app.hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
        self.assertEqual(app.hints.scheme, Qt.ColorScheme.Dark)
        self.assertEqual(app.palette.window().color().name().lower(), DARK.bg_primary.lower())
        # A replaced manager stays out of it.
        ColorThemeManager._inst = object()
        app.hints.scheme = Qt.ColorScheme.Light
        app.hints.colorSchemeChanged.emit(Qt.ColorScheme.Light)
        self.assertEqual(app.hints.scheme, Qt.ColorScheme.Light)
        ColorThemeManager._inst = self.manager

    def test_invalid_accent_falls_back_and_noop_does_not_emit(self):
        self.settings.setValue('accent_color', 'unknown')
        restored = ColorThemeManager()
        self.assertEqual(restored.accent_name, 'blue')
        spy = QSignalSpy(self.manager.theme_changed)
        self.manager.set_accent('unknown')
        self.manager.set_accent(self.manager.accent_name)
        self.assertEqual(spy.count(), 0)
        self.manager.set_accent('green')
        self.assertEqual(spy.count(), 1)

    def test_text_and_every_accent_have_readable_contrast(self):
        surfaces = (DARK.bg_primary, DARK.bg_secondary, DARK.bg_tertiary, DARK.bg_input,
                    DARK.bg_elevated, DARK.surface_hover)
        for color in (DARK.text_primary, DARK.text_secondary, DARK.error, DARK.success, DARK.warning):
            for surface in surfaces:
                self.assertGreaterEqual(contrast(color, surface), 3.0, (color, surface))
        self.assertGreaterEqual(contrast(DARK.text_primary, DARK.bg_primary), 4.5)
        seen = {}
        for name in ACCENT_PRESETS:
            self.manager.set_accent(name)
            c = self.manager.colors
            # The accent is used for links and icons on dark cards; it must stay
            # visible on every surface (white-on-yellow buttons are the shipped
            # design, so text_inverse is not a constraint for the accent).
            for color in (c.accent, c.accent_hover, c.accent_pressed):
                for surface in surfaces:
                    self.assertGreaterEqual(contrast(color, surface), 1.8, (name, color, surface))
            seen[name] = c.accent
            self.assertEqual(self.manager.accent_hex(), c.accent)
            self.assertEqual(self.manager.accent_rgb(), QColor(c.accent).getRgb()[:3])
            self.assertEqual(c.selection, c.accent)
        self.assertEqual(len(set(seen.values())), len(ACCENT_PRESETS))

    def test_native_roles_update_for_active_and_inactive_windows(self):
        self.manager.set_accent('teal')
        c = self.manager.colors
        palette = self.manager.build_palette()
        for group in (QPalette.Active, QPalette.Inactive):
            self.assertEqual(palette.color(group, QPalette.Base).name(), c.bg_input.lower())
            self.assertEqual(palette.color(group, QPalette.Text).name(), c.text_primary.lower())
            self.assertEqual(palette.color(group, QPalette.HighlightedText).name(), c.text_inverse.lower())
            self.assertEqual(palette.color(group, QPalette.ToolTipText).name(), c.text_primary.lower())
        self.assertEqual(palette.color(QPalette.Disabled, QPalette.Text).name(), c.text_disabled.lower())

    def test_every_shared_template_renders(self):
        for key in STYLES:
            if key == 'accent_swatch':
                from src.gui.theme import themed_stylesheet
                rendered = themed_stylesheet(key, swatch=self.manager.accent_hex())
            else:
                rendered = t(key)
            self.assertTrue(rendered.strip(), key)

    def test_swatch_numeric_dialog_and_about_follow_live_changes(self):
        from src.gui.theme import AccentPicker
        from src.gui.ios.components import NumberInputDialog
        from src.gui.dialogs.dialogs import AboutProgramDialog
        picker = AccentPicker()
        numeric = NumberInputDialog('Number', 1.5, 0, 10, step=.5)
        about = AboutProgramDialog()
        try:
            self.manager.set_accent('green')
            APP.processEvents()
            self.assertTrue(picker._buttons['green'].isChecked())
            self.assertIn(self.manager.colors.text_primary, picker._buttons['green'].styleSheet())
            self.assertIn(self.manager.colors.text_primary, numeric.styleSheet())
            self.assertIn(self.manager.colors.text_inverse, about.styleSheet())
            self.assertIn(DARK.text_secondary, ''.join(label.styleSheet() for label in about.findChildren(QLabel)))
        finally:
            for widget in (picker, numeric, about):
                widget.close()
                widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_pages_pick_up_an_accent_change_lazily(self):
        """Pages re-theme lazily (set_ios_page checks a revision), so a page that
        was NOT on screen when the accent changed must still come up with the
        new accent. Guards the lazy path: the previous accent must not survive
        on any page reached afterwards (the accent swatches keep their own
        preset colours by design)."""
        from src.gui.translator import Translator
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
        from src.gui.theme import AccentPicker
        from PySide6.QtWidgets import QWidget
        dm = DeviceManager()
        dm.pref_manager.settings = self.settings
        with patch.object(MainWindow, 'refresh_devices'), patch.object(MainWindow, '_load_last_preset'), \
             patch.object(MainWindow, '_register_tweak_autosave'), \
             patch('src.gui.main_window.DeviceMonitorThread.start'), \
             patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=self.tmp.name):
            window = MainWindow(dm, Translator(APP, self.settings))
        try:
            window.show()
            window.content_stack.setCurrentIndex(1)
            window.set_ios_page(0, animate=False)
            stale = {color.lower() for color in ACCENT_PRESETS['blue']}
            self.manager.set_accent('green')
            window._on_color_theme_changed()
            self.assertFalse(stale & {self.manager.colors.accent.lower(),
                                      self.manager.colors.accent_hover.lower(),
                                      self.manager.colors.accent_pressed.lower()})
            for index in range(window.ios_pages.count()):
                window.set_ios_page(index, animate=False)
                APP.processEvents()
                page = window.ios_pages.widget(index)
                # Hidden widgets are re-themed when they are next shown
                # (connect_visible_theme), so only what is on screen counts.
                shown = [w for w in [page, *page.findChildren(QWidget)]
                         if w.isVisibleTo(page) and not isinstance(w.parentWidget(), AccentPicker)]
                leftovers = sorted(
                    f'{type(w).__name__}#{w.objectName()}:{color}' for w in shown
                    for color in stale if color in w.styleSheet().lower())
                self.assertEqual(leftovers, [], f'{type(page).__name__} (index {index}) still carries the old accent')
            # The result card is hidden until an operation finishes; it must come
            # up in the current accent the moment it appears.
            window.set_ios_page(0, animate=False)
            card = window.ios_home.result_card
            was_hidden = card.isHidden()
            card.show()
            APP.processEvents()
            sheets = ' '.join(w.styleSheet().lower() for w in [card, *card.findChildren(QWidget)])
            self.assertEqual(sorted(color for color in stale if color in sheets), [],
                             'home.result_card appeared with the old accent')
            card.setVisible(not was_hidden)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_settings_has_no_mode_switch_and_rethemes_without_editing_tweaks(self):
        from src.gui.translator import Translator
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
        from src.tweaks.tweaks import tweaks
        dm = DeviceManager()
        dm.pref_manager.settings = self.settings
        with patch.object(MainWindow, 'refresh_devices'), patch.object(MainWindow, '_load_last_preset'), \
             patch.object(MainWindow, '_register_tweak_autosave'), \
             patch('src.gui.main_window.DeviceMonitorThread.start'), \
             patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=self.tmp.name):
            window = MainWindow(dm, Translator(APP, self.settings))
        try:
            page = window.ios_settings
            window.show()
            window.content_stack.setCurrentIndex(1)
            window.set_ios_page(4, animate=False)
            APP.processEvents()
            self.assertFalse(hasattr(page, 'color_theme_combo'))
            before = {tid: (tweak.enabled, repr(tweak.value)) for tid, tweak in tweaks.items()}
            for name in ('green', 'blue', 'green'):
                self.manager.set_accent(name)
                window._on_color_theme_changed()
                APP.processEvents()
                self.assertEqual(self.manager.accent_name, name)
                labels = [label for label in page.findChildren(QLabel) if label.property('theme_style_key')]
                self.assertTrue(labels)
                for label in labels:
                    self.assertEqual(label.styleSheet(), t(label.property('theme_style_key')))
                    self.assertIn('transparent', label.styleSheet())
            self.assertEqual(before, {tid: (tweak.enabled, repr(tweak.value)) for tid, tweak in tweaks.items()})
            self.assertEqual(ColorThemeManager().accent_name, 'green')
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
