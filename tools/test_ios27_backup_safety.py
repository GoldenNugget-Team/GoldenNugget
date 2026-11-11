#!/usr/bin/env python3
"""Offline checks for the iOS 27 protective-backup fail-safes.

No device: these lock the two rules an apply has to keep.

* Do not start the iOS 27 restore unless a selective backup finished and was
  verified. A storage error or an explicit skip stops first and says the
  device was not changed.
* Do not delete the previous good backup until that restore has finished.
  A failed cache refresh rolls the master back to the copy taken beforehand
  and does not replace a copy that is still waiting.

Run: python tools/test_ios27_backup_safety.py
"""
import asyncio
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.exceptions.nugget_exception import BackupDiskSpaceError, NuggetException
from src.restore.protective import list_protective_backups, retire_previous_backups
from src.restore.protective_cache import (
    CACHE_FILTER_REVISION,
    ProtectiveBackupCache,
    discard_previous_master,
)
from src.utils.file_to_restore import FileToRestore


def _sqlite_manifest(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE Files (fileID TEXT)")
    conn.execute("INSERT INTO Files (fileID) VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _live_run(root: Path, udid: str, name: str, marker: str, mtime: float) -> Path:
    device = root / udid / name / "device_backup" / udid
    _sqlite_manifest(device / "Manifest.db", marker)
    run = root / udid / name
    os.utime(run, (mtime, mtime))
    return run


class Retention(unittest.TestCase):
    def test_previous_run_stays_until_the_restore_finishes(self):
        udid = "00008101-SAFETY"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = _live_run(root, udid, "older", "previous-good", 1_700_000_000)
            newer = _live_run(root, udid, "newer", "just-taken", 1_700_000_100)
            with patch("src.restore.protective.protective_persistent_base", return_value=root):
                self.assertEqual(len(list_protective_backups(udid)), 2)
                self.assertEqual(retire_previous_backups(udid, restore_finished=False), 0)
                self.assertTrue(older.is_dir())
                self.assertTrue(newer.is_dir())
                self.assertEqual(retire_previous_backups(udid, restore_finished=True), 1)
            self.assertFalse(older.exists())
            self.assertTrue(newer.is_dir())

    def test_call_sites_do_not_retire_before_the_restore(self):
        import src.devicemanagement.device_manager as dm
        from src.restore import restore

        self.assertNotIn(
            "prune_protective_backups",
            inspect.getsource(dm.DeviceManager._build_protective_backup))
        body = inspect.getsource(restore._restore_ios27)
        self.assertLess(body.find("_deliver_sparse_phase"), body.rfind("retire_previous_backups"))


class UnverifiedApply(unittest.IsolatedAsyncioTestCase):
    async def test_ios27_skip_stops_before_any_restore(self):
        from src.restore import restore

        device = type("LD", (), {"udid": "TEST", "product_version": "27.0", "all_values": {}})()
        payload = FileToRestore(b"x", "Library/Preferences/example.plist", domain="HomeDomain")
        env = os.environ.copy()
        env.pop("GOLDENNUGGET_NO_PROTECTIVE_BACKUP", None)
        with patch.dict(os.environ, env, clear=True), \
                patch.object(restore, "perform_restore", new_callable=AsyncMock) as perform:
            with self.assertRaises(NuggetException) as caught:
                await restore.restore_files(
                    [payload], lockdown_client=device, skip_protective_backup=True)
        self.assertIn("not verified", str(caught.exception))
        self.assertIn("not", (caught.exception.detailed_text or "").lower())
        perform.assert_not_awaited()

    async def test_explicit_raw_sparse_override_still_reaches_restore(self):
        from src.restore import restore

        device = type("LD", (), {"udid": "TEST", "product_version": "27.0", "all_values": {}})()
        payload = FileToRestore(b"x", "Library/Preferences/example.plist", domain="HomeDomain")
        with patch.dict(os.environ, {"GOLDENNUGGET_NO_PROTECTIVE_BACKUP": "1"}, clear=False), \
                patch.object(restore, "perform_restore", new_callable=AsyncMock) as perform:
            await restore.restore_files(
                [payload], lockdown_client=device, reboot=False, skip_setup=False)
        perform.assert_awaited()

    async def test_disk_space_stops_the_apply_and_names_the_reason(self):
        import src.devicemanagement.device_manager as dm

        pb = type("PB", (), {"tendies": [], "videoFile": None})()
        selected = {
            dm.TweakID.PosterBoard: pb,
            dm.TweakID.Templates: type("T", (), {"templates": []})(),
        }
        manager = type("M", (), {})()
        manager._raise_if_unsupported = Mock()
        manager._disable_unavailable_controls = Mock(return_value=set())
        manager.get_current_device_version = lambda: "27.0"
        manager.get_current_device_model = lambda: "iPhone16,1"
        manager.get_current_device_partially_supported = lambda: True
        manager._report_operation_stage = Mock()
        manager._prepare_protective_backup = AsyncMock(
            side_effect=BackupDiskSpaceError("backup drive full"))
        manager._apply_tweak_pass = AsyncMock()
        seen = {}

        def report(exc, *args, **kwargs):
            seen["error"] = exc
            return "alert"

        env = os.environ.copy()
        env.pop("GOLDENNUGGET_NO_PROTECTIVE_BACKUP", None)
        with patch.object(dm, "tweaks", selected), \
                patch.object(dm, "show_apply_error", report), \
                patch.dict(os.environ, env, clear=True):
            result = await dm.DeviceManager._apply_changes(manager, show_alert=Mock())
        self.assertFalse(result)
        manager._apply_tweak_pass.assert_not_awaited()
        self.assertIn("stopped before the device was changed", str(seen["error"]))
        self.assertIn("backup drive full", seen["error"].detailed_text)
        self.assertIsInstance(seen["error"].__cause__, BackupDiskSpaceError)

    async def test_disconnect_during_backup_notes_that_nothing_changed(self):
        import src.devicemanagement.device_manager as dm

        pb = type("PB", (), {"tendies": [], "videoFile": None})()
        selected = {
            dm.TweakID.PosterBoard: pb,
            dm.TweakID.Templates: type("T", (), {"templates": []})(),
        }
        manager = type("M", (), {})()
        manager._raise_if_unsupported = Mock()
        manager._disable_unavailable_controls = Mock(return_value=set())
        manager.get_current_device_version = lambda: "27.0"
        manager.get_current_device_model = lambda: "iPhone16,1"
        manager.get_current_device_partially_supported = lambda: True
        manager._report_operation_stage = Mock()
        manager._prepare_protective_backup = AsyncMock(side_effect=ConnectionError("usb gone"))
        manager._apply_tweak_pass = AsyncMock()
        seen = {}

        def report(exc, *args, **kwargs):
            seen["error"] = exc
            return "alert"

        env = os.environ.copy()
        env.pop("GOLDENNUGGET_NO_PROTECTIVE_BACKUP", None)
        with patch.object(dm, "tweaks", selected), \
                patch.object(dm, "show_apply_error", report), \
                patch.dict(os.environ, env, clear=True):
            result = await dm.DeviceManager._apply_changes(manager, show_alert=Mock())
        self.assertFalse(result)
        manager._apply_tweak_pass.assert_not_awaited()
        if sys.version_info >= (3, 11):
            self.assertTrue(any("not modified" in note for note in seen["error"].__notes__))

    async def test_rebuild_does_not_continue_without_a_backup(self):
        import src.restore.posterboard_backup as pb
        from src.tweaks.posterboard.posterboard_rebuild import rebuild_posterboard

        manager = type("M", (), {})()
        manager._prepare_protective_backup = AsyncMock(
            side_effect=BackupDiskSpaceError("disk full"))
        manager.start_restore = AsyncMock()
        plan = type("P", (), {
            "changed": True, "repacked": ["a"], "skipped": [], "kept": [], "failed": [], "files": [],
        })()
        with patch.object(pb, "pull_posterboard_container", new=AsyncMock(return_value=("/tmp", 61))), \
                patch("src.tweaks.posterboard.posterboard_rebuild.plan_rebuild", return_value=plan):
            with self.assertRaises(NuggetException) as caught:
                await rebuild_posterboard("U", manager, prompt_choice=lambda *_a: "resume")
        self.assertIn("stopped before the device was changed", str(caught.exception))
        manager.start_restore.assert_not_awaited()


class CacheSnapshot(unittest.TestCase):
    def _cache(self, root: Path) -> ProtectiveBackupCache:
        udid = "00008101-CACHE"
        device = root / "master" / udid
        _sqlite_manifest(device / "Manifest.db", "original")
        (device / "Manifest.plist").write_bytes(b"plist-original")
        (device / "Status.plist").write_bytes(b"status-original")
        info = {
            "udid": udid,
            "product_version": "27.0",
            "filter_revision": CACHE_FILTER_REVISION,
            "encrypted": False,
            "created_ts": 1,
        }
        import json
        (root / f"{udid}.json").write_text(json.dumps(info), encoding="utf-8")
        cache = ProtectiveBackupCache(udid, product_version="27.0", encrypted=False)
        cache._temp_base = root / "absent-temp"
        cache._persist_base = root
        cache._set_home(root)
        return cache

    def test_refresh_snapshot_is_not_replaced_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(Path(tmp))
            self.assertTrue(cache.retain_previous_master())
            original = (cache._previous_device_dir() / "Manifest.db").read_bytes()
            (cache.device_dir / "Manifest.db").unlink()
            _sqlite_manifest(cache.device_dir / "Manifest.db", "overwritten")
            self.assertTrue(cache.retain_previous_master())
            self.assertEqual((cache._previous_device_dir() / "Manifest.db").read_bytes(), original)
            self.assertTrue(cache.rollback_master_from_previous())
            conn = sqlite3.connect(cache.device_dir / "Manifest.db")
            try:
                marker = conn.execute("SELECT fileID FROM Files").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(marker, "original")
            master_root = str(cache.master_root)
            discard_previous_master(master_root)
            self.assertFalse(cache._previous_device_dir().exists())


if __name__ == "__main__":
    unittest.main()
