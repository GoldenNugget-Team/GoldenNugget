"""Share a preset as a QR code / text code, and import one back."""
from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.controllers import share_code
from src.gui.theme import ColorThemeManager, t
from src.gui.theme.theme_manager import connect_visible_theme


def _tr(text):
    return QCoreApplication.translate("ShareCode", text)


def _error_text(error):
    return QCoreApplication.translate("ShareCode", str(error))


def _qr_pixmap(code, size=300):
    image = share_code.qr_image(code, module=8)
    height, width = image.shape
    qimage = QImage(image.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(qimage).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)


class _ThemedDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 20, 24, 20)
        self._layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("confirmTitle")
        self._layout.addWidget(heading)
        connect_visible_theme(self)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(t("confirm_dialog") + t("summary_dialog") + f"""
            QLineEdit, QPlainTextEdit {{ background-color: {c.bg_input}; color: {c.text_primary};
                border: 1px solid {c.border}; border-radius: 10px; padding: 8px 10px; font-size: 13px; }}
            QLabel#qrImage {{ background-color: #FFFFFF; border-radius: 12px; padding: 0px; }}
        """)

    def _muted(self, text):
        label = QLabel(text)
        label.setObjectName("confirmMuted")
        label.setWordWrap(True)
        self._layout.addWidget(label)
        return label

    def _button(self, text, handler, secondary=True):
        button = QPushButton(text)
        if secondary:
            button.setObjectName("cancelBtn")
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(44)
        button.clicked.connect(handler)
        return button


class ShareCodeDialog(_ThemedDialog):
    """QR code plus the same code as text, with copy and save actions."""

    def __init__(self, name, code, parent=None):
        super().__init__(_tr("Share “{0}”").format(name), parent)
        self.code = code
        self.name = name
        self.setMinimumWidth(560)
        self._muted(_tr("Scan the QR code or send the text code. Anyone with GoldenNugget can "
                        "import it with Import Code. Templates, icon themes and wallpapers are "
                        "not included, since they are files on this computer."))
        self.qr = QLabel()
        self.qr.setObjectName("qrImage")
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setFixedSize(316, 316)
        self.qr.setPixmap(_qr_pixmap(code))
        self.qr.setAccessibleName(_tr("QR code"))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.qr)
        row.addStretch()
        self._layout.addLayout(row)

        self.code_field = QLineEdit(code)
        self.code_field.setReadOnly(True)
        self.code_field.setCursorPosition(0)
        self.code_field.setAccessibleName(_tr("Share code"))
        self._layout.addWidget(self.code_field)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.copy_button = self._button(_tr("Copy Code"), self._copy)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self._button(_tr("Save QR Image…"), self._save))
        buttons.addWidget(self._button(_tr("Done"), self.accept, secondary=False))
        self._layout.addLayout(buttons)
        self._retheme()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.code)
        self.copy_button.setText(_tr("Copied"))
        QTimer.singleShot(1500, lambda: self.copy_button.setText(_tr("Copy Code")))

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, _tr("Save QR Image…"), f"{self.name}.png", _tr("PNG Images (*.png)"))
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if not _qr_pixmap(self.code, 640).save(path, "PNG"):
            QMessageBox.warning(self, self.windowTitle(), _tr("The image could not be saved."))


