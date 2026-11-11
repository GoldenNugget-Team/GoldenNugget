"""Offline risk assessment and share-code / QR regressions (no device)."""
import base64
import json
import os
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QTranslator
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import resources_rc  # noqa: F401  (icons used by the dialogs)

from src.controllers import share_code
from src.controllers.hotload import HotLoad
from src.controllers.preset_manager import PresetManager
from src.controllers.risk_assessment import (
    TWEAK_RISKS,
    RiskLevel,
    apply_factors,
    assess,
)

ON = {'enabled': True, 'value': True}


def hotload_with(rules):
    hotload = HotLoad(None)
    hotload._rules = {'version': 1, 'rules': rules}
    return hotload


class Risk(unittest.TestCase):
    def test_empty_selection_is_low_without_reasons(self):
        report = assess({'RTL': {'enabled': False}}, '26.2', 'iPhone15,2')
        self.assertEqual(report.level, RiskLevel.LOW)
        self.assertEqual(report.factors, [])

    def test_known_risky_tweaks_and_daemons(self):
        self.assertEqual(assess({'RTL': ON}).level, RiskLevel.MEDIUM)
        daemons = {'enabled': True, 'value': {'com.apple.thermalmonitord': True,
                                              'com.apple.locationd': False}}
        report = assess({'Daemons': daemons})
        self.assertEqual(report.level, RiskLevel.HIGH)
        self.assertEqual(len(report.factors), 1, 'location is not disabled, so only thermal counts')
        daemons['enabled'] = False
        self.assertEqual(assess({'Daemons': daemons}).factors, [])

    def test_incompatible_tweak_is_high(self):
        # SBAlwaysShowSystemApertureInSnapshots is iPhone-only.
        report = assess({'SBAlwaysShowSystemApertureInSnapshots': ON}, '26.2', 'iPad14,1')
        self.assertEqual(report.level, RiskLevel.HIGH)

    def test_many_changes_and_debug_options(self):
        from src.tweaks.registry import SPECS_BY_ID, Section
        names = [spec.id.name for spec in SPECS_BY_ID.values()
                 if spec.section == Section.LIQUID_GLASS and spec.min_version == '27.0'
                 and spec.id.name not in TWEAK_RISKS][:21]
        report = assess({name: ON for name in names}, '27.0', 'iPhone17,1')
        levels = sorted(factor.level for factor in report.factors)
        self.assertEqual(levels, [RiskLevel.LOW, RiskLevel.MEDIUM])

    def test_apply_factors(self):
        self.assertEqual(apply_factors(battery={'percent': 15, 'charging': False})[0].level, RiskLevel.HIGH)
        self.assertEqual(apply_factors(battery={'percent': 15, 'charging': True}), [])
        self.assertEqual(apply_factors(battery={'percent': 80, 'charging': False}), [])
        self.assertEqual(apply_factors(storage_low=True)[0].level, RiskLevel.HIGH)
        report = assess({}, extra=apply_factors(conflicts=2, first_apply=True))
        self.assertEqual(report.level, RiskLevel.MEDIUM)
        self.assertEqual(report.sorted_factors()[0].level, RiskLevel.MEDIUM)

    def test_remote_risk_rules_warn_but_never_block(self):
        hotload = hotload_with([
            {'action': 'risk', 'tweak': 'SBBuildNumber', 'level': 'high',
             'reason': 'Respring loop reported', 'min_version': '27.0', 'max_version': '27.0.9'},
            {'action': 'risk', 'tweak': 'SBDisableIconParallax', 'level': 'nonsense'},
        ])
        self.assertIsNone(hotload.rule_for('SBBuildNumber', '27.0', 'iPhone17,1'))
        selection = {'SBBuildNumber': ON, 'SBDisableIconParallax': ON}
        report = assess(selection, '27.0', 'iPhone17,1', hotload=hotload)
        self.assertEqual(report.level, RiskLevel.HIGH)
        self.assertTrue(any('Respring loop reported' in f.text for f in report.factors))
        self.assertTrue(any(f.level == RiskLevel.MEDIUM for f in report.factors), 'bad level falls back to medium')
        self.assertEqual(assess(selection, '26.2', 'iPhone17,1', hotload=hotload).level, RiskLevel.MEDIUM)
        self.assertEqual(assess({'SBBuildNumber': {'enabled': False}}, '27.0', hotload=hotload).factors, [])

    def test_summary_requires_acknowledgement_for_high_risk(self):
        from src.gui.ios.components import IOSSummaryDialog
        from src.gui.ios.risk_panel import RiskPanel
        panel = RiskPanel(assess({'RTL': ON}))
        dialog = IOSSummaryDialog('Apply', ['• 1'], header_widget=panel,
                                  acknowledge_text='I understand')
        self.assertFalse(dialog.confirm_btn.isEnabled())
        dialog.acknowledge.setChecked(True)
        self.assertTrue(dialog.confirm_btn.isEnabled())
        self.assertIs(panel.parent(), dialog)
        plain = IOSSummaryDialog('Apply', ['• 1'])
        self.assertTrue(plain.confirm_btn.isEnabled())
        self.assertIsNone(plain.acknowledge)


class ShareCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pm = PresetManager.__new__(PresetManager)
        self.pm.presets_dir = str(Path(self.tmp.name) / 'presets')
        Path(self.pm.presets_dir).mkdir()

    def raw_code(self, payload):
        raw = json.dumps(payload).encode()
        return share_code.PREFIX + base64.urlsafe_b64encode(zlib.compress(raw)).decode().rstrip('=')

    def test_roundtrip_keeps_selected_and_turns_the_rest_off(self):
        data = {'RTL': {'type': 'BasicPlistTweak', 'enabled': True, 'value': True},
                'LTR': {'type': 'BasicPlistTweak', 'enabled': False, 'value': True},
                'Templates': {'templates': ['/home/me/a.batter']},
                'Daemons': {'enabled': True, 'value': {'com.apple.tipsd': True}}}
        code = share_code.encode(data, 'Мой сетап', 'desc', '26.2')
        self.assertTrue(code.startswith('GN1.'))
        self.assertNotIn('/home/me', zlib.decompress(base64.urlsafe_b64decode(code[4:] + '==')).decode())
        decoded = share_code.decode(f'look: {code} cool', self.pm._valid_import_structure)
        self.assertEqual(decoded['shared_count'], 2)
        self.assertEqual(decoded['metadata']['name'], 'Мой сетап')
        self.assertEqual(decoded['metadata']['ios_version'], '26.2')
        tweaks = decoded['tweaks']
        self.assertEqual(tweaks['RTL'], {'enabled': True, 'value': True})
        self.assertEqual(tweaks['LTR'], {'enabled': False})
        self.assertEqual(tweaks['Daemons']['value'], {'com.apple.tipsd': True})
        self.assertNotIn('Templates', tweaks)
        self.assertNotIn('PosterBoard', tweaks)

    def test_code_survives_line_breaks_from_chat_apps(self):
        code = share_code.encode({'RTL': ON})
        wrapped = '\n'.join(code[i:i + 20] for i in range(0, len(code), 20))
        self.assertEqual(share_code.extract(wrapped), code)

    def test_rejects_bad_input(self):
        for text in ('', 'hello', 'GN1.!!!!', 'GN1.' + 'A' * 7000):
            with self.assertRaises(share_code.ShareCodeError):
                share_code.decode(text)
        with self.assertRaises(share_code.ShareCodeError):
            share_code.decode(self.raw_code({'v': 2, 't': {}}))
        with self.assertRaises(share_code.ShareCodeError):
            share_code.decode(self.raw_code({'v': 1, 't': {'RTL': 'not a dict'}}),
                              self.pm._valid_import_structure)
        bomb = share_code.PREFIX + base64.urlsafe_b64encode(
            zlib.compress(b' ' * (share_code.MAX_JSON_BYTES * 4), 9)).decode()
        self.assertLess(len(bomb), share_code.MAX_CODE_CHARS)
        with self.assertRaises(share_code.ShareCodeError):
            share_code.decode(bomb)
        with self.assertRaises(share_code.ShareCodeError):
            share_code.encode({'RTL': {'enabled': False}})

    def test_unknown_and_local_only_names_are_dropped(self):
        decoded = share_code.decode(self.raw_code({'v': 1, 't': {
            'RTL': ON, 'NotATweak': ON, 'PosterBoard': ON, 'IconThemes': {'themes': []}}}))
        self.assertEqual(decoded['shared_count'], 1)
        self.assertNotIn('NotATweak', decoded['tweaks'])

    def test_truncated_compressed_code_is_rejected_even_if_json_is_intact(self):
        raw = json.dumps({'v': 1, 't': {'RTL': ON}}).encode()
        # The final four bytes are zlib's checksum, after the JSON payload.
        compressed = zlib.compress(raw)[:-4]
        code = share_code.PREFIX + base64.urlsafe_b64encode(compressed).decode().rstrip('=')
        with self.assertRaises(share_code.ShareCodeError):
            share_code.decode(code)

    def test_qr_roundtrip(self):
        code = share_code.encode({'RTL': ON, 'SBBuildNumber': ON}, 'QR')
        self.assertEqual(share_code.read_qr_array(share_code.qr_image(code)), code)
        path = Path(self.tmp.name) / 'qr шифр.png'
        import cv2
        ok, buffer = cv2.imencode('.png', share_code.qr_image(code, module=3))
        self.assertTrue(ok)
        buffer.tofile(str(path))
        self.assertEqual(share_code.read_qr(str(path)), code)

    def test_foreign_qr_and_missing_qr(self):
        import cv2
        import numpy as np
        foreign = cv2.QRCodeEncoder.create().encode('https://example.com')
        foreign = cv2.copyMakeBorder(cv2.resize(foreign, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST),
                                     32, 32, 32, 32, cv2.BORDER_CONSTANT, value=255)
        with self.assertRaises(share_code.ShareCodeError):
            share_code.read_qr_array(foreign)
        with self.assertRaises(share_code.ShareCodeError):
            share_code.read_qr_array(np.full((200, 200), 255, dtype=np.uint8))

    def test_import_stores_a_preset_without_activating_it(self):
        from src.tweaks.basic_plist_locations import FileLocation
        from src.tweaks.tweak_classes import BasicPlistTweak
        from src.tweaks.tweak_names import TweakID
        live = {TweakID.RTL: BasicPlistTweak(FileLocation.globalPreferences, 'RTL', True)}
        code = share_code.encode({'RTL': ON}, 'Friend')
        with patch('src.controllers.preset_manager.tweaks', live):
            first = self.pm.import_share_code(code)
            second = self.pm.import_share_code(code)
        self.assertEqual((first, second), ('Friend', 'Friend 1'))
        self.assertFalse(live[TweakID.RTL].enabled)
        stored = self.pm.read_preset('Friend')
        self.assertTrue(stored['tweaks']['RTL']['enabled'])
        self.assertIn('shared', stored['metadata']['tags'])
        self.assertNotIn('name', stored['metadata'])
        self.assertNotIn('shared_count', stored)
        self.assertEqual(share_code.decode(self.pm.share_code('Friend'))['tweaks']['RTL'], ON)

    def test_import_dialog_gates_the_import_button(self):
        from src.gui.dialogs.share_preset import ImportCodeDialog
        dialog = ImportCodeDialog(self.pm, '26.2', 'iPhone15,2')
        self.assertFalse(dialog.import_button.isEnabled())
        dialog.code_edit.setPlainText('garbage')
        self.assertFalse(dialog.import_button.isEnabled())
        dialog.code_edit.setPlainText(share_code.encode({'RTL': ON}, 'Friend'))
        self.assertTrue(dialog.import_button.isEnabled())
        self.assertEqual(dialog.name_edit.text(), 'Friend')
        self.assertEqual(dialog.risk_panel.report.level, RiskLevel.MEDIUM)
        dialog._import()
        self.assertEqual(dialog.imported_name, 'Friend')


class Translations(unittest.TestCase):
    def test_new_strings_are_translated_to_russian(self):
        root = Path(__file__).resolve().parents[1] / 'src' / 'qt' / 'translations'
        translator = QTranslator()
        self.assertTrue(translator.load(str(root / 'GoldenNuggetUI_ru.qm')))
        QCoreApplication.installTranslator(translator)
        try:
            self.assertEqual(QCoreApplication.translate('RiskAssessment', 'High risk'), 'Высокий риск')
            self.assertEqual(QCoreApplication.translate('ShareCode', 'Copy Code'), 'Копировать код')
            self.assertEqual(QCoreApplication.translate('Nugget', 'Share as QR'), 'Поделиться QR')
            text = assess({'RTL': ON}).factors[0].text
            self.assertIn('направление интерфейса', text)
        finally:
            QCoreApplication.removeTranslator(translator)


if __name__ == '__main__':
    unittest.main()
