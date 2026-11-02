"""Focused UI polish regressions, without device access or a MainWindow fixture."""
import ast
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from src.gui.ios import settings as settings_module
from src.gui.ios.settings import IOSSettingsPage
from src.gui.theme import ColorThemeManager, t
from src.gui.widgets import IOSCollapsibleSection, IOSSearchField

from settings_sandbox import SettingsSandbox

APP = QApplication.instance() or QApplication([])
APP.setStyle('Fusion')


class SettingsHarness(IOSSettingsPage):
    """Run individual real page helpers with only their UI dependencies."""
    def __init__(self):
        QWidget.__init__(self)
        self._tm = ColorThemeManager.instance()
        self.content_layout = QVBoxLayout(self)
        self.org_value_lbl = QLabel(self)
        self.window = SimpleNamespace(device_manager=SimpleNamespace(
            pref_manager=SimpleNamespace(organization_name='Original')))


class UIPolish(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        sandbox = SettingsSandbox(Path(directory.name))
        sandbox.__enter__()
        self.addCleanup(sandbox.__exit__, None, None, None)
        old_manager = ColorThemeManager._inst
        self.addCleanup(setattr, ColorThemeManager, '_inst', old_manager)
        self.manager = ColorThemeManager()
        ColorThemeManager._inst = self.manager
        self.page = SettingsHarness()
        self.addCleanup(self.page.deleteLater)

    def test_accent_label_uses_wrapping_row_title(self):
        # Execute only the accent-label construction from __init__, not the
        # device/controller setup surrounding it. This tests the actual wiring.
        tree = ast.parse((ROOT / 'src/gui/ios/settings.py').read_text())
        page = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == 'IOSSettingsPage')
        init = next(node for node in page.body if isinstance(node, ast.FunctionDef)
                    and node.name == '__init__')
        start = next(index for index, node in enumerate(init.body)
                     if isinstance(node, ast.Assign) and any(
                         isinstance(target, ast.Name) and target.id == 'accent_label'
                         for target in node.targets))
        end = next(index for index in range(start + 1, len(init.body))
                   if isinstance(init.body[index], ast.Expr)
                   and isinstance(init.body[index].value, ast.Call)
                   and ast.unparse(init.body[index].value.func) == 'accent_row.addWidget')
        block = ast.Module(body=init.body[start:end + 1], type_ignores=[])
        card = QWidget(self.page)
        scope = dict(vars(settings_module), self=self.page, accent_row=QHBoxLayout(card))
        exec(compile(block, 'settings-accent-row', 'exec'), scope)
        label = scope['accent_label']
        self.assertTrue(label.wordWrap())
        self.assertEqual(label.property('theme_style_key'), 'row_title')
        self.assertEqual(label.styleSheet(), t('row_title'))

    def test_organization_dialog_uses_shared_style_and_preserves_submit(self):
        submitted = []

        def accept(dialog):
            self.assertEqual(dialog.styleSheet(), t('text_input_dialog'))
            self.assertEqual(dialog.textValue(), 'Original')
            self.assertIn(self.manager.colors.text_inverse, dialog.styleSheet())
            dialog.setTextValue('Edited')
            return QDialog.Accepted

        with patch.object(settings_module.QInputDialog, 'exec', accept):
            self.page._on_text_row_edit('Organization', submitted.append)
        self.assertEqual(self.page.org_value_lbl.text(), 'Edited')
        self.assertEqual(submitted, ['Edited'])
        with patch.object(settings_module.QInputDialog, 'exec', return_value=QDialog.Rejected):
            self.page._on_text_row_edit('Organization', submitted.append)
        self.assertEqual(len(submitted), 1)

    def test_history_search_shared_control_filter_and_clear(self):
        entries = [dict(timestamp='2026-10-27T12:00:00', mode='apply',
                        device=name, model='iPhone', ios='27', success=True)
                   for name in ('Alpha', 'Beta')]
        with patch('src.controllers.apply_history.load_history', return_value=entries):
            self.page._make_history_section()
            field = self.page.history_search
            self.assertIsInstance(field, IOSSearchField)
            self.assertEqual(field.height(), 44)
            self.assertEqual(field.accessibleName(), field.placeholderText())
            self.assertEqual(self.page.history_list.count(), 2)
            field.setText('Alpha')
            self.assertEqual(self.page.history_list.count(), 1)
            item = self.page.history_list.item(0)
            self.assertIn('Alpha', self.page.history_list.itemWidget(item).text())
            field._clear_button.click()
            self.assertEqual(field.text(), '')
            self.assertEqual(self.page.history_list.count(), 2)
            field._retheme()
            self.assertEqual(field.styleSheet(), t('list_search'))

    def test_home_title_init_and_retheme_use_palette_without_overrides(self):
        tree = ast.parse((ROOT / 'src/gui/ios/home.py').read_text())
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Both shapes are accepted: the direct call and the ``_restyle``
            # helper that skips the re-polish when the sheet is unchanged.
            if (ast.unparse(node.func) == 'self._title.setStyleSheet'
                    and len(node.args) == 1):
                calls.append(node)
            elif (ast.unparse(node.func) == '_restyle' and node.args
                  and ast.unparse(node.args[0]) == 'self._title'):
                calls.append(node)
        self.assertEqual(len(calls), 2)
        title = QLabel()
        self.addCleanup(title.deleteLater)
        scope = dict(self=SimpleNamespace(_title=title), t=t,
                     _restyle=lambda widget, sheet: widget.setStyleSheet(sheet))
        for call in calls:
            exec(compile(ast.fix_missing_locations(ast.Module(
                body=[ast.Expr(value=call)], type_ignores=[])),
                         'home-title-style', 'exec'), scope)
            self.assertEqual(title.styleSheet(), t('home_title'))
            self.assertIn(f'color: {self.manager.colors.text_primary};', title.styleSheet())
            self.assertIn('background-color: transparent;', title.styleSheet())
            self.assertNotIn('color: white', title.styleSheet())

    def test_collapsible_keyboard_focus_is_visible_even_when_checked(self):
        section = IOSCollapsibleSection('Advanced', expanded=True)
        self.addCleanup(section.deleteLater)
        section.header.setFocusPolicy(Qt.StrongFocus)
        section.show()
        section.activateWindow()
        section._retheme()
        section.header.setFocus(Qt.TabFocusReason)
        APP.processEvents()
        self.assertTrue(section.header.hasFocus())
        self.assertTrue(section.header.isChecked())
        # Qt resolves pseudo-state colors while painting; palette() alone
        # can still expose the non-focus color on a styled QPushButton.
        image = section.header.grab().toImage()
        accent = QColor(self.manager.colors.accent)
        self.assertTrue(any(image.pixelColor(x, y) == accent
                            for x in range(image.width())
                            for y in range(image.height())))


if __name__ == '__main__':
    unittest.main()
