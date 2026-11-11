"""Exercise real exec restarts: language writes must survive process replacement."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.gui.ios.settings import IOSSettingsPage


class LanguageRestartTests(unittest.TestCase):
    def restart(self, target):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                       XDG_CONFIG_HOME=folder, XDG_DATA_HOME=folder)
            code = f'''import sys
from PySide6.QtWidgets import QApplication
from src.controllers.settings import Settings
from src.controllers.translator import Translator
app=QApplication([])
settings=Settings()
settings.setValue('locale_code','en')
settings.sync()
sys.argv=['-c', "from src.controllers.settings import Settings; print(Settings().value('locale_code', 'system', type=str))"]
Translator(app,settings).set_new_language({target!r},restart=True)
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                    env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

    def test_explicit_choice_survives_exec(self):
        self.assertEqual(self.restart('ru'), 'ru')

    def test_system_choice_removal_survives_exec(self):
        self.assertEqual(self.restart(''), 'system')

    def test_selector_compares_mode_not_resolved_system_language(self):
        settings, translator = Mock(), Mock()
        settings.value.return_value = ''
        translator.get_saved_locale_code.return_value = 'ru'
        page = SimpleNamespace(lang_indexes=['', 'ru'],
                               window=SimpleNamespace(settings=settings, translator=translator))
        IOSSettingsPage._on_lang_selected(page, 1)
        translator.set_new_language.assert_called_once_with('ru')
        translator.reset_mock()
        settings.value.return_value = 'ru'
        IOSSettingsPage._on_lang_selected(page, 0)
        translator.set_new_language.assert_called_once_with('')
        translator.reset_mock()
        IOSSettingsPage._on_lang_selected(page, 1)
        translator.set_new_language.assert_not_called()


if __name__ == '__main__':
    unittest.main()
