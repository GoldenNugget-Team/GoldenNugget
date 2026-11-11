"""Mandatory HotLoad updates cannot be dismissed or bypassed by downloading."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from src.controllers.hotload import HotLoad
from src.gui.dialogs.update_dialog import UpdateDialog
from src.gui.startup_services import StartupServices


class BadNewsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch.object(HotLoad, '_load_local'):
            self.hotload = HotLoad()
        self.rule = {'action': 'badNews', 'max_app_version': '9.7.1',
                     'reason': 'A required fix is available.'}
        self.hotload._rules = {'rules': [self.rule]}

    def test_app_scope_excludes_updated_build(self):
        self.assertIs(self.hotload.bad_news_rule(app_version='9.7.1'), self.rule)
        self.assertIsNone(self.hotload.bad_news_rule(app_version='9.7.2'))

    def test_device_scope_and_inactive_rule(self):
        self.rule.update(min_version='27.0', only_models=['iPhone16'])
        self.assertIsNone(self.hotload.bad_news_rule(app_version='9.7.1'))
        self.assertIsNone(self.hotload.bad_news_rule('26.2', 'iPhone16,1', '9.7.1'))
        self.assertIsNone(self.hotload.bad_news_rule('27.0', 'iPad16,1', '9.7.1'))
        self.assertIs(self.hotload.bad_news_rule('27.0', 'iPhone16,1', '9.7.1'), self.rule)
        self.rule['disabled'] = False
        self.assertIsNone(self.hotload.bad_news_rule('27.0', 'iPhone16,1', '9.7.1'))

    def test_hotload_switch_disables_requirement(self):
        with patch.object(self.hotload, 'is_enabled', return_value=False):
            self.assertIsNone(self.hotload.bad_news_rule(app_version='9.7.1'))

    def test_update_rule_does_not_block_individual_tweak(self):
        self.rule['tweak'] = 'Daemons'
        self.assertIsNone(self.hotload.rule_for('Daemons', app_version='9.7.1'))

    def test_required_dialog_blocks_every_dismissal_path(self):
        dialog = UpdateDialog(required=True, rule=self.rule)
        try:
            dialog.show()
            self.app.processEvents()
            self.assertEqual(dialog.windowModality(), Qt.ApplicationModal)
            self.assertTrue(dialog.cancel_btn.isHidden())
            QTest.keyClick(dialog, Qt.Key_Escape)
            dialog.reject()
            dialog.done(QDialog.Accepted)
            dialog.close()
            self.assertTrue(dialog.isVisible())
            with patch('src.gui.dialogs.update_dialog.QDesktopServices.openUrl', return_value=True) as download:
                dialog.accept()
            download.assert_called_once()
            self.assertTrue(dialog.isVisible())
        finally:
            dialog.destroy()

    def test_optional_update_still_dismisses(self):
        dialog = UpdateDialog()
        dialog.show()
        dialog.reject()
        self.assertFalse(dialog.isVisible())
        dialog.deleteLater()

    def test_cached_and_fresh_rules_show_one_dialog(self):
        self.rule.pop('max_app_version')
        window = QWidget()
        manager = SimpleNamespace(get_current_device_version=lambda: '',
                                  get_current_device_model=lambda: '')
        services = StartupServices(self.app, window, manager, self.hotload,
                                   Mock(), lambda *_: None, Mock())
        try:
            with patch('src.gui.startup_services.Thread'):
                services.start()
            dialog = services._required_update_dialog
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.isVisible())
            services._apply_rules(True)
            services._check_kill()
            self.assertIs(services._required_update_dialog, dialog)
        finally:
            services.timer.stop()
            if services._required_update_dialog:
                services._required_update_dialog.destroy()
            services.deleteLater()
            window.destroy()

    def test_fetched_rule_triggers_dialog_without_release_check(self):
        self.rule.pop('max_app_version')
        window = QWidget()
        manager = SimpleNamespace(get_current_device_version=lambda: '',
                                  get_current_device_model=lambda: '')
        services = StartupServices(self.app, window, manager, self.hotload,
                                   Mock(), lambda *_: None, Mock())
        try:
            services._apply_rules(True)
            self.assertTrue(services._required_update_dialog.isVisible())
        finally:
            if services._required_update_dialog:
                services._required_update_dialog.destroy()
            services.deleteLater()
            window.destroy()


if __name__ == '__main__':
    unittest.main()
