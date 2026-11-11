"""Run bounded local archive work without blocking the Qt event loop."""
import weakref
from concurrent.futures import CancelledError
from concurrent.futures.thread import ThreadPoolExecutor
from threading import BoundedSemaphore, Event

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from src.gui.theme import ColorThemeManager, t
from src.utils.cancellation import CancellationToken, JobCancelled, run_cancellable

_job_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="local-files")
_job_slots = BoundedSemaphore(64)


class _FileThread(QObject):
    """Legacy worker interface backed by a bounded pool instead of one QThread/job."""
    finished = Signal()

    def __init__(self, callback, parent):
        super().__init__(parent)
        self.callback, self.result, self.error = callback, None, None
        self.token, self.future = CancellationToken(), None
        self._done_ready = Event()

    def start(self):
        if not _job_slots.acquire(blocking=False):
            self.error = RuntimeError("Too many pending local file operations")
            QTimer.singleShot(0, self.finished.emit)
            return
        try:
            self.future = _job_pool.submit(self._run)
        except Exception:
            _job_slots.release()
            raise
        self.future.add_done_callback(self._done)

    def _run(self):
        try:
            self.result = run_cancellable(self.callback, self.token)
        except Exception as exc:
            self.error = exc

    def _done(self, future):
        if future.cancelled():
            self.error = JobCancelled("Local background operation cancelled")
        _job_slots.release()
        # done callbacks can run synchronously when a pending job is cancelled.
        # Always queue delivery onto the QObject's thread.
        from PySide6.QtCore import QMetaObject, Qt
        try:
            QMetaObject.invokeMethod(self, "_deliver_finished", Qt.ConnectionType.QueuedConnection)
        finally:
            self._done_ready.set()

    @Slot()
    def _deliver_finished(self):
        self.finished.emit()

    def wait(self):
        if self.future is not None:
            try:
                self.future.result()
            except CancelledError:
                pass
            self._done_ready.wait()

    def isRunning(self):
        return self.future is not None and not self.future.done()

    def cancel(self):
        self.token.cancel()
        if self.future is not None:
            self.future.cancel()


class _FileTaskDialog(QDialog):
    def __init__(self, parent, title, callback):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title, self))
        bar = QProgressBar(self)
        bar.setRange(0, 0)
        layout.addWidget(bar)
        self.worker = _FileThread(callback, self)
        self.worker.finished.connect(self.accept)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _retheme(self):
        self.setStyleSheet(t('confirm_dialog'))

    def reject(self):
        if not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)


def run_file_task(parent, title, callback):
    dialog = _FileTaskDialog(parent, title, callback)
    dialog.worker.start()
    dialog.exec()
    dialog.worker.wait()
    result, error = dialog.worker.result, dialog.worker.error
    dialog.deleteLater()
    if error is not None:
        raise error
    return result


_background_tasks = set()


def _drain_background_tasks():
    for task in list(_background_tasks):
        if not task.must_finish:
            task.cancel()
        task.worker.wait()
        _background_tasks.discard(task)
        task.deleteLater()


class _BackgroundTask(QObject):
    def __init__(self, owner, callback, completed, failed, must_finish=False):
        super().__init__()
        self.must_finish = must_finish
        self.cancelled = False
        self.owner = weakref.ref(owner)
        self.completed, self.failed = completed, failed
        self.worker = _FileThread(callback, self)
        self.worker.finished.connect(self._finish)

    def cancel(self):
        if not self.must_finish:
            self.cancelled = True
            self.worker.cancel()

    @Slot()
    def _finish(self):
        from shiboken6 import isValid
        try:
            owner = self.owner()
            if not self.cancelled and owner is not None and isValid(owner):
                if self.worker.error is None:
                    self.completed(self.worker.result)
                elif self.failed is not None:
                    self.failed(self.worker.error)
        finally:
            _background_tasks.discard(self)
            self.deleteLater()


def start_file_task(owner, callback, completed, failed=None, *, must_finish=False):
    """Keep a worker alive even if its dialog closes; deliver only to a live UI."""
    app = QCoreApplication.instance()
    if app is not None and not app.property("fileTasksShutdownConnected"):
        app.setProperty("fileTasksShutdownConnected", True)
        app.aboutToQuit.connect(_drain_background_tasks)
    task = _BackgroundTask(owner, callback, completed, failed, must_finish)
    _background_tasks.add(task)
    task.worker.start()
    return task
