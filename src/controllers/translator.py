from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from src.qt.mainwindow_ui import Ui_Nugget


class Translator:
    def __init__(self, app: QApplication, settings: QSettings):
        self.app = app
        self.settings = settings
        self._installed_translators = []

    def get_saved_locale_code(self) -> str:
        saved = self.settings.value("locale_code", "", type=str)
        return saved if saved else self.system_locale_code()
    def system_locale_code(self) -> str:
        """Best matching app-locale code for the OS language (e.g. 'ru',
        'es_MX', 'zh_CN'); falls back to 'en'."""
        from src.gui.pages.main.settings import available_languages
        codes = set(available_languages.values())
        sys_locale = QLocale.system()
        name = sys_locale.name()  # e.g. "ru_RU", "es_MX", "zh_CN"
        if name in codes:
            return name
        base = sys_locale.languageToCode(sys_locale.language())
        if base in codes:
            return base
        return "en"
    def set_default_locale(self, code: str):
        QLocale.setDefault(QLocale(code))
    def set_new_language(self, code: str, restart: bool = False):
        from src.controllers.live_translation import (
            apply_translatable_ui,
            collect_translatable_ui,
        )
        snapshot = collect_translatable_ui(self.app, self._disk_translations_path(), QLocale().name())
        if not code:
            self.settings.remove("locale_code")
            code = self.system_locale_code()
        else:
            self.settings.setValue("locale_code", code)
        # exec replaces this process without running QSettings destructors.
        # Flush the explicit choice (or removal for System) before restarting.
        self.settings.sync()
        self.set_default_locale(code)
        self.load_translations()
        self.app.setLayoutDirection(QLocale().textDirection())
        apply_translatable_ui(snapshot)
        if restart:
            from src.utils.restart import restart_app
            restart_app()

    def load_translations(self):
        for previous in self._installed_translators:
            self.app.removeTranslator(previous)
            previous.deleteLater()
        self._installed_translators = []
        qt_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        qt_base = QTranslator(self.app)
        if qt_base.load(QLocale(), 'qtbase', '_', qt_path):
            self.app.installTranslator(qt_base)
            self._installed_translators.append(qt_base)

        app_tr = self._load_app_translations()
        if app_tr is not None:
            self.app.installTranslator(app_tr)
            self._installed_translators.append(app_tr)
        # UI additions are kept apart from catalogs replaced by i18n sync.
        ui_tr = self._load_app_translations('GoldenNuggetUI', ':/ui_translations')
        if ui_tr is not None:
            self.app.installTranslator(ui_tr)
            self._installed_translators.append(ui_tr)

    def _load_app_translations(self, prefix='Nugget', resource_prefix=':/translations') -> "QTranslator":
        """Load the app's own ``translations/Nugget_<locale>.qm``.

        Tries the on-disk translations folder first (bundled by PyInstaller
        via ``--add-data=src/qt:src/qt`` or present in the source tree on
        Windows dev runs), then falls back to the compiled-in Qt resource
        (``:/translations``). Returns the live translator or None.
        """
        translator = QTranslator(self.app)
        disk = self._disk_translations_path()
        if os.path.isdir(disk):
            try:
                # Files live as ``Nugget_<locale>.qm`` directly inside the
                # directory (no extra "translations/" prefix component).
                if translator.load(QLocale(), prefix, '_', disk):
                    return translator
            except Exception:
                pass
        try:
            # Compiled-in resource: ``:/translations/translations/Nugget_<loc>.qm``
            if translator.load(QLocale(), 'translations/' + prefix, '_', resource_prefix):
                return translator
        except Exception:
            pass
        return None

    def _disk_translations_path(self) -> str:
        """Directory holding the app's .qm files on disk (bundled or source)."""
        base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(base, "src", "qt", "translations")

    def fix_ui_for_rtl(self, ui: Ui_Nugget):
        curr_locale = self.get_saved_locale_code()
        if curr_locale == "ar" or curr_locale == "ar_SA" or curr_locale == "ar_EG":
            # need to correct for stuff
            # TOP BAR
            ui.phoneIconBtn.setStyleSheet("QToolButton {\n	border-top-left-radius: 0px;\n	border-bottom-left-radius: 0px;\n}")
            ui.titleBar.setStyleSheet("QToolButton {\n	border-top-right-radius: 0px;\n	border-bottom-right-radius: 0px;\n}")
            # HOME PAGE
            ui.leminTwitterBtn.setStyleSheet("QToolButton {\n	border-top-left-radius: 0px;\n	border-bottom-left-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n	border-left: none;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
            ui.leminKoFiBtn.setStyleSheet("QToolButton {\n	border-top-right-radius: 0px;\n	border-bottom-right-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
            ui.posterRestoreBtn.setStyleSheet("QToolButton {\n	border-top-left-radius: 0px;\n	border-bottom-left-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n	border-left: none;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
            ui.translatorsBtn.setStyleSheet("QToolButton {\n	border-top-left-radius: 0px;\n	border-bottom-left-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n	border-left: none;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
            ui.mikasaBtn.setStyleSheet("QToolButton {\n	border-top-right-radius: 0px;\n	border-bottom-right-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
            ui.qtBtn.setStyleSheet("QToolButton {\n	border-top-right-radius: 0px;\n	border-bottom-right-radius: 0px;\n	background: none;\n	border: 1px solid #3b3b3b;\n}\n\nQToolButton:pressed {\n    background-color: #535353;\n    color: #FFFFFF;\n}")
