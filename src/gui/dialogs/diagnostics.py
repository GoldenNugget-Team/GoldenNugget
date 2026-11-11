"""Editable preview of the local diagnostic bundle before export."""
import json

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.controllers.diagnostics import collect_diagnostics, write_diagnostics
from src.gui.theme import ColorThemeManager, t


class DiagnosticsDialog(QDialog):
    def __init__(self, settings=None, manager=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tr = lambda text: QCoreApplication.translate('Nugget', text)
        self.setWindowTitle(tr('Export Diagnostics'))
        self.resize(800, 580)
        layout = QVBoxLayout(self)
        description = QLabel(tr('Review and edit the report before saving. Known credentials and device identifiers are removed. The archive is saved locally.'), self)
        description.setWordWrap(True)
        layout.addWidget(description)
        self.preview = QPlainTextEdit(self)
        self.preview.setPlainText(json.dumps(collect_diagnostics(settings, manager), ensure_ascii=False, indent=2))
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        self.save_button = QPushButton(tr('Save Diagnostic Archive'), self)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        self.close_button = QPushButton(tr('Close'), self)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _save(self):
        try:
            report = json.loads(self.preview.toPlainText())
            if not isinstance(report, dict):
                raise ValueError(QCoreApplication.translate('Nugget', 'Report must be a JSON object.'))
            path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), 'GoldenNugget-diagnostics.zip', 'ZIP (*.zip)')
            if path:
                write_diagnostics(path, report)
                self.accept()
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), str(exc))

    def _retheme(self):
        self.setStyleSheet(t('confirm_dialog'))
        self.preview.setStyleSheet(t('apply_preview_text'))
        self.save_button.setStyleSheet(t('mini_button'))
        self.close_button.setStyleSheet(t('mini_button'))
