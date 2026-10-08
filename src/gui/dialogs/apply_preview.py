"""Scrollable read-only preview, opened without accepting the apply summary."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from src.gui.theme import ColorThemeManager, t


class ApplyPreviewDialog(QDialog):
    def __init__(self, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("ApplyPreview", "View changes"))
        self.resize(700, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        note = QLabel(QCoreApplication.translate(
            "ApplyPreview", "Compared with the last successful apply through GoldenNugget. "
            "Current device settings are not read. Deselecting a tweak does not reset it; "
            "use Reset Tweaks to restore defaults."), self)
        note.setObjectName("confirmMuted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlainText("\n\n".join(lines))
        layout.addWidget(self.details, 1)
        close = QPushButton(QCoreApplication.translate("ApplyPreview", "Back"), self)
        close.setObjectName("cancelBtn")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog"))
        self.details.setStyleSheet(t("apply_preview_text"))
