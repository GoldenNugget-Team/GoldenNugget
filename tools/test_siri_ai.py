"""Offline coverage for Siri AI payloads and protective manifest delivery."""
import asyncio
import hashlib
import os
import plistlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from src.exceptions.nugget_exception import NuggetException
from src.restore.inject import inject_files_into_backup
from src.tweaks.siri_ai import (
    DOMAIN,
    RELATIVE_PATH,
    SiriAITweak,
    payload_file,
    require_protective_delivery,
)
from tools.test_inject_ownership import make_pruned_backup


class SiriAITests(unittest.TestCase):
    def test_archive_contents(self):
        for action, keys in [('enable', {96, 122, 155}), ('reset', set())]:
            file = payload_file(action)
            archive = plistlib.loads(file.contents)
            self.assertEqual(archive['$archiver'], 'NSKeyedArchiver')
            objects = archive['$objects']
            root = objects[archive['$top']['root'].data]
            mapping = objects[root['overrideMap'].data]
            entries = {objects[k.data]: objects[v.data]
                       for k, v in zip(mapping['NS.keys'], mapping['NS.objects'])}
            self.assertEqual(set(entries), keys)
            for item in entries.values():
                self.assertEqual(objects[item['answer'].data], 4)
            if action == 'enable':
                context = objects[entries[96]['context'].data]
                self.assertEqual(
                    dict(zip([objects[k.data] for k in context['NS.keys']],
                             [objects[v.data] for v in context['NS.objects']])),
                    {'OS_ELIGIBILITY_CONTEXT_LINWOOD_AVAILABILITY': 2})

    def test_selection_and_device_guard(self):
        tweak = SiriAITweak()
        files = []
        tweak.apply_tweak(files, '27.0', 'iPhone17,1')
        self.assertEqual(files, [])
        tweak.set_enabled(True)
        for version, model in [('26.6', 'iPhone17,1'), ('27.0', 'iPad16,1'),
                               ('28.0', 'iPhone17,1'), ('27.0', 'iPhone15,4'),
                               ('27.0', 'iPhone15,2'), ('', '')]:
            with self.assertRaises(NuggetException):
                tweak.apply_tweak(files, version, model)
        tweak.apply_tweak(files, '27.0', 'iPhone17,1')
        self.assertEqual(len(files), 1)
        self.assertEqual((files[0].owner, files[0].group), (0, 0))
        with self.assertRaises(NuggetException):
            require_protective_delivery(files, False)
        require_protective_delivery(files, True)
        require_protective_delivery([], False)

    def test_all_ios27_versions_and_supported_iphone_generations(self):
        from src.gui.ios.compat import compatibility_reasons
        from src.tweaks.tweak_names import TweakID
        for version in ('27.0', '27.0.1', '27.1', '27.2', '27.9.3'):
            for model in ('iPhone16,1', 'iPhone16,2', 'iPhone17,1', 'iPhone17,5',
                          'iPhone18,1', 'iPhone18,5', 'iPhone19,7'):
                with self.subTest(version=version, model=model):
                    self.assertEqual(compatibility_reasons(TweakID.SiriAI, version, model), [])
                    tweak = SiriAITweak()
                    tweak.set_enabled(True)
                    files = []
                    tweak.apply_tweak(files, version, model)
                    self.assertEqual(len(files), 1)
        for version, model in (('26.9', 'iPhone16,1'),
                               ('27.1', 'iPhone15,4'), ('27.1', 'iPhone15,5'),
                               ('27.1', 'iPad16,1'), ('27.1', '')):
            self.assertTrue(compatibility_reasons(TweakID.SiriAI, version, model))
        # Enable metadata has no upper version gate, but delivery rejects iOS 28.
        for version, model in (('28.0', 'iPhone19,7'),):
            self.assertEqual(compatibility_reasons(TweakID.SiriAI, version, model), [])
            operation = SiriAITweak()
            operation.set_enabled(True)
            with self.assertRaises(NuggetException):
                operation.apply_tweak([], version, model)
        # Keep reset available for recovery even on hardware that cannot enable AI.
        reset = SiriAITweak('reset')
        reset.set_enabled(True)
        files = []
        reset.apply_tweak(files, '27.2', 'iPhone15,4')
        self.assertEqual(len(files), 1)

    def test_manifest_file_and_directory_metadata(self):
        for action in ('enable', 'reset'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dev = make_pruned_backup(root, 'TEST')
                file = payload_file(action)
                result = inject_files_into_backup(str(root), 'TEST', [
                    (DOMAIN, RELATIVE_PATH, file.contents, 0o100644, 0, 0)])
                self.assertEqual(result, (1, 0, 0))
                with closing(sqlite3.connect(dev / 'Manifest.db')) as db:
                    rows = db.execute('SELECT relativePath, flags, file FROM Files '
                                      'WHERE domain = ?', (DOMAIN,)).fetchall()
                self.assertEqual(len(rows), 5)
                for rel, flags, blob in rows:
                    archive = plistlib.loads(blob)
                    objects = archive['$objects']
                    info = objects[1]
                    self.assertEqual((info['UserID'], info['GroupID']), (0, 0))
                    self.assertEqual(info['ProtectionClass'], 4 if flags == 1 else 0)
                    self.assertEqual(info['Mode'], 0o100644 if flags == 1 else 0o40755)
                    if flags == 1:
                        self.assertEqual(objects[info['Digest'].data], hashlib.sha1(file.contents).digest())
                        file_id = hashlib.sha1(f'{DOMAIN}-{rel}'.encode()).hexdigest()
                        self.assertEqual((dev / file_id[:2] / file_id).read_bytes(), file.contents)

    def test_registry_and_compatibility(self):
        from src.gui.ios.compat import compatibility_reasons
        from src.tweaks.registry import SPECS_BY_ID
        from src.tweaks.tweak_loader import load_plist_tweaks
        from src.tweaks.tweaks import TweakID, tweaks
        load_plist_tweaks()
        for tid in (TweakID.SiriAI, TweakID.ResetSiriAIOverrides):
            self.assertIsInstance(tweaks[tid], SiriAITweak)
            self.assertEqual(SPECS_BY_ID[tid].experimental, tid == TweakID.ResetSiriAIOverrides)
            self.assertIsNotNone(SPECS_BY_ID[tid].exclusive_with)
            self.assertEqual(compatibility_reasons(tid, '27.0', 'iPhone17,1'), [])
            self.assertEqual(compatibility_reasons(tid, '27.0', 'iPhone18,1'), [])
            self.assertTrue(compatibility_reasons(tid, '27.0', 'iPad16,1'))
            for model in ('iPhone16,1', 'iPhone18,1'):
                operation = SiriAITweak(tweaks[tid].action)
                operation.set_enabled(True)
                files = []
                operation.apply_tweak(files, '27.0', model)
                self.assertEqual(len(files), 1)

    def test_payload_integrity_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            corrupt = Path(directory) / 'enable.data'
            corrupt.write_bytes(b'bplist00 damaged')
            with patch('src.tweaks.siri_ai.get_bundle_files', return_value=str(corrupt)):
                with self.assertRaises(NuggetException):
                    payload_file('enable')

    def test_actual_restore_routing(self):
        import importlib
        restore = importlib.import_module('src.restore.restore')
        from src.restore.protective import PreparedBackup
        device = SimpleNamespace(udid='TEST', product_version='27.0', all_values={})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dev = make_pruned_backup(root, 'TEST')
            prepared = PreparedBackup(root=directory)
            for encrypted, skip, env in [(True, False, {}), (False, True, {}),
                    (False, False, {'GOLDENNUGGET_PB_SPARSE': '1'}),
                    (False, False, {'GOLDENNUGGET_NO_PROTECTIVE_BACKUP': '1'})]:
                (dev / 'Manifest.plist').write_bytes(plistlib.dumps({'IsEncrypted': encrypted}))
                with patch.dict(os.environ, env, clear=True), \
                     patch.object(restore, '_restore_ios27', new_callable=AsyncMock) as deliver:
                    with self.assertRaises(NuggetException):
                        asyncio.run(restore.restore_files([payload_file('enable')],
                            lockdown_client=device, prepared_backup_root=prepared,
                            skip_protective_backup=skip))
                    deliver.assert_not_called()
            (dev / 'Manifest.plist').write_bytes(plistlib.dumps({'IsEncrypted': False}))
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(restore, '_restore_ios27', new_callable=AsyncMock) as deliver:
                asyncio.run(restore.restore_files([payload_file('reset')],
                    lockdown_client=device, prepared_backup_root=prepared))
                deliver.assert_awaited_once()
                self.assertEqual(deliver.call_args.kwargs['inject_files'][0].domain, DOMAIN)

    def test_device_manager_generates_custom_file(self):
        import importlib
        dm = importlib.import_module('src.devicemanagement.device_manager')
        from src.tweaks.tweak_names import TweakID
        enable, reset = SiriAITweak(), SiriAITweak('reset')
        enable.set_enabled(True)
        manager = SimpleNamespace(
            get_current_device_version=lambda: '27.0',
            get_current_device_model=lambda: 'iPhone17,1',
            get_current_device_udid=lambda: 'TEST',
            _disable_unavailable_controls=lambda _: set(),
            pref_manager=SimpleNamespace(settings=None, supervised=False, organization_name=''),
            add_skip_setup=AsyncMock(), concat_file=Mock(), _add_community_files=Mock(),
            _known_backup_encryption=False, start_restore=AsyncMock())
        rules = Mock()
        rules.hidden_tweak_names.return_value = set()
        rules.rule_for.return_value = None
        with patch.dict(dm.tweaks, {TweakID.SiriAI: enable,
                                   TweakID.ResetSiriAIOverrides: reset}, clear=True), \
             patch.object(dm, 'HotLoad', return_value=rules):
            _, files = asyncio.run(dm.DeviceManager._apply_tweak_pass(manager, templates=[]))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].contents, payload_file('enable').contents)
            manager.start_restore.assert_awaited_once()
            reset.set_enabled(True)
            with self.assertRaises(NuggetException):
                asyncio.run(dm.DeviceManager._apply_tweak_pass(manager, templates=[]))


if __name__ == '__main__':
    unittest.main()
