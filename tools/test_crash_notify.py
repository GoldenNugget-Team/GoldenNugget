"""Crash handler event routing: events for dead objects are dropped, errors in
our own event handlers still reach the crash dialog (no device)."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from src.exceptions import crash_handler

APP = QApplication.instance() or crash_handler.CrashHandlerApp([])
DEAD = 'Internal C++ object (PySide6.QtWidgets.QVBoxLayout) already deleted.'


class RaisingFilter(QObject):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.User:
            raise self.error
        return False


def frameless_error(message):
    """An exception whose traceback ends in the frame that caught it, like the
    one PySide raises before calling a Python event filter."""
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


class Notify(unittest.TestCase):
    def setUp(self):
        if not isinstance(APP, crash_handler.CrashHandlerApp):
            self.skipTest('another QApplication is already running')

    def send(self, error):
        target = QWidget()
        event_filter = RaisingFilter(error)
        APP.installEventFilter(event_filter)
        try:
            with patch.object(crash_handler, '_handle_crash') as handle:
                APP.notify(target, QEvent(QEvent.Type.User))
        finally:
            APP.removeEventFilter(event_filter)
        return handle

    def test_errors_inside_handlers_reach_the_crash_dialog(self):
        self.assertTrue(self.send(RuntimeError('boom')).called)
        self.assertTrue(self.send(RuntimeError(DEAD)).called)
        self.assertTrue(self.send(ValueError('boom')).called)

    def test_dead_object_error_before_any_handler_is_dropped(self):
        _, value, tb = frameless_error(DEAD)
        self.assertTrue(crash_handler._is_dead_object_event(value, tb))
        _, value, tb = frameless_error('boom')
        self.assertFalse(crash_handler._is_dead_object_event(value, tb))


if __name__ == '__main__':
    unittest.main()
