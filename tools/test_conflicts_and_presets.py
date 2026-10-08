"""Offline conflict detection and preset exchange regressions (no device)."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from src.controllers.tweak_conflicts import find_conflicts, current_conflicts
from src.controllers.preset_manager import PresetManager
from src.tweaks.tweak_classes import BasicPlistTweak, AdvancedPlistTweak, CompanionKeyTweak, NullifyFileTweak
from src.tweaks.tweak_names import TweakID
from src.tweaks.basic_plist_locations import FileLocation


def enabled(tweak):
    tweak.enabled = True
    return tweak


class Conflicts(unittest.TestCase):
    def test_same_key_different_values_and_disabled_writer(self):
        first = enabled(BasicPlistTweak(FileLocation.uikit, 'key', True))
        second = enabled(BasicPlistTweak(FileLocation.uikit, 'key', False))
        selected = {TweakID.RTL: first, TweakID.LTR: second}
        self.assertEqual(len(find_conflicts(selected)), 1)
        second.value = True
        # Test same-key duplicates without the independent RTL/LTR rule.
        selected = {TweakID.RTL: first, TweakID.SBBuildNumber: second}
        self.assertEqual(find_conflicts(selected), [])
        second.value = 1  # plist bool and integer are distinct even though Python == says equal
        self.assertEqual(len(find_conflicts(selected)), 1)
        second.enabled = False
        self.assertEqual(find_conflicts(selected), [])

    def test_real_layout_conflict(self):
        selected = {TweakID.RTL: enabled(BasicPlistTweak(FileLocation.globalPreferences, 'RTL', True)),
                    TweakID.LTR: enabled(BasicPlistTweak(FileLocation.globalPreferences, 'LTR', True))}
        self.assertEqual(len(find_conflicts(selected)), 1)
        selected[TweakID.LTR].value = False
        self.assertEqual(find_conflicts(selected), [])

    def test_companion_keys_and_replacement_order(self):
        first = enabled(CompanionKeyTweak(FileLocation.uikit, 'first', True, companion_keys={'second': True}))
        second = enabled(BasicPlistTweak(FileLocation.uikit, 'second', False))
        self.assertEqual(len(find_conflicts({TweakID.RTL: first, TweakID.LTR: second})), 1)
        replacement = enabled(AdvancedPlistTweak(FileLocation.uikit, {'other': True}))
        self.assertEqual(len(find_conflicts({TweakID.RTL: first, TweakID.SBBuildNumber: replacement})), 1)
        self.assertEqual(find_conflicts({TweakID.SBBuildNumber: replacement, TweakID.RTL: first}), [])
        self.assertEqual(first.companion_keys, {'second': True})

    def test_clear_file_conflict(self):
        selected = {TweakID.RTL: enabled(BasicPlistTweak(FileLocation.uikit, 'key', True)),
                    TweakID.ClearScreenTimeAgentPlist: enabled(NullifyFileTweak(FileLocation.uikit))}
        self.assertEqual(len(find_conflicts(selected)), 1)

    def test_hotload_skipped_tweaks_do_not_conflict(self):
        selected = {TweakID.RTL: enabled(BasicPlistTweak(FileLocation.uikit, 'key', True)),
                    TweakID.LTR: enabled(BasicPlistTweak(FileLocation.uikit, 'key', False))}
        hotload = Mock()
        hotload.hidden_tweak_names.return_value = {'LTR'}
        hotload.rule_for.return_value = None
        manager = SimpleNamespace(pref_manager=SimpleNamespace(settings=None),
                                  get_current_device_version=lambda:'27.0',
                                  get_current_device_model=lambda:'iPhone16,1')
        with patch('src.controllers.hotload.HotLoad', return_value=hotload), \
             patch('src.tweaks.tweaks.tweaks', selected), \
             patch('src.tweaks.tweak_loader.load_plist_tweaks'), \
             patch('src.tweaks.tweak_loader.load_daemons'):
            self.assertEqual(current_conflicts(manager), [])
            hotload.hidden_tweak_names.return_value = set()
            hotload.rule_for.side_effect = lambda tid, **kw: {} if tid == TweakID.LTR else None
            self.assertEqual(current_conflicts(manager), [])

    def test_warning_defaults_to_review_and_requires_explicit_continue(self):
        from PySide6.QtWidgets import QApplication, QWidget
        from src.gui.main_window_mixins import ApplyMixin
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.device_manager = Mock()
        conflict = Mock()
        conflict.description.return_value = 'Two incompatible choices'
        from src.gui.main_window_mixins import QtWidgets
        with patch('src.controllers.tweak_conflicts.current_conflicts', return_value=[conflict]), \
             patch.object(QtWidgets.QMessageBox, 'exec', return_value=0), \
             patch.object(QtWidgets.QMessageBox, 'clickedButton', return_value=None):
            self.assertFalse(ApplyMixin._confirm_tweak_conflicts(parent))
        def continue_dialog(dialog):
            self.assertEqual(dialog.defaultButton().text(), 'Review selection')
            self.assertEqual(dialog.escapeButton().text(), 'Review selection')
            button = next(b for b in dialog.buttons() if b.text() == 'Continue anyway')
            button.click()
            return 0
        with patch('src.controllers.tweak_conflicts.current_conflicts', return_value=[conflict]), \
             patch.object(QtWidgets.QMessageBox, 'exec', continue_dialog):
            self.assertTrue(ApplyMixin._confirm_tweak_conflicts(parent))
        parent.close()


class PresetExchange(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pm = PresetManager.__new__(PresetManager)
        self.pm.presets_dir = str(Path(self.tmp.name) / 'presets')
        Path(self.pm.presets_dir).mkdir()
        self.source = Path(self.tmp.name) / 'import.json'

    def test_roundtrip_and_duplicate_name_keep_selections(self):
        selected = {TweakID.RTL: enabled(BasicPlistTweak(FileLocation.globalPreferences, 'RTL', True)),
                    TweakID.LTR: BasicPlistTweak(FileLocation.globalPreferences, 'LTR', False)}
        with patch('src.controllers.preset_manager.tweaks', selected):
            self.assertTrue(self.pm.save_preset('Shared', description='Shared', tags=['test']))
            self.assertTrue(self.pm.export_preset('Shared', str(self.source)))
            expected = json.loads(self.source.read_text(encoding='utf-8'))['tweaks']
            selected[TweakID.RTL].enabled = False
            ok, name = self.pm.import_preset(str(self.source))
            self.assertTrue(ok)
            self.assertNotEqual(name, 'Shared')
            self.assertFalse(selected[TweakID.RTL].enabled)  # importing does not activate it
            loaded = json.loads(Path(self.pm.get_preset_path(name)).read_text(encoding='utf-8'))
            self.assertEqual(loaded['tweaks'], expected)
            with patch.object(self.pm, '_load_all_tweaks'), \
                 patch('src.tweaks.hidden.current_hidden_tweak_names', return_value=set()):
                self.assertTrue(self.pm.load_preset(name))
            self.assertTrue(selected[TweakID.RTL].enabled)

    def test_partial_export_and_legacy_import(self):
        self.source.write_text(json.dumps({'tweaks': {'RTL': {'enabled': True}, 'LTR': {'enabled': False}}}), encoding='utf-8')
        ok, name = self.pm.import_preset(str(self.source))
        self.assertTrue(ok)
        self.assertTrue(self.pm.export_preset(name, str(self.source), include=[TweakID.RTL]))
        data = json.loads(self.source.read_text(encoding='utf-8'))
        self.assertEqual(set(data['tweaks']), {'RTL'})
        self.assertTrue(data['metadata']['partial'])
        self.assertTrue(self.pm.import_preset(str(self.source))[0])

    def test_malformed_files_are_not_saved(self):
        for value in ([], {}, {'metadata': {}}, {'tweaks': []},
                      {'tweaks': {'RTL': True}}, {'tweaks': {}, 'metadata': {'tags': 'bad'}},
                      {'tweaks': {'RTL': {'enabled': 'false'}}},
                      {'tweaks': {'Daemons': {'value': []}}},
                      {'tweaks': {'StatusBar': {'override_data': '??'}}}):
            with self.subTest(value=value):
                self.source.write_text(json.dumps(value), encoding='utf-8')
                self.assertFalse(self.pm.import_preset(str(self.source))[0])
                self.assertEqual(list(Path(self.pm.presets_dir).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
