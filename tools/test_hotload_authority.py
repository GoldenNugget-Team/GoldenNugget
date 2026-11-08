"""Remote daemon rules remain authoritative without enabling manual selections."""
import asyncio
import os
import plistlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from src.controllers.apply_preview import capture_preview
from src.devicemanagement import device_manager as dm
from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.tweak_classes import AdvancedPlistTweak
from src.tweaks.tweak_names import TweakID


class HotLoadAuthority(unittest.TestCase):
    def setUp(self):
        self.daemon = AdvancedPlistTweak(
            FileLocation.disabledDaemons, {'manual': True},
            allowed_keys={'manual'}, never_enable={'protected'})
        self.daemon.enabled = False
        self.manager = SimpleNamespace(
            pref_manager=SimpleNamespace(settings=None),
            get_current_device_version=lambda: '27.0',
            get_current_device_model=lambda: 'iPhone13,2')
        self.safety = Mock()
        self.safety.disabled_daemon_keys.return_value = {'remote'}
        self.safety.hidden_tweak_names.return_value = set()
        self.safety.rule_for.return_value = None

    def test_forcing_does_not_depend_on_master_switch(self):
        with patch.object(dm, 'tweaks', {TweakID.Daemons: self.daemon}), \
                patch.object(dm, 'HotLoad', return_value=self.safety), \
                patch('src.tweaks.tweak_loader.load_daemons'):
            dm.DeviceManager._apply_hotload_daemon_forcing(self.manager)
        self.assertIs(self.daemon.value['remote'], True)
        self.assertIn('remote', self.daemon.allowed_keys)
        self.assertFalse(self.daemon.enabled)

    def test_master_off_preview_includes_only_forced_daemons(self):
        with patch('src.controllers.hotload.HotLoad', return_value=self.safety), \
                patch('src.tweaks.tweaks.tweaks', {TweakID.Daemons: self.daemon}), \
                patch('src.tweaks.tweak_loader.load_daemons'), \
                patch('src.tweaks.tweak_loader.load_plist_tweaks'):
            preview = capture_preview(self.manager)
        self.assertEqual(set(preview['entries']), {'Daemons/remote'})
        self.assertEqual(preview['forced'], ['remote'])
        self.assertEqual(self.daemon.value, {'manual': True})
        self.assertFalse(self.daemon.enabled)

    def test_master_off_payload_contains_only_remote_overrides(self):
        manager = SimpleNamespace(
            pref_manager=SimpleNamespace(settings=None, supervised=False, organization_name=""),
            get_current_device_version=lambda: '27.0',
            get_current_device_model=lambda: 'iPhone13,2',
            _disable_unavailable_controls=Mock(return_value=set()),
            add_skip_setup=AsyncMock(), concat_file=Mock(), _add_community_files=Mock(),
            _known_backup_encryption=False, start_restore=AsyncMock(return_value="done"))
        with patch.object(dm, 'tweaks', {TweakID.Daemons: self.daemon}), \
                patch.object(dm, 'HotLoad', return_value=self.safety):
            asyncio.run(dm.DeviceManager._apply_tweak_pass(manager, templates=[]))
        writes = [call.kwargs for call in manager.concat_file.call_args_list
                  if call.kwargs['path'] == FileLocation.disabledDaemons.value]
        self.assertEqual(len(writes), 1)
        self.assertEqual(plistlib.loads(writes[0]['contents']), {'remote': True})
        self.assertFalse(self.daemon.enabled)
        manager.start_restore.assert_awaited_once()

    def test_hard_protected_services_remain_excluded(self):
        self.safety.disabled_daemon_keys.return_value = {'protected'}
        with patch.object(dm, 'tweaks', {TweakID.Daemons: self.daemon}), \
                patch.object(dm, 'HotLoad', return_value=self.safety), \
                patch('src.tweaks.tweak_loader.load_daemons'):
            dm.DeviceManager._apply_hotload_daemon_forcing(self.manager)
        self.assertNotIn('protected', self.daemon.value)


if __name__ == '__main__':
    unittest.main()
