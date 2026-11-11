"""Offline regressions for issue #60: backup volume and DeviceLink space refusal."""
import errno
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pymobiledevice3.exceptions import NotEnoughDiskSpaceError, PyMobileDevice3Exception
from pymobiledevice3.services.device_link import DeviceLink

from src.exceptions.nugget_exception import BackupDiskSpaceError, NuggetException
from src.restore import posterboard_backup as pb
from src.restore import protective
from src.restore.storage import posterboard_dir


class FakeConnection:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def recv_plist(self):
        return next(self.messages)

    async def send_plist(self, message):
        self.sent.append(message)


class DiskProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_purge_is_answered_and_device_can_continue(self):
        service = FakeConnection([
            ["DLMessageGetFreeDiskSpace"],
            ["DLMessagePurgeDiskSpace", 4 * 1024 ** 3, 4],
            ["DLMessageProcessMessage", {"ErrorCode": 0, "Content": "completed"}],
        ])
        with tempfile.TemporaryDirectory() as root:
            sentinel = Path(root) / "keep-me"
            sentinel.write_text("user data")
            with patch.object(protective.sys, "platform", "win32"), \
                 patch.object(protective.shutil, "disk_usage", return_value=SimpleNamespace(free=12345)):
                result = await DeviceLink(service, Path(root)).dl_loop()
            self.assertEqual(result, "completed")
            self.assertEqual(sentinel.read_text(), "user data")
        # Actual free bytes, then a failed purge with zero bytes reclaimed.
        self.assertEqual(service.sent[0][-1], 12345)
        self.assertEqual(service.sent[1], [
            "DLMessageStatusResponse", 2 ** 64 - 1, "DLPurgeDiskSpace failed to purge", 0])

    async def test_final_space_refusal_is_actionable_and_not_success(self):
        service = FakeConnection([
            ["DLMessageGetFreeDiskSpace"],
            ["DLMessagePurgeDiskSpace", 1000, 4],
            ["DLMessageProcessMessage", {"ErrorCode": 105, "ErrorDescription": "No room"}],
        ])
        with tempfile.TemporaryDirectory() as root:
            with patch.object(protective.sys, "platform", "win32"), \
                 patch.object(protective.shutil, "disk_usage", return_value=SimpleNamespace(free=26 * 1024 ** 3)):
                with self.assertRaises(NotEnoughDiskSpaceError) as caught:
                    await DeviceLink(service, Path(root)).dl_loop()
            text = str(caught.exception)
            self.assertIn(root, text)
            self.assertIn("26.0 GiB", text)
            self.assertIn("Backup/Cache Location", text)
            self.assertNotIn("device ran out", text)

    async def test_other_device_errors_are_preserved_after_purge(self):
        service = FakeConnection([
            ["DLMessagePurgeDiskSpace", 1000, 4],
            ["DLMessageProcessMessage", {"ErrorCode": 42, "ErrorDescription": "Device failure"}],
        ])
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PyMobileDevice3Exception) as caught:
                await DeviceLink(service, Path(root)).dl_loop()
        self.assertNotIsInstance(caught.exception, NotEnoughDiskSpaceError)
        self.assertIn("Device failure", str(caught.exception))


class PosterBoardStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"GOLDENNUGGET_BACKUP_DIR": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.root = posterboard_dir()
        self.calls = []
        owner = self

        class Lockdown:
            async def __aenter__(self):
                owner.calls.append("lockdown")
                return SimpleNamespace(all_values={"ProductVersion": "27.0"})

            async def __aexit__(self, *args):
                return False

        self.lockdown = patch.object(pb, "lockdown_session", return_value=Lockdown())
        self.lockdown.start()
        self.addCleanup(self.lockdown.stop)
        # Do not depend on the test host's actual free space.
        self.preflight = patch.object(pb, "check_disk_space")
        self.preflight.start()
        self.addCleanup(self.preflight.stop)

    def fake_service(self, failure=None):
        owner = self

        class Backup:
            async def get_will_encrypt(self):
                return False

            def __init__(self, lockdown, include_posterboard=False):
                owner.assertTrue(include_posterboard)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def backup(self, **kwargs):
                owner.calls.append(kwargs)
                root = Path(kwargs["backup_directory"])
                owner.assertTrue(root.is_relative_to(owner.root / ".work"))
                keep = kwargs["filter_callback"]
                owner.assertTrue(keep(SimpleNamespace(device_name="AppDomain-com.apple.PosterBoard/Library/file")))
                owner.assertFalse(keep(SimpleNamespace(device_name="CameraRollDomain/Media/DCIM/photo.jpg")))
                if failure is not None:
                    raise failure
                device_root = root / "TESTUDID"
                device_root.mkdir()
                (device_root / "Manifest.db").touch()

        return Backup

    async def test_database_and_rebuild_workspaces_use_configured_volume(self):
        def extract(root, udid, dest):
            self.assertTrue(Path(root).is_relative_to(self.root / ".work"))
            if Path(dest).parent != self.root:
                self.assertTrue(Path(dest).is_relative_to(self.root / ".work"))
            return dest, 61

        with patch.object(pb, "ProtectiveBackupService", self.fake_service()), \
             patch.object(protective, "extract_posterboard_db", side_effect=extract), \
             patch.object(pb, "_materialise_backup", return_value=1):
            result = await pb.targeted_posterboard_database_backup("TESTUDID")
            self.assertEqual(result, (str(self.root / "TESTUDID.sqlite3"), 61))
            out = str(self.root / "rebuild" / "TESTUDID")
            self.assertEqual(await pb.pull_posterboard_container("TESTUDID", out), (out, 61))
        self.assertEqual(len([call for call in self.calls if isinstance(call, dict)]), 2)
        self.assertEqual(list((self.root / ".work").iterdir()), [])

    async def test_real_low_space_fails_before_opening_device(self):
        self.preflight.stop()
        with patch.object(protective.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaises(NuggetException) as caught:
                await pb.targeted_posterboard_database_backup("TESTUDID")
        self.assertIn(str(self.root / ".work"), str(caught.exception))
        self.assertEqual(self.calls, [])

    async def test_empty_space_error_and_enospc_do_not_retry_or_extract(self):
        for error in (NotEnoughDiskSpaceError(), OSError(errno.ENOSPC, "Disk full")):
            self.calls.clear()
            with self.subTest(error=type(error).__name__), \
                 patch.object(pb, "ProtectiveBackupService", self.fake_service(error)), \
                 patch.object(protective, "extract_posterboard_db") as extract, \
                 patch("src.utils.async_retry.asyncio.sleep", new_callable=AsyncMock) as sleep:
                for action in (
                    lambda: pb.targeted_posterboard_database_backup("TESTUDID"),
                    lambda: pb.pull_posterboard_container("TESTUDID", str(self.root / "out")),
                ):
                    with self.assertRaises(NuggetException) as caught:
                        await action()
                    self.assertIn("Backup/Cache Location", str(caught.exception))
                    self.assertIn(str(self.root / ".work"), str(caught.exception))
                sleep.assert_not_awaited()
                extract.assert_not_called()
                self.assertEqual(len([call for call in self.calls if isinstance(call, dict)]), 2)
                self.assertEqual(list((self.root / ".work").iterdir()), [])

    async def test_rebuild_stops_before_any_restore_on_space_refusal(self):
        from src.tweaks.posterboard.posterboard_rebuild import rebuild_posterboard
        manager = SimpleNamespace(_prepare_protective_backup=AsyncMock(), start_restore=AsyncMock())
        with patch.object(pb, "pull_posterboard_container", side_effect=NuggetException("No disk space")):
            with self.assertRaises(NuggetException):
                await rebuild_posterboard("TESTUDID", manager)
        manager._prepare_protective_backup.assert_not_awaited()
        manager.start_restore.assert_not_awaited()

    async def test_apply_preserves_storage_error_instead_of_missing_database_error(self):
        from src.devicemanagement import device_manager as dm
        manager = SimpleNamespace(
            get_current_device_udid=lambda: "TESTUDID",
            _backup_progress=lambda update: None,
        )
        selected = {
            dm.TweakID.PosterBoard: SimpleNamespace(tendies=[object()], videoFile=None),
            dm.TweakID.Templates: SimpleNamespace(templates=[]),
        }
        original = BackupDiskSpaceError("Backup drive full; choose another location")
        with patch.object(dm, "tweaks", selected), \
             patch.object(pb, "targeted_posterboard_database_backup", side_effect=original):
            with self.assertRaises(BackupDiskSpaceError) as caught:
                await dm.DeviceManager._backup_posterboard_database(manager, force=True)
        self.assertIs(caught.exception, original)

    async def test_protective_backup_does_not_blame_device_storage(self):
        class Backup:
            async def get_will_encrypt(self):
                return False

            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get_will_encrypt(self):
                return False

            async def backup(self, **kwargs):
                raise NotEnoughDiskSpaceError("Host drive full at selected backup destination")

        with patch.object(protective, "check_disk_space_for_backup", new_callable=AsyncMock), \
             patch.object(protective, "ProtectiveBackupService", Backup):
            with self.assertRaises(BackupDiskSpaceError) as caught:
                await protective.perform_protective_backup(object(), str(self.root))
        self.assertEqual(str(caught.exception), "Host drive full at selected backup destination")

    def test_error_dialog_classifies_backup_space_as_computer_storage(self):
        from src.exceptions.crash_handler import _classify
        for error in (BackupDiskSpaceError("Host drive full"), NotEnoughDiskSpaceError()):
            info = _classify(type(error), error)
            self.assertEqual(info["fault"], "Your computer's storage")
            self.assertIn("drive", info["friendly"])


if __name__ == "__main__":
    unittest.main()
