"""Offline regressions for PosterBoard fetch failures (#59) and daemon recovery (#58)."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.devicemanagement import device_manager as dm
from src.exceptions.nugget_exception import NuggetException
from src.restore import posterboard_backup
from src.tweaks.daemons_tweak import (
    NOTIFICATION_RECOVERY_DAEMONS,
    RECOMMENDED_ANALYTICS,
    Daemon,
)
from src.tweaks.tweak_loader import load_daemons


class PosterBoardFailures(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_failures_propagate_even_with_an_old_selected_database(self):
        manager = SimpleNamespace(get_current_device_udid=lambda: "TESTUDID",
                                  _backup_progress=lambda update: None)
        selected = {
            dm.TweakID.PosterBoard: SimpleNamespace(
                tendies=[object()], videoFile=None, config_manager=SimpleNamespace(database="old.sqlite")),
            dm.TweakID.Templates: SimpleNamespace(templates=[]),
        }
        for error in (ConnectionError("USB disconnected"), NuggetException("Invalid snapshot")):
            with self.subTest(error=error), patch.object(dm, "tweaks", selected), patch.object(
                    posterboard_backup, "targeted_posterboard_database_backup", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    await dm.DeviceManager._backup_posterboard_database(manager, force=True)
                self.assertIs(caught.exception, error)

    async def test_locked_device_has_actionable_message(self):
        manager = SimpleNamespace(get_current_device_udid=lambda: "TESTUDID",
                                  _backup_progress=lambda update: None)
        selected = {
            dm.TweakID.PosterBoard: SimpleNamespace(tendies=[object()], videoFile=None),
            dm.TweakID.Templates: SimpleNamespace(templates=[]),
        }
        with patch.object(dm, "tweaks", selected), patch.object(
                posterboard_backup, "targeted_posterboard_database_backup",
                side_effect=RuntimeError("ErrorCode 208: Device locked")):
            with self.assertRaisesRegex(NuggetException, "Unlock it"):
                await dm.DeviceManager._backup_posterboard_database(manager, force=True)

    async def test_apply_does_not_restore_or_record_success_after_failed_fetch(self):
        manager = Mock()
        manager.get_current_device_partially_supported.return_value = False
        manager.get_current_device_version.return_value = "26.2"
        manager.get_current_device_model.return_value = "iPhone16,1"
        manager._backup_posterboard_database = AsyncMock(side_effect=ConnectionError("USB disconnected"))
        manager._apply_tweak_pass = AsyncMock()
        pb = SimpleNamespace(tendies=[object()], videoFile=None)
        selected = {dm.TweakID.PosterBoard: pb, dm.TweakID.Templates: SimpleNamespace(templates=[])}
        with patch.object(dm, "tweaks", selected), patch.dict(os.environ, {}, clear=False), \
                patch.object(dm, "show_apply_error", return_value="fetch failed") as report:
            with patch.dict(os.environ, {"GOLDENNUGGET_NO_PROTECTIVE_BACKUP": "0",
                                         "GOLDENNUGGET_SKIP_PB_BACKUP": ""}):
                result = await dm.DeviceManager._apply_changes(manager)
        self.assertFalse(result)
        manager._apply_tweak_pass.assert_not_awaited()
        self.assertIn("USB disconnected", str(report.call_args.args[0]))
        self.assertEqual(len(pb.tendies), 1)


class NotificationRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shortcut_excludes_shared_services(self):
        for daemon in (Daemon.Spotlight, Daemon.CallAnalytics, Daemon.CoreDuet,
                       Daemon.MediaExperience, Daemon.Symptomsd, Daemon.DuetExpert,
                       Daemon.Sociald, Daemon.FollowUp, Daemon.Shazam):
            self.assertNotIn(daemon, RECOMMENDED_ANALYTICS)

    def test_removed_daemons_cannot_be_selected_or_applied_from_old_presets(self):
        from src.tweaks.basic_plist_locations import FileLocation
        from src.tweaks.daemons_tweak import INTERFACE_KEYS
        from src.tweaks.tweak_classes import DaemonPlistTweak

        removed = {"DeviceCheck": "com.apple.devicecheckd",
                   "Translate": "com.apple.translated",
                   "Decisiond": "com.apple.decisiond"}
        for name, key in removed.items():
            self.assertNotIn(name, Daemon.__members__)
            self.assertNotIn(key, INTERFACE_KEYS)
        # A stored preset may still contain the retired launchd keys.
        values = dict.fromkeys(removed.values(), True)
        values[Daemon.Tips.value[0]] = True
        tweak = DaemonPlistTweak(FileLocation.disabledDaemons, values,
                                 allowed_keys=INTERFACE_KEYS)
        tweak.set_enabled(True)
        self.assertEqual(tweak.apply_tweak({})[tweak.file_location],
                         {Daemon.Tips.value[0]: True})

    def test_recovery_writes_explicit_enable_overrides_and_respects_hotload(self):
        from src.gui.ios.daemons import IOSDaemonsContent
        load_daemons()
        tweak = dm.tweaks[dm.TweakID.Daemons]
        tweak.set_enabled(True)
        for daemon in NOTIFICATION_RECOVERY_DAEMONS:
            tweak.set_multiple_values(daemon.value, True)
        # The real widget exercises refresh and switch synchronization too.
        window = SimpleNamespace(settings=None, device_manager=None)
        content = IOSDaemonsContent(window)
        from PySide6.QtCore import QElapsedTimer
        from PySide6.QtTest import QTest
        deadline = QElapsedTimer()
        deadline.start()
        while content._building and deadline.elapsed() < 10000:
            QApplication.processEvents()
            QTest.qWait(5)
        self.assertFalse(content._building)
        content._forced_daemons = {Daemon.CoreDuet.name: "test safety rule"}
        with patch("src.gui.ios.daemons.QMessageBox.information"):
            content.recover_notifications_button.click()
        payload = tweak.apply_tweak({})[tweak.file_location]
        for daemon in NOTIFICATION_RECOVERY_DAEMONS:
            for key in daemon.value:
                if key in tweak.never_enable:
                    self.assertNotIn(key, payload)
                else:
                    self.assertIs(payload[key], daemon is Daemon.CoreDuet)
        self.assertFalse(content.analytics_switch.isChecked())
        content.close()


if __name__ == "__main__":
    unittest.main()
