"""Live viewer for the GoldenNugget session log.

Backed by the single rotating session file that
``src/controllers/nugget_logger.py`` owns, so this is the same text a bug
report gets. Two things make it useful while an apply is running:

* it **tails**: a QTimer polls file identity and size every second and only
  changes the view when the text changed, and the scroll position is
  preserved unless the user is already parked at the bottom (then it sticks
  there, like a terminal);
* it **filters**: a level floor (All / Info / Warning / Error) plus a
  free-text search, both applied on the raw lines, so the noisy
  ``pymobiledevice3`` chatter can be dropped out of a restore session.

The file is read with explicit binary offsets and decoded with
``errors="replace"``: a log is written concurrently, so the last line can
be half-written, and a stray byte must never take the dialog down. The
record format comes from ``nugget_logger._make_formatter``
(``asctime | LEVELNAME | thread | name:lineno | message``); the level is
parsed back out of it, so rotated files and hand-edited ones still filter.

Only the newest ``TAIL_BYTES`` are held, which keeps a multi-megabyte
verbose session cheap to re-render every second.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from awesomeui.controls import _auto_retheme
from awesomeui.liquid.choice_editor import GlassComboBox as QComboBox
from awesomeui.liquid.controls import LiquidSwitch
from src.controllers.nugget_logger import get_log_path
from src.gui.theme import t
from src.gui.widgets import IOSSearchField

# Newest slice of the log that is ever held in memory. The rotating handler
# writes up to 16 MiB per file, and the interesting part of a long session
# (the failure and everything leading up to it) is always at the end.
TAIL_BYTES = 1024 * 1024
# Hard cap on rendered lines, so a pathological single-line record cannot
# make setPlainText() crawl.
MAX_LINES = 20000

# Level name -> numeric rank, matching logging's own levels. Only the four
# levels the app actually emits are listed; anything else ranks as INFO.
_LEVEL_RANKS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "WARN": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}

# (label, minimum rank) - "All" is the default so the first open shows
# everything rather than hiding the context around an error.
#
# The labels live in a tuple, so lupdate cannot see a literal at the call
# site either. Declaring them through QT_TRANSLATE_NOOP puts them in the
# catalog for translators while the rendered text still goes through
# translate() at the call site below.
_LEVEL_CHOICES = (
    (QT_TRANSLATE_NOOP("Nugget", "All"), 0),
    (QT_TRANSLATE_NOOP("Nugget", "Info"), 20),
    (QT_TRANSLATE_NOOP("Nugget", "Warning"), 30),
    (QT_TRANSLATE_NOOP("Nugget", "Error"), 40),
)


def _monospace_font() -> QFont:
    """A fixed-pitch font for the log view.

    ``QFontDatabase.systemFont(FixedFont)`` is the obvious call but it is not
    trustworthy on Windows: it reports a family (Courier New) whose font file
    may not be resolvable, and ``fixedPitch()`` then reads False — the columns
    silently stop lining up. So the installed families are asked directly and
    the platform hint is only the fallback.
    """
    for family in QFontDatabase.families():
        if QFontDatabase.isFixedPitch(family):
            return QFont(family)
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def record_rank(line: str) -> int:
    """Rank of a formatted log line (0 when it is not a record).

    ``%(asctime)s | %(levelname)s | ...`` puts the level in field 2. A
    message that embeds newlines (progress payloads do) produces trailing
    lines with no level; those are reported as 0 so a level floor keeps
    them together with the record they belong to instead of dropping the
    payload of an error the user wanted to read.
    """
    parts = line.split(" | ", 2)
    if len(parts) < 2:
        return 0
    return _LEVEL_RANKS.get(parts[1].strip().upper(), 0)


def filter_lines(lines: list[str], min_rank: int, needle: str) -> list[str]:
    """Apply the level floor and the search needle to ``lines``.

    ``needle`` is a plain case-insensitive substring, not a regex: it is
    typed by hand into a live UI, and a malformed pattern must not raise.
    It is lowercased here so the caller cannot get the case handling wrong.
    """
    needle = needle.strip().lower()
    if min_rank <= 0 and not needle:
        return lines
    out = []
    keep_previous = min_rank <= 0
    for line in lines:
        rank = record_rank(line)
        if rank:
            keep_previous = rank >= min_rank
        # else: a continuation line of the previous record, which keeps that
        # record's verdict - the payload of an error the user asked for must
        # not be filtered away from under it
        if not keep_previous:
            continue
        if needle and needle not in line.lower():
            continue
        out.append(line)
    return out


class LogViewerDialog(QDialog):
    """Modal viewer for the session log, with a level filter and search."""

    REFRESH_MS = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Application Log"))
        self.setModal(True)
        self.resize(900, 620)
        self.setMinimumSize(520, 360)

        self._path = get_log_path()
        self._offset = 0
        self._buffer = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel(QCoreApplication.translate("Nugget", "Application Log"), self)
        title.setObjectName("logViewerTitle")
        layout.addWidget(title)

        path_lbl = QLabel(self._path, self)
        path_lbl.setObjectName("logViewerPath")
        # selectable so the path can be copied straight into a bug report
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_lbl.setWordWrap(True)
        layout.addWidget(path_lbl)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self._search = IOSSearchField(self)
        self._search.setPlaceholderText(QCoreApplication.translate("Nugget", "Search log..."))
        self._search.textChanged.connect(self._reapply)
        filters.addWidget(self._search, 1)

        self._level_combo = QComboBox(self)
        for label, rank in _LEVEL_CHOICES:
            self._level_combo.addItem(
                QCoreApplication.translate("Nugget", label), rank)
        self._level_combo.setCurrentIndex(0)
        self._level_combo.currentIndexChanged.connect(self._reapply)
        filters.addWidget(self._level_combo)

        self._follow = LiquidSwitch(True, self)
        self._follow.setToolTip(
            QCoreApplication.translate("Nugget", "Keep scrolling to the newest lines as they are written"))
        self._follow.toggled.connect(self._on_follow_toggled)
        follow_box = QHBoxLayout()
        follow_box.setContentsMargins(4, 0, 0, 0)
        follow_box.setSpacing(6)
        follow_lbl = QLabel(QCoreApplication.translate("Nugget", "Live"), self)
        follow_box.addWidget(follow_lbl)
        follow_box.addWidget(self._follow)
        filters.addLayout(follow_box)

        layout.addLayout(filters)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._view.setPlaceholderText(QCoreApplication.translate("Nugget", "No log output yet."))
        # fixed pitch so the pipe-separated columns line up; set here instead
        # of in the stylesheet because styles.py names no font family
        self._view.setFont(_monospace_font())
        layout.addWidget(self._view, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("logViewerStatus")
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        refresh_btn = QPushButton(QCoreApplication.translate("Nugget", "Reload"), self)
        refresh_btn.setToolTip(QCoreApplication.translate("Nugget", "Re-read the log from the beginning"))
        refresh_btn.clicked.connect(self._reload)
        buttons.addWidget(refresh_btn)

        open_btn = QPushButton(QCoreApplication.translate("Nugget", "Open File"), self)
        open_btn.setToolTip(QCoreApplication.translate("Nugget", "Open the log in your default text editor"))
        open_btn.clicked.connect(self._open_file)
        buttons.addWidget(open_btn)

        folder_btn = QPushButton(QCoreApplication.translate("Nugget", "Open Folder"), self)
        folder_btn.setToolTip(QCoreApplication.translate("Nugget", "Open the folder holding the log"))
        folder_btn.clicked.connect(self._open_folder)
        buttons.addWidget(folder_btn)

        copy_btn = QPushButton(QCoreApplication.translate("Nugget", "Copy Visible"), self)
        copy_btn.setToolTip(QCoreApplication.translate("Nugget", "Copy the lines currently shown to the clipboard"))
        copy_btn.clicked.connect(self._copy_visible)
        buttons.addWidget(copy_btn)

        diagnostics_btn = QPushButton(QCoreApplication.translate('Nugget', 'Export Diagnostics'), self)
        diagnostics_btn.clicked.connect(self._export_diagnostics)
        buttons.addWidget(diagnostics_btn)

        buttons.addStretch(1)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"), self)
        close_btn.setObjectName("logViewerPrimary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)

        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._retheme()
        _auto_retheme(self)
        self.reload()

    # ---- data ------------------------------------------------------------

    def _export_diagnostics(self):
        from src.controllers.settings import Settings
        from src.gui.dialogs.diagnostics import DiagnosticsDialog
        owner = self.parentWidget()
        while owner is not None and not hasattr(owner, 'device_manager'):
            owner = owner.parentWidget()
        manager = getattr(owner, 'device_manager', None)
        settings = getattr(owner, 'settings', None) or Settings('settings')
        DiagnosticsDialog(settings, manager, parent=self).exec()

    def reload(self):
        """Discard the cached buffer and render from scratch."""
        from src.utils.log_tail import LogTailReader
        self._tail_reader = LogTailReader(self._path, TAIL_BYTES)
        self._last_buffer = None
        self._tick()

    def _tick(self):
        """Poll the Qt-free tail; render only after the buffer changes."""
        from src.utils.log_tail import LogTailReader
        reader = getattr(self, "_tail_reader", None)
        if reader is None:
            reader = self._tail_reader = LogTailReader(self._path, TAIL_BYTES)
        snapshot = reader.poll()
        self._buffer, self._offset = snapshot.text, snapshot.offset
        if not snapshot.available:
            self._last_buffer = None
            self._render([])
            self._update_status(0)
            return
        if getattr(self, "_last_buffer", None) == self._buffer:
            self._update_status(getattr(self, "_last_shown", 0))
            return
        self._last_buffer = self._buffer
        self._render(self._buffer.splitlines()[-MAX_LINES:])

    def _render(self, lines: list[str]):
        shown = filter_lines(
            lines, self._level_combo.currentData() or 0,
            self._search.text())
        text = "\n".join(shown)
        old_text = getattr(self, "_rendered_text", None)
        self._last_shown = len(shown)
        self._buffer_line_count = len(lines)
        if text == old_text:
            self._update_status(len(shown))
            return

        bar = self._view.verticalScrollBar()
        # Sticking to the bottom is the terminal behaviour and is what the
        # "Live" switch promises; anyone who scrolled up keeps their place.
        at_bottom = bar.value() >= bar.maximum() - 2
        if old_text and text.startswith(old_text + "\n"):
            self._view.appendPlainText(text[len(old_text) + 1:])
        else:
            self._view.setPlainText(text)
        self._rendered_text = text
        if at_bottom:
            bar.setValue(bar.maximum())
        self._update_status(len(shown))

    def _reapply(self):
        """Level/search changed: re-filter what is already buffered."""
        self._render(self._buffer.splitlines())

    def _update_status(self, shown: int):
        try:
            size = os.path.getsize(self._path)
        except OSError:
            size = 0
        if shown:
            status = QCoreApplication.translate("Nugget", "{0} of {1} lines  -  {2} KB on disk").format(
                f"{shown:,}", f"{getattr(self, '_buffer_line_count', 0):,}",
                f"{size // 1024:,}")
        else:
            status = QCoreApplication.translate("Nugget", "Empty log  -  {0} KB on disk").format(
                f"{size // 1024:,}")
        self._status.setText(status)

    # ---- actions ---------------------------------------------------------

    def _on_follow_toggled(self, checked: bool):
        # "Live" owns the poll: off means the view only changes when the user
        # asks for it, so a long session does not keep repainting.
        if not checked:
            self._timer.stop()
            return
        self._tick()
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._timer.start()

    def _reload(self):
        self.reload()

    def _copy_visible(self):
        from PySide6.QtWidgets import QApplication
        text = self._view.toPlainText()
        QApplication.clipboard().setText(text)
        self._status.setText(QCoreApplication.translate("Nugget", "Copied {0} lines to the clipboard").format(
            f"{len(text.splitlines()):,}"))

    def _open_file(self):
        if os.path.exists(self._path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        else:
            self._status.setText(QCoreApplication.translate("Nugget", "Log file not found yet."))

    def _open_folder(self):
        folder = os.path.dirname(self._path) or "."
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ---- lifecycle -------------------------------------------------------

    def _retheme(self):
        self.setStyleSheet(t("log_viewer"))

    def reject(self):
        self._timer.stop()
        super().reject()

    def accept(self):
        self._timer.stop()
        super().accept()
