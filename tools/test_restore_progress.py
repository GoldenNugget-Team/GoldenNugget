"""Offline checks for stable progress and explicit operation stages."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from src.devicemanagement.device_manager import DeviceManager
from src.devicemanagement.progress_status import BackupStatus
from src.gui.ios.restore_progress import RestoreProgressCard


class HideSpy(QObject):
    def __init__(self):
        super().__init__()
        self.hides = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Hide:
            self.hides += 1
        return False


class RestoreProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.card = RestoreProgressCard()
        self.card.start(True)
        self.card.show()
        self.app.processEvents()
        self.addCleanup(self.card.close)

    def test_text_updates_keep_last_percentage_without_hiding(self):
        spy = HideSpy()
        self.card.bar.installEventFilter(spy)
        self.card.set_stage('backup', 'photos')
        self.card.set_status('Photos and videos… (23%)')
        for text in ('Messages…', 'Waiting for your iPhone…', 'Settings…', 'Checking backup…'):
            self.card.set_status(text)
            self.app.processEvents()
            self.assertTrue(self.card.bar.isVisible())
            self.assertEqual(self.card.bar.value(), 23)
            self.assertEqual(self.card.value.text(), '23%')
        self.assertEqual(spy.hides, 0)

    def test_percentage_does_not_invent_a_stage_transition(self):
        self.card.set_stage('backup', 'keychain')
        self.card.set_status('Keychain… (99%)')
        self.assertEqual(self.card._stage, 'backup')
        self.assertNotIn('backup', self.card._completed)
        self.card.set_stage('restore')
        self.assertIn('backup', self.card._completed)
        self.assertNotIn('tweaks', self.card._completed)
        self.assertTrue(self.card._steps['tweaks'][0].isHidden())
        self.assertEqual(self.card._steps['restore'][2].text(), 'Restore data & changes')

    def test_awaiting_percentage_stays_visible_and_new_run_resets(self):
        self.card.set_status('Waiting for passcode entry…')
        self.assertTrue(self.card.bar.isVisible())
        self.assertEqual(self.card.bar.maximum(), 0)
        self.card.set_status('Restoring… (80%)\nTime Left: 20 sec')
        self.assertEqual(self.card.eta.text(), 'Time Left: 20 sec')
        self.card.start(False)
        self.assertEqual(self.card.bar.maximum(), 0)
        self.assertEqual(set(self.card._steps), {'tweaks'})
        self.assertFalse(self.card._completed)
        self.assertEqual(self.card.eta.text(), '')

    def test_backup_category_reports_a_separate_stage_event(self):
        manager = DeviceManager.__new__(DeviceManager)
        manager.operation_stage_callback = Mock()
        update = Mock()
        callback = manager._backup_progress(update)
        callback(BackupStatus('Photos and videos…', 'photos'))
        manager.operation_stage_callback.assert_called_once_with('backup', 'photos')
        callback(12.4)
        self.assertIn('(12%)', update.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
