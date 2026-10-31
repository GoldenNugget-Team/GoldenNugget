"""Keep Python's cyclic GC off the worker threads that drive the device.

Qt objects are not thread-safe: a ``QWidget``/``QDialog`` may only be destroyed
on the GUI thread. Python's *refcounting* already respects that in practice (a
widget's last reference is normally dropped by a main-thread slot), but the
*cyclic* collector runs on whichever thread happens to trip its threshold, and
widget wrappers land in cycles constantly — every
``button.clicked.connect(lambda: self.something())`` or
``signal.connect(self.slot)`` is one. An apply runs for minutes on
``ApplyThread``, so that worker is very often the thread that ends up collecting
the wrapper of a dialog the user closed earlier.

Shiboken then runs ``~QDialog`` / ``~QWidget`` on the worker thread: it deletes
the children and delivers their events while the main thread may still be
dispatching for the same widgets. That is the
``PySide::getWrapperForQObject`` SIGSEGV seen from applies, with the crashing
main thread inside ``QApplicationWrapper::notify``.

:func:`worker_gc_guard` turns the cyclic collector off for the duration of the
worker's ``run()`` and schedules a collection on the GUI thread afterwards, so
the cycles are still reclaimed — just from the thread that is allowed to destroy
widgets.
"""

import gc
from contextlib import contextmanager

from PySide6.QtCore import QCoreApplication, QTimer


@contextmanager
def worker_gc_guard():
    """Disable cyclic GC while a device worker runs; collect on the GUI thread.

    Refcounting stays active, so memory is still freed as usual; only the
    collection of *cycles* is deferred to the GUI thread.
    """
    was_enabled = gc.isenabled()
    if was_enabled:
        gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()
            # Queue the collection on the GUI thread. Without an application
            # (tests, CLI, shutdown) there is no GUI thread to race with, so
            # collect right here instead of arming a timer that never fires.
            if QCoreApplication.instance() is not None:
                QTimer.singleShot(0, gc.collect)
            else:
                gc.collect()
