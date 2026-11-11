"""Offline AFC transfer regressions: python -m unittest tools.test_afc_regressions."""
import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from src.devicemanagement import session
from src.exceptions.nugget_exception import NuggetException
from src.restore import afc_media as media
from src.restore.pause_control import RestorePauseControl, current_pause_control


def _symlink(link, target, **kw):
    # Windows without admin/Developer Mode refuses os.symlink (WinError 1314):
    # the escape tests need a real link, so skip instead of failing the run.
    try:
        link.symlink_to(target, **kw)
    except OSError as exc:
        raise unittest.SkipTest(f"symlinks unavailable: {exc}") from exc


class MemoryAfc:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.mtimes = {path: 1 for path in self.files}
        self.handles = {}
        self.closed = []
        self.opened = []
        self.close_error = None
        self.read_error = None
        self.write_error = None
        self.truncate = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def listdir(self, path):
        prefix = path.rstrip('/') + '/'
        return sorted({name[len(prefix):].split('/')[0]
                       for name in self.files if name.startswith(prefix)})

    async def stat(self, path):
        if path in self.files:
            return dict(st_ifmt='S_IFREG', st_size=len(self.files[path]),
                        st_mtime=self.mtimes.get(path, 1))
        return dict(st_ifmt='S_IFDIR', st_size=0)

    async def fopen(self, path, mode='r'):
        handle = len(self.opened)
        self.opened.append(path)
        self.handles[handle] = [path, 0]
        if mode == 'w':
            self.files[path] = b''
        return handle

    async def fread(self, handle, size):
        if self.read_error:
            raise self.read_error
        path, offset = self.handles[handle]
        chunk = self.files[path][offset:offset + size]
        self.handles[handle][1] += len(chunk)
        return chunk

    async def fwrite(self, handle, chunk):
        if self.write_error:
            raise self.write_error
        if self.truncate:
            chunk = chunk[:-1]
        path, _ = self.handles[handle]
        self.files[path] += chunk

    async def fclose(self, handle):
        self.closed.append(handle)
        if self.close_error:
            raise self.close_error


