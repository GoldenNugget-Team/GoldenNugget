"""Dedicated iOS-style preset manager page."""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.controllers.preset_manager import PresetManager
from src.gui.ios.preset_menu import (
    delete_preset_flow,
    export_preset_flow,
    import_preset_flow,
    load_preset_flow,
    partial_export_preset_flow,
    preset_subtitle,
    rollback_preset_flow,
    save_preset_flow,
)
from src.gui.theme import ColorThemeManager, t
from src.gui.widgets import (
    IOSCard,
    IOSPrimaryButton,
    IOSSectionHeader,
    IOSSwitch,
)


class IOSPresetsPage(QWidget):
    """Full preset workflow, separate from general application settings."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.preset_manager = PresetManager()
        self._tm = ColorThemeManager.instance()
        self._mini_buttons = []
        self._danger_buttons = []
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

        catalog_card = IOSCard()
        catalog_layout = QHBoxLayout(catalog_card)
        catalog_layout.setContentsMargins(16, 10, 16, 10)
        self._catalog_label = QLabel(QCoreApplication.translate(
            "Nugget", "Presets made by the community, reviewed by the team"))
        self._catalog_label.setWordWrap(True)
        catalog_layout.addWidget(self._catalog_label, 1)
        catalog_layout.addWidget(self._mini_button("Browse Catalog", self._browse_catalog))
        self._layout.addWidget(catalog_card)

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
        # Compact toolbars sit ABOVE the list: the window is only 600px tall,
        # so full-height buttons under the list ended up below the fold.
        actions = QHBoxLayout()
        actions.setSpacing(6)
        for title, handler in [
            ("Load", self._load), ("Preview", self._preview), ("Delete", self._delete),
            ("Refresh", self.refresh), ("Rollback Last Apply", self._rollback),
        ]:
            actions.addWidget(self._mini_button(title, handler, danger=title == "Delete"))
        actions.addStretch()
        self._layout.addLayout(actions)
        # Transfer actions get their own row so neither row overflows at the
        # 1000px minimum window width.
        transfer = QHBoxLayout()
        transfer.setSpacing(6)
        for title, handler in [
            ("Export", self._export),
            ("Partial Export", self._partial_export),
            ("Import", self._import),
            ("Share as QR", self._share),
            ("Import Code", self._import_code),
            ("Submit to Catalog", self._submit_to_catalog),
        ]:
            transfer.addWidget(self._mini_button(title, handler))
        transfer.addStretch()
        self._layout.addLayout(transfer)

        self.preset_list = QListWidget()
        self.preset_list.setMinimumHeight(120)
        self.preset_list.itemDoubleClicked.connect(lambda _item: self._load())
        self._layout.addWidget(self.preset_list)
        self._empty_lbl = QLabel(QCoreApplication.translate(
            "Nugget", "No saved presets yet. Save the current tweaks above or import a preset."))
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._empty_lbl)
        self._layout.addStretch()

        self._retheme()
        self.refresh()

    def _button(self, text, handler):
        button = IOSPrimaryButton(QCoreApplication.translate("Nugget", text))
        button.clicked.connect(handler)
        return button

    def _mini_button(self, text, handler, danger=False):
        button = QPushButton(QCoreApplication.translate("Nugget", text))
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(32)
        button.clicked.connect(handler)
        (self._danger_buttons if danger else self._mini_buttons).append(button)
        return button

    def _retheme(self):
        c = self._tm.colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self._intro.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        for label in (self._autosave_label, self._catalog_label):
            label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px; background-color: transparent;")
        for edit in (self.name_edit, self.description_edit):
            edit.setStyleSheet(f"""
                QLineEdit {{ background-color: {c.bg_input};
                    border: 1px solid {c.border}; border-radius: 10px; color: {c.text_primary};
                    font-size: 14px; padding: 10px 14px; }}
                QLineEdit:focus {{ border-color: {c.accent}; }}
            """)
        for button in self._mini_buttons:
            button.setStyleSheet(t("mini_button"))
        for button in self._danger_buttons:
            button.setStyleSheet(t("mini_button_danger"))
        self._empty_lbl.setStyleSheet(t("list_search_empty"))
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
        has_presets = self.preset_list.count() > 0
        self.preset_list.setVisible(has_presets)
        self._empty_lbl.setVisible(not has_presets)

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

    def _share(self):
        name = self._require_selection("Share Preset")
        if name:
            from src.gui.dialogs.share_preset import share_preset_flow
            share_preset_flow(self, self.preset_manager, name)

    def _import_code(self):
        from src.gui.dialogs.share_preset import import_code_flow
        if import_code_flow(self, self.preset_manager, self.window):
            self.refresh()

    def _browse_catalog(self):
        show = getattr(self.window, "show_ios_page", None)
        if show is not None and hasattr(self.window, "ios_catalog"):
            show(self.window.ios_pages.indexOf(self.window.ios_catalog))
            return
        from src.gui.dialogs.preset_catalog import browse_catalog_flow
        if browse_catalog_flow(self, self.preset_manager, self.window):
            self.refresh()

    def _submit_to_catalog(self):
        name = self._require_selection("Submit to Catalog")
        if name:
            from src.gui.dialogs.preset_catalog import submit_preset_flow
            submit_preset_flow(self, self.preset_manager, name, self.window)

    def _preview(self):
        name = self._require_selection("Preview")
        data = self.preset_manager.read_preset(name) if name else None
        if data is None:
            return
        from src.gui.dialogs.device_twin import show_twin
        manager = self.window.device_manager
        show_twin(self, data["tweaks"], manager.get_current_device_version() or "",
                  manager.get_current_device_model() or "", title=name)
