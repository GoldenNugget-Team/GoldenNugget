#!/usr/bin/env python3
"""Offline regressions for template isolation and backup delivery failures."""
import asyncio
import io
import json
import os
import plistlib
import sys
import tempfile
import unittest
from contextlib import ExitStack, asynccontextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QStandardPaths

QStandardPaths.setTestModeEnabled(True)

import restore_cache
from src.airlift import grappa
from src.controllers.archive_safety import package_matches, package_path
from src.controllers.files_handler import get_bundle_files
from src.controllers.xml_handler import parse_equation
from src.exceptions.nugget_exception import NuggetException
from src.restore import afc_media as media
from src.restore import restore
from src.tweaks.posterboard.template_options.picker_option import PickerOption
from src.tweaks.posterboard.template_options.remove_option import RemoveOption
from src.utils.file_to_restore import FileToRestore
from tools import backup_ios


def _symlink(link, target, **kw):
    # Windows without admin/Developer Mode refuses os.symlink (WinError 1314):
    # the escape test needs a real link, so skip instead of failing the run.
    try:
        link.symlink_to(target, **kw)
    except OSError as exc:
        raise unittest.SkipTest(f"symlinks unavailable: {exc}") from exc


class Repairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_arithmetic_offsets(self):
        result = parse_equation('x * 2 + y, -(z / 2), a ** 2, 5 % 2', '10 4 8 3')
        self.assertEqual(list(map(float, result.split())), [24, -4, 9, 1])

    def test_offsets_reject_python_objects_and_excessive_powers(self):
        for expression in ('().__class__.__bases__', 'x.__class__', 'abs(x)',
                           '[x for x in (1,)]', '2 ** 10000000', '1e999', 'True'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                parse_equation(expression, '2')

    def test_package_paths_and_globs(self):
        package = self.root / 'package'
        package.mkdir()
        (package / 'wallpaper.caml').write_text('safe')
        self.assertEqual(package_matches(package, '*.caml'), [str((package / 'wallpaper.caml').resolve())])
        for name in ('../outside', '/tmp/outside', 'C:/outside', 'a/../../outside', r'..\outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                package_path(package, name)

    def test_template_remove_rejects_escape_before_deleting(self):
        victim = self.root / 'victim'
        victim.write_text('keep')
        with self.assertRaises(ValueError):
            option = RemoveOption(dict(type='remove', label='remove',
                                       files=['../victim'], default_value=True))
            option.apply(str(self.root / 'package'))
        self.assertEqual(victim.read_text(), 'keep')

    def test_glob_rejects_symlink_escape(self):
        package = self.root / 'package'
        package.mkdir()
        (self.root / 'victim').write_text('keep')
        _symlink(package / 'linked.caml', self.root / 'victim')
        with self.assertRaises(ValueError):
            package_matches(package, '*.caml')

    def test_picker_rejects_escape_in_source_and_destination(self):
        base = dict(type='picker', label='pick', options=[dict(label='one', files=['one'])])
        with self.assertRaises(ValueError):
            PickerOption({**base, 'options': [dict(label='one', files=['../victim'])]})
        with self.assertRaises(ValueError):
            PickerOption({**base, 'rename': True, 'names': ['../victim']})

    def test_picker_rename_allows_option_without_files(self):
        picker = PickerOption(dict(type='picker', label='pick', rename=True, names=['main.caml'],
                                   options=[dict(label='None'), dict(label='one', files=['one.caml'])]))
        self.assertEqual(picker.names, ['main.caml'])
        with self.assertRaises(ValueError):
            PickerOption(dict(type='picker', label='pick', rename=True, names=['main.caml'],
                              options=[dict(label='two', files=['a.caml', 'b.caml'])]))

    def make_media(self):
        target = self.root / 'DCIM' / 'current.jpg'
        target.parent.mkdir()
        target.write_bytes(b'x' * 10000)
        media._write_media_state(str(self.root), 1, 10000, 0,
                                 {'DCIM/current.jpg': 10000})
        self.assertTrue(media.media_store_verified(str(self.root)))
        return target

    def test_historical_files_cannot_mask_missing_current_file(self):
        target = self.make_media()
        (target.parent / 'historical.jpg').write_bytes(b'x' * 20000)
        target.unlink()
        self.assertFalse(media.media_store_verified(str(self.root)))

    def test_even_one_missing_byte_invalidates_media(self):
        target = self.make_media()
        target.write_bytes(b'x' * 9999)
        self.assertFalse(media.media_store_verified(str(self.root)))

    def test_extra_historical_files_are_allowed(self):
        target = self.make_media()
        (target.parent / 'historical.jpg').write_bytes(b'old')
        self.assertTrue(media.media_store_verified(str(self.root)))

    def test_aggregate_only_legacy_marker_requires_refresh(self):
        self.make_media()
        (self.root / media.MEDIA_STATE_FILE).write_text(json.dumps(
            dict(complete=True, files=1, bytes=10000)))
        self.assertFalse(media.media_store_verified(str(self.root)))

    def test_warned_enumeration_failure_never_marks_partial_media_complete(self):
        afc = SimpleNamespace(
            listdir=AsyncMock(side_effect=lambda path: ['DCIM'] if path == '/' else ['good.jpg', 'locked']),
            stat=AsyncMock(side_effect=lambda path: {'st_ifmt': 'S_IFREG', 'st_size': 5}
                           if path.endswith('good.jpg') else {'st_ifmt': 'S_IFDIR'}))

        async def listdir(path):
            if path == '/DCIM/locked':
                raise PermissionError('locked')
            return ['DCIM'] if path == '/' else ['good.jpg', 'locked']

        afc.listdir.side_effect = listdir

        @asynccontextmanager
        async def service(client):
            yield afc

        async def pull(client, src, dst, st):
            Path(dst).write_bytes(b'photo')
            return 5

        with patch.object(media, 'AfcService', service), patch.object(media, '_pull_one', pull):
            result = asyncio.run(media.backup_media_via_afc(None, str(self.root), on_error='warn'))
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['failed'], ['/DCIM/locked'])
        self.assertFalse(media.media_store_verified(str(self.root)))
        self.assertFalse((self.root / media.MEDIA_STATE_FILE).exists())

    def test_empty_and_missing_media_fail_before_opening_device_service(self):
        (self.root / media.MEDIA_STATE_FILE).write_text('{}')
        (self.root / 'incomplete.part').write_bytes(b'partial')
        with patch.object(media, 'open_afc_for_media') as service:
            for directory in (self.root, self.root / 'missing'):
                with self.subTest(directory=directory), self.assertRaises(NuggetException):
                    asyncio.run(media.restore_media_via_afc(None, str(directory)))
            service.assert_not_called()

    def test_recovery_uses_selected_cache_and_keeps_missing_media_expectation(self):
        (self.root / 'device.json').write_text(json.dumps(dict(media_afc=True)))
        expected = str(self.root / 'media' / 'device')
        self.assertEqual(media.recovery_media_dir(str(self.root / 'master'), 'device',
                                                  cache_base=self.root), expected)
        (self.root / 'device.json').write_text(json.dumps(dict(media_afc=False)))
        Path(expected).mkdir(parents=True)
        self.assertEqual(media.recovery_media_dir(str(self.root / 'master'), 'device',
                                                  cache_base=self.root), '')

    def test_live_backup_records_missing_afc_store(self):
        backup = self.root / 'device_backup'
        backup.mkdir()
        self.assertEqual(media.recovery_media_dir(str(backup), 'device'), '')
        (self.root / '.afc_media_required').touch()
        self.assertEqual(media.recovery_media_dir(str(backup), 'device'),
                         media.afc_media_dir_for(str(backup)))

    def test_bundle_files_are_independent_of_current_directory(self):
        previous = os.getcwd()
        try:
            os.chdir(self.root)
            self.assertEqual(get_bundle_files('src/qt/fonts/InterVariable.ttf'),
                             str(ROOT / 'src/qt/fonts/InterVariable.ttf'))
        finally:
            os.chdir(previous)

    def test_grappa_dictionary_builds_with_ctypes_in_helper_scope(self):
        cf = Mock()
        cf.CFStringCreateWithCString.return_value = 1
        cf.CFNumberCreate.return_value = 2
        cf.CFDictionaryCreate.return_value = 3
        self.assertEqual(grappa._cf_dictionary(None, cf, None, {'version': 1}), 3)
        self.assertEqual(cf.CFRelease.call_count, 2)

    def test_async_backup_awaits_service_and_closes_sessions(self):
        ld = SimpleNamespace(udid='device', all_values={'DeviceName': 'Test'})
        service = SimpleNamespace(get_will_encrypt=AsyncMock(return_value=False),
                                  backup=AsyncMock())
        closed = []

        @asynccontextmanager
        async def session(udid):
            try:
                yield ld
            finally:
                closed.append('lockdown')

        @asynccontextmanager
        async def backup_service(client):
            try:
                yield service
            finally:
                closed.append('backup')

        args = SimpleNamespace(output=str(self.root), udid='device', incremental=True)
        with patch.object(backup_ios, 'lockdown_session', session), \
                patch.object(backup_ios, 'Mobilebackup2Service', backup_service):
            self.assertEqual(asyncio.run(backup_ios.run(args)), 0)
        service.get_will_encrypt.assert_awaited_once()
        self.assertTrue(service.backup.await_args.kwargs['full'])
        self.assertEqual(closed, ['backup', 'lockdown'])

    def test_backup_cli_failure_returns_error(self):
        with patch.object(backup_ios, 'run', AsyncMock(side_effect=RuntimeError('failed'))):
            self.assertEqual(backup_ios.main(['--output', str(self.root)]), 1)

    def test_restore_cli_checks_completeness_and_reports_media_failure(self):
        args = SimpleNamespace(udid='device', cache_root=None, source='cache',
                               password=None, timeout=1, no_skip_setup=True, no_reboot=True)
        ld = SimpleNamespace(close=AsyncMock())
        output = io.StringIO()
        with patch.object(restore_cache, '_find_cache_udid', AsyncMock(return_value='device')), \
                patch.object(restore_cache, '_resolve_source', return_value=(str(self.root), str(self.root / 'media'), 'test')), \
                patch.object(restore_cache, 'make_protective_working_copy', return_value=str(self.root)), \
                patch.object(restore_cache, 'clean_backup_for_restore', return_value=(0, 0)) as prune, \
                patch.object(restore_cache, 'verify_backup_payloads', return_value=[]), \
                patch.object(restore_cache, 'create_using_usbmux', AsyncMock(return_value=ld)), \
                patch.object(restore_cache, '_restore_with_wait', AsyncMock()), \
                patch.object(restore_cache, 'restore_media_via_afc', AsyncMock(return_value={'files': 1, 'failed': ['DCIM/photo.jpg']})), \
                redirect_stdout(output):
            self.assertEqual(asyncio.run(restore_cache.run(args)), 4)
        self.assertFalse(prune.call_args.kwargs['exclude_afc_media_trees'])
        self.assertNotIn('SUCCESS', output.getvalue())
        ld.close.assert_awaited_once()

    def test_gui_restore_uses_selected_cache_metadata(self):
        from src.devicemanagement import session
        from src.gui.thread_workers.apply_worker import RestoreCacheThread
        from src.restore import protective

        dummy = SimpleNamespace(
            manager=SimpleNamespace(get_current_device_udid=lambda: 'device'),
            update_label=lambda value: None, _find_cache_base=lambda udid: self.root,
            _backup_password=lambda: '', _progress_cb=lambda value: None,
            prompt_user_choice=None)

        @asynccontextmanager
        async def connection(udid):
            yield None

        for uses_afc in (True, False):
            (self.root / 'device.json').write_text(json.dumps({'media_afc': uses_afc}))
            expected = self.root / 'media' / 'device'
            expected.mkdir(parents=True, exist_ok=True)
            (expected / 'photo.jpg').write_bytes(b'photo')
            with self.subTest(uses_afc=uses_afc), ExitStack() as stack:
                stack.enter_context(patch.object(protective, '_validate_sqlite_db', return_value=True))
                stack.enter_context(patch.object(protective, 'make_protective_working_copy', return_value=str(self.root)))
                stack.enter_context(patch.object(protective, 'discard_protective_working_copy'))
                stack.enter_context(patch.object(protective, 'clean_backup_for_restore', return_value=(0, 0)))
                stack.enter_context(patch.object(protective, 'verify_backup_payloads', return_value=[]))
                gate = stack.enter_context(patch.object(media, 'media_store_verified', return_value=False))
                push = stack.enter_context(patch.object(media, 'restore_media_via_afc', AsyncMock(return_value={'files': 1})))
                stack.enter_context(patch.object(restore, '_restore_protective_backup', AsyncMock()))
                stack.enter_context(patch.object(session, 'lockdown_session', connection))
                asyncio.run(RestoreCacheThread._restore(dummy))
                self.assertTrue(gate.called)
                self.assertTrue(all(call.args == (str(expected) if uses_afc else '',)
                                    for call in gate.call_args_list))
                self.assertEqual(push.await_count, int(uses_afc))

    def test_encrypted_posterboard_payload_stays_in_sparse_restore(self):
        dev = self.root / 'device'
        dev.mkdir()
        (dev / 'Manifest.plist').write_bytes(plistlib.dumps({'IsEncrypted': True}))
        ld = SimpleNamespace(udid='device', product_version='27.0', all_values={})
        ips = AsyncMock()
        ips.__aenter__.return_value = ips
        ips.get_apps.return_value = {'com.apple.PosterBoard': {'Path': '/Applications/PosterBoard.app'}}
        payload = FileToRestore(b'sqlite', 'Library/test.sqlite', domain='AppDomain-com.apple.PosterBoard')
        with patch.object(restore, 'InstallationProxyService', return_value=ips), \
                patch.object(restore, '_restore_ios27', AsyncMock()) as flow:
            asyncio.run(restore.restore_files([payload], lockdown_client=ld,
                        prepared_backup_root=SimpleNamespace(root=str(self.root))))
        self.assertEqual(flow.await_args.kwargs['inject_files'], [])
        self.assertTrue(any(getattr(f, 'contents', None) == b'sqlite'
                            for f in flow.await_args.args[0].files))

    def test_sparse_rejection_restores_protection_but_reports_failure(self):
        ld = SimpleNamespace(udid='device', close=AsyncMock())
        prepared = SimpleNamespace(root=str(self.root / 'device_backup'), master=False,
                                   manifest_password='', media_src='')
        protective = AsyncMock()
        with patch.object(restore, 'clean_backup_for_restore', return_value=(0, 0)), \
                patch.object(restore, 'verify_backup_payloads', return_value=[]), \
                patch.object(restore, 'perform_restore', AsyncMock(side_effect=restore.ConnectionTerminatedError())) as sparse, \
                patch.object(restore, '_restore_protective_backup', protective), \
                patch.object(restore.asyncio, 'sleep', AsyncMock()):
            with self.assertRaisesRegex(NuggetException, 'rejected.*tweak transfer'):
                asyncio.run(restore._restore_ios27(SimpleNamespace(files=[object()]),
                            False, ld, lambda value: None,
                            prepared_backup_root=prepared, skip_setup=False))
        self.assertEqual(sparse.await_count, 2)
        protective.assert_awaited_once()

    def test_failed_injection_aborts_before_device_restore(self):
        ld = SimpleNamespace(udid='device', close=AsyncMock())
        prepared = SimpleNamespace(root=str(self.root / 'device_backup'), master=False,
                                   manifest_password='', media_src='')
        payload = FileToRestore(b'x', 'Library/test', domain='HomeDomain')
        with patch.object(restore, 'clean_backup_for_restore', return_value=(0, 0)), \
                patch.object(restore, 'inject_files_into_backup', return_value=(0, 0, 1)), \
                patch.object(restore, 'perform_restore', AsyncMock()) as sparse, \
                patch.object(restore, '_restore_protective_backup', AsyncMock()) as protective:
            with self.assertRaisesRegex(NuggetException, 'Could not prepare'):
                asyncio.run(restore._restore_ios27(SimpleNamespace(files=[]),
                            False, ld, lambda value: None, inject_files=[payload],
                            prepared_backup_root=prepared, skip_setup=False))
        sparse.assert_not_called()
        protective.assert_not_called()

    def test_phase3_prestart_wait_window_is_bounded(self):
        # A Find My error opens the swallow-retry loop in _restore_once; a
        # device that then keeps failing before the restore starts used to be
        # retried forever (no exception escaped the outer async_retry bound).
        async def scenario():
            from src.restore.find_my_wait import current_find_my_wait
            control = SimpleNamespace(finish=Mock(), wait_for_retry=AsyncMock())
            token = current_find_my_wait.set(control)
            try:
                attempts = {'n': 0}

                class _FakeMB:
                    async def restore(self, *args, **kwargs):
                        attempts['n'] += 1
                        if attempts['n'] == 1:
                            raise Exception('Find My must be disabled on the device')
                        raise OSError('connection dropped')

                @asynccontextmanager
                async def fake_mobilebackup2(client):
                    yield _FakeMB()

                @asynccontextmanager
                async def fake_session(*args, **kwargs):
                    yield SimpleNamespace()

                with patch.object(restore, '_start_mobilebackup2', fake_mobilebackup2), \
                        patch.object(restore, '_PHASE3_WAIT_WINDOW_SEC', 0), \
                        patch('src.devicemanagement.session.lockdown_session', fake_session):
                    with self.assertRaises(NuggetException) as caught:
                        await restore._restore_protective_backup(
                            SimpleNamespace(), str(self.root), 'device', False,
                            lambda value: None)
                self.assertIn('could not start within', str(caught.exception))
                self.assertTrue(control.finish.called)
                # one Find My failure + one post-window failure — never a loop
                self.assertEqual(attempts['n'], 2)
            finally:
                current_find_my_wait.reset(token)

        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
