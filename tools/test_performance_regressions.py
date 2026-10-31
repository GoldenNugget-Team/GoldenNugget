"""Offline correctness checks for the performance changes (no device needed)."""
import asyncio
import copy
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.restore import afc_media as media
from src.utils.payload import install_payload
from tools.test_afc_regressions import MemoryAfc


def backup_fixture(root):
    device = root / "udid"
    device.mkdir(parents=True)
    (device / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    with closing(sqlite3.connect(device / "Manifest.db")) as db:
        db.executescript("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
                         "relativePath TEXT, flags INTEGER, file BLOB);"
                         "CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB);")
    return device


class PayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_injection_accepts_path_without_unbounded_reads(self):
        from src.restore.inject import inject_files_into_backup
        device = backup_fixture(self.root / "backup")
        source = self.root / "source"
        data = b"01234567" * 400000
        source.write_bytes(data)
        real_open = open
        reads = []

        class Guard:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, count=-1):
                if not 0 < count <= 1024 * 1024:
                    raise AssertionError(f"Unbounded payload read: {count}")
                reads.append(count)
                return self.stream.read(count)

        def guarded_open(path, mode="r", *args, **kwargs):
            stream = real_open(path, mode, *args, **kwargs)
            return Guard(stream) if Path(path) == source and mode == "rb" else stream

        row = ("HomeDomain", "Library/Preferences/large.bin", source, 0o100644, 0, 0)
        with patch("builtins.open", guarded_open):
            self.assertEqual(inject_files_into_backup(device.parent, "udid", [row]), (1, 0, 0))
            self.assertEqual(inject_files_into_backup(device.parent, "udid", [row]), (0, 1, 0))
        self.assertGreater(len(reads), 3)
        file_id = hashlib.sha1(b"HomeDomain-Library/Preferences/large.bin").hexdigest()
        self.assertEqual((device / file_id[:2] / file_id).read_bytes(), data)
        with closing(sqlite3.connect(device / "Manifest.db")) as db:
            blob = plistlib.loads(db.execute("SELECT file FROM Files WHERE fileID=?", (file_id,)).fetchone()[0])
        info = blob["$objects"][1]
        self.assertEqual(info["Size"], len(data))
        self.assertEqual(blob["$objects"][info["Digest"]], hashlib.sha1(data).digest())
        self.assertEqual((info["UserID"], info["GroupID"]), (0, 0))

    def test_atomic_replacement_preserves_snapshot_and_equal_inode(self):
        target, snapshot = self.root / "payload", self.root / "snapshot"
        target.write_bytes(b"old")
        os.link(target, snapshot)
        inode = target.stat().st_ino
        self.assertFalse(install_payload(b"old", target)[2])
        self.assertEqual(target.stat().st_ino, inode)
        self.assertTrue(install_payload(b"new", target)[2])
        self.assertEqual(snapshot.read_bytes(), b"old")
        self.assertEqual(target.read_bytes(), b"new")

    def test_failed_copy_keeps_destination_and_removes_temporary_file(self):
        target = self.root / "payload"
        target.write_bytes(b"old")
        with patch("src.utils.payload.copy_payload", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                install_payload(b"new", target)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_sparse_backup_streams_and_hashes(self):
        from src.restore.backup import Backup, ConcreteFile
        source = self.root / "source"
        source.write_bytes(b"path-backed payload")
        file = ConcreteFile("Library/test", "HomeDomain", None, src_path=str(source))
        destination = self.root / "sparse"
        destination.mkdir()
        with patch.object(ConcreteFile, "read_contents", side_effect=AssertionError("read all")):
            Backup([file], []).write_to_directory(destination)
        self.assertEqual(file.size, source.stat().st_size)
        self.assertEqual(file.hash, hashlib.sha1(source.read_bytes()).digest())

    def test_prune_inventory_and_inode_hint_remain_safe_after_injection(self):
        from src.restore.inject import inject_files_into_backup
        from src.restore.protective import clean_backup_for_restore, verify_backup_payloads
        device = backup_fixture(self.root / "backup")
        row = ("HomeDomain", "Library/Preferences/kept.plist", b"keep", 0o100644, 501, 501)
        inject_files_into_backup(device.parent, "udid", [row])
        orphan = device / "aa" / "unreferenced"
        orphan.parent.mkdir(exist_ok=True)
        orphan.write_bytes(b"orphan")
        result = clean_backup_for_restore(device.parent, "udid", collect_inode=True)
        self.assertFalse(orphan.exists())
        self.assertGreaterEqual(result.max_inode, 1)
        with patch("src.restore.inject._max_inode_in_manifest", side_effect=AssertionError("repeat scan")):
            inject_files_into_backup(device.parent, "udid",
                [("HomeDomain", "Library/Preferences/new", b"new", 0o100644, 501, 501)],
                max_inode_hint=result.max_inode)
        self.assertEqual(verify_backup_payloads(device.parent, "udid"), [])
        with closing(sqlite3.connect(device / "Manifest.db")) as db:
            inodes = [plistlib.loads(row[0])["$objects"][1]["InodeNumber"]
                      for row in db.execute("SELECT file FROM Files")]
            file_id = db.execute("SELECT fileID FROM Files WHERE relativePath='Library/Preferences/new'").fetchone()[0]
        self.assertEqual(len(inodes), len(set(inodes)))
        (device / file_id[:2] / file_id).unlink()
        self.assertEqual(verify_backup_payloads(device.parent, "udid"), ["Library/Preferences/new"])

    def test_materialise_backup_copies_regular_payloads(self):
        from src.restore.inject import inject_files_into_backup
        from src.restore.posterboard_backup import _materialise_backup
        device = backup_fixture(self.root / 'backup')
        inject_files_into_backup(device.parent, 'udid',
            [('HomeDomain', 'Library/Preferences/payload', b'content', 0o100644, 501, 501)])
        destination = self.root / 'materialised'
        self.assertEqual(_materialise_backup(str(device), str(device / 'Manifest.db'), str(destination)), 1)
        self.assertEqual((destination / 'Library/Preferences/payload').read_bytes(), b'content')

    def test_recovery_cleanup_cannot_target_a_master(self):
        from src.restore.protective import discard_protective_working_copy, WORKING_COPY_PREFIX
        master = self.root / 'master'
        master.mkdir()
        with self.assertRaises(ValueError):
            discard_protective_working_copy(master)
        working = self.root / (WORKING_COPY_PREFIX + 'test') / 'device_backup'
        working.mkdir(parents=True)
        with patch('src.restore.backup_store._retire_backup_tree') as retire:
            discard_protective_working_copy(working)
        retire.assert_called_once_with(working.parent)
        self.assertTrue(master.is_dir())

    def test_restore_view_is_independent_and_discards_cleanly(self):
        from src.restore.protective import make_restore_view, discard_restore_view
        from src.utils.filecopy import clone_or_copy
        source, cloned = self.root / "source", self.root / "cloned"
        source.write_bytes(b"original")
        clone_or_copy(source, cloned)
        cloned.write_bytes(b"changed")
        self.assertEqual(source.read_bytes(), b"original")
        master = backup_fixture(self.root / "master")
        payload = master / "Library/Preferences/payload"
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b"master")
        master_manifest = (master / "Manifest.db").read_bytes()
        view = make_restore_view(str(master.parent), "udid", str(self.root / "view"))
        self.assertEqual(view, str(self.root / "view"))
        view_device = self.root / "view" / "udid"
        # The manifest is real-copied (the prune rewrites it in place), the
        # payload is hardlinked (no disk cost, no copy).
        self.assertEqual((view_device / "Manifest.db").read_bytes(), master_manifest)
        self.assertEqual(os.stat(view_device / "Library/Preferences/payload").st_ino,
                         os.stat(payload).st_ino)
        (view_device / "Manifest.db").write_bytes(b"pruned")
        self.assertEqual((master / "Manifest.db").read_bytes(), master_manifest)
        discard_restore_view(view, "udid")
        self.assertFalse(view_device.exists())
        self.assertEqual(payload.read_bytes(), b"master")


