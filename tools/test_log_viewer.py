#!/usr/bin/env python3
"""Offline test for the session-log viewer (no device needed).

The viewer tails a file that is being written concurrently, so the risky
parts are all in the offset bookkeeping:

* a byte offset must stay a byte offset. Decoding with
  ``errors="replace"`` turns one bad byte into a 3-byte U+FFFD, so an
  offset measured on the decoded text drifts and real records get re-read
  or skipped;
* a half-written last record must be left for the next tick, never shown
  and never consumed;
* the rotating handler renames the file aside and starts a new one at the
  SAME path, so a shrinking size has to reset the buffer instead of
  rendering nothing.

Plus the filtering behaviour: a level floor and a search needle, and the
rule that a multi-line payload (progress records embed newlines) stays
attached to the record it belongs to.

Run: python tools/test_log_viewer.py
"""
import logging
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

from src.controllers import nugget_logger
from src.gui.dialogs import log_viewer
from src.gui.dialogs.log_viewer import (
    LogViewerDialog, filter_lines, record_rank, TAIL_BYTES,
)

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def rec(level, msg, line=1):
    """One line in the exact shape ``nugget_logger._make_formatter`` writes."""
    return (f"2026-10-05 12:00:{line:02d} | {level:<8} | MainThread     | "
            f"GoldenNugget.test:{line} | {msg}")


def append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def open_viewer(path):
    """A real dialog reading *path* instead of the live session log."""
    log_viewer.get_log_path = lambda: path
    dlg = LogViewerDialog()
    # the poll timer is irrelevant here and would only race the assertions
    dlg._timer.stop()
    return dlg


