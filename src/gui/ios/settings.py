from PySide6.QtCore import Qt, QCoreApplication, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QInputDialog,
    QFileDialog, QDialog, QProgressDialog, QGraphicsOpacityEffect
)
from pathlib import Path

from src.exceptions.nugget_exception import NuggetException
from src.gui.ios.components import (
    IOSSectionHeader, IOSSwitch, IOSPrimaryButton
)
from src.gui.pages.main.settings import available_languages
from src.controllers.video_handler import set_ignore_frame_limit
from src.controllers.preset_manager import PresetManager
from src.controllers.hotload import HotLoad
from src.tweaks.tweaks import tweaks, TweakID
from src.gui.thread_workers.apply_worker import ResetPairingThread
from src.gui.theme import ColorThemeManager, AccentPicker, t
from src.gui.ios.preset_menu import (
    load_preset_flow, save_preset_flow, delete_preset_flow,
    export_preset_flow, partial_export_preset_flow, import_preset_flow,
    rollback_preset_flow, preset_subtitle,
)


class IOSSettingsPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")
        self.lang_indexes = []
        self.preset_manager = PresetManager()
        self._tm = ColorThemeManager.instance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self.scroll_area = self._scroll
        content = QWidget()
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll)

        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(16, 16, 16, 32)
        self.content_layout.setSpacing(8)

        # --- Appearance ---
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Appearance")))

        accent_row_card = QWidget()
        accent_row = QHBoxLayout(accent_row_card)
        accent_row.setContentsMargins(16, 10, 16, 10)
        accent_row.setSpacing(12)
        accent_label = QLabel(QCoreApplication.translate("Nugget", "Accent Color"))
        accent_row.addWidget(accent_label, 1)
        self._accent_picker = AccentPicker()
        accent_row.addWidget(self._accent_picker)
        self.content_layout.addWidget(accent_row_card)

        # TEMP: Classic UI removed — the "iOS-style Interface" switch is hidden;
        # the app is pinned to the iOS-style interface until Classic returns.

        # HotLoad safety rules
        self.content_layout.addWidget(
            IOSSectionHeader(QCoreApplication.translate("Nugget", "Safety (HotLoad)")))
        self._hotload = HotLoad(self.window.settings)
        self.hotload_switch = self._make_switch(
            QCoreApplication.translate("Nugget",
                "Apply automatic safety rules (warns on dangerous features)"),
            self._hotload.is_enabled(),
            self._make_hotload_handler(),
        )

        # Language
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "App Language")))
        self._make_language_row()

        # Device
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Device")))
        pref = self.window.device_manager.pref_manager

        self._make_switch(
            QCoreApplication.translate("Nugget", "Auto Reboot After Applying"),
            pref.auto_reboot,
            self._make_setting_handler("auto_reboot"),
        )

        reset_pairing_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Reset Device Pairing"))
        reset_pairing_btn.clicked.connect(self._on_reset_pairing_clicked)
        self.content_layout.addWidget(reset_pairing_btn)

        # PosterBoard
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "PosterBoard")))

        self._make_switch(
            QCoreApplication.translate("Nugget", "Ignore Posterboard Frame Limit"),
            self.window.settings.value("ignore_pb_frame_limit", False, type=bool),
            lambda checked: (
                set_ignore_frame_limit(checked),
                self.window.settings.setValue("ignore_pb_frame_limit", checked),
                self.window._sync_settings(),
            ),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Disable Tendies Limit"),
            pref.disable_tendies_limit,
            self._make_setting_handler("disable_tendies_limit"),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Force PosterBoard Refresh"),
            pref.auto_refresh_posterboard,
            self._make_setting_handler("auto_refresh_posterboard"),
        )

        self._make_pb_setup_section()

        # Backup
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Backup")))

        cache_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "Use Fast Backup Cache (Experimental)"),
            pref.use_backup_cache,
            lambda checked: self._on_backup_cache_toggled(checked, cache_switch),
        )

        encrypted_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "Use Encrypted Backups (Experimental)"),
            pref.use_encrypted_backup,
            lambda checked: self._on_encrypted_backup_toggled(checked, encrypted_switch),
        )

        afc_media_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "Backup Photos Over AFC (Parallel)"),
            pref.use_afc_media,
            lambda checked: self._on_afc_media_toggled(checked, afc_media_switch),
        )

        self._make_backup_location_row()

        restore_btn = IOSPrimaryButton(
            QCoreApplication.translate("Nugget", "Restore Data From Backup"))
        restore_btn.setToolTip(QCoreApplication.translate(
            "Nugget",
            "Restore photos, messages, contacts and settings from the last "
            "protective backup. Applied tweaks and wallpapers are kept."))
        restore_btn.clicked.connect(self._on_restore_data_clicked)
        self.content_layout.addWidget(restore_btn)

        self._make_history_section()

        # Setup
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Setup")))

        self._make_switch(
            QCoreApplication.translate("Nugget", "Skip Setup * (non-exploit files only)"),
            pref.skip_setup,
            self._make_setting_handler("skip_setup"),
        )

        self._make_switch(
            QCoreApplication.translate("Nugget", "Enable Supervision * (requires Skip Setup)"),
            pref.supervised,
            self._make_setting_handler("supervised"),
        )

        self._make_text_row(
            QCoreApplication.translate("Nugget", "Enter Organization Name"),
            pref.organization_name,
            self._on_org_name_edited,
        )

        # About
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "About")))

        about_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "About GoldenNugget"))
        about_btn.clicked.connect(self.show_about)
        self.content_layout.addWidget(about_btn)

        self.content_layout.addStretch()

        self._retheme()
        self._tm.theme_changed.connect(self._retheme)

    def _retheme(self):
        c = self._tm.colors
        self._scroll.setStyleSheet(
            f"background-color: {c.bg_primary}; border: none;"
        )
        self._accent_picker.setStyleSheet(
            f"background-color: {c.bg_primary};"
        )
        if hasattr(self, '_lang_drp'):
            self._retheme_lang_dropdown()
        if hasattr(self, '_saved_ids_list'):
            self._retheme_saved_ids_list()
        if hasattr(self, '_preset_name_txt'):
            self._retheme_preset_inputs()
        if hasattr(self, '_preset_list'):
            self._retheme_preset_list()
        if hasattr(self, 'history_count_lbl'):
            self.history_count_lbl.setStyleSheet(t("value_label"))

    def _retheme_lang_dropdown(self):
        c = self._tm.colors
        self._lang_drp.setStyleSheet(f"""
            QComboBox {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 10.5pt;
                padding: 8px 12px;
                min-width: 140px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid {c.text_secondary}; margin-right: 10px; }}
            QComboBox QAbstractItemView {{
                background-color: {c.bg_tertiary};
                border: 1px solid {c.border};
                border-radius: 10px;
                color: {c.text_primary};
                selection-background-color: {c.accent};
            }}
        """)

    def _retheme_saved_ids_list(self):
        c = self._tm.colors
        self._saved_ids_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 8px;
                color: {c.text_primary};
                font-size: 13px;
                padding: 4px;
            }}
            QListWidget::item {{ padding: 6px; }}
            QListWidget::item:selected {{ background-color: {c.scrollbar_pressed}; color: {c.text_primary}; }}
        """)

    def _retheme_preset_inputs(self):
        c = self._tm.colors
        for edit in (self._preset_name_txt, self._preset_desc_txt):
            edit.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {c.bg_input};
                    border: none;
                    border-radius: 10px;
                    color: {c.text_primary};
                    font-size: 14px;
                    padding: 10px 14px;
                }}
            """)

    def _retheme_preset_list(self):
        c = self._tm.colors
        self._preset_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 8px;
                color: {c.text_primary};
                font-size: 13px;
                padding: 4px;
            }}
            QListWidget::item {{ padding: 8px; }}
            QListWidget::item:selected {{ background-color: {c.scrollbar_pressed}; color: {c.text_primary}; }}
        """)

    # ---------- helpers ----------

    def _make_switch(self, title: str, checked: bool, on_toggled) -> IOSSwitch:
        c = self._tm.colors
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        label.setWordWrap(True)
        row.addWidget(label, 1)

        switch = IOSSwitch(checked)
        switch.toggled.connect(on_toggled)
        row.addWidget(switch)
        self.content_layout.addWidget(card)
        return switch

    def _make_setting_handler(self, pref_attr: str):
        pref = self.window.device_manager.pref_manager
        def handler(checked: bool):
            setattr(pref, pref_attr, checked)
            self.window.settings.setValue(pref_attr, checked)
            self.window._sync_settings()
        return handler

    def _make_hotload_handler(self):
        def handler(checked: bool):
            self._hotload.set_enabled(checked)
        return handler

    def _on_autosave_toggled(self, checked: bool):
        """Persist the AutoSave option and re-label the home preset banner.

        Nothing is written or deleted here: an existing AutoSave preset stays
        on disk and remains loadable from the preset list, it just stops being
        updated and loaded at startup.
        """
        pref = self.window.device_manager.pref_manager
        pref.tweak_autosave = checked
        self.window.settings.setValue("tweak_autosave", checked)
        self.window._sync_settings()
        try:
            self.window._refresh_preset_widgets()
        except Exception:
            # a banner refresh must never break the switch itself
            pass

    def _on_reset_pairing_clicked(self):
        if self.window.device_manager.data_singleton.current_device is None:
            QMessageBox.information(
                self.window,
                QCoreApplication.translate("Nugget", "Pairing Reset"),
                QCoreApplication.translate("Nugget", "No device selected."),
            )
            return
        current = getattr(self, "_reset_pairing_thread", None)
        if current is not None and getattr(current, "isRunning", lambda: False)():
            # already resetting — never spawn a second thread over the device
            return
        thread = ResetPairingThread(self.window.device_manager)
        # Hold the thread on this page like the other workers (ApplyThread,
        # RefreshDevicesThread, RestoreCacheThread, PasscodeThemeWriteThread):
        # a bare local reference lets the Python wrapper be garbage-collected
        # while the native thread is still running, which Qt reports as
        # "QThread: Destroyed while thread '' is still running" and aborts.
        self._reset_pairing_thread = thread
        thread.done.connect(self._on_reset_pairing_done)
        thread.finished.connect(self._on_reset_pairing_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_reset_pairing_thread_finished(self):
        # run() returned, so the native thread is done; drop the page's
        # reference (deleteLater is already queued via the other connection).
        try:
            self._reset_pairing_thread = None
        except Exception:
            pass

    def _on_reset_pairing_done(self, ok: bool, error: str):
        title = QCoreApplication.translate("Nugget", "Pairing Reset")
        if ok:
            QMessageBox.information(
                self.window,
                title,
                QCoreApplication.translate(
                    "Nugget", "Your device's pairing was successfully reset. "
                    "Refresh the device list before applying.")
            )
        else:
            QMessageBox.critical(
                self.window,
                title,
                QCoreApplication.translate(
                    "Nugget", "Failed to reset device pairing: %1").replace("%1", error)
            )

    def _on_restore_data_clicked(self):
        reply = QMessageBox.question(
            self.window,
            "Restore Data From Backup?",
            "This restores photos, messages, contacts and settings from the "
            "last protective backup on this computer.\n\n"
            "Applied tweaks and GoldenNugget wallpapers are KEPT.\n\n"
            "Make sure the iPhone is connected, unlocked and awake, "
            "then do you want to continue?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.window._start_cache_restore()

    def _on_backup_cache_toggled(self, checked: bool, switch):
        pref = self.window.device_manager.pref_manager
        if checked:
            reply = QMessageBox.question(
                self.window,
                "Enable Fast Backup Cache?",
                "WARNING: The cached backup feature is experimental and, when it "
                "fails, can leave your device without wallpaper data or on the "
                "Setup screen.\n\n"
                "Enable the fast backup cache anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                switch.blockSignals(True)
                switch.setChecked(False)
                switch.blockSignals(False)
                return
        pref.use_backup_cache = checked
        self.window.settings.setValue("use_backup_cache", checked)
        self.window._sync_settings()

    def _on_encrypted_backup_toggled(self, checked: bool, switch):
        pref = self.window.device_manager.pref_manager
        if checked:
            reply = QMessageBox.question(
                self.window,
                "Enable Encrypted Backups?",
                "WARNING: Using encrypted backups with GoldenNugget is experimental "
                "and may cause DATA LOSS or leave your device stuck on the Setup "
                "screen after applying tweaks.\n\n"
                "Make sure you know your backup password before continuing.\n\n"
                "Enable encrypted backups anyway?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                switch.blockSignals(True)
                switch.setChecked(False)
                switch.blockSignals(False)
                return
        pref.use_encrypted_backup = checked
        self.window.settings.setValue("use_encrypted_backup", checked)
        self.window._sync_settings()

    def _on_afc_media_toggled(self, checked: bool, switch):
        pref = self.window.device_manager.pref_manager
        if checked and pref.use_backup_cache:
            QMessageBox.warning(
                self.window,
                "Fast Backup Cache is on",
                "The Fast Backup Cache also uses the AFC (parallel) media "
                "channel for photos, so this switch has no effect while the "
                "cache is on. Turn the cache off to use it on the standard "
                "backup path.",
            )
        pref.use_afc_media = checked
        self.window.settings.setValue("use_afc_media", checked)
        self.window._sync_settings()

    def _custom_backup_dir_value(self) -> str:
        try:
            return str(self.window.settings.value("backup_storage_dir", "", type=str)).strip()
        except Exception:
            return ""

    def _default_backup_dir_text(self) -> str:
        try:
            from src.restore.storage import cache_base
            return str(cache_base())
        except Exception:
            return QCoreApplication.translate("Nugget", "Default (system drive)")

    def _make_backup_location_row(self):
        c = self._tm.colors
        card = QWidget()
        row = QVBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(8)

        title = QLabel(QCoreApplication.translate("Nugget", "Backup/Cache Location"))
        title.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        row.addWidget(title)

        custom = self._custom_backup_dir_value()
        self.backup_location_lbl = QLabel(
            custom if custom else self._default_backup_dir_text())
        self.backup_location_lbl.setWordWrap(True)
        self.backup_location_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 13px;")
        row.addWidget(self.backup_location_lbl)

        hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "The protective backup cache, AFC media cache and temporary "
            "backup/restore files for iOS 27 are stored in this folder. "
            "Useful when the system drive is small (e.g. C: 28 GB)."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
        row.addWidget(hint)

        btns = QHBoxLayout()
        browse_btn = self._make_mini_button(
            QCoreApplication.translate("Nugget", "Browse"))
        browse_btn.clicked.connect(self._on_backup_location_browse)
        btns.addWidget(browse_btn)
        if custom:
            reset_btn = self._make_mini_button(
                QCoreApplication.translate("Nugget", "Reset to Default"))
            reset_btn.clicked.connect(self._on_backup_location_reset)
            btns.addWidget(reset_btn)
        btns.addStretch()
        row.addLayout(btns)

        self.content_layout.addWidget(card)

    def _on_backup_location_browse(self):
        current = self._custom_backup_dir_value()
        folder = QFileDialog.getExistingDirectory(
            self.window,
            QCoreApplication.translate("Nugget", "Choose Backup/Cache Location"),
            current if current else str(Path.home()),
        )
        if not folder:
            return
        self.window.settings.setValue("backup_storage_dir", folder)
        self.window._sync_settings()
        self._refresh_backup_location_row()

    def _on_backup_location_reset(self):
        self.window.settings.remove("backup_storage_dir")
        self.window._sync_settings()
        self._refresh_backup_location_row()

    def _refresh_backup_location_row(self):
        custom = self._custom_backup_dir_value()
        if hasattr(self, "backup_location_lbl"):
            self.backup_location_lbl.setText(
                custom if custom else self._default_backup_dir_text())

    def _make_text_row(self, title: str, current: str, on_submit):
        c = self._tm.colors
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        row.addWidget(label, 1)

        self.org_value_lbl = QLabel(current if current else QCoreApplication.translate("MainWindow", "None"))
        self.org_value_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 14px;")
        row.addWidget(self.org_value_lbl)

        edit_btn = QLabel("\u270e")
        edit_btn.setStyleSheet(f"color: {c.accent}; font-size: 17px;")
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.mousePressEvent = lambda e: self._on_text_row_edit(title, on_submit)
        row.addWidget(edit_btn)

        self.content_layout.addWidget(card)

    def _on_text_row_edit(self, title: str, on_submit):
        c = self._tm.colors
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(QCoreApplication.translate("Nugget", "Enter value:"))
        dialog.setTextValue(self.window.device_manager.pref_manager.organization_name)
        dialog.setStyleSheet(f"""
            QDialog, QInputDialog {{ background-color: {c.bg_primary}; }}
            QLabel {{ color: {c.text_primary}; font-size: 15px; }}
            QLineEdit {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 15px;
                padding: 10px 14px;
            }}
            QPushButton {{
                background-color: {c.accent};
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 15px;
                font-weight: 600;
                padding: 10px 20px;
                border: none;
            }}
        """)
        if dialog.exec() == QDialog.Accepted:
            text = dialog.textValue()
            on_submit(text)
            self.org_value_lbl.setText(text if text else QCoreApplication.translate("MainWindow", "None"))

    def _on_org_name_edited(self, text: str):
        pref = self.window.device_manager.pref_manager
        pref.organization_name = text
        self.window.settings.setValue("organization_name", text)
        self.window._sync_settings()

    def _make_language_row(self):
        c = self._tm.colors
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(QCoreApplication.translate("Nugget", "App Language"))
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        row.addWidget(label, 1)

        self.lang_drp = QComboBox()
        self._lang_drp = self.lang_drp
        for language, code in available_languages.items():
            self.lang_indexes.append(code)
            self.lang_drp.addItem(QCoreApplication.translate("Nugget", language))
        if self.window.settings.contains("locale_code"):
            try:
                idx = self.lang_indexes.index(self.window.translator.get_saved_locale_code())
            except ValueError:
                idx = 0
        else:
            idx = 0
        self.lang_drp.setCurrentIndex(idx)
        self.lang_drp.activated.connect(self._on_lang_selected)
        row.addWidget(self.lang_drp)

        self.content_layout.addWidget(card)

    def _on_lang_selected(self, index: int):
        new_lang = self.lang_indexes[index]
        currently_system = not self.window.settings.contains("locale_code")
        if new_lang == "" and currently_system:
            return
        if new_lang != self.window.translator.get_saved_locale_code():
            self.window.translator.set_new_language(new_lang, restart=True)

    def _make_pb_setup_section(self):
        c = self._tm.colors
        self.content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "PosterBoard Database")
        ))

        self._make_label_row(QCoreApplication.translate("Nugget", "Database"), "sqlite: None")

        self._make_button_row(
            QCoreApplication.translate("Nugget", "Get Database from Device"),
            self._on_pb_get_db,
        )
        self._make_button_row(
            QCoreApplication.translate("Nugget", "Select Database File"),
            self._on_pb_select_db,
        )
        self._make_button_row(
            QCoreApplication.translate("Nugget", "Rebuild Database (Clownfish)"),
            self._on_pb_rebuild,
        )

        ids_card = QWidget()
        ids_layout = QVBoxLayout(ids_card)
        ids_layout.setContentsMargins(16, 12, 16, 12)
        ids_layout.setSpacing(8)
        ids_title = QLabel(QCoreApplication.translate("Nugget", "Saved Configuration IDs"))
        ids_title.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        ids_layout.addWidget(ids_title)

        self.saved_ids_list = QListWidget()
        self._saved_ids_list = self.saved_ids_list
        ids_layout.addWidget(self.saved_ids_list)

        ids_btns = QHBoxLayout()
        clear_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Clear"))
        clear_btn.clicked.connect(self._on_clear_saved_ids)
        remove_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Remove Selected"))
        remove_btn.clicked.connect(self._on_remove_selected_id)
        ids_btns.addWidget(clear_btn)
        ids_btns.addWidget(remove_btn)
        ids_layout.addLayout(ids_btns)
        self.content_layout.addWidget(ids_card)

        self._refresh_saved_ids()

    def _make_label_row(self, title: str, value: str):
        c = self._tm.colors
        card = QWidget()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)

        label = QLabel(title)
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        row.addWidget(label, 1)

        self.pb_db_lbl = QLabel(value)
        self.pb_db_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 14px;")
        row.addWidget(self.pb_db_lbl)
        self.content_layout.addWidget(card)

    def _make_button_row(self, title: str, on_click):
        btn = IOSPrimaryButton(title)
        btn.setFixedHeight(44)
        btn.clicked.connect(on_click)
        self.content_layout.addWidget(btn)

    def _make_history_section(self):
        self.content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Operation History")))
        card = QWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        self.history_list = QListWidget()
        self.history_list.setMinimumHeight(120)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Search history..."))
        self.history_search.textChanged.connect(self._refresh_history)
        layout.addWidget(self.history_search)
        filters = QHBoxLayout()
        self.history_mode_filter = QComboBox()
        self.history_mode_filter.addItem(QCoreApplication.translate("Nugget", "All operations"), "all")
        self.history_mode_filter.addItem(QCoreApplication.translate("Nugget", "Apply"), "apply")
        self.history_mode_filter.addItem(QCoreApplication.translate("Nugget", "Reset"), "reset")
        self.history_result_filter = QComboBox()
        self.history_result_filter.addItem(QCoreApplication.translate("Nugget", "All results"), "all")
        self.history_result_filter.addItem(QCoreApplication.translate("Nugget", "Success"), "success")
        self.history_result_filter.addItem(QCoreApplication.translate("Nugget", "Failed"), "failed")
        self.history_mode_filter.currentIndexChanged.connect(self._refresh_history)
        self.history_result_filter.currentIndexChanged.connect(self._refresh_history)
        filters.addWidget(self.history_mode_filter)
        filters.addWidget(self.history_result_filter)
        self.history_reset_btn = self._make_mini_button(
            QCoreApplication.translate("Nugget", "Reset Filters"))
        self.history_reset_btn.clicked.connect(self._reset_history_filters)
        filters.addWidget(self.history_reset_btn)
        layout.addLayout(filters)
        self.history_count_lbl = QLabel("")
        self.history_count_lbl.setStyleSheet(t("value_label"))
        layout.addWidget(self.history_count_lbl)
        layout.addWidget(self.history_list)
        self._history_anims = []
        clear = self._make_mini_button(QCoreApplication.translate("Nugget", "Clear History"))
        clear.clicked.connect(self._clear_history)
        layout.addWidget(clear)
        self.content_layout.addWidget(card)
        self._refresh_history()

    def _refresh_history(self, *_args):
        from datetime import datetime
        from src.controllers.apply_history import load_history
        self._history_anims.clear()
        self.history_list.clear()
        query = self.history_search.text().strip().casefold()
        mode_filter = self.history_mode_filter.currentData()
        result_filter = self.history_result_filter.currentData()
        matches = []
        for item in reversed(load_history()):
            if mode_filter != "all" and item.get("mode") != mode_filter:
                continue
            if result_filter == "success" and not item.get("success"):
                continue
            if result_filter == "failed" and item.get("success"):
                continue
            haystack = " ".join(str(item.get(key, "")) for key in
                                ("timestamp", "mode", "device", "model", "ios", "error"))
            if query and query not in haystack.casefold():
                continue
            matches.append(item)
        entries = matches[:10]
        if matches:
            if len(matches) > len(entries):
                self.history_count_lbl.setText(
                    QCoreApplication.translate("Nugget", "Showing {0} of {1} operations").format(
                        len(entries), len(matches)))
            else:
                self.history_count_lbl.setText(
                    QCoreApplication.translate("Nugget", "{0} operations found").format(len(matches)))
        elif query or mode_filter != "all" or result_filter != "all":
            self.history_count_lbl.setText(
                QCoreApplication.translate("Nugget", "No matching operations"))
        else:
            self.history_count_lbl.setText(
                QCoreApplication.translate("Nugget", "No operations recorded yet"))
        for row_index, item in enumerate(entries):
            try:
                when = datetime.fromisoformat(item.get("timestamp", "")).astimezone().strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                when = item.get("timestamp", "")
            mode = QCoreApplication.translate("Nugget", "Apply") if item.get("mode") == "apply" else QCoreApplication.translate("Nugget", "Reset")
            result = QCoreApplication.translate("Nugget", "Success") if item.get("success") else QCoreApplication.translate("Nugget", "Failed")
            text = f"{when}  •  {mode}  •  {item.get('device', 'Unknown device')}  •  iOS {item.get('ios', '?')}  •  {result}"
            if item.get("error"):
                text += f"\n{item['error']}"
            list_item = QListWidgetItem(self.history_list)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setMinimumHeight(30)
            label.setStyleSheet("background-color: transparent; padding: 5px 2px;")
            self.history_list.setItemWidget(list_item, label)
            list_item.setSizeHint(label.sizeHint())
            effect = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setDuration(220)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            QTimer.singleShot(row_index * 25, animation.start)
            self._history_anims.append(animation)
        if not self.history_list.count():
            self.history_list.addItem(
                QCoreApplication.translate("Nugget", "No matching operations." if (query or mode_filter != "all" or result_filter != "all") else "No operations recorded yet."))

    def _reset_history_filters(self):
        self.history_search.clear()
        self.history_mode_filter.setCurrentIndex(0)
        self.history_result_filter.setCurrentIndex(0)

    def _clear_history(self):
        from src.controllers.apply_history import clear_history
        clear_history()
        self._refresh_history()

    def _make_mini_button(self, title: str):
        from PySide6.QtWidgets import QPushButton
        c = self._tm.colors
        btn = QPushButton(title)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.scrollbar};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 13px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{ background-color: {c.surface_hover}; }}
        """)
        return btn

    def _on_pb_get_db(self):
        from src.gui.dialogs import PosterBoardDBWizard
        current = self.window.device_manager.data_singleton.current_device
        if current is None:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Get Database"),
                QCoreApplication.translate("QCoreApplication", "Please connect a device."))
            return
        wizard = PosterBoardDBWizard(current.udid, self.pb_db_lbl, self._refresh_saved_ids)
        wizard.exec()

    def _on_pb_select_db(self):
        from PySide6.QtWidgets import QFileDialog as FD
        selected_file, _ = FD.getOpenFileName(
            self, QCoreApplication.translate("Nugget", "Select PBFPosterExtensionDataStoreSQLiteDatabase File"),
            "", "*.sqlite3", options=FD.ReadOnly)
        if selected_file in (None, ""):
            tweaks[TweakID.PosterBoard].config_manager.database = None
            self.pb_db_lbl.setText("sqlite: None")
        else:
            # update_database_file RAISES on a rejected database; without this the
            # exception escapes the slot and lands in the crash handler, which is
            # what the user saw instead of an explanation.
            try:
                if not tweaks[TweakID.PosterBoard].config_manager.update_database_file(
                        selected_file, self.window.device_manager.get_current_device_udid()):
                    QMessageBox.critical(
                        self, QCoreApplication.translate("QtCore.QCoreApplication", "Error!"),
                        QCoreApplication.translate("Nugget", "The database is not of the correct format!"))
                    return
            except NuggetException as e:
                QMessageBox.critical(
                    self, QCoreApplication.translate("Nugget", "Error!"),
                    str(e), e.detailed_text or "")
                return
            self.pb_db_lbl.setText("sqlite: Selected")

    def _on_pb_rebuild(self):
        from src.gui.thread_workers.pb_worker import PBRebuildThread
        current = self.window.device_manager.data_singleton.current_device
        if current is None:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Rebuild Database"),
                QCoreApplication.translate("QCoreApplication", "Please connect a device."))
            return
        confirm = QMessageBox.question(
            self, QCoreApplication.translate("Nugget", "Rebuild Database"),
            QCoreApplication.translate(
                "Nugget",
                "Repack all Marble/Lavender wallpapers already on this device "
                "into the Clownfish format (enables the Depth effect) in place?\n\n"
                "Mercury spatial posters and every other family are left "
                "untouched.\n\nThe device must be unlocked and have Find My "
                "turned off, and it will restart when the rebuild finishes."))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        worker = PBRebuildThread(manager=self.window.device_manager, udid=current.udid)
        self._pb_rebuild_thread = worker  # keep a strong ref while running
        prog = QProgressDialog(
            QCoreApplication.translate("Nugget", "Rebuilding wallpapers..."),
            "", 0, 0, self)
        prog.setWindowTitle(QCoreApplication.translate("Nugget", "Rebuild Database"))
        prog.setWindowModality(Qt.WindowModal)
        prog.setCancelButton(None)
        prog.setMinimumDuration(0)

        def _on_finish(ok: bool, msg: str):
            prog.close()
            if ok:
                # Defer past the progress dialog's nested event loop so the
                # modal result box is not opened from inside it.
                QTimer.singleShot(0, lambda: QMessageBox.information(
                    self, QCoreApplication.translate("Nugget", "Rebuild Database"),
                    msg or QCoreApplication.translate("Nugget", "Done.")))

        worker.progress.connect(prog.setLabelText)
        worker.request_text.connect(self.window.on_password_request)
        worker.choice_prompt.connect(self.window.on_choice_prompt)
        worker.alert.connect(self.window.alert_message)
        worker.finished_with_result.connect(_on_finish)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        prog.exec()

    def _refresh_saved_ids(self):
        self.saved_ids_list.clear()
        saved_ids = tweaks[TweakID.PosterBoard].config_manager.saved_items
        if len(saved_ids) == 0:
            self.saved_ids_list.setEnabled(False)
            self.saved_ids_list.addItem(QCoreApplication.translate("MainWindow", "None"))
        else:
            self.saved_ids_list.setEnabled(True)
            self.saved_ids_list.addItems([item.to_str() for item in saved_ids])

    def _on_clear_saved_ids(self):
        confirm = QMessageBox.question(
            self, QCoreApplication.translate("Nugget", "Clear Saved IDs"),
            QCoreApplication.translate("Nugget", "Clear all saved configuration IDs?"))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        tweaks[TweakID.PosterBoard].config_manager.saved_items.clear()
        self._refresh_saved_ids()

    def _on_remove_selected_id(self):
        curr_row = self.saved_ids_list.currentRow()
        if curr_row >= 0 and len(tweaks[TweakID.PosterBoard].config_manager.saved_items) > 0:
            tweaks[TweakID.PosterBoard].config_manager.saved_items.pop(curr_row)
            self._refresh_saved_ids()

    # ---------- presets ----------

    def _make_presets_section(self):
        c = self._tm.colors
        self.content_layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Presets")
        ))

        self.autosave_switch = self._make_switch(
            QCoreApplication.translate("Nugget", "Save Tweaks Automatically"),
            self.window.device_manager.pref_manager.tweak_autosave,
            self._on_autosave_toggled,
        )
        autosave_hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "Saves your tweak selection to a built-in \"AutoSave\" preset "
            "and restores it on the next launch. Turn off to keep changes "
            "for this session only — an existing AutoSave preset stays on "
            "disk and is not loaded at startup."))
        autosave_hint.setWordWrap(True)
        autosave_hint.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(16, 0, 16, 8)
        hint_row.addWidget(autosave_hint, 1)
        self.content_layout.addLayout(hint_row)

        card = QWidget()
        presets_layout = QVBoxLayout(card)
        presets_layout.setContentsMargins(16, 12, 16, 12)
        presets_layout.setSpacing(8)

        name_row = QHBoxLayout()
        self.preset_name_txt = QLineEdit()
        self._preset_name_txt = self.preset_name_txt
        self.preset_name_txt.setPlaceholderText(QCoreApplication.translate("Nugget", "Preset name"))
        self.preset_desc_txt = QLineEdit()
        self._preset_desc_txt = self.preset_desc_txt
        self.preset_desc_txt.setPlaceholderText(QCoreApplication.translate("Nugget", "Description (optional)"))
        name_row.addWidget(self.preset_name_txt, 2)
        name_row.addWidget(self.preset_desc_txt, 3)
        presets_layout.addLayout(name_row)

        save_btn = self._make_mini_button(QCoreApplication.translate("Nugget", "Save Preset"))
        save_btn.clicked.connect(self._on_preset_save)
        presets_layout.addWidget(save_btn)

        self.preset_list = QListWidget()
        self._preset_list = self.preset_list
        self.preset_list.setMinimumHeight(120)
        presets_layout.addWidget(self.preset_list)

        btns_row = QHBoxLayout()
        for title, handler in [
            (QCoreApplication.translate("Nugget", "Load"), self._on_preset_load),
            (QCoreApplication.translate("Nugget", "Delete"), self._on_preset_delete),
            (QCoreApplication.translate("Nugget", "Refresh"), self.refresh_presets),
            (QCoreApplication.translate("Nugget", "Rollback Last Apply"), self._on_preset_rollback),
        ]:
            btn = self._make_mini_button(title)
            btn.clicked.connect(handler)
            btns_row.addWidget(btn)
        presets_layout.addLayout(btns_row)
        transfer_row = QHBoxLayout()
        for title, handler in [
            (QCoreApplication.translate("Nugget", "Export"), self._on_preset_export),
            (QCoreApplication.translate("Nugget", "Partial Export"), self._on_preset_partial_export),
            (QCoreApplication.translate("Nugget", "Import"), self._on_preset_import),
        ]:
            btn = self._make_mini_button(title)
            btn.clicked.connect(handler)
            transfer_row.addWidget(btn)
        presets_layout.addLayout(transfer_row)

        self.content_layout.addWidget(card)

    def scroll_to_presets(self):
        if self.scroll_area is not None:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh_presets(self):
        self.preset_list.clear()
        for meta in self.preset_manager.list_presets_with_metadata():
            name = meta["name"]
            if name.startswith("__"):
                continue
            desc = meta.get("description", "")
            sub = preset_subtitle(meta)
            if desc:
                item_text = f"{name}\n  {desc}  ({sub})"
            else:
                item_text = f"{name}  ({sub})"
            item = QListWidgetItem(item_text)
            self.preset_list.addItem(item)
            item.setData(Qt.UserRole, name)


    def _on_preset_save(self):
        if save_preset_flow(
                self, self.window, self.preset_manager,
                self.preset_name_txt.text(), self.preset_desc_txt.text()):
            self.preset_name_txt.clear()
            self.preset_desc_txt.clear()
            self.refresh_presets()

    def _on_preset_load(self):
        if self.preset_list.currentRow() < 0:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", "Load Preset"),
                QCoreApplication.translate("Nugget", "Select a preset to load first."))
            return
        name = self._selected_preset_name()
        if not name:
            return
        load_preset_flow(self, self.window, self.preset_manager, name)

    def _on_preset_rollback(self):
        rollback_preset_flow(self, self.window, self.preset_manager)

    def _selected_preset_name(self) -> str:
        """Name of the preset selected in the list ("" when nothing is)."""
        item = self.preset_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.UserRole) or item.text().split("\n")[0].strip()

    def _require_selection(self, title: str, message: str) -> str:
        name = self._selected_preset_name()
        if not name:
            QMessageBox.warning(
                self, QCoreApplication.translate("Nugget", title),
                QCoreApplication.translate("Nugget", message))
            return ""
        return name


    def _on_preset_delete(self):
        name = self._require_selection(
            "Delete Preset", "Select a preset to delete first.")
        if name and delete_preset_flow(self, self.preset_manager, name):
            self.refresh_presets()

    def _on_preset_export(self):
        name = self._require_selection(
            "Export Preset", "Select a preset to export first.")
        if name:
            export_preset_flow(self, self.preset_manager, name)

    def _on_preset_partial_export(self):
        name = self._require_selection(
            "Partial Export", "Select a preset to export first.")
        if name:
            partial_export_preset_flow(self, self.preset_manager, name)

    def _on_preset_import(self):
        if import_preset_flow(self, self.preset_manager):
            self.refresh_presets()

    # ---------- about ----------

    def show_about(self):
        from src.gui.dialogs import AboutProgramDialog
        dialog = AboutProgramDialog(self.window)
        dialog.exec()
