"""Behavioural regressions for the rewrite audit; never connects to a device."""
import asyncio
from contextlib import asynccontextmanager, closing
import io
import os
from pathlib import Path
import plistlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
import json
import threading
import zipfile
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src/qt")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.exceptions.nugget_exception import NuggetException
from src.utils.log_tail import LogTailReader
from src.controllers.autosave_state import AutosaveState
from src.tweaks.store import TweakStore
from src.tweaks.tweak_classes import Tweak


class RewriteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_posterboard_commit_keeps_saved_ids_independent(self):
        from src.tweaks.posterboard.pb_config_manager import PBConfigManager, PreferenceManager
        manager = PBConfigManager()
        manager.start_staging()
        manager.add_config("wallpaper", "extension")
        persisted = []
        with patch.object(PreferenceManager, "save_pbconfig_ids",
                          side_effect=lambda ids, udid: persisted.extend(ids)):
            manager.save_staged_ids("device")
        self.assertEqual([item.uuid for item in manager.saved_items], ["wallpaper"])
        self.assertEqual(manager.saved_items, persisted)
        manager.start_staging()
        self.assertEqual([item.uuid for item in manager.saved_items], ["wallpaper"])
        self.assertEqual(manager.staged_items, [])

    def test_pairing_service_never_opens_a_dialog(self):
        from src.devicemanagement import device_manager as dm
        client = SimpleNamespace(unpair=AsyncMock(), pair=AsyncMock())
        @asynccontextmanager
        async def connection(udid):
            yield client
        manager = SimpleNamespace(data_singleton=SimpleNamespace(
            current_device=SimpleNamespace(udid="device")))
        with patch.object(dm, "lockdown_session", connection), \
                patch.object(dm.QMessageBox, "information", side_effect=AssertionError("GUI in worker")):
            asyncio.run(dm.DeviceManager._reset_device_pairing(manager))
        client.unpair.assert_awaited_once()
        client.pair.assert_awaited_once()

    def test_unavailable_and_corrupt_manifests_are_not_verified(self):
        from src.restore.protective import verify_backup_payloads
        with self.assertRaises(NuggetException):
            verify_backup_payloads(self.root, "device")
        device = self.root / "device"
        device.mkdir()
        (device / "Manifest.db").write_bytes(b"not sqlite")
        with self.assertRaises(NuggetException):
            verify_backup_payloads(self.root, "device")

    def test_encryption_read_error_never_becomes_plain(self):
        from src.restore import inject
        from unittest.mock import Mock
        backend = SimpleNamespace(_is_encrypted_backup=Mock(side_effect=OSError("unreadable")))
        with patch.object(inject, "Mobilebackup2Service", backend):
            with self.assertRaises(NuggetException):
                inject._is_encrypted_backup(self.root)

    def test_failed_decryption_removes_scratch(self):
        from src.restore.verification import inspect_backup_payloads, VerificationStatus
        (self.root / "Manifest.db").write_bytes(b"encrypted")
        scratch = []
        def decrypt(root, password, output):
            scratch.append(output)
            raise ValueError("wrong password")
        result = inspect_backup_payloads(self.root, "device", "password",
            inventory=lambda root: None, is_sqlite=lambda path: False,
            is_encrypted=lambda root: True, decrypt=decrypt)
        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertTrue(scratch)
        self.assertFalse(scratch[0].exists())
        with self.assertRaises(NuggetException):
            result.require_verified()

    def test_mbfile_preserves_unknown_fields_and_supports_other_root_index(self):
        from src.restore.mbfile import MBFileArchive
        data = {"$top": {"root": plistlib.UID(2)}, "$objects": ["$null", "old", {
            "RelativePath": plistlib.UID(1), "ExtraAppleMetadata": {"x": b"keep"}}]}
        source = MBFileArchive.decode(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
        clone = source.clone()
        clone.set_reference("RelativePath", "new")
        self.assertEqual(source.archive["$objects"][1], "old")
        loaded = MBFileArchive.decode(clone.encode())
        self.assertEqual(loaded.root_index, 2)
        self.assertEqual(loaded.fields["ExtraAppleMetadata"], {"x": b"keep"})
        self.assertEqual(loaded.archive["$objects"][1], "new")

    def test_bad_inode_metadata_aborts_injection_scan(self):
        from src.restore.inject import _max_inode_in_manifest
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE Files (flags INTEGER, file BLOB)")
            db.execute("INSERT INTO Files VALUES (1, ?)", (b"bad plist",))
            with self.assertRaises(NuggetException):
                _max_inode_in_manifest(db)

    def test_store_subscriptions_are_independent_and_batch_changes(self):
        a, b = TweakStore({"x": Tweak("x")}), TweakStore({"x": Tweak("x")})
        seen_a, seen_b = [], []
        unsubscribe = a.changes.subscribe(lambda: seen_a.append("changed"))
        b.changes.subscribe(lambda: seen_b.append("changed"))
        with a.changes.batch():
            a["x"].set_value(2)
            a["x"].set_value(3)
        self.assertEqual(seen_a, ["changed"])
        self.assertEqual(seen_b, [])
        unsubscribe()
        a["x"].set_value(4)
        self.assertEqual(seen_a, ["changed"])

    def test_preset_failure_does_not_publish_earlier_prepared_values(self):
        from copy import copy
        from src.controllers.preset_apply import apply_preset_transaction
        from src.tweaks.tweak_names import TweakID
        key = TweakID.HideDICompletely
        store = TweakStore({key: Tweak("first", value=1)})
        def prepare(name, value):
            if name == "broken":
                raise ValueError("invalid package")
            candidate = copy(store[key])
            candidate.value = value
            return key, candidate
        result = apply_preset_transaction({"first": 42, "broken": 0}, store, prepare)
        self.assertFalse(result.success)
        self.assertEqual(store[key].value, 1)

    def test_injected_preset_store_does_not_modify_global_selections(self):
        from src.controllers import preset_manager
        from src.tweaks.tweak_names import TweakID
        key = TweakID.HideDICompletely
        own = TweakStore({key: Tweak("local")})
        manager = preset_manager.PresetManager.__new__(preset_manager.PresetManager)
        manager._selected_store = own
        manager._load_all_tweaks = lambda: None
        previous = {key: tweak.enabled for key, tweak in preset_manager.tweaks.items()}
        with patch("src.tweaks.hidden.current_hidden_tweak_names", return_value=set()):
            self.assertTrue(manager._apply({"tweaks": {key.name: {"enabled": True}}}))
        self.assertTrue(own[key].enabled)
        self.assertEqual(set(manager.snapshot()["tweaks"]), {key.name})
        self.assertEqual({key: tweak.enabled for key, tweak in preset_manager.tweaks.items()}, previous)

    def test_log_rotation_equal_larger_and_smaller(self):
        path = self.root / "session.log"
        path.write_bytes(b"old line\n")
        reader = LogTailReader(path)
        self.assertEqual(reader.poll().text, "old line\n")
        for payload in (b"new line\n", b"longer new log line\n", b"x\n"):
            replacement = self.root / "new.log"
            replacement.write_bytes(payload)
            os.replace(replacement, path)
            self.assertEqual(reader.poll().text, payload.decode())

    def test_log_partial_utf8_and_missing_file_reset(self):
        path = self.root / "session.log"
        reader = LogTailReader(path)
        self.assertFalse(reader.poll().available)
        path.write_bytes(b"\xd0")
        self.assertEqual(reader.poll().text, "")
        with path.open("ab") as stream:
            stream.write(b"\xb0\n")
        self.assertEqual(reader.poll().text, "а\n")
        path.unlink()
        self.assertEqual(reader.poll().offset, 0)

    def test_caml_document_uses_one_xml_parse(self):
        from src.controllers.ca import caml
        xml = '<caml><CALayer id="root" bounds="0 0 10 10"/></caml>'
        with patch.object(caml.ET, "fromstring", wraps=caml.ET.fromstring) as parse:
            self.assertIsNotNone(caml.parse_ca_document(xml))
        self.assertEqual(parse.call_count, 1)

    def test_template_payload_is_path_backed(self):
        from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
        package = self.root / "Container"
        package.mkdir()
        (package / "video.mov").write_bytes(b"large media payload")
        files = []
        TemplatesTweak().recursive_add("HomeDomain", "HomeDomain", files, str(self.root))
        self.assertEqual(len(files), 1)
        self.assertIsNone(files[0].contents)
        self.assertEqual(Path(files[0].contents_path).read_bytes(), b"large media payload")

    def test_xml_and_plist_batch_parse_once_and_keep_order(self):
        from src.controllers import xml_handler, plist_handler
        from src.controllers.patch_session import patch_batch
        xml = self.root / "main.xml"
        xml.write_text('<caml><CALayer nuggetId="a" x="1"/></caml>')
        plist = self.root / "main.plist"
        plist.write_bytes(plistlib.dumps({"nested": {"enabled": False}}))
        with patch.object(xml_handler.tree, "parse", wraps=xml_handler.tree.parse) as parse:
            with patch_batch():
                xml_handler.set_xml_value(xml, "a", "x", 2)
                xml_handler.set_xml_value(xml, "a", "x", 3)
                plist_handler.write_plist_value(plist, "enabled", True)
                plist_handler.write_plist_value(plist, "enabled", False)
            self.assertEqual(parse.call_count, 1)
        self.assertIn('x="3"', xml.read_text())
        self.assertFalse(plistlib.loads(plist.read_bytes())["nested"]["enabled"])

    def test_failed_patch_does_not_write_partial_xml(self):
        from src.controllers.xml_handler import set_xml_value
        from src.controllers.patch_session import patch_batch
        path = self.root / "main.xml"
        original = '<caml><CALayer nuggetId="a" x="1"/></caml>'
        path.write_text(original)
        with self.assertRaises(ValueError):
            with patch_batch():
                set_xml_value(path, "a", "x", 2)
                raise ValueError("later patch failed")
        self.assertEqual(path.read_text(), original)

    def test_key_times_are_prepared_once_per_animation(self):
        from src.controllers.ca import animate
        from src.controllers.ca.models import Animation
        animation = Animation(keyPath="opacity", values=[0, 1], durationSeconds=1, infinite=True)
        with patch.object(animate, "_build_key_times", wraps=animate._build_key_times) as build:
            self.assertEqual(animate.layer_animation_overrides([animation], 250)["opacity"], .25)
            self.assertEqual(animate.layer_animation_overrides([animation], 750)["opacity"], .75)
        self.assertEqual(build.call_count, 1)

    def test_autosave_failure_retains_dirty_revision(self):
        state = AutosaveState()
        state.changed()
        state.finish(1, OSError("disk full"))
        self.assertTrue(state.dirty)
        self.assertEqual(state.status, "error")
        state.finish(1, True)
        self.assertFalse(state.dirty)
        self.assertEqual(state.status, "saved")
        state.changed()
        state.finish(2, False, enabled=False)
        self.assertEqual(state.status, "cancelled")
        self.assertTrue(state.dirty)

    def test_recovery_stops_before_inject_when_prune_fails(self):
        from src.restore.recovery import RecoverySource, RecoveryBackend, prepare_recovery
        from unittest.mock import Mock
        prune = Mock(side_effect=OSError("disk full"))
        verify, inject = Mock(), Mock()
        backend = RecoveryBackend(prune, verify, lambda root: False, inject)
        with self.assertRaises(OSError):
            asyncio.run(prepare_recovery(RecoverySource("root", "device"), backend))
        verify.assert_not_called()
        inject.assert_not_called()

    def test_normal_restore_requires_media_marker_before_prune(self):
        from src.restore.recovery import RecoverySource, RecoveryBackend, prepare_recovery
        from unittest.mock import Mock
        prune, verify, inject = Mock(), Mock(), Mock()
        backend = RecoveryBackend(prune, verify, lambda root: False, inject)
        with self.assertRaisesRegex(NuggetException, "AFC media store"):
            asyncio.run(prepare_recovery(RecoverySource(
                "backup", "device", media_dir="partial", require_media_complete=True), backend))
        prune.assert_not_called()
        verify.assert_not_called()
        inject.assert_not_called()

    def test_preset_repository_cancel_preserves_file_and_input_snapshot(self):
        from src.controllers.preset_repository import PresetRepository
        repo = PresetRepository(self.root)
        first = {"tweaks": {"A": {"enabled": True}}}
        self.assertTrue(repo.save_snapshot("Example", first))
        path = Path(repo.get_preset_path("Example"))
        original = path.read_bytes()
        self.assertNotIn("metadata", first)
        self.assertFalse(repo.save_snapshot("Example", {"tweaks": {}}, should_commit=lambda: False))
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.root.glob(".preset-*")))

    def test_recovery_cancel_joins_disk_work_before_returning(self):
        from src.utils.async_disk import disk_call
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(2)
            finished.set()
        async def scenario():
            task = asyncio.create_task(disk_call(work))
            await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(.01)
            task.cancel()  # repeated cancellation cannot detach the disk worker
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(finished.is_set())
        try:
            asyncio.run(scenario())
        finally:
            release.set()

    def test_restore_cancel_discards_view_and_keeps_master(self):
        from src.restore import restore
        from src.restore.protective import PreparedBackup
        from src.restore.verification import PruneResult
        from unittest.mock import Mock
        client = SimpleNamespace(udid="device", close=AsyncMock())
        prepared = PreparedBackup(root=str(self.root / "master"), master=True,
                                  view_root=str(self.root / "view"))
        build_view = Mock(return_value=str(self.root / "view"))
        discard = Mock()
        with patch.object(restore, "make_restore_view", build_view), \
                patch.object(restore, "clean_backup_for_restore", return_value=PruneResult()), \
                patch.object(restore, "verify_backup_payloads", return_value=[]), \
                patch.object(restore, "_restore_protective_backup", AsyncMock(side_effect=asyncio.CancelledError())), \
                patch.object(restore, "discard_restore_view", discard), \
                patch.object(restore.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(restore._restore_ios27(SimpleNamespace(files=[]), False, client,
                    lambda value: None, prepared_backup_root=prepared, skip_setup=False))
        # The master is never pruned/injected in place: the apply restores from a
        # disposable view and drops it, whatever the outcome.
        build_view.assert_called_once_with(prepared.root, "device", prepared.view_root)
        discard.assert_called_once_with(str(self.root / "view"), "device")
        client.close.assert_awaited_once()

    def test_conversion_error_identifies_stage_and_preserves_cause(self):
        from src.tweaks.posterboard import posterboard_converter as converter
        error = ValueError("bad CAML")
        with self.assertRaises(converter.ConversionStageError) as failure:
            converter._conversion_stage("descriptor", "Modernize Background",
                                        lambda: (_ for _ in ()).throw(error))
        self.assertEqual(failure.exception.stage, "Modernize Background")
        self.assertIs(failure.exception.__cause__, error)


class GuiRewriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_app_list_refresh_same_size_updates_ids_and_names(self):
        from src.gui.dialogs.app_list_dialog import AppListExportDialog
        with patch.object(AppListExportDialog, "_start_fetch"):
            dialog = AppListExportDialog(None)
        self.addCleanup(dialog.deleteLater)
        dialog._on_done([dict(bundle_id="old", display_name="Old")])
        dialog._on_done([dict(bundle_id="new", display_name="New")])
        self.assertEqual(list(dialog._app_items), ["new"])
        dialog._on_done([dict(bundle_id="new", display_name="Renamed")])
        self.assertIn("Renamed", dialog._app_items["new"].text())

    def test_decoded_images_have_a_byte_budget(self):
        from PySide6.QtGui import QImage
        from src.controllers.ca import render
        from src.controllers.ca.models import CADocument, Layer
        doc = CADocument(root=Layer(), assets={str(i): b"image" for i in range(3)})
        renderer = render.CAMLRenderer(doc)
        image = QImage(8, 8, QImage.Format.Format_RGBA8888)
        with patch.object(render, "_MAX_IMAGE_BYTES", image.sizeInBytes() * 2), \
                patch.object(render, "decode_image_bytes", return_value=image):
            for key in doc.assets:
                self.assertIsNotNone(renderer._image_for(key))
        self.assertEqual(len(renderer._images), 2)
        self.assertNotIn("0", renderer._images)
        self.assertEqual(renderer._image_bytes, image.sizeInBytes() * 2)

    def test_document_edit_invalidates_render_and_animation_caches(self):
        from src.controllers.ca.render import CAMLRenderer
        from src.controllers.ca.models import CADocument, Layer, Size
        root = Layer(size=Size(4, 4), backgroundColor="#ff0000")
        doc = CADocument(root=root)
        renderer = CAMLRenderer(doc)
        self.assertEqual(renderer.render().pixelColor(0, 0).name(), "#ff0000")
        with doc.edit():
            root.backgroundColor = "#0000ff"
        self.assertEqual(renderer.render().pixelColor(0, 0).name(), "#0000ff")

    def test_template_editor_updates_model_and_uses_model_widget_key(self):
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QToolButton
        from src.tweaks.posterboard.template_file import TemplateFile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.batter"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("config.json", json.dumps(dict(
                    title="Example", author="Test", domain="AppDomain-org.test", format_version=2,
                    options=[{"type": "bundle_id"}])))
            model = TemplateFile(str(path))
            parent = QWidget()
            self.addCleanup(parent.deleteLater)
            layout, widgets = QVBoxLayout(parent), {}
            holder = SimpleNamespace(templates=[model])
            model.create_ui(None, holder, widgets, layout)
            self.assertIn(model, widgets)
            widgets[model].findChild(QLineEdit).textEdited.emit("org.changed")
            self.assertEqual(model.bundle_id, "org.changed")
            widgets[model].findChildren(QToolButton)[-1].click()
            self.assertEqual(holder.templates, [])

    def test_tweak_notifications_from_worker_are_delivered_to_gui(self):
        from PySide6.QtCore import QObject
        from src.gui.main_window_mixins import SettingsMixin
        from src.tweaks.store import default_changes
        class Window(QObject, SettingsMixin):
            def __init__(self):
                super().__init__()
                self._preset_autosave_pending = False
                self.device_manager = SimpleNamespace(pref_manager=SimpleNamespace(tweak_autosave=False))
                self._get_autosave_state()
                self._register_tweak_autosave()
        window = Window()
        self.addCleanup(window.deleteLater)
        thread = threading.Thread(target=default_changes.notify)
        thread.start()
        thread.join()
        self.assertEqual(window.autosave_state.revision, 0)
        self.app.processEvents()
        self.assertEqual(window.autosave_state.revision, 1)
        window._unsubscribe_tweak_changes()

    def test_background_jobs_have_bounded_workers_and_cancel_queued_work(self):
        from PySide6.QtWidgets import QWidget
        from src.gui.dialogs.file_task import start_file_task
        owner = QWidget()
        self.addCleanup(owner.deleteLater)
        release = threading.Event()
        lock = threading.Lock()
        active, maximum, seen = 0, 0, []
        def work():
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            release.wait(2)
            with lock:
                active -= 1
            return "ok"
        tasks = [start_file_task(owner, work, seen.append) for _ in range(4)]
        tasks[-1].cancel()
        try:
            release.set()
            for task in tasks:
                task.worker.wait()
            self.app.processEvents()
            self.assertLessEqual(maximum, 2)
            self.assertEqual(len(seen), 3)
        finally:
            release.set()

    def test_startup_safety_notice_is_queued_to_gui(self):
        from PySide6.QtCore import QThread
        from src.gui.startup_services import StartupServices
        from unittest.mock import Mock
        notices = []
        service = StartupServices(self.app, None, None, SimpleNamespace(update=lambda: True),
            Mock(), lambda manager, rules: {"reason": "test"},
            lambda rule: notices.append(QThread.currentThread()))
        self.addCleanup(service.deleteLater)
        with patch("src.gui.startup_services.os._exit") as exit_app:
            worker = threading.Thread(target=service._fetch_rules)
            worker.start()
            worker.join()
            self.assertEqual(notices, [])
            self.app.processEvents()
            self.assertEqual(notices, [self.app.thread()])
            exit_app.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
