from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.pages.pages_list import Page, get_resettable_pages
from src.gui.theme import ColorThemeManager, t


class ResetDialog(QDialog):
    def __init__(self, device_manager, apply_reset=lambda x: None, parent=None):
        super().__init__(parent)
        self.device_manager = device_manager
        self.apply_reset = apply_reset
        self.selected_pages: list[Page] = []

        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.setWindowTitle(QCoreApplication.translate('Nugget', 'Restore Defaults'))
        self.buttonBox.button(QDialogButtonBox.Ok).setText(QCoreApplication.translate('Nugget', 'Restore Defaults'))
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel(QCoreApplication.translate('Nugget', 'Restore Defaults'))
        title.setObjectName('confirmTitle')
        layout.addWidget(title)
        message = QLabel(QCoreApplication.translate('Nugget',
            'Select the sections whose original values you want to restore. Turning off a tweak only excludes it from the next apply.'))
        message.setWordWrap(True)
        message.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(message)
        shared_warning = QLabel(QCoreApplication.translate('Nugget',
            'Some sections share preference files. Restoring one may also reset tweaks in another section.'))
        shared_warning.setWordWrap(True)
        layout.addWidget(shared_warning)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(10)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        pages = get_resettable_pages(self.device_manager)
        for page in pages:
            name = "Community Tweaks" if page == Page.Templates else page.getPageName()
            label = QCoreApplication.translate("Nugget", name)
            page_button = QPushButton(label)
            page_button.setObjectName('resetSelection')
            page_button.setCheckable(True)
            page_button.setMinimumHeight(60)
            page_button.setCursor(Qt.PointingHandCursor)
            page_button.toggled.connect(
                lambda checked, button=page_button, name=label:
                button.setText(('✓  ' if checked else '') + name))
            page_button.toggled.connect(lambda checked, p=page: self.toggle_page(checked, p))
            rows.addWidget(page_button)

        rows.addStretch()
        self.buttonBox.button(QDialogButtonBox.Cancel).setObjectName('cancelBtn')
        for button in self.buttonBox.buttons():
            button.setMinimumHeight(48)
            button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)
        self.setMinimumWidth(520)
        self.resize(560, 540)
        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog") + t("reset_dialog"))

    def toggle_page(self, checked: bool, page: Page):
        if checked:
            self.selected_pages.append(page)
        else:
            try:
                self.selected_pages.remove(page)
            except ValueError:
                print("Page not found in list, ignoring error.")
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(bool(self.selected_pages))

    def accept(self):
        super().accept()
        if self.selected_pages:
            self.apply_reset(self.selected_pages)
