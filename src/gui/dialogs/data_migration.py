"""Installer-style window that moves the pre-rename data folder.

GoldenNugget used to keep its files in a ``GoldenNugget`` folder; they now
live in ``gnugget`` (see :mod:`src.utils.paths`). This window is the one-time
move, laid out like a disk-image installer: the app icon in black and white on
the left, a progress bar in the middle, the icon in colour on the right, and
the *Migrate* button underneath the bar.

The move itself is :mod:`src.utils.user_data_migration` (Qt-free); this module
only drives it and renders progress. Closing the window without migrating is
not destructive — the old folder is left exactly as it was, and Settings →
Backup can open the window again later.
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QCoreApplication, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

try:  # the artwork lives in the compiled resource bundle
    from src.qt import resources_rc  # noqa: F401
except Exception:  # pragma: no cover - icons are cosmetic
    resources_rc = None

from src.gui.theme import ColorThemeManager, t
from src.utils.user_data_migration import (
    MigrationPlan, MigrationResult, clear_declined, format_bytes, is_declined,
    mark_declined, plan_migration, run_migration,
)

ICON_PX = 104
DIALOG_WIDTH = 600


def _desaturated(path: str, size: int) -> QPixmap:
    """The artwork in black and white (luminosity and alpha kept)."""
    source = QPixmap(path)
    if source.isNull():
        return source
    image = source.toImage().scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    # Qt's composition modes have no HSL "saturation" mode, so mix the channels
    # by luma. The icon is ~100 px, which makes this loop irrelevant.
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() == 0:
                continue
            grey = int(round(0.299 * colour.red()
                             + 0.587 * colour.green()
                             + 0.114 * colour.blue()))
            colour.setRed(grey)
            colour.setGreen(grey)
            colour.setBlue(grey)
            image.setPixelColor(x, y, colour)
    return QPixmap.fromImage(image)


class _MigrationThread(QThread):
    """Runs the move off the GUI thread so the bar keeps painting."""

    # Byte counts cross a QMetaCallEvent as C++ ints when declared Signal(int):
    # a multi-gigabyte backup cache overflows 2**31 and PySide raises
    # OverflowError (with no traceback) during the delivery, surfacing through
    # sys.excepthook on the QThread as one crash report per progress tick. The
    # args ride as doubles instead, exact far beyond any byte count.
    progress = Signal(float, float, str)
    completed = Signal(object)

    def __init__(self, plan: MigrationPlan, parent=None):
        super().__init__(parent)
        self._plan = plan
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D102 - QThread entry point
        result = run_migration(
            self._plan,
            on_progress=lambda moved, total, label: self.progress.emit(
                float(moved), float(total), label),
            should_cancel=lambda: self._cancelled,
        )
        self.completed.emit(result)


class DataMigrationDialog(QDialog):
    """The one-time "move your data" installer window."""

    def __init__(self, plan: MigrationPlan, parent=None, auto_start=False):
        super().__init__(parent)
        self.plan = plan
        self.result_data: MigrationResult | None = None
        self._thread: _MigrationThread | None = None
        self._running = False

        self.setObjectName("dataMigration")
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Move User Data"))
        self.setModal(True)
        self.setFixedWidth(DIALOG_WIDTH)

        self._build()
        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

        if auto_start:
            self.start()

    # -- layout ------------------------------------------------------------ #

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(10)

        self._title = QLabel(QCoreApplication.translate("Nugget", "Move your data"), self)
        self._title.setObjectName("migrationTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._title)

        self._subtitle = QLabel(
            QCoreApplication.translate(
                "Nugget",
                "GoldenNugget keeps its files in a new folder. Move the "
                "existing ones to keep your presets, wallpapers and backups. "
                "You can also do this later in Settings > Backup."),
            self)
        self._subtitle.setObjectName("migrationSubtitle")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        root.addSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(18)
        row.setContentsMargins(0, 0, 0, 0)

        left = QLabel(self)
        left.setObjectName("migrationIcon")
        left.setPixmap(_desaturated(":/credits/big_nugget.png", ICON_PX))
        left.setFixedSize(ICON_PX, ICON_PX)
        left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(left)

        middle = QVBoxLayout()
        middle.setSpacing(10)

        self.progress = QProgressBar(self)
        self.progress.setObjectName("migrationProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        middle.addWidget(self.progress)

        self.button = QPushButton(QCoreApplication.translate("Nugget", "Migrate"), self)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setMinimumWidth(220)
        self.button.clicked.connect(self._on_button)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.button)
        button_row.addStretch(1)
        middle.addLayout(button_row)

        self.status = QLabel(self._summary_text(), self)
        self.status.setObjectName("migrationStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        middle.addWidget(self.status)

        row.addLayout(middle, 1)

        right = QLabel(self)
        right.setObjectName("migrationIcon")
        right.setPixmap(QPixmap(":/credits/big_nugget.png").scaled(
            ICON_PX, ICON_PX, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        right.setFixedSize(ICON_PX, ICON_PX)
        right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(right)

        root.addLayout(row)
        root.addStretch(1)

    def _retheme(self) -> None:
        self.setStyleSheet(t("migration_dialog"))
        self.button.setStyleSheet(t("migration_button"))

    # -- state ------------------------------------------------------------- #

    def _summary_text(self) -> str:
        count = len(self.plan.moves)
        size = format_bytes(self.plan.total_bytes)
        return QCoreApplication.translate("Nugget", "{0} · {1} item(s)").format(size, count)

    def _on_button(self) -> None:
        if self._running:
            return
        if self.result_data is not None:
            self.accept()
            return
        self.start()

    def start(self) -> None:
        if self._running or self.result_data is not None:
            return
        self._running = True
        self.button.setEnabled(False)
        self.button.setText(QCoreApplication.translate("Nugget", "Migrating…"))
        self.status.setText(QCoreApplication.translate("Nugget", "Moving your files…"))
        self._thread = _MigrationThread(self.plan, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.completed.connect(self._on_completed)
        self._thread.start()

    def _on_progress(self, moved: float, total: float, label: str) -> None:
        total = max(total, 1)
        self.progress.setValue(int(1000 * moved / total))
        self.status.setText(QCoreApplication.translate("Nugget", "Moving {0}…").format(label))

    def _on_completed(self, result: MigrationResult) -> None:
        self._running = False
        self.result_data = result
        self.progress.setValue(1000 if result.ok else self.progress.value())
        if result.errors:
            self.button.setEnabled(True)
            self.button.setText(QCoreApplication.translate("Nugget", "Retry"))
            self.status.setText(QCoreApplication.translate(
                "Nugget",
                "Some files could not be moved. They are still in the old "
                "folder."))
            return
        if result.cancelled:
            self.button.setEnabled(True)
            self.button.setText(QCoreApplication.translate("Nugget", "Migrate"))
            self.status.setText(QCoreApplication.translate("Nugget", "Migration cancelled."))
            return
        self.button.setEnabled(True)
        self.button.setText(QCoreApplication.translate("Nugget", "Done"))
        self.status.setText(QCoreApplication.translate("Nugget", "Moved {0} of {1} files.").format(
            result.moved_files, self.plan.total_files))

    # -- closing ----------------------------------------------------------- #

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(5000)
        super().closeEvent(event)

    def reject(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(5000)
        super().reject()


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #

def maybe_prompt_migration(parent=None, force: bool = False) -> bool:
    """Show the window when there is something to move.

    Returns True when the data was migrated. A dismissal is remembered for
    this exact set of files, so the app does not ask on every launch; a move
    that FAILED is not remembered, so the next launch offers it again.
    """
    plan = plan_migration()
    if plan.is_empty:
        clear_declined()
        return False
    if not force and is_declined(plan):
        return False
    dialog = DataMigrationDialog(plan, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = dialog.result_data
    finished = result is not None and result.ok
    if accepted or finished:
        clear_declined()
        return True
    if result is None or not result.errors:
        mark_declined(plan)
    return False


def restart_application() -> bool:
    """Restart the process so every path resolves against the new folder.

    Returns False when the exec failed (the caller should say "restart it
    yourself" instead of leaving a half-switched process behind).
    """
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    try:
        os.execl(sys.executable, sys.executable, *sys.argv)
    except OSError:
        return False
    return True


def migrate_now(parent=None) -> bool:
    """Force the window open (Settings → Backup → "Move User Data")."""
    clear_declined()
    return maybe_prompt_migration(parent, force=True)


def migration_pending() -> bool:
    """True when an old data folder still has something to move."""
    return not plan_migration().is_empty
