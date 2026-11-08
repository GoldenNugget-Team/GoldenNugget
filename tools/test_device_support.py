"""Offline coverage of compatibility explanations and safety restrictions."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.controllers.hotload import HotLoad
from src.gui.dialogs.device_support import support_lines
from src.tweaks.registry import SPECS_BY_ID
from src.tweaks.tweak_names import TweakID


class DeviceSupportTests(unittest.TestCase):
    def setUp(self):
        self.safety = Mock()
        self.safety.hidden_tweak_names.return_value = set()
        self.safety.hidden_feature_reasons.return_value = {}
        self.safety.hidden_features.return_value = set()
        self.safety.rule_for.return_value = None
        self.safety.kill_rule.return_value = None
        self.safety.disabled_daemons.return_value = {}
        self.safety.is_enabled.return_value = True
        self.manager = SimpleNamespace(
            pref_manager=SimpleNamespace(settings=None),
            get_current_device_version=lambda: '27.0',
            get_current_device_model=lambda: 'iPhone17,3',
            get_current_device_is_supported_by_fork=lambda: True,
            get_current_device_partially_supported=lambda: True)
        patcher = patch('src.gui.dialogs.device_support.HotLoad', return_value=self.safety)
        patcher.start()
        self.addCleanup(patcher.stop)

    def text(self):
        return '\n'.join(support_lines(self.manager))

    def test_version_limits_and_experimental_status(self):
        self.assertIn('experimental', self.text())
        self.assertIn(SPECS_BY_ID[TweakID.ForceSolariumFallback].title + ': supports iOS 26.99 or older', self.text())
        self.manager.get_current_device_version = lambda: '26.2'
        self.manager.get_current_device_partially_supported = lambda: False
        self.assertIn(SPECS_BY_ID[TweakID.DisallowGlassButtons].title + ': requires iOS 27.0 or newer', self.text())
        self.manager.get_current_device_is_supported_by_fork = lambda: False
        self.assertIn('Available registry tweaks (0)', self.text())

    def test_safety_reason_and_disabled_rules(self):
        self.safety.rule_for.side_effect = lambda tid, **kw: (
            {'reason': 'Blocked for test'} if tid == TweakID.NoLiquidDock else None)
        self.assertIn(SPECS_BY_ID[TweakID.NoLiquidDock].title + ': Blocked for test', self.text())
        self.safety.rule_for.side_effect = None
        self.safety.is_enabled.return_value = False
        self.assertIn('HotLoad safety rules are turned off', self.text())

    def test_hidden_feature_reason_matches_existing_gating(self):
        settings = Mock()
        settings.value.return_value = True
        safety = HotLoad(settings)
        safety._rules = {'rules': [{'action': 'hide_feature', 'feature': 'Liquid Glass',
                                  'reason': 'Hidden for test'}]}
        context = dict(device_version='27.0', device_model='iPhone17,3')
        self.assertEqual(safety.hidden_feature_reasons(**context), {'Liquid Glass': 'Hidden for test'})
        self.assertEqual(safety.hidden_features(**context), {'Liquid Glass'})
        settings.value.return_value = False
        self.assertEqual(safety.hidden_features(**context), set())


if __name__ == '__main__':
    unittest.main()