class DemuxMemoryAfc(MemoryAfc):
    def __init__(self, files=None):
        super().__init__(files)
        self._afc_pending = {}
        self._afc_write_lock = asyncio.Lock()
        self.active = self.peak = 0

    async def fread(self, handle, size):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.005)
            return await super().fread(handle, size)
        finally:
            self.active -= 1

    async def fwrite(self, handle, chunk):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.005)
            await super().fwrite(handle, chunk)
        finally:
            self.active -= 1

    async def isdir(self, _):
        return True


class AfcPerformanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.client = SimpleNamespace(identifier="test-device")

    async def test_bounded_parallel_pull_preserves_all_files(self):
        files = {f"/DCIM/100APPLE/{i}.jpg": str(i).encode() for i in range(20)}
        afc = DemuxMemoryAfc(files)
        with patch.object(media, "AfcService", return_value=afc):
            result = await media.backup_media_via_afc(self.client, str(self.root))
        self.assertEqual(result['files'], 20)
        self.assertTrue(1 < afc.peak <= 4)
        self.assertTrue(media.media_store_verified(str(self.root)))
        self.assertEqual(len(afc.closed), 20)
        for path, data in files.items():
            self.assertEqual((self.root / path.lstrip('/')).read_bytes(), data)

    async def test_parallel_push_selects_current_set_and_recovery_keeps_history(self):
        entries = {}
        (self.root / "DCIM").mkdir()
        for index in range(12):
            name = f"DCIM/{index}.jpg"
            (self.root / name).write_bytes(b"photo")
            entries[name] = 5
        (self.root / "DCIM" / "historical.jpg").write_bytes(b"old")
        media._write_media_state(str(self.root), 12, 60, 0, entries)
        afc = DemuxMemoryAfc()
        with patch.object(media, "AfcService", return_value=afc):
            result = await media.restore_media_via_afc(self.client, str(self.root), include_historical=False)
        self.assertEqual(result['files'], 12)
        self.assertTrue(1 < afc.peak <= 4)
        self.assertNotIn('/DCIM/historical.jpg', afc.files)
        rescue = DemuxMemoryAfc()
        with patch.object(media, "AfcService", return_value=rescue):
            result = await media.restore_media_via_afc(self.client, str(self.root))
        self.assertEqual(result['files'], 13)
        self.assertEqual(rescue.files['/DCIM/historical.jpg'], b"old")

    async def test_failed_parallel_pull_cancels_and_closes_other_handles(self):
        afc = DemuxMemoryAfc({f"/DCIM/{i}": b"x" for i in range(12)})
        afc.read_error = ConnectionError("disconnected")
        with patch.object(media, "AfcService", return_value=afc):
            with self.assertRaises(Exception):
                await media.backup_media_via_afc(self.client, str(self.root))
        self.assertEqual(set(afc.closed), set(range(len(afc.opened))))
        self.assertEqual(afc.active, 0)
        self.assertFalse(media.media_store_verified(str(self.root)))
        self.assertFalse(list(self.root.rglob("*.part")))

    async def test_cancelled_disk_operation_finishes_before_cleanup(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def disk_write():
            started.set()
            release.wait(2)
            finished.set()
        task = asyncio.create_task(media._disk_io(disk_write))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finished.is_set())

    async def test_legacy_client_is_not_multiplexed(self):
        self.assertEqual(media._afc_concurrency(MemoryAfc()), 1)

    async def test_cancellation_during_local_open_closes_and_removes_temporary(self):
        started, release = threading.Event(), threading.Event()
        opened = []
        def slow_open():
            stream = tempfile.NamedTemporaryFile(dir=self.root, delete=False)
            opened.append(stream)
            started.set()
            release.wait(2)
            return stream
        async def operation():
            async with media._local_file(slow_open, temporary=True):
                self.fail('Cancelled open entered the body')
        task = asyncio.create_task(operation())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(opened[0].closed)
        self.assertFalse(list(self.root.iterdir()))

    async def test_unverified_normal_restore_rescues_remaining_files_but_reports_failure(self):
        (self.root / 'DCIM').mkdir()
        (self.root / 'DCIM' / 'remaining').write_bytes(b'photo')
        media._write_media_state(str(self.root), 2, 10, 0,
                                 {'DCIM/remaining': 5, 'DCIM/missing': 5})
        afc = DemuxMemoryAfc()
        with patch.object(media, 'AfcService', return_value=afc):
            with self.assertRaisesRegex(Exception, 'restoration is incomplete'):
                await media.restore_media_via_afc(self.client, str(self.root), include_historical=False)
        self.assertEqual(afc.files['/DCIM/remaining'], b'photo')

    async def test_marker_cannot_authorise_pushing_host_bookkeeping(self):
        (self.root / 'DCIM').mkdir()
        (self.root / 'DCIM' / 'photo').write_bytes(b'photo')
        (self.root / 'DCIM' / 'unfinished.part').write_bytes(b'partial')
        media._write_media_state(str(self.root), 2, 12, 0,
            {'DCIM/photo': 5, 'DCIM/unfinished.part': 7})
        self.assertFalse(media.media_store_verified(str(self.root)))
        afc = DemuxMemoryAfc()
        with patch.object(media, 'AfcService', return_value=afc):
            with self.assertRaisesRegex(Exception, 'restoration is incomplete'):
                await media.restore_media_via_afc(self.client, str(self.root), include_historical=False)
        self.assertEqual(set(afc.files), {'/DCIM/photo'})

    async def test_device_probes_are_independent_and_selection_order_is_stable(self):
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, Mock
        from src.devicemanagement.device_manager import DeviceManager
        manager = DeviceManager.__new__(DeviceManager)
        manager._test_mode = False
        manager.pref_manager = SimpleNamespace(use_encrypted_backup=True)
        manager.get_current_device_udid = lambda: 'two'
        manager.set_current_device = lambda index: setattr(manager, 'selected', index)
        settings = Mock()
        settings.value.return_value = ''
        entered, both_entered = set(), asyncio.Event()
        @asynccontextmanager
        async def session(serial, **_):
            entered.add(serial)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), 0.5)
            yield SimpleNamespace(all_values=dict(ProductType='iPhone15,2', HardwareModel='D73AP',
                HardwarePlatform='t8120', DeviceName=serial, ProductVersion='27.0', BuildVersion='24A1'),
                get_locale=AsyncMock(return_value='en_US'))
        devices = [SimpleNamespace(serial=serial, is_usb=True) for serial in ('one', 'two')]
        with patch('src.devicemanagement.device_manager.usbmux.list_devices', AsyncMock(return_value=devices)), \
                patch('src.devicemanagement.device_manager.lockdown_session', session), \
                patch('src.devicemanagement.developer_mode.read_developer_mode', AsyncMock(return_value=False)):
            await manager._get_devices(settings)
        self.assertEqual([device.udid for device in manager.devices], ['one', 'two'])
        self.assertEqual(manager.selected, 1)


