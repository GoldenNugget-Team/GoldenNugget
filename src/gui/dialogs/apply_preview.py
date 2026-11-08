"""Scrollable read-only preview, opened without accepting the apply summary."""
from PySide6.QtCore import QCoreApplication, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from src.gui.theme import ColorThemeManager, t


class _WrappedPreviewDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        table = self.parent()
        item = table.itemFromIndex(index)
        if item is not None and item.isFirstColumnSpanned():
            width = table.viewport().width()
        else:
            width = table.columnWidth(index.column())
        if index.column() == 0:
            depth = 1
            parent = index.parent()
            while parent.isValid():
                depth += 1
                parent = parent.parent()
            width -= depth * table.indentation()
        width = max(40, width - 20)
        height = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 10000), Qt.TextWordWrap, str(index.data() or '')).height()
        return QSize(size.width(), max(size.height(), height + 16))


class ApplyPreviewDialog(QDialog):
    def __init__(self, lines=None, parent=None, *, preview=None, previous=None, conflicts=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("ApplyPreview", "View changes"))
        self.resize(940, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        note = QLabel(QCoreApplication.translate(
            "ApplyPreview", "Compared with the last successful apply through GoldenNugget. "
            "Current device settings are not read. Deselecting a tweak does not reset it; "
            "use Restore Defaults to restore original values."), self)
        note.setObjectName("confirmMuted")
        note.setWordWrap(True)
        layout.addWidget(note)
        if preview is None:
            self.details = QPlainTextEdit(self)
            self.details.setReadOnly(True)
            self.details.setPlainText("\n\n".join(lines or []))
        else:
            self.details = self._build_table(preview, previous, conflicts or [])
        layout.addWidget(self.details, 1)
        close = QPushButton(QCoreApplication.translate("ApplyPreview", "Back"), self)
        close.setObjectName("cancelBtn")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog"))
        self.details.setStyleSheet(t("apply_preview_table" if isinstance(self.details, QTreeWidget)
                                    else "apply_preview_text"))

    def _build_table(self, preview, previous, conflicts):
        from src.controllers.apply_preview import preview_rows, preview_value
        tr = lambda text: QCoreApplication.translate("ApplyPreview", text)
        q = lambda text: QCoreApplication.translate("Nugget", text)
        table = QTreeWidget(self)
        table.setHeaderLabels([tr("Setting"), tr("Before"), tr("After")])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.ElideNone)
        table.setItemDelegate(_WrappedPreviewDelegate(table))
        table.setColumnWidth(0, 360)
        table.setColumnWidth(1, 180)
        table.header().setSectionResizeMode(QHeaderView.Interactive)
        table.header().setStretchLastSection(True)
        table.setAccessibleName(tr("Changes compared with the last successful apply"))

        def group(title):
            item = QTreeWidgetItem(table, [title])
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setFirstColumnSpanned(True)
            item.setExpanded(True)
            return item

        def row(parent, values):
            item = QTreeWidgetItem(parent, values)
            for col, text in enumerate(values):
                item.setToolTip(col, text)
            return item

        if previous is None:
            group(tr("No comparable history for this device and iOS version. Current selections are shown."))
        if conflicts:
            parent = group(tr("Conflicting tweaks"))
            for conflict in conflicts:
                row(parent, [conflict])
        groups = {}
        removed = []
        changes = preview_rows(preview, previous)
        for change in changes:
            if change['removed']:
                removed.append(change)
                continue
            section = change['section']
            if section not in groups:
                groups[section] = group(q(section))
            before = preview_value(change['before']) if change['before'] is not None else (
                tr("Unknown") if previous is None else tr("Not selected"))
            after = preview_value(change['after'])
            if change['before'] is not None and before == after:
                after = tr("Configuration changed ({0})").format(after)
            row(groups[section], [q(change['title']), before, after])
        if removed:
            parent = group(tr("Deselected — not reapplied; original values are not restored"))
            for change in removed:
                row(parent, [f"{q(change['section'])} — {q(change['title'])}",
                             preview_value(change['before']), tr("Not reapplied (not a reset)")])
        if not changes:
            group(tr("No selection changes since the last successful apply.") if previous is not None
                  else tr("No plist tweaks or status bar overrides selected."))
        if preview['queued']:
            parent = group(tr("Current queue (processed again on each apply):"))
            for section, name in preview['queued']:
                row(parent, [q(section), "", name])
        if preview['blocked']:
            parent = group(tr("Skipped by HotLoad"))
            for name in preview['blocked']:
                row(parent, [q(name), "", tr("Will not be applied")])
        if preview['forced']:
            parent = group(tr("Services forced off by HotLoad"))
            for name in preview['forced']:
                row(parent, [name, "", tr("Disable service")])
        return table
