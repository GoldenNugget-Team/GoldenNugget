"""Passcode Themes: import a ``.passthm`` keypad theme and write it to the
device through the cross-platform AirLift driver (``src.airlift``).

The page stages the theme images (``src.tweaks.passcode_theme``) into the
exact file names the passcode keypad expects and pushes them into
``/var/mobile/Library/Caches/TelephonyUI-10`` (or the 9/8 variant for older
iOS). AirLift can only create **new** files — existing names are reported as
skipped, so re-applying the same theme over itself is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import os
import traceback
from typing import Optional

from PySide6.QtCore import Qt, QCoreApplication, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QMessageBox, QFileDialog, QComboBox,
)

from src.airlift import write_files, AirliftError
from src.tweaks.passcode_theme import (
    PASSTHME_TARGET,
    PASSTHME_TARGETS_ALL,
    KEYPAD_LOCALES_ALL,
    PasscodeThemeError,
    parse_passthm,
    stage_files,
    keypad_code_for_locale,
    theme_size,
)
from src.devicemanagement.session import lockdown_session
from pymobiledevice3.exceptions import (
    NotPairedError, PasswordRequiredError, UserDeniedPairingError,
    PairingDialogResponsePendingError, FatalPairingError,
)
from src.gui.ios.components import (
    IOSSectionHeader, IOSCard, IOSPrimaryButton, IOSDangerButton,
)
from src.gui.theme import ColorThemeManager

logger = logging.getLogger("GoldenNugget.passthme")

_NUGGET = "Nugget"


class PasscodeThemeWriteThread(QThread):
    """Background writer: AirLift the staged theme onto the device."""

    progress = Signal(str)
    done = Signal(bool, str)

    def __init__(self, udid: str, theme_path: str, key_digits: int,
                 locale: str, lang_opt: str, bold: str, target_opt: str,
                 parent=None):
        super().__init__(parent)
        self.udid = udid
        self.theme_path = theme_path
        self.key_digits = key_digits
        self.locale = locale
        self.lang_opt = lang_opt
        self.bold = bold
        self.target_opt = target_opt

    def _emit(self, message: str):
        # Mirror every ATC/airlift line into the session log too — the status
        # label's last line alone doesn't tell whether the sync observed a
        # tolerated SyncFailed and then completed, or was rejected.
        try:
            logging.getLogger("GoldenNugget.passthme").info("atc: %s", message)
        except Exception:
            pass
        self.progress.emit(message)

    def _targets(self) -> list[str]:
        if self.target_opt == "all":
            return list(PASSTHME_TARGETS_ALL)
        return [f"/var/mobile/Library/Caches/TelephonyUI-{self.target_opt}"]

    def _languages(self):
        if self.lang_opt == "all":
            return "all"
        if self.lang_opt:
            return [self.lang_opt]
        return None

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.progress.emit(QCoreApplication.translate("Nugget", "Parsing theme…"))
            keys = parse_passthm(self.theme_path)
            staged = stage_files(
                keys, locale=self.locale, langs=self._languages(), bold=self.bold)
            targets = self._targets()

            self.progress.emit(
                QCoreApplication.translate("Nugget", "Staged {0} key files, {1} targets").format(len(staged), len(targets)))

            written: list[str] = []
            failures: list[str] = []
            try:
                async def apply_all():
                    self.progress.emit(QCoreApplication.translate("Nugget", 
                        "Step 1/3 — Trust check: opening a device session. If "
                        "this computer isn't trusted yet, unlock your iPhone "
                        "and tap \u201cTrust This Computer\u201d now."))
                    async with lockdown_session(self.udid) as lockdown:
                        if not getattr(lockdown, "paired", True):
                            # lockdown_session already refuses unpaired clients,
                            # but keep the belt-and-suspenders check so we
                            # never sync against a half-trusted device.
                            raise AirliftError(QCoreApplication.translate("Nugget", 
                                "the iPhone did not confirm this computer as "
                                "trusted — tap \u201cTrust This Computer\u201d "
                                "on the device and try again"))
                        self.progress.emit(QCoreApplication.translate("Nugget", 
                            "Step 2/3 — Device trust confirmed; staging the "
                            "theme…"))
                        for target in targets:
                            self.progress.emit(
                                QCoreApplication.translate("Nugget", "Writing {0} files to {1}…").format(len(staged), target))
                            result = await write_files(
                                lockdown, target, staged, log_cb=self._emit)
                            written.extend(result["written"])
                            failures.extend(result["failures"])
                        self.progress.emit(QCoreApplication.translate("Nugget", "Step 3/3 — Done."))
                try:
                    loop.run_until_complete(apply_all())
                except PasswordRequiredError:
                    raise RuntimeError(QCoreApplication.translate("Nugget", 
                        "The device is locked. Unlock your iPhone, then tap "
                        "\u201cTrust This Computer\u201d when the dialog appears "
                        "and try again."))
                except UserDeniedPairingError:
                    raise RuntimeError(QCoreApplication.translate("Nugget", 
                        "You declined the trust request on the device. Connect "
                        "your iPhone, tap \u201cTrust This Computer\u201d and "
                        "try again."))
                except (PairingDialogResponsePendingError, NotPairedError, FatalPairingError):
                    raise RuntimeError(QCoreApplication.translate("Nugget", 
                        "The device did not confirm this computer as trusted — "
                        "the Apple\u00ae sync service (ATC) refuses an untrusted "
                        "host and the write would fail. Unlock your iPhone and "
                        "tap \u201cTrust This Computer\u201d, then try again."))
            except (AirliftError, OSError, TimeoutError, ConnectionError) as error:
                raise RuntimeError(f"{type(error).__name__}: {error}") from error

            lines = [
                QCoreApplication.translate("Nugget", "Wrote {0} file(s) to the device.").format(len(written)),
            ]
            if failures:
                lines.append(
                    QCoreApplication.translate("Nugget", "{0} file(s) skipped — they already exist (AirLift only "
                        "writes new names). Remove the old keypad cache first to "
                        "replace an existing theme.").format(len(failures)))
            self.done.emit(True, "\n".join(lines))
        except Exception as error:
            logging.getLogger("GoldenNugget.passthme").error(
                "Passcode theme write failed: %s\n%s", error, traceback.format_exc())
            self.done.emit(False, f"{type(error).__name__}: {error}")
        finally:
            loop.close()


class IOSPasscodeThemePage(QWidget):
    """iOS-style page to import a ``.passthm`` and push it to the device."""

    LANG_DEVICE = ""
    LANG_ALL = "all"

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        self._theme_path: Optional[str] = None
        self._key_digits = 0
        self._worker: Optional[PasscodeThemeWriteThread] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        content = QWidget()
        self._scroll.setWidget(content)
        layout.addWidget(self._scroll)

        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(16, 16, 16, 32)
        self.content_layout.setSpacing(8)

        self._hint = QLabel(QCoreApplication.translate("Nugget", 
            "Customize the Passcode keypad with a theme package (.passthm) — "
            "images, sub-labels and bold keys. Themes are written straight to "
            "the device over USB/Wi-Fi (no reboot).\n\n"
            "AirLift only creates NEW files on the device: re-applying the "
            "same theme is a no-op, and replacing an existing theme with "
            "different art requires removing the old keypad cache first."))
        self._hint.setWordWrap(True)
        self.content_layout.addWidget(self._hint)

        # ---- Theme --------------------------------------------------------
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Theme")))

        self.theme_placeholder = QLabel(QCoreApplication.translate("Nugget", "No theme selected yet."))
        self.theme_placeholder.setAlignment(Qt.AlignCenter)
        self.theme_placeholder.setStyleSheet("padding: 24px 0;")
        self.content_layout.addWidget(self.theme_placeholder)

        self._theme_card_box = QVBoxLayout()
        self._theme_card_box.setSpacing(8)
        self.content_layout.addLayout(self._theme_card_box)

        self._choose_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Choose .passthm…"))
        self._choose_btn.clicked.connect(self.choose_theme_dialog)
        self.content_layout.addWidget(self._choose_btn)

        # ---- Options ------------------------------------------------------
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Options")))

        options_card = IOSCard()
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(16, 12, 16, 12)
        options_layout.setSpacing(12)

        self._lang_combo = QComboBox()
        options_layout.addLayout(self._row(
            QCoreApplication.translate("Nugget", "Keypad Language"), self._lang_combo))
        self._populate_lang_combo()

        self._bold_combo = QComboBox()
        options_layout.addLayout(self._row(QCoreApplication.translate("Nugget", "Bold Keys"), self._bold_combo))
        self._populate_bold_combo()

        self._target_combo = QComboBox()
        options_layout.addLayout(self._row(
            QCoreApplication.translate("Nugget", "Target TelephonyUI"), self._target_combo))
        self._populate_target_combo()

        self.content_layout.addWidget(options_card)

        # ---- Write to device ----------------------------------------------
        self.content_layout.addWidget(IOSSectionHeader(QCoreApplication.translate("Nugget", "Write to device")))

        self._device_lbl = QLabel("")
        self._device_lbl.setWordWrap(True)
        self.content_layout.addWidget(self._device_lbl)

        self._write_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Write Theme to Device"))
        self._write_btn.clicked.connect(self.start_write)
        self.content_layout.addWidget(self._write_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.hide()
        self.content_layout.addWidget(self._status_lbl)

        self.content_layout.addStretch()

        self._retheme()
        self._load_settings()
        self._refresh_device_line()

    def _row(self, label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        text = QLabel(label)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        row.addWidget(widget)
        return row

    def _populate_lang_combo(self):
        self._lang_combo.blockSignals(True)
        self._lang_combo.clear()
        self._lang_combo.addItem(QCoreApplication.translate("Nugget", "Device Language"), self.LANG_DEVICE)
        self._lang_combo.addItem(QCoreApplication.translate("Nugget", "All Languages"), self.LANG_ALL)
        for code in KEYPAD_LOCALES_ALL:
            self._lang_combo.addItem(self._lang_label(code), code)
        self._lang_combo.blockSignals(False)

    @staticmethod
    def _lang_label(code: str) -> str:
        names = {
            "en": "English", "other": "Others", "ru": "Русский", "uk": "Українська",
            "es": "Español", "fr": "Français", "de": "Deutsch", "it": "Italiano",
            "pt": "Português", "tr": "Türkçe", "pl": "Polski", "nl": "Nederlands",
            "ja": "日本語", "ko": "한국어", "zh": "中文", "ar": "العربية", "he": "עברית",
        }
        return f"{code} — {names.get(code, code)}"

    def _populate_bold_combo(self):
        self._bold_combo.blockSignals(True)
        self._bold_combo.clear()
        self._bold_combo.addItem(QCoreApplication.translate("Nugget", "Both (Regular + Bold)"), "both")
        self._bold_combo.addItem(QCoreApplication.translate("Nugget", "Regular only"), "regular")
        self._bold_combo.addItem(QCoreApplication.translate("Nugget", "Bold only"), "bold")
        self._bold_combo.blockSignals(False)

    def _populate_target_combo(self):
        self._target_combo.blockSignals(True)
        self._target_combo.clear()
        self._target_combo.addItem("TelephonyUI-10 (iOS 27)", "10")
        self._target_combo.addItem("TelephonyUI-9 (iOS 26.x)", "9")
        self._target_combo.addItem("TelephonyUI-8 (older)", "8")
        self._target_combo.addItem(QCoreApplication.translate("Nugget", "All (8, 9, 10)"), "all")
        self._target_combo.blockSignals(False)

    # ---- theme lifecycle -------------------------------------------------

    def _load_settings(self):
        settings = self.window.settings
        path = settings.value("passcode_theme_path", "", type=str)
        if path and os.path.isfile(path):
            try:
                keys = parse_passthm(path)
                self._apply_theme(path, keys)
            except (PasscodeThemeError, OSError):
                settings.setValue("passcode_theme_path", "")
        lang = settings.value("passcode_theme_lang", self.LANG_DEVICE, type=str)
        bold = settings.value("passcode_theme_bold", "both", type=str)
        target = settings.value("passcode_theme_target", "10", type=str)
        self._set_combo_value(self._lang_combo, lang, self.LANG_DEVICE)
        self._set_combo_value(self._bold_combo, bold, "both")
        self._set_combo_value(self._target_combo, target, "10")
        self._refresh_theme_area()

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str, default: str):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else combo.findData(default))

    def _save_options(self):
        settings = self.window.settings
        settings.setValue("passcode_theme_lang",
                          self._lang_combo.currentData())
        settings.setValue("passcode_theme_bold",
                          self._bold_combo.currentData())
        settings.setValue("passcode_theme_target",
                          self._target_combo.currentData())
        self.window._sync_settings()

    def choose_theme_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, QCoreApplication.translate("Nugget", "Choose a Passcode Theme"), "", QCoreApplication.translate("Nugget", "passthemes (*.passthm)"))
        if not path:
            return
        try:
            keys = parse_passthm(path)
        except PasscodeThemeError as error:
            QMessageBox.warning(self.window, QCoreApplication.translate("Nugget", "Invalid Theme"),
                                f"{type(error).__name__}: {error}")
            return
        self._apply_theme(path, keys)
        self.window.settings.setValue("passcode_theme_path", path)
        self.window._sync_settings()

    def _apply_theme(self, path: str, keys: dict[str, bytes]):
        self._theme_path = path
        self._key_digits = len(keys)
        self._refresh_theme_area()

    def _remove_theme(self):
        self._theme_path = None
        self._key_digits = 0
        self.window.settings.setValue("passcode_theme_path", "")
        self.window._sync_settings()
        self._refresh_theme_area()

    def _refresh_theme_area(self):
        c = ColorThemeManager.instance().colors
        has_theme = self._theme_path is not None
        self.theme_placeholder.setVisible(not has_theme)
        while self._theme_card_box.count():
            item = self._theme_card_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not has_theme:
            return
        card = IOSCard()
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(os.path.basename(self._theme_path) or self._theme_path)
        name.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {c.text_primary};")
        name.setWordWrap(True)
        text_col.addWidget(name)
        size = theme_size(self._theme_path)
        size_hint = ""
        if size == 1:
            size_hint = QCoreApplication.translate("Nugget", ", small keys")
        elif size == 2:
            size_hint = QCoreApplication.translate("Nugget", ", big keys")
        detail = QLabel(QCoreApplication.translate("Nugget", "{0} key images{1}").format(self._key_digits, size_hint))
        detail.setStyleSheet(f"font-size: 12px; color: {c.text_secondary};")
        text_col.addWidget(detail)
        row.addLayout(text_col, 1)

        remove_btn = QPushButton(QCoreApplication.translate("Nugget", "Remove"))
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setStyleSheet(
            f"QPushButton {{ background-color: {c.surface_hover}; color: {c.error}; "
            f"border: 1px solid {c.border}; border-radius: 12px; padding: 8px 14px; }}"
            f"QPushButton:hover {{ background-color: {c.error}; color: {c.text_inverse}; }}")
        remove_btn.clicked.connect(self._remove_theme)
        row.addWidget(remove_btn)
        self._theme_card_box.addWidget(card)

    # ---- write flow ------------------------------------------------------

    def _device_locale(self) -> str:
        try:
            device = self.window.device_manager.data_singleton.current_device
            return getattr(device, "locale", "") or ""
        except Exception:
            return ""

    def _refresh_device_line(self):
        c = ColorThemeManager.instance().colors
        dm = self.window.device_manager
        device = None
        try:
            device = dm.data_singleton.current_device
        except Exception:
            pass
        if device is None:
            self._device_lbl.setText(QCoreApplication.translate("Nugget", 
                "No trusted iPhone connected. Plug it in, unlock it, tap "
                "\u201cTrust This Computer\u201d when iOS asks, and wait for it "
                "to appear here."))
            self._device_lbl.setStyleSheet(f"color: {c.error}; font-size: 13px;")
            return
        version = getattr(device, "version", "")
        build = getattr(device, "build", "")
        model = getattr(device, "model", "")
        self._device_lbl.setText(QCoreApplication.translate("Nugget", 
            "Device: {0} — iOS {1} ({2}). This computer is trusted by it, so "
            "the write runs immediately — no \u201cTrust This Computer\u201d "
            "pop-up will appear.").format(
                model or QCoreApplication.translate("Nugget", "iPhone"), version or "?", build or "?"))
        self._device_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        if not dm.data_singleton.device_available:
            self._device_lbl.setText(QCoreApplication.translate("Nugget", 
                "Device present, but it is not supported for AirLift (needs an "
                "iPhone on iOS 26.2+)."))
            self._device_lbl.setStyleSheet(f"color: {c.error}; font-size: 13px;")

    def start_write(self):
        self._save_options()
        self._refresh_device_line()
        if not self._theme_path:
            self._show_status(QCoreApplication.translate("Nugget", "Choose a theme first."), "error")
            return
        udid = self.window.device_manager.get_current_device_udid()
        if not udid:
            self._show_status(
                QCoreApplication.translate("Nugget", "No trusted iPhone is listed. Plug it in, unlock it, tap "
                    "\u201cTrust This Computer\u201d when iOS asks, then wait "
                    "for it to appear."),
                "error")
            return
        if not self.window.device_manager.data_singleton.device_available:
            self._show_status(
                QCoreApplication.translate("Nugget", "This device is not supported for AirLift (needs an "
                    "iPhone on iOS 26.2+)."),
                "error")
            return

        if self._worker is not None and self._worker.isRunning():
            self._show_status(QCoreApplication.translate("Nugget", "A write is already running."), "info")
            return

        locale = self._device_locale()
        self._write_btn.setEnabled(False)
        self._show_status(QCoreApplication.translate("Nugget", "Starting…"), "info")

        self._worker = PasscodeThemeWriteThread(
            udid=udid,
            theme_path=self._theme_path,
            key_digits=self._key_digits,
            locale=locale,
            lang_opt=self._lang_combo.currentData(),
            bold=self._bold_combo.currentData(),
            target_opt=self._target_combo.currentData(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        # Clean teardown: deleteLater after run() returns, and only drop our
        # reference once the native thread is finished (clearing it in
        # ``_on_done`` would free the QThread object while run() is still
        # winding down -> "QThread: Destroyed while thread '...' is still
        # running" hard abort at app shutdown).
        self._worker.finished.connect(self._on_write_thread_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_progress(self, message: str):
        self._show_status(message, "info")

    def _on_done(self, success: bool, message: str):
        self._write_btn.setEnabled(True)
        self._show_status(message, "success" if success else "error")
        try:
            if self.window.isVisible():
                QMessageBox.information(
                    self.window,
                    QCoreApplication.translate("Nugget", "Passcode Theme"),
                    message if success else QCoreApplication.translate("Nugget", "Apply failed:\n\n{0}").format(message),
                )
        except RuntimeError:
            pass

    def _on_write_thread_finished(self):
        # run() returned, so the native thread is done; drop the reference
        # (deleteLater is already queued via the other connection).
        try:
            self._worker = None
        except Exception:
            pass

    def _show_status(self, text: str, kind: str):
        c = ColorThemeManager.instance().colors
        color = {"success": c.success, "error": c.error}.get(kind, c.accent)
        self._status_lbl.setStyleSheet(f"font-size: 13px; color: {color};")
        self._status_lbl.setText(text)
        self._status_lbl.show()

    # ---- theme reactivity --------------------------------------------------

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(
            f"background-color: {c.bg_primary}; border: none;")
        self._hint.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        self.theme_placeholder.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 15px; padding: 24px 0;")
        self._lang_combo.setStyleSheet(
            f"QComboBox {{ background-color: {c.bg_secondary}; color: {c.text_primary}; "
            f"border: 1px solid {c.border}; border-radius: 10px; padding: 6px 10px; }}")
        self._bold_combo.setStyleSheet(self._lang_combo.styleSheet())
        self._target_combo.setStyleSheet(self._lang_combo.styleSheet())
        self._status_lbl.setStyleSheet(f"font-size: 13px; color: {c.accent};")
        self._refresh_theme_area()
        self._refresh_device_line()