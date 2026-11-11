from time import perf_counter

from PySide6.QtCore import QObject, QTimer


class IncrementalBuilder(QObject):
    def __init__(self, parent, on_error=None):
        super().__init__(parent)
        self._steps = None
        self._on_error = on_error
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    def start(self, steps):
        self.cancel()
        self._steps = iter(steps)
        self._timer.start(0)

    def cancel(self):
        self._timer.stop()
        if self._steps is not None:
            self._steps.close()
            self._steps = None

    def _on_step_error(self):
        self.cancel()
        if self._on_error is not None:
            self._on_error()

    def finish(self):
        self._timer.stop()
        try:
            while self._steps is not None:
                next(self._steps)
        except StopIteration:
            self._steps = None
        except Exception:
            self._on_step_error()
            raise

    def _advance(self):
        deadline = perf_counter() + 0.004
        try:
            while self._steps is not None and perf_counter() < deadline:
                next(self._steps)
        except StopIteration:
            self._steps = None
        except Exception:
            self._on_step_error()
            raise
        if self._steps is not None:
            self._timer.start(1)
