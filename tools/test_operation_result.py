"""Completion reporting must not turn swallowed errors or cancellation into success."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from src.gui.ios.operation_result import OperationResultCard, result_text
from src.gui.theme import ColorThemeManager
from src.gui.thread_workers.apply_worker import ApplyThread


class OperationResultTests(unittest.TestCase):
    def test_worker_requires_explicit_success(self):
        manager = Mock()
        for completed, expected in ((True, True), (False, False), (None, False)):
            manager.apply_changes.return_value = completed
            worker = ApplyThread(manager, Mock())
            results = []
            worker.finished_with_result.connect(lambda success, error: results.append(success))
            with patch('src.controllers.apply_history.record_operation') as history, \
                 patch('src.controllers.nugget_logger.log_context'):
                worker.run()
            self.assertEqual(results, [expected])
            self.assertEqual(worker.success, expected)
            self.assertEqual(history.call_args.args[2], expected)

    def test_success_details_and_failure_do_not_claim_partial_success(self):
        preview = dict(entries={'one':dict(section='SpringBoard', title='Example')},
                       queued=[['PosterBoard', 'wallpaper']], blocked=['Blocked tweak'],
                       forced=['forced.service'], skipped_packages=['extra wallpaper'])
        text = result_text(True, '', preview=preview)
        for expected in ('Example', 'wallpaper', 'Skipped: 2', 'Blocked tweak', 'forced.service', 'Find My'):
            self.assertIn(expected, text)
        text = result_text(False, 'Connection lost', preview=preview)
        self.assertIn('Connection lost', text)
        self.assertIn('Completion was not confirmed', text)
        self.assertNotIn('completed apply', text)

    def test_result_persists_and_actions_work_after_retheme(self):
        app = QApplication.instance() or QApplication([])
        logs, dismiss = Mock(), Mock()
        card = OperationResultCard(logs, dismiss)
        card.show_result(False, 'Connection lost')
        app.processEvents()
        ColorThemeManager.instance().theme_changed.emit()
        self.assertTrue(card.isVisible())
        self.assertEqual(card.details.toPlainText(), 'Connection lost')
        card.logs_btn.click()
        card.close_btn.click()
        logs.assert_called_once()
        dismiss.assert_called_once()
        card.close()


if __name__ == '__main__':
    unittest.main()
