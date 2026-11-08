from PySide6.QtCore import QEvent, QPersistentModelIndex, QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)
from shiboken6 import isValid

from src.gui.theme import ColorThemeManager

from .value_editor import ValueEditor


class ChoiceDialog(QDialog):
    def __init__(self, options, current=None, parent=None):
        super().__init__(parent)
        self._committed = False
        layout = QVBoxLayout(self)
        self.input = QLineEdit()
        self.input.setPlaceholderText(self.tr('Search options'))
        self.input.setAccessibleName(self.tr('Search options'))
        self.input.installEventFilter(self)
        layout.addWidget(self.input)
        self.options = QListWidget()
        self.options.setAccessibleName(self.tr('Options'))
        self.options.setMinimumWidth(0)
        self.options.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.options.setTextElideMode(Qt.ElideRight)
        self.options.setFixedHeight(min(252, max(76, len(options) * 36 + 4)))
        for label, value, enabled, icon in options:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, value)
            item.setToolTip(label)
            item.setSizeHint(QSize(0, 36))
            if icon is not None:
                item.setIcon(icon)
            if not enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled & ~Qt.ItemIsSelectable)
            self.options.addItem(item)
            if value == current:
                self.options.setCurrentItem(item)
        layout.addWidget(self.options)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton(self.tr('Cancel'))
        cancel.setObjectName('valueEditorCancel')
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addStretch()
        layout.addLayout(row)
        self.options.setStyleSheet(
            f'QListWidget{{color:{ColorThemeManager.instance().colors.text_primary};background:transparent;border:none;outline:none;}}'
            'QListWidget::item{padding:8px 10px;border-radius:8px;}'
            'QListWidget::item:selected{background:rgba(255,255,255,32);}'
            'QListWidget::item:hover{background:rgba(255,255,255,18);}')
        self.input.textChanged.connect(self.filter_options)
        self.input.returnPressed.connect(self.accept)
        self.options.itemClicked.connect(lambda _item: self.accept())
        self.options.itemActivated.connect(lambda _item: self.accept())

    def filter_options(self, text):
        text = text.casefold().strip()
        for index in range(self.options.count()):
            item = self.options.item(index)
            item.setHidden(text not in item.text().casefold())
        selected = self.options.currentItem()
        if selected is None or selected.isHidden():
            for index in range(self.options.count()):
                item = self.options.item(index)
                if not item.isHidden() and item.flags() & Qt.ItemIsEnabled:
                    self.options.setCurrentItem(item)
                    break

    def eventFilter(self, target, event):
        if target is self.input and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Down:
            self.options.setFocus(Qt.TabFocusReason)
            if self.options.currentItem() is None:
                self.filter_options(self.input.text())
            return True
        return super().eventFilter(target, event)

    def get_value(self):
        item = self.options.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def accept(self):
        item = self.options.currentItem()
        if (self._committed or item is None or item.isHidden()
                or not item.flags() & Qt.ItemIsEnabled):
            return
        self._committed = True
        super().accept()


class GlassComboBox(QComboBox):
    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self.hidePopup()
        super().changeEvent(event)

    def showPopup(self):
        if not self.isEnabled() or self.count() == 0:
            return
        old = getattr(self, '_choice_editor', None)
        if old is not None and isValid(old):
            old.close()
        options = []
        for row in range(self.count()):
            index = self.model().index(row, self.modelColumn(), self.rootModelIndex())
            enabled = bool(index.flags() & Qt.ItemIsEnabled and index.flags() & Qt.ItemIsSelectable)
            options.append((self.itemText(row), QPersistentModelIndex(index), enabled, self.itemIcon(row)))
        current = QPersistentModelIndex(self.model().index(
            self.currentIndex(), self.modelColumn(), self.rootModelIndex()))
        title = self.accessibleName() or self.placeholderText()
        if not title:
            labels = self.parentWidget().findChildren(QLabel, options=Qt.FindDirectChildrenOnly) if self.parentWidget() else []
            title = next((label.text() for label in labels if label.text()), self.tr('Choose option'))
        dialog = ChoiceDialog(options, current, self)

        def select():
            index = dialog.get_value()
            if not isValid(self) or not self.isEnabled() or index is None or not index.isValid():
                return
            if index.model() != self.model() or index.parent() != self.rootModelIndex():
                return
            if not (index.flags() & Qt.ItemIsEnabled and index.flags() & Qt.ItemIsSelectable):
                return
            row = index.row()
            text = self.itemText(row)
            self.setCurrentIndex(row)
            if isValid(self):
                self.activated.emit(row)
            if isValid(self):
                self.textActivated.emit(text)

        self._choice_editor = ValueEditor(self.window(), self, dialog, title, select, fit_anchor=True)
        dialog.input.setPlaceholderText(self.tr('Search options'))

    def hidePopup(self):
        editor = getattr(self, '_choice_editor', None)
        if editor is not None and isValid(editor):
            editor.close()
        super().hidePopup()
