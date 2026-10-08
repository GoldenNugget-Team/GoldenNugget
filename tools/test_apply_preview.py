"""Offline preview regression: no USB, backups, or real preference writes."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton
from src.controllers import apply_preview as preview
from src.devicemanagement import device_manager as dm
from src.tweaks.tweak_classes import AdvancedPlistTweak
from src.tweaks.tweak_loader import _build_spec
from src.tweaks.registry import SPECS
from src.tweaks.tweak_names import TweakID
from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = patch.object(preview, "_path", lambda udid: str(Path(self.tmp.name) / (udid + '.json')))
        self.path.start()
        self.addCleanup(self.path.stop)
        self.entry = {"section": "SpringBoard", "title": "Example", "value": True}
        self.state = dict(entries={"Example": self.entry}, queued=[], blocked=[], forced=[])

    def test_history_is_per_device_version_and_atomic(self):
        self.assertIsNone(preview.load_preview("one", "27.0"))
        preview.write_preview("one", "27.0", self.state)
        self.assertEqual(preview.load_preview("one", "27.0"), self.state["entries"])
        self.assertIsNone(preview.load_preview("two", "27.0"))
        self.assertIsNone(preview.load_preview("one", "27.1"))
        self.assertEqual(len(list(Path(self.tmp.name).iterdir())), 1)
        preview.clear_preview("one")
        self.assertIsNone(preview.load_preview("one", "27.0"))
        Path(preview._path("one")).write_text('{broken', encoding='utf-8')
        self.assertIsNone(preview.load_preview("one", "27.0"))

    def test_diff_and_unknown_do_not_claim_device_values_or_reset(self):
        self.assertIn("No comparable", preview.preview_lines(self.state, None)[0])
        self.assertEqual(len(preview.preview_lines(self.state, self.state["entries"])), 1)
        old = {"Example": dict(self.entry, value=False), "Removed": dict(self.entry, title="Removed")}
        text = '\n'.join(preview.preview_lines(self.state, old))
        self.assertIn("Off → On", text)
        self.assertIn("not a reset", text)
        self.state['queued'] = [["PosterBoard", "<wallpaper>.tendies"]]
        self.assertIn("<wallpaper>.tendies", '\n'.join(preview.preview_lines(self.state, old)))

    def test_capture_applies_safety_rules_without_mutation(self):
        spec = next(s for s in SPECS if not s.disabled and s.factory is None)
        tweak = _build_spec(spec)
        tweak.enabled = True
        daemon = AdvancedPlistTweak(FileLocation.disabledDaemons, {"visible": False}, allowed_keys={"visible"})
        daemon.enabled = True
        status = StatusBarTweak()
        status.enabled = True
        status.set_carrier_override("Test carrier")
        wallpaper = SimpleNamespace(enabled=False, tendies=[SimpleNamespace(name=str(i)) for i in range(8)], videoFile='movie.mov')
        selections = {spec.id: tweak, TweakID.Daemons: daemon, TweakID.StatusBar: status, TweakID.PosterBoard: wallpaper}
        safety = Mock()
        safety.hidden_tweak_names.return_value = {spec.id.name}
        safety.rule_for.return_value = None
        safety.disabled_daemon_keys.return_value = {"forced"}
        manager = SimpleNamespace(pref_manager=SimpleNamespace(settings=None),
                                  get_current_device_version=lambda: '27.0',
                                  get_current_device_model=lambda: 'iPhone16,1')
        with patch('src.controllers.hotload.HotLoad', return_value=safety), \
             patch('src.tweaks.tweaks.tweaks', selections), \
             patch('src.tweaks.tweak_loader.load_plist_tweaks'), \
             patch('src.tweaks.tweak_loader.load_daemons'):
            result = preview.capture_preview(manager)
        self.assertNotIn(spec.id.name, result['entries'])
        self.assertIn(spec.title, result['blocked'])
        self.assertTrue(result['entries']['Daemons/forced']['value'])
        self.assertEqual(result['forced'], ['forced'])
        self.assertEqual(daemon.value, {'visible': False})
        self.assertEqual(daemon.allowed_keys, {'visible'})
        self.assertEqual(result['entries']['StatusBar/carrier']['value'], 'Test carrier')
        self.assertEqual(len(result['queued']), 7)  # five packages + limit note + video
        status.set_carrier_override('Changed later')
        self.assertEqual(result['entries']['StatusBar/carrier']['value'], 'Test carrier')

    def test_apply_history_written_only_after_success(self):
        manager = Mock()
        manager._raise_if_unsupported.return_value = None
        manager.get_current_device_partially_supported.return_value = False
        manager.get_current_device_udid.return_value = 'one'
        manager.get_current_device_version.return_value = '26.2'
        pb = SimpleNamespace(tendies=[], videoFile=None)
        selections = {TweakID.PosterBoard: pb, TweakID.Templates: SimpleNamespace(templates=[])}
        with patch.dict(dm.tweaks, selections, clear=True), \
             patch.object(preview, 'safe_capture_preview', return_value=self.state), \
             patch.object(preview, 'write_preview') as write, \
             patch('src.restore.lastapply.write_lastapply'), \
             patch.object(dm, 'show_apply_error', return_value=None):
            manager._apply_tweak_pass = AsyncMock(side_effect=RuntimeError('restore failed'))
            asyncio.run(dm.DeviceManager._apply_changes(manager))
            write.assert_not_called()
            manager._apply_tweak_pass = AsyncMock(return_value=(None, []))
            asyncio.run(dm.DeviceManager._apply_changes(manager))
            write.assert_called_once_with('one', '26.2', self.state)

    def test_preview_button_does_not_accept_summary(self):
        from src.gui.ios.components import IOSSummaryDialog
        from src.gui.dialogs.apply_preview import ApplyPreviewDialog
        from src.gui.theme import ColorThemeManager
        app = QApplication.instance() or QApplication([])
        opened = []
        summary = IOSSummaryDialog('Apply', ['One tweak'], extra_button='Update Cache',
                                   details_callback=lambda parent: opened.append(parent))
        summary.show()
        app.processEvents()
        button = next(b for b in summary.findChildren(QPushButton) if b.text() == 'View changes')
        button.click()
        self.assertEqual(opened, [summary])
        self.assertTrue(summary.isVisible())
        self.assertEqual(summary.result(), 0)
        dialog = ApplyPreviewDialog(['<b>Plain text</b>'] * 80, summary)
        dialog.show()
        app.processEvents()
        self.assertTrue(dialog.details.isReadOnly())
        self.assertIn('<b>Plain text</b>', dialog.details.toPlainText())
        self.assertGreater(dialog.details.verticalScrollBar().maximum(), 0)
        ColorThemeManager.instance().theme_changed.emit()
        dialog.reject()
        self.assertTrue(summary.isVisible())
        cache_button = next(b for b in summary.findChildren(QPushButton) if b.text() == 'Update Cache')
        cache_button.click()
        self.assertEqual(summary.result(), 2)
        dialog.deleteLater()
        summary.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    unittest.main()
