"""Background package inspection with a saveable report."""
import json

from PySide6.QtCore import QCoreApplication, Qt, QThread
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.controllers.wallpaper_validation import validate_wallpaper, validation_text
from src.gui.theme import ColorThemeManager, t


class _InspectionThread(QThread):
    def __init__(self, path, version, parent):
        super().__init__(parent)
        self.path, self.version, self.report = path, version, None

    def run(self):
        try:
            self.report = validate_wallpaper(self.path, self.version)
        except Exception as exc:
            self.report = {'error': str(exc)}


class WallpaperValidationDialog(QDialog):
    def __init__(self, path, version=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        tr = lambda text: QCoreApplication.translate('Nugget', text)
        self.setWindowTitle(tr('Check Wallpaper Package'))
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlainText(tr('Checking archive integrity and package documents…'))
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        self.save = QPushButton(tr('Save Report'), self)
        self.save.setEnabled(False)
        self.save.clicked.connect(self._save)
        buttons.addWidget(self.save)
        buttons.addStretch()
        self.close_button = QPushButton(tr('Close'), self)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self._thread = _InspectionThread(path, version, self)
        self._thread.finished.connect(self._finished)
        self._thread.start()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _finished(self):
        report = self._thread.report
        self.details.setPlainText(report['error'] if 'error' in report else validation_text(report))
        self.save.setEnabled(True)
        self.close_button.setEnabled(True)

    def reject(self):
        if not self._thread.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self._thread.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), 'wallpaper-report.json', 'JSON (*.json)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as stream:
                    json.dump(self._thread.report, stream, ensure_ascii=False, indent=2)
            except OSError as exc:
                QMessageBox.critical(self, self.windowTitle(), str(exc))

    def _retheme(self):
        self.setStyleSheet(t('confirm_dialog'))
        self.details.setStyleSheet(t('apply_preview_text'))
        self.save.setStyleSheet(t('mini_button'))
        self.close_button.setStyleSheet(t('mini_button'))
