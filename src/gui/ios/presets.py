"""Dedicated iOS-style preset manager page."""

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QScrollArea,
)

from src.controllers.preset_manager import PresetManager
from src.gui.ios.components import IOSSectionHeader, IOSCard, IOSSwitch, IOSPrimaryButton
from src.gui.ios.preset_menu import (
    load_preset_flow, save_preset_flow, delete_preset_flow,
    export_preset_flow, partial_export_preset_flow, import_preset_flow,
    rollback_preset_flow, preset_subtitle,
)
from src.gui.theme import ColorThemeManager


class IOSPresetsPage(QWidget):
    """Full preset workflow, separate from general application settings."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.preset_manager = PresetManager()
        self._tm = ColorThemeManager.instance()
        self.setObjectName("iosContainer")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        content = QWidget()
        self._scroll.setWidget(content)
        root.addWidget(self._scroll)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(16, 16, 16, 32)
        self._layout.setSpacing(8)

        self._layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Presets")))
        self._intro = QLabel(QCoreApplication.translate(
            "Nugget", "Save, switch and share complete tweak configurations."))
        self._intro.setWordWrap(True)
        self._layout.addWidget(self._intro)

        autosave_card = IOSCard()
        autosave_layout = QHBoxLayout(autosave_card)
        autosave_layout.setContentsMargins(16, 10, 16, 10)
        self._autosave_label = QLabel(QCoreApplication.translate(
            "Nugget", "Save tweaks automatically"))
        autosave_layout.addWidget(self._autosave_label, 1)
        self.autosave_switch = IOSSwitch(
            self.window.device_manager.pref_manager.tweak_autosave)
        self.autosave_switch.toggled.connect(self._on_autosave_toggled)
        autosave_layout.addWidget(self.autosave_switch)
        self._layout.addWidget(autosave_card)

        editor = IOSCard()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(16, 12, 16, 12)
        editor_layout.setSpacing(8)
        fields = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Preset name"))
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Description (optional)"))
        fields.addWidget(self.name_edit, 2)
        fields.addWidget(self.description_edit, 3)
        editor_layout.addLayout(fields)
        editor_layout.addWidget(self._button("Save Preset", self._save))
        self._layout.addWidget(editor)

        self._layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Saved presets")))
        self.preset_list = QListWidget()
        self.preset_list.setMinimumHeight(180)
        self.preset_list.itemDoubleClicked.connect(lambda _item: self._load())
        self._layout.addWidget(self.preset_list)

        actions = QHBoxLayout()
        for title, handler in [
            ("Load", self._load), ("Delete", self._delete),
            ("Refresh", self.refresh), ("Rollback Last Apply", self._rollback),
        ]:
            actions.addWidget(self._button(title, handler))
        self._layout.addLayout(actions)

        transfer = QHBoxLayout()
        for title, handler in [
            ("Export", self._export),
            ("Partial Export", self._partial_export),
            ("Import", self._import),
        ]:
            transfer.addWidget(self._button(title, handler))
        self._layout.addLayout(transfer)
        self._layout.addStretch()

        self._retheme()
        self._tm.theme_changed.connect(self._retheme)
        self.refresh()

    def _button(self, text, handler):
        button = IOSPrimaryButton(QCoreApplication.translate("Nugget", text))
        button.clicked.connect(handler)
        return button

    def _retheme(self):
        c = self._tm.colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self._intro.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self._autosave_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        for edit in (self.name_edit, self.description_edit):
            edit.setStyleSheet(f"""
                QLineEdit {{ background-color: {c.bg_input}; border: none;
                    border-radius: 10px; color: {c.text_primary};
                    font-size: 14px; padding: 10px 14px; }}
            """)
        self.preset_list.setStyleSheet(f"""
            QListWidget {{ background-color: {c.bg_input}; border: none;
                border-radius: 8px; color: {c.text_primary};
                font-size: 13px; padding: 4px; }}
            QListWidget::item {{ padding: 8px; }}
            QListWidget::item:selected {{ background-color: {c.scrollbar_pressed};
                color: {c.text_primary}; }}
        """)

    def _selected_name(self):
        item = self.preset_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def _require_selection(self, action):
        name = self._selected_name()
        if not name:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", action),
                QCoreApplication.translate("Nugget", "Select a preset first."))
        return name

    def refresh(self):
        self.preset_list.clear()
        for meta in self.preset_manager.list_presets_with_metadata():
            name = meta["name"]
            if name.startswith("__"):
                continue
            desc = meta.get("description", "")
            subtitle = preset_subtitle(meta)
            text = f"{name}\n  {desc}  ({subtitle})" if desc else f"{name}  ({subtitle})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.preset_list.addItem(item)

    def _on_autosave_toggled(self, checked):
        pref = self.window.device_manager.pref_manager
        pref.tweak_autosave = checked
        self.window.settings.setValue("tweak_autosave", checked)
        self.window._sync_settings()

    def _save(self):
        if save_preset_flow(self, self.window, self.preset_manager,
                            self.name_edit.text(), self.description_edit.text()):
            self.name_edit.clear()
            self.description_edit.clear()
            self.refresh()

    def _load(self):
        name = self._require_selection("Load Preset")
        if name:
            load_preset_flow(self, self.window, self.preset_manager, name)

    def _delete(self):
        name = self._require_selection("Delete Preset")
        if name and delete_preset_flow(self, self.preset_manager, name):
            self.refresh()

    def _rollback(self):
        rollback_preset_flow(self, self.window, self.preset_manager)

    def _export(self):
        name = self._require_selection("Export Preset")
        if name:
            export_preset_flow(self, self.preset_manager, name)

    def _partial_export(self):
        name = self._require_selection("Partial Export")
        if name:
            partial_export_preset_flow(self, self.preset_manager, name)

    def _import(self):
        if import_preset_flow(self, self.preset_manager):
            self.refresh()
