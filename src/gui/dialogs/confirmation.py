from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from awesomeui.liquid.controls import LiquidCard
from src.gui.theme import ColorThemeManager, t, theme_pixmap
from src.gui.theme.theme_manager import connect_visible_theme


class ConfirmationDialog(QDialog):
    def __init__(self, parent, title, message, confirm_text, *, destructive=False,
                 icon=":/icon/questionmark.circle.svg", subject=None):
        super().__init__(parent)
        self.setObjectName("themedConfirmation")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.resize(520, 300)
        self._icon_path = icon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(30, 30)
        header.addWidget(self.icon_label)
        heading = QLabel(title, self)
        heading.setObjectName("confirmationTitle")
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.PlainText)
        header.addWidget(heading, 1)
        layout.addLayout(header)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        card = LiquidCard(scroll)
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 16, 16, 16)
        body.setSpacing(8)
        labels = []
        if subject:
            subject_label = QLabel(subject, card)
            subject_label.setObjectName("confirmationSubject")
            labels.append(subject_label)
        message_label = QLabel(message, card)
        message_label.setObjectName("confirmationMessage")
        labels.append(message_label)
        for label in labels:
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.addWidget(label)
        scroll.setWidget(card)
        layout.addWidget(scroll)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.cancel_btn = QPushButton(QCoreApplication.translate("Nugget", "Cancel"), self)
        self.cancel_btn.setObjectName("confirmationCancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton(confirm_text, self)
        self.confirm_btn.setObjectName("confirmationAction")
        self.confirm_btn.setProperty("destructive", destructive)
        self.confirm_btn.clicked.connect(self.accept)
        for button in (self.cancel_btn, self.confirm_btn):
            button.setMinimumWidth(140)
            button.setFixedHeight(48)
            button.setCursor(Qt.PointingHandCursor)
            actions.addWidget(button, 1)
        self.confirm_btn.setAutoDefault(False)
        self.cancel_btn.setDefault(True)
        self.cancel_btn.setFocus()
        layout.addLayout(actions)
        self._retheme()
        connect_visible_theme(self)
        height = 32 + max(0, len(labels) - 1) * 8
        height += sum(max(label.sizeHint().height(), label.heightForWidth(440)) for label in labels)
        scroll.setFixedHeight(max(96, min(300, height)))
        self.adjustSize()

    def _retheme(self):
        self.setStyleSheet(t("confirmation_dialog"))
        self.icon_label.setPixmap(theme_pixmap(
            self._icon_path, ColorThemeManager.instance().colors.text_primary,
            28, self.devicePixelRatioF()))


def ask_confirmation(parent, title, message, confirm_text, *, destructive=False,
                     icon=":/icon/questionmark.circle.svg", subject=None):
    dialog = ConfirmationDialog(parent, title, message, confirm_text,
                                destructive=destructive, icon=icon, subject=subject)
    accepted = dialog.exec() == QDialog.Accepted
    dialog.deleteLater()
    return accepted
