#!/usr/bin/env python3
"""Live smoke test for the log viewer: real window, real session log, live writes.

The offline suite (tools/test_log_viewer.py) drives a bare dialog. This builds
the real IOSHomePage, clicks the actual header button, and then writes to the
real session log while the viewer's own 1 s timer is running - i.e. the exact
path a user hits while an apply is in progress.

The session log is redirected to a temp file through GOLDENNUGGET_LOG_FILE
(which get_log_path() honours) so the run exercises the real handler, the real
rotating file and the real poll without polluting the developer's real log in
AppData.

Run: python tools/test_log_viewer_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# must be set before anything imports nugget_logger / src.gui.logger, both of
# which create the session file handler at import time
_TMP_DIR = tempfile.mkdtemp(prefix="gn_logviewer_live_")
os.environ["GOLDENNUGGET_LOG_FILE"] = os.path.join(_TMP_DIR, "session.log")

import logging
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

from src.qt import resources_rc  # noqa: F401
from src.controllers.nugget_logger import init_logging, get_log_path
init_logging()
from src.gui.ios.home import IOSHomePage
from src.gui.dialogs import log_viewer as lv

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def pump(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeDM:
    devices = []
    pref_manager = None

    def get_current_device_udid(self):
        return None

    def get_current_device_is_supported_by_fork(self):
        return True

    def get_current_device_partially_supported(self):
        return False


class FakeWindow(QWidget):
    """A real QWidget: open_logs() passes the window in as the dialog parent,
    so a non-widget stand-in would not reproduce the production call."""

    def __init__(self):
        super().__init__()
        self.settings = None
        self.device_manager = FakeDM()

    def show_ios_page(self, i):
        pass

    def refresh_devices(self):
        pass


# capture the dialog the button creates instead of exec()ing it
created = []


class Spy(lv.LogViewerDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        created.append(self)

    def exec(self):
        return 1


lv.LogViewerDialog = Spy

page = IOSHomePage(FakeWindow())
page.resize(1200, 800)
page.show()
pump()

print("1) the button opens the viewer")
page._logs_btn.click()
pump()
check("the home header button created a viewer", len(created) == 1)
dlg = created[0]
check("it reads the session log", dlg._path == get_log_path(), dlg._path)
check("the session log was redirected out of AppData",
      _TMP_DIR in dlg._path, dlg._path)
check("its poll timer is running", dlg._timer.isActive())
check("the icon on the button rendered", not page._logs_btn.icon().isNull())
check("Live mode is on by default", dlg._follow.isChecked())

print("2) writes reach the view while the timer runs")
log = logging.getLogger("GoldenNugget.smoke")
before = len(dlg._view.toPlainText().splitlines())
for i in range(12):
    log.info("smoke record %02d — payload from a worker thread", i)
for h in list(log.handlers):
    h.flush()
pump(1400)                      # let at least one 1s tick fire
body = dlg._view.toPlainText()
after = len(body.splitlines())
check("new lines appeared without any manual refresh", after > before,
      f"{before} -> {after}")
check("the newest record is the last line",
      "smoke record 11" in body.splitlines()[-1])
check("the columns kept their order (timestamp | level | ...)",
      body.splitlines()[-1].split(" | ")[1].strip() == "INFO",
      body.splitlines()[-1].split(" | ")[1].strip())

print("3) filters apply to live content")
dlg._level_combo.setCurrentIndex(3)          # ERROR floor
pump(1200)
err = logging.getLogger("GoldenNugget.smoke")
err.error("smoke ERROR should be visible")
for h in list(err.handlers):
    h.flush()
pump(1400)
text = dlg._view.toPlainText()
check("the ERROR record is shown under the ERROR floor",
      "smoke ERROR should be visible" in text)
check("the INFO records are hidden under the ERROR floor",
      "smoke record 05" not in text)

dlg._level_combo.setCurrentIndex(0)
dlg._search.setText("smoke ERROR")
pump(120)
text = dlg._view.toPlainText()
check("search narrows the live view",
      "smoke ERROR" in text and "smoke record 05" not in text)
dlg._search.clear()
pump(120)

print("4) closing stops the poll")
dlg.accept()
check("the timer is stopped after close", not dlg._timer.isActive())

print(f"\nALL {PASS} CHECKS PASSED")