def main():
    QApplication.instance() or QApplication([])

    # ---- the level parser matches the real formatter ------------------------
    sample = nugget_logger._make_formatter().format(
        logging.LogRecord("GoldenNugget.restore", logging.ERROR,
                          "p", 12, "restore failed", None, None))
    check("the level parses out of the real formatter's own output",
          record_rank(sample) == 40, sample.split(" | ")[1].strip())
    check("a DEBUG record parses", record_rank(rec("DEBUG", "x")) == 10)
    check("a WARNING record parses", record_rank(rec("WARNING", "x")) == 30)
    check("a continuation line carries no level",
          record_rank("    DO NOT unplug the device") == 0)
    check("an unrelated line carries no level",
          record_rank("Traceback (most recent call last):") == 0)

    # ---- filtering ---------------------------------------------------------
    lines = [rec("DEBUG", "noise", 1), rec("INFO", "hello", 2),
             rec("WARNING", "careful", 3), rec("ERROR", "broken", 4)]
    check("min_rank 0 keeps everything", len(filter_lines(lines, 0, "")) == 4)
    check("a WARNING floor drops info and debug",
          filter_lines(lines, 30, "") == [lines[2], lines[3]])
    check("an ERROR floor keeps only the error",
          filter_lines(lines, 40, "") == [lines[3]])
    check("search is a case-insensitive substring",
          filter_lines(lines, 0, "BROKEN") == [lines[3]])
    check("search combines with the level floor",
          filter_lines(lines, 30, "careful") == [lines[2]])
    check("a search with no match returns nothing",
          filter_lines(lines, 0, "zzz-nope") == [])

    # a multi-line payload must survive an ERROR filter: the user asked to see
    # the error, and the traceback under it is why they did
    payload = [rec("ERROR", "restore failed", 9),
               '  File "restore.py", line 12, in run',
               "RuntimeError: device locked"]
    check("a payload stays attached to its record under a level floor",
          filter_lines(payload, 40, "") == payload)
    check("a payload is dropped together with the record it belongs to",
          filter_lines([lines[0], "    pm3 chatter"], 20, "") == [],
          "DEBUG record + its continuation are both below an INFO floor")

    # ---- tailing -----------------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="gn_logviewer_")
    path = os.path.join(tmp, "nugget_test.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(rec("INFO", "first", 1) + "\n")

    dlg = open_viewer(path)
    check("the first read shows the record", "first" in dlg._view.toPlainText())
    check("the offset lands on the real file size",
          dlg._offset == os.path.getsize(path))

    # a half-written last line must NOT be consumed
    append(path, rec("INFO", "half", 2))          # no trailing newline
    before = dlg._offset
    dlg._tick()
    check("a half-written record is not consumed",
          dlg._offset == before, f"offset {before} -> {dlg._offset}")
    check("a half-written record is not shown either",
          "half" not in dlg._view.toPlainText())
    append(path, "\n")
    dlg._tick()
    check("it appears once the newline lands", "half" in dlg._view.toPlainText())

    # --- an invalid utf-8 byte must not desync the offset ---
    # one bad byte -> one U+FFFD, which is 3 bytes when re-encoded. If the
    # offset were measured on the decoded text it would run 2 bytes ahead and
    # slice the next record in half, for good.
    append(path, rec("INFO", "before-bad", 3) + "\n")
    with open(path, "ab") as f:
        f.write(b"2026-10-05 12:00:04 | INFO      | MainThread     | "
                b"GoldenNugget.test:4 | bad \xff byte\n")
    append(path, rec("INFO", "after-bad", 5) + "\n")
    dlg._tick()
    body = dlg._view.toPlainText()
    check("both records around a bad byte are present",
          "before-bad" in body and "after-bad" in body)
    check("a bad byte is replaced, not fatal", "bad" in body)
    check("the offset still matches the real file size",
          dlg._offset == os.path.getsize(path),
          f"{dlg._offset} vs {os.path.getsize(path)}")

    # appending again must not duplicate or skip
    append(path, rec("INFO", "next", 6) + "\n")
    dlg._tick()
    check("the next record is read exactly once",
          dlg._view.toPlainText().count("next") == 1)

    # --- rotation: the handler restarts the SAME path, so the size drops -----
    with open(path, "w", encoding="utf-8") as f:
        f.write(rec("INFO", "after-rotation", 1) + "\n")
    dlg._tick()
    check("a shrinking file is treated as a rotation",
          "after-rotation" in dlg._view.toPlainText())
    check("the rotated buffer holds no stale records",
          "before-bad" not in dlg._buffer)

    # --- the view keeps its place when the user scrolled up -----------------
    # needs a viewport that actually overflows: with a handful of lines the
    # whole document fits and the scrollbar has no range to preserve
    scroll_path = os.path.join(tmp, "scroll.log")
    with open(scroll_path, "w", encoding="utf-8") as f:
        for i in range(300):
            f.write(rec("INFO", f"row-{i}", i % 60) + "\n")
    s = open_viewer(scroll_path)
    s._view.resize(500, 100)
    bar = s._view.verticalScrollBar()
    check("the document really overflows the viewport",
          bar.maximum() > 0, f"maximum={bar.maximum()}")

    bar.setValue(bar.maximum())
    s._tick()
    check("Live mode stays parked at the bottom",
          bar.value() == bar.maximum(), f"{bar.value()} / {bar.maximum()}")

    bar.setValue(0)
    append(scroll_path, rec("INFO", "appended-line", 7) + "\n")
    s._tick()
    check("scrolling up is not yanked back to the bottom",
          bar.value() == 0, f"value={bar.value()}")
    check("but the new line is still there",
          "appended-line" in s._view.toPlainText())

    # --- filters act on the live buffer ------------------------------------
    s._search.setText("appended-line")
    check("typing in the search filters the view",
          "row-0 " not in s._view.toPlainText()
          and "appended-line" in s._view.toPlainText())
    s._search.clear()
    s._level_combo.setCurrentIndex(3)          # ERROR floor
    check("the level combo filters the view",
          "row-299" not in s._view.toPlainText())
    s._level_combo.setCurrentIndex(0)
    check("clearing the filters brings everything back",
          "row-299" in s._view.toPlainText())

    # --- truncation keeps only the newest TAIL_BYTES ------------------------
    big = os.path.join(tmp, "big.log")
    with open(big, "w", encoding="utf-8") as f:
        for i in range(40000):
            f.write(rec("INFO", f"line-{i}", i % 60) + "\n")
    d = open_viewer(big)
    check("a huge log is capped, not loaded whole",
          len(d._buffer) <= TAIL_BYTES, f"{len(d._buffer)} chars")
    check("the newest line of a huge log is still there",
          "line-39999" in d._view.toPlainText())

    # --- a missing file must not raise --------------------------------------
    d = open_viewer(os.path.join(tmp, "does-not-exist.log"))
    check("a missing log file is handled quietly", d._view.toPlainText() == "")

    # --- the log view must be fixed pitch -----------------------------------
    # QFont.fixedPitch() reads False for EVERY family in this Qt build (even
    # Consolas), so the check has to go through the font database, which is
    # also what _monospace_font() selects on.
    from PySide6.QtGui import QFontDatabase
    family = d._view.font().family()
    fixed = [f for f in QFontDatabase.families()
             if QFontDatabase.isFixedPitch(f)]
    if fixed:
        # a real desktop font database: the view must be on one of them
        check("the log view is rendered in a fixed-pitch font",
              QFontDatabase.isFixedPitch(family),
              f"{family!r} (installed fixed: {fixed[:3]})")
    else:
        # the offscreen/minimal platform ships no real fonts at all, only
        # generic aliases - nothing to assert beyond "a font was chosen"
        check("a font was still chosen for the log view", bool(family),
              f"{family!r} (no fixed-pitch family on this platform)")

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()