def application():
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QApplication
    QStandardPaths.setTestModeEnabled(True)
    return QApplication.instance() or QApplication([])


class GuiPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def test_background_work_keeps_events_alive_and_does_not_call_destroyed_owner(self):
        from PySide6.QtCore import QObject, QEventLoop, QTimer
        from shiboken6 import delete
        from src.gui.dialogs.file_task import start_file_task
        owner = QObject()
        release = threading.Event()
        completed, ticks = [], []
        task = start_file_task(owner, lambda: release.wait(2), completed.append)
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        QTimer.singleShot(30, loop.quit)
        loop.exec()
        self.assertTrue(ticks)
        delete(owner)
        release.set()
        task.worker.wait()
        self.app.processEvents()
        timer.stop()
        self.assertEqual(completed, [])

    def test_icon_catalog_only_materialises_visible_window(self):
        from src.gui.dialogs.icon_pack_downloader import IconPackDownloaderDialog
        with patch.object(IconPackDownloaderDialog, "_fetch_catalog"), patch.object(IconPackDownloaderDialog, "_drain_preview_queue"):
            dialog = IconPackDownloaderDialog()
            self.addCleanup(dialog.deleteLater)
            themes = [SimpleNamespace(name=f"Theme {i}", author="", version="", description="", preview_url="")
                      for i in range(10000)]
            dialog._populate(themes)
            dialog.show()
            self.app.processEvents()
            self.assertLess(len(dialog._cards), 60)
            bar = dialog.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            dialog._update_visible_cards()
            self.assertIn(9999, dialog._card_indices.values())
            self.assertLess(len(dialog._cards), 60)
            dialog.close()

    def test_app_filter_preserves_items_and_decoded_icons(self):
        from src.gui.dialogs.app_list_dialog import AppListExportDialog
        window = SimpleNamespace(device_manager=SimpleNamespace(get_current_device_udid=lambda: None))
        dialog = AppListExportDialog(window)
        self.addCleanup(dialog.deleteLater)
        dialog._on_done([dict(bundle_id="a", display_name="Alpha", version="1"),
                         dict(bundle_id="b", display_name="Beta", version="1")])
        first = dialog._app_items['a']
        dialog.filter_input.setText("Beta")
        dialog._apply_filter()
        self.assertTrue(first.isHidden())
        self.assertEqual(dialog.selected_app()['bundle_id'], 'b')
        dialog.filter_input.clear()
        dialog._apply_filter()
        self.assertIs(dialog._app_items['a'], first)
        self.assertFalse(first.isHidden())
        dialog.close()

    def test_autosave_snapshot_is_immutable_and_shutdown_writes_latest_state(self):
        from PySide6.QtCore import QObject
        from src.gui.main_window_mixins import SettingsMixin
        class Manager:
            def __init__(self):
                self.data, self.saved = {'values': [1]}, []
            def _serialize(self):
                return self.data
            def snapshot(self):
                return copy.deepcopy(self.data)
            def save_snapshot(self, name, snapshot, *args, **kwargs):
                self.saved.append(copy.deepcopy(snapshot))
                return True
            def save_preset(self, *args, _data=None, **kwargs):
                self.saved.append(copy.deepcopy(self.data if _data is None else _data))
                return True
        class Window(QObject, SettingsMixin):
            def __init__(self):
                super().__init__()
                self.preset_manager = Manager()
                self._preset_autosave_pending = True
                self.device_manager = SimpleNamespace(pref_manager=SimpleNamespace(tweak_autosave=True),
                    get_current_device_model=lambda: "", get_current_device_version=lambda: "")
        window = Window()
        window._save_autosave_preset()
        window.preset_manager.data['values'].append(2)
        window._preset_autosave_pending = True
        window._flush_autosave()
        self.app.processEvents()
        self.assertEqual(window.preset_manager.saved[0], {'values': [1]})
        self.assertEqual(window.preset_manager.saved[-1], {'values': [1, 2]})

    def test_autosave_waits_for_quiet_period(self):
        from PySide6.QtCore import QObject
        from PySide6.QtTest import QTest
        from src.gui.main_window_mixins import SettingsMixin
        class Window(QObject, SettingsMixin):
            def __init__(self):
                super().__init__()
                self._preset_autosave_pending = False
                self.saved = []
                self.device_manager = SimpleNamespace(pref_manager=SimpleNamespace(tweak_autosave=True),
                    get_current_device_model=lambda: '', get_current_device_version=lambda: '')
                self.preset_manager = SimpleNamespace(snapshot=lambda: {'tweaks': {}},
                    save_snapshot=lambda *args, **kwargs: (self.saved.append(kwargs), True)[1],
                    save_preset=lambda *args, **kwargs: True)
        window = Window()
        try:
            window._on_tweak_changed()
            QTest.qWait(300)
            window._on_tweak_changed()
            QTest.qWait(300)
            self.assertEqual(window.saved, [])
            QTest.qWait(300)
            self.assertEqual(len(window.saved), 1)
        finally:
            window._flush_autosave()


class RenderAndCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def test_hsl_approximation_preserves_rgb_and_source_alpha(self):
        from PySide6.QtGui import QColor, QImage
        from src.controllers.ca.render import _hsl_blend
        for mode in (QImage.Format.Format_RGBA8888, QImage.Format.Format_ARGB32_Premultiplied):
            image = QImage(5, 3, mode)
            image.fill(QColor(170, 80, 43, 128))
            expected = image.pixelColor(0, 0).getRgb()
            for kind in ('hue', 'color', 'saturation', 'luminosity'):
                result = _hsl_blend(image, kind)
                self.assertEqual(result.pixelColor(0, 0).getRgb(), (*expected[:3], 255))
                self.assertEqual(image.pixelColor(0, 0).alpha(), 128)

    def test_transition_matches_fresh_tree_at_both_directions(self):
        from src.controllers.ca.models import CADocument, Layer, Size
        from src.controllers.ca.render import CAMLRenderer, interpolated_state_root
        child = Layer(id='child', size=Size(10, 10), backgroundColor='#ff0000')
        document = CADocument(root=Layer(id='root', size=Size(20, 20), children=[child]),
            stateOverrides={'Locked': [{'targetId': 'child', 'keyPath': 'opacity', 'value': 0.2}],
                            'Unlock': [{'targetId': 'child', 'keyPath': 'opacity', 'value': 0.8}]})
        renderer = CAMLRenderer(document)
        root_id = None
        for progress in (0, 0.5, 1, 0.25, 0):
            cached = renderer.render_state_transition(progress=progress)
            fresh = interpolated_state_root(document.root, document.stateOverrides, 'Locked', 'Unlock', progress)
            self.assertEqual(cached, renderer._paint_root(fresh))
            if root_id is None:
                root_id = id(renderer._transition_root)
            self.assertEqual(id(renderer._transition_root), root_id)
        self.assertEqual(child.opacity, 1.0)

    def test_static_filter_cache_does_not_change_rendered_result(self):
        from src.controllers.ca.models import CADocument, Filter, Layer, Size
        import importlib
        module = importlib.import_module('src.controllers.ca.render')
        child = Layer(id='child', size=Size(12, 12), backgroundColor='#e07030',
                      filters=[Filter(type='colorContrast', value=1.4)])
        renderer = module.CAMLRenderer(CADocument(root=Layer(size=Size(20, 20), children=[child])))
        with patch.object(module, '_apply_filters', wraps=module._apply_filters) as apply:
            first = renderer.render(0)
            second = renderer.render(1000)
        self.assertEqual(first, second)
        self.assertEqual(apply.call_count, 1)

    def test_tendie_assets_are_lazy_and_survive_index_archive_close(self):
        from src.controllers.ca.tendie import load_tendie
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'scene.tendies'
            caml = '<caml xmlns="http://www.apple.com/CoreAnimation/1.0"><CALayer bounds="0 0 20 20"/></caml>'
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('wallpaper.ca/main.caml', caml)
                zf.writestr('wallpaper.ca/assets/first.jpg', b'first')
                zf.writestr('wallpaper.ca/assets/second.jpg', b'second')
            real_read, seen = zipfile.ZipFile.read, []
            def recorded_read(handle, name, *args, **kwargs):
                seen.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
                return real_read(handle, name, *args, **kwargs)
            with patch.object(zipfile.ZipFile, 'read', recorded_read):
                bundle = load_tendie(str(archive))
            self.assertFalse(any('/assets/' in name for name in seen))
            assets = bundle.wallpaper.assets
            self.assertEqual(assets.source.cache_bytes, 0)
            self.assertEqual(set(assets), {'first.jpg', 'second.jpg'})
            self.assertEqual(assets['first.jpg'], b'first')
            self.assertEqual(assets.source.cache_bytes, 5)
            assets.source.archive.close()
            assets.source.archive = None

    def test_database_validation_cache_invalidates_on_main_or_wal_change(self):
        from src.tweaks.posterboard import db_validate
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'poster.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE poster (value INTEGER)')
                db.commit()
            with patch.object(db_validate, '_snapshot_problem_uncached', wraps=db_validate._snapshot_problem_uncached) as check:
                self.assertIsNone(db_validate.snapshot_problem(path, strict=False))
                self.assertIsNone(db_validate.snapshot_problem(path, strict=False))
                self.assertEqual(check.call_count, 1)
                with closing(sqlite3.connect(path)) as db:
                    db.execute('INSERT INTO poster VALUES (1)')
                    db.commit()
                self.assertIsNone(db_validate.snapshot_problem(path, strict=False))
                self.assertEqual(check.call_count, 2)
                Path(str(path) + '-wal').write_bytes(b'new journal')
                db_validate.snapshot_problem(path, strict=False)
                self.assertEqual(check.call_count, 3)

    def test_disabled_autosave_does_not_replace_existing_preset(self):
        from src.controllers.preset_manager import PresetManager
        with tempfile.TemporaryDirectory() as directory:
            manager = PresetManager()
            manager.presets_dir = directory
            target = Path(directory) / 'AutoSave.json'
            target.write_text('{"metadata": {"created_at": 1}, "tweaks": {}}')
            original = target.read_bytes()
            self.assertFalse(manager.save_preset('AutoSave', _data={'tweaks': {'new': {}}},
                                                _should_commit=lambda: False))
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_icon_replacement_order_and_preset_metadata_invalidation(self):
        from src.tweaks.icon_themes.icon_themes_tweak import IconThemesTweak
        from src.controllers.preset_manager import PresetManager
        tweak = IconThemesTweak()
        a, b = SimpleNamespace(bundle_id='a'), SimpleNamespace(bundle_id='b')
        tweak.add_theme(a)
        tweak.add_theme(b)
        replacement = SimpleNamespace(bundle_id='a')
        tweak.add_theme(replacement)
        self.assertEqual(tweak.themes, [b, replacement])
        tweak.themes = [a, b]
        tweak.remove_theme('a')
        self.assertEqual(tweak.themes, [b])
        with tempfile.TemporaryDirectory() as directory:
            manager = PresetManager()
            manager.presets_dir = directory
            path = Path(directory) / 'test.json'
            path.write_text(json.dumps({'metadata': {'version': 1}}))
            self.assertEqual(manager.get_preset_metadata('test')['version'], 1)
            with patch('src.controllers.preset_manager.json.load', side_effect=AssertionError('repeat parse')):
                self.assertEqual(manager.get_preset_metadata('test')['version'], 1)
            path.write_text(json.dumps({'metadata': {'version': 200}}))
            self.assertEqual(manager.get_preset_metadata('test')['version'], 200)


if __name__ == '__main__':
    unittest.main()