class AfcTransfers(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = patch.object(media, 'MAXIMUM_READ_SIZE', 4)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def pull(self, afc, size=None):
        st = await afc.stat('/DCIM/photo')
        if size is not None:
            st['st_size'] = size
        return await media._pull_one(afc, '/DCIM/photo', str(self.root / 'photo'), st)

    async def test_pull_short_read_preserves_existing_copy_and_removes_temporary_file(self):
        (self.root / 'photo').write_bytes(b'original')
        afc = MemoryAfc({'/DCIM/photo': b'short'})
        with self.assertRaises(NuggetException):
            await self.pull(afc, size=10)
        self.assertEqual((self.root / 'photo').read_bytes(), b'original')
        self.assertEqual(list(self.root.iterdir()), [self.root / 'photo'])
        self.assertEqual(afc.closed, [0])

    async def test_pull_cancellation_closes_handle_and_cleans_temp_even_when_close_fails(self):
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        afc.read_error = asyncio.CancelledError()
        afc.close_error = ConnectionError('close failure')
        with self.assertRaises(asyncio.CancelledError):
            await self.pull(afc)
        self.assertEqual(afc.closed, [0])
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_pull_close_failure_keeps_old_copy_and_removes_temp(self):
        (self.root / 'photo').write_bytes(b'old')
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        afc.close_error = ConnectionError('close failure')
        with self.assertRaisesRegex(ConnectionError, 'close failure'):
            await self.pull(afc)
        self.assertEqual((self.root / 'photo').read_bytes(), b'old')
        self.assertEqual(list(self.root.iterdir()), [self.root / 'photo'])

    async def test_pull_detects_zero_size_file_growing(self):
        afc = MemoryAfc({'/DCIM/photo': b'new'})
        with self.assertRaisesRegex(NuggetException, 'changed during backup'):
            await self.pull(afc, size=0)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_pull_detects_same_size_edit_during_transfer(self):
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        st = await afc.stat('/DCIM/photo')
        afc.mtimes['/DCIM/photo'] = 2
        with self.assertRaisesRegex(NuggetException, 'changed during backup'):
            await media._pull_one(afc, '/DCIM/photo', str(self.root / 'photo'), st)
        self.assertEqual(list(self.root.iterdir()), [])

    async def test_pull_never_follows_predictable_part_symlink(self):
        victim = self.root / 'victim'
        victim.write_bytes(b'keep')
        _symlink(self.root / 'photo.part', victim)
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        self.assertEqual(await self.pull(afc), 5)
        self.assertEqual(victim.read_bytes(), b'keep')
        self.assertEqual((self.root / 'photo').read_bytes(), b'photo')

    async def test_push_detects_short_writes_for_small_and_large_files(self):
        for contents in (b'abc', b'long video payload'):
            with self.subTest(size=len(contents)):
                (self.root / 'photo').write_bytes(contents)
                afc = MemoryAfc()
                afc.truncate = True
                with self.assertRaisesRegex(NuggetException, 'written short'):
                    await media._push_one(afc, str(self.root / 'photo'), '/DCIM/photo')
                self.assertEqual(afc.closed, [0])

    async def test_push_verifies_only_after_close(self):
        (self.root / 'photo').write_bytes(b'photo')
        afc = MemoryAfc()
        stat = afc.stat

        async def committed_stat(path):
            self.assertEqual(afc.closed, [0])
            return await stat(path)

        afc.stat = committed_stat
        self.assertEqual(await media._push_one(afc, str(self.root / 'photo'), '/DCIM/photo'), 5)
        self.assertEqual(afc.files['/DCIM/photo'], b'photo')

    async def test_push_failure_is_not_masked_by_close(self):
        (self.root / 'photo').write_bytes(b'photo')
        afc = MemoryAfc()
        afc.write_error = ValueError('write failure')
        afc.close_error = ConnectionError('close failure')
        with self.assertRaisesRegex(ValueError, 'write failure'):
            await media._push_one(afc, str(self.root / 'photo'), '/DCIM/photo')
        self.assertEqual(afc.closed, [0])

    async def test_push_empty_file_is_created_and_verified(self):
        (self.root / 'photo').touch()
        afc = MemoryAfc()
        self.assertEqual(await media._push_one(afc, str(self.root / 'photo'), '/DCIM/photo'), 0)
        self.assertEqual(afc.files['/DCIM/photo'], b'')

    async def test_push_empty_file_requires_a_regular_remote_file(self):
        (self.root / 'photo').touch()
        afc = MemoryAfc()
        afc.stat = AsyncMock(return_value=dict(st_ifmt='S_IFDIR', st_size=0))
        with self.assertRaises(NuggetException):
            await media._push_one(afc, str(self.root / 'photo'), '/DCIM/photo')

    async def test_marker_write_does_not_follow_old_temporary_symlink(self):
        victim = self.root / 'victim'
        victim.write_bytes(b'keep')
        _symlink(self.root / (media.MEDIA_STATE_FILE + '.tmp'), victim)
        media._write_media_state(str(self.root), 0, 0, 0, {})
        self.assertEqual(victim.read_bytes(), b'keep')
        self.assertEqual(media.media_store_state(str(self.root))['entries'], {})

    async def backup(self, afc, **kwargs):
        with patch.object(media, 'AfcService', return_value=afc):
            return await media.backup_media_via_afc(None, str(self.root), **kwargs)

    async def test_diff_repulls_same_size_file_with_new_mtime(self):
        afc = MemoryAfc({'/DCIM/photo': b'old'})
        await self.backup(afc)
        afc.files['/DCIM/photo'] = b'new'
        afc.mtimes['/DCIM/photo'] = 2
        result = await self.backup(afc, diff=True)
        self.assertEqual(result['skipped'], 0)
        self.assertEqual((self.root / 'DCIM/photo').read_bytes(), b'new')
        self.assertTrue(media.media_store_verified(str(self.root)))

    async def test_diff_skips_verified_unchanged_file_and_reports_full_progress(self):
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        await self.backup(afc)
        afc.opened.clear()
        progress = Mock()
        result = await self.backup(afc, diff=True, progress_callback=progress)
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(afc.opened, [])
        self.assertIn('100%', progress.call_args.args[0])

    async def test_diff_repulls_unverified_and_legacy_files(self):
        (self.root / 'DCIM').mkdir()
        target = self.root / 'DCIM/photo'
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                target.write_bytes(b'old')
                if legacy:
                    media._write_media_state(str(self.root), 1, 3, 0)
                afc = MemoryAfc({'/DCIM/photo': b'new'})
                result = await self.backup(afc, diff=True)
                self.assertEqual(result['skipped'], 0)
                self.assertEqual(target.read_bytes(), b'new')
                media._invalidate_media_state(str(self.root), 'test')

    async def test_failure_to_invalidate_marker_aborts_before_device_access(self):
        afc = MemoryAfc({'/DCIM/photo': b'photo'})
        await self.backup(afc)
        with patch.object(media.os, 'remove', side_effect=PermissionError('read only')):
            with patch.object(media, 'AfcService') as service:
                with self.assertRaises(PermissionError):
                    await media.backup_media_via_afc(None, str(self.root))
                service.assert_not_called()
        self.assertTrue(media.media_store_verified(str(self.root)))

    async def test_linked_parent_is_never_followed_by_pull_or_verification(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'photo').write_bytes(b'old')
        _symlink(self.root / 'DCIM', outside, target_is_directory=True)
        media._write_media_state(str(self.root), 1, 3, 0, {'DCIM/photo': 3})
        self.assertFalse(media.media_store_verified(str(self.root)))
        afc = MemoryAfc({'/DCIM/photo': b'new'})
        with self.assertRaises(ValueError):
            await self.backup(afc)
        self.assertEqual((outside / 'photo').read_bytes(), b'old')

    async def test_remote_traversal_entry_is_rejected(self):
        afc = MemoryAfc({'/DCIM/../outside': b'bad'})
        # A directory listing can contain a slash even though it cannot be a filename.
        original = afc.listdir

        async def listing(path):
            return ['../outside'] if path == '/DCIM' else await original(path)

        afc.listdir = listing
        with self.assertRaisesRegex(NuggetException, 'unsafe directory entry'):
            await self.backup(afc)
        self.assertFalse((self.root / 'outside').exists())
        self.assertFalse(media.media_store_verified(str(self.root)))


class AfcConnections(unittest.IsolatedAsyncioTestCase):
    async def test_service_close_error_does_not_fail_completed_transfer(self):
        service = SimpleNamespace(__aenter__=AsyncMock(return_value='service'),
                                  __aexit__=AsyncMock(side_effect=ConnectionError('afc close')))
        with patch.object(media, 'AfcService', return_value=service):
            async with media.open_afc_for_media(None) as opened:
                self.assertEqual(opened, 'service')
        service.__aexit__.assert_awaited_once()

    async def test_failed_service_open_is_cleaned_and_not_retried_on_cancellation(self):
        service = SimpleNamespace(__aenter__=AsyncMock(side_effect=asyncio.CancelledError()),
                                  __aexit__=AsyncMock())
        with patch.object(media, 'AfcService', return_value=service):
            with self.assertRaises(asyncio.CancelledError):
                async with media.open_afc_for_media(None):
                    self.fail('body should not run')
        service.__aenter__.assert_awaited_once()
        service.__aexit__.assert_awaited_once()

    async def test_transfer_failure_survives_service_and_lockdown_close_errors(self):
        client = SimpleNamespace(close=AsyncMock(side_effect=ConnectionError('lockdown close')))
        service = SimpleNamespace(__aenter__=AsyncMock(return_value='service'),
                                  __aexit__=AsyncMock(side_effect=ConnectionError('afc close')))
        original = SimpleNamespace(identifier='device', usbmux_address='custom-mux')
        with patch.object(session, 'create_using_usbmux', AsyncMock(return_value=client)) as connect:
            with patch.object(media, 'AfcService', return_value=service):
                with self.assertRaisesRegex(ValueError, 'transfer failure'):
                    async with media.open_afc_for_media(original, refresh_client=True):
                        raise ValueError('transfer failure')
        self.assertEqual(connect.call_args.kwargs['usbmux_address'], 'custom-mux')
        client.close.assert_awaited_once()
        service.__aexit__.assert_awaited_once()

    async def test_cancelled_fresh_service_open_closes_lockdown(self):
        client = SimpleNamespace(close=AsyncMock())
        service = SimpleNamespace(__aenter__=AsyncMock(side_effect=asyncio.CancelledError()),
                                  __aexit__=AsyncMock())
        original = SimpleNamespace(identifier='device')
        with patch.object(session, 'create_using_usbmux', AsyncMock(return_value=client)):
            with patch.object(media, 'AfcService', return_value=service):
                with self.assertRaises(asyncio.CancelledError):
                    async with media.open_afc_for_media(original, refresh_client=True):
                        self.fail('body should not run')
        client.close.assert_awaited_once()
        service.__aexit__.assert_awaited_once()

    async def test_pause_resume_opens_fresh_connection(self):
        calls = []
        closed = []

        @asynccontextmanager
        async def connect(client, **kwargs):
            calls.append(kwargs['refresh_client'])
            try:
                yield len(calls)
            finally:
                closed.append(len(calls))

        control = RestorePauseControl()

        async def resume():
            control.resume()

        control.wait_for_resume = resume
        token = current_pause_control.set(control)
        try:
            with patch.object(media, 'open_afc_for_media', connect):
                async with media._pausable_media_connection(None, Mock(), None, None) as checkpoint:
                    self.assertEqual(await checkpoint(), 1)
                    control.request_pause()
                    self.assertEqual(await checkpoint(), 2)
        finally:
            current_pause_control.reset(token)
        self.assertEqual(calls, [False, True])
        self.assertEqual(closed, [1, 2])
        self.assertEqual(control.state, 'unavailable')

    async def test_failed_initial_connection_clears_pause_state(self):
        control = RestorePauseControl()
        control.state = 'resuming'
        token = current_pause_control.set(control)
        try:
            with patch.object(media, 'open_afc_for_media', side_effect=ValueError('open failure')):
                with self.assertRaises(ValueError):
                    async with media._pausable_media_connection(None, Mock(), None, None):
                        self.fail('body should not run')
        finally:
            current_pause_control.reset(token)
        self.assertEqual(control.state, 'unavailable')

    async def test_protective_backup_cancellation_awaits_parallel_media_cleanup(self):
        from src.restore import protective
        started = asyncio.Event()
        stopped = asyncio.Event()
        never = asyncio.Event()

        async def pull(*args, **kwargs):
            started.set()
            try:
                await never.wait()
            finally:
                stopped.set()

        async def backup(**kwargs):
            await started.wait()
            raise asyncio.CancelledError()

        @asynccontextmanager
        async def backup_service(*args, **kwargs):
            yield SimpleNamespace(get_will_encrypt=AsyncMock(return_value=False), backup=backup)

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(protective, 'check_disk_space_for_backup', AsyncMock()), \
                    patch.object(protective, 'ProtectiveBackupService', backup_service), \
                    patch.object(protective, 'backup_media_via_afc', pull):
                with self.assertRaises(asyncio.CancelledError):
                    await protective.perform_protective_backup(
                        None, str(Path(directory) / 'device_backup'), include_afc_media=True)
                self.assertTrue(stopped.is_set(), 'AFC must finish cleanup before cancellation propagates')


if __name__ == '__main__':
    unittest.main()