class ImportCodeDialog(_ThemedDialog):
    """Paste a code or open a QR image, review the risk, then store it as a preset."""

    def __init__(self, preset_manager, device_version="", device_model="", hotload=None, parent=None):
        super().__init__(_tr("Import Code"), parent)
        self.pm = preset_manager
        self.device_version = device_version
        self.device_model = device_model
        self.hotload = hotload
        self.data = None
        self.imported_name = None
        self.setMinimumWidth(520)
        self._muted(_tr("Paste a GoldenNugget share code, or open a screenshot or photo of its QR code. "
                        "The setup is saved as a new preset; nothing is applied until you load it."))
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlaceholderText("GN1.…")
        self.code_edit.setFixedHeight(84)
        self.code_edit.setAccessibleName(_tr("Share code"))
        self.code_edit.textChanged.connect(self._decode_text)
        self._layout.addWidget(self.code_edit)
        sources = QHBoxLayout()
        sources.setSpacing(12)
        sources.addWidget(self._button(_tr("Paste"), self._paste))
        sources.addWidget(self._button(_tr("Open QR Image…"), self._open_image))
        sources.addStretch()
        self._layout.addLayout(sources)

        self.status = self._muted("")
        self._risk_holder = QVBoxLayout()
        self._layout.addLayout(self._risk_holder)
        self.risk_panel = None
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(_tr("Preset name"))
        self._layout.addWidget(self.name_edit)
        self._layout.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addWidget(self._button(_tr("Cancel"), self.reject))
        self.preview_button = self._button(
            QCoreApplication.translate("DeviceTwin", "Preview on iPhone"), self._preview)
        buttons.addWidget(self.preview_button)
        self.import_button = self._button(_tr("Import"), self._import, secondary=False)
        buttons.addWidget(self.import_button)
        self._layout.addLayout(buttons)
        self._show(None, "")
        self._retheme()

    def _paste(self):
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image()
        if not image.isNull() and not clipboard.text().strip():
            self._decode_qimage(image)
        else:
            self.code_edit.setPlainText(clipboard.text())

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, _tr("Open QR Image…"), "", _tr("Images (*.png *.jpg *.jpeg *.bmp *.webp)"))
        if not path:
            return
        try:
            self.code_edit.setPlainText(share_code.read_qr(path))
        except share_code.ShareCodeError as error:
            self._show(None, _error_text(error))

    def _decode_qimage(self, image):
        import numpy as np
        gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
        width, height, stride = gray.width(), gray.height(), gray.bytesPerLine()
        array = np.frombuffer(gray.constBits(), dtype=np.uint8, count=stride * height)
        array = array.reshape(height, stride)[:, :width].copy()
        try:
            self.code_edit.setPlainText(share_code.read_qr_array(array))
        except share_code.ShareCodeError as error:
            self._show(None, _error_text(error))

    def _decode_text(self):
        text = self.code_edit.toPlainText()
        if not text.strip():
            self._show(None, "")
            return
        try:
            data = self.pm.decode_share_code(text)
        except share_code.ShareCodeError as error:
            self._show(None, _error_text(error))
            return
        meta = data["metadata"]
        details = _tr("{0} tweak(s) turned on.").format(data["shared_count"])
        if meta.get("ios_version"):
            details += " " + _tr("Made on iOS {0}.").format(meta["ios_version"])
        if meta.get("description"):
            details += "\n" + meta["description"]
        if not self.name_edit.text().strip():
            self.name_edit.setText(meta.get("name") or _tr("Shared Preset"))
        self._show(data, details)

    def _show(self, data, message):
        from src.controllers.risk_assessment import assess
        from src.gui.ios.risk_panel import RiskPanel
        self.data = data
        self.status.setText(message)
        self.status.setVisible(bool(message))
        if self.risk_panel is not None:
            self.risk_panel.deleteLater()
            self.risk_panel = None
        if data is not None:
            report = assess(data["tweaks"], self.device_version, self.device_model, hotload=self.hotload)
            self.risk_panel = RiskPanel(report)
            self._risk_holder.addWidget(self.risk_panel)
        self.name_edit.setVisible(data is not None)
        self.import_button.setEnabled(data is not None)
        self.preview_button.setEnabled(data is not None)

    def _preview(self):
        if self.data is None:
            return
        from src.gui.dialogs.device_twin import show_twin
        show_twin(self, self.data["tweaks"], self.device_version, self.device_model,
                  title=self.name_edit.text().strip())

    def _import(self):
        if self.data is None:
            return
        try:
            self.imported_name = self.pm.import_share_code(
                self.code_edit.toPlainText(), self.name_edit.text().strip())
        except (share_code.ShareCodeError, OSError) as error:
            QMessageBox.critical(self, self.windowTitle(), _error_text(error))
            return
        self.accept()


def share_preset_flow(parent, pm, name) -> bool:
    try:
        code = pm.share_code(name)
    except share_code.ShareCodeError as error:
        QMessageBox.warning(parent, _tr("Share Preset"), _error_text(error))
        return False
    dialog = ShareCodeDialog(name, code, parent)
    dialog.exec()
    dialog.deleteLater()
    return True


def import_code_flow(parent, pm, window=None):
    """Returns the new preset's name, or None."""
    version = model = ""
    hotload = None
    manager = getattr(window, "device_manager", None)
    if manager is not None:
        from src.controllers.hotload import HotLoad
        version = manager.get_current_device_version() or ""
        model = manager.get_current_device_model() or ""
        hotload = HotLoad(manager.pref_manager.settings)
    dialog = ImportCodeDialog(pm, version, model, hotload, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    name = dialog.imported_name if accepted else None
    dialog.deleteLater()
    if name:
        QMessageBox.information(
            parent, _tr("Import Code"),
            QCoreApplication.translate("Nugget", "Preset \"{0}\" imported successfully.").format(name))
    return name
