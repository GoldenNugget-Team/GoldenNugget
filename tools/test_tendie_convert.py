"""The imported-tendies card shows and controls the legacy format conversion.

Each imported ``.tendies`` that ships a legacy (pre-iOS 27) wallpaper carries a
``Convert`` switch on its card: on = rewritten to the modern format on apply,
off = the original files are pushed untouched. The switch state must be the
same decision ``apply_tweak`` reads, or the card would lie about the apply.
"""
import os
import plistlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from src.gui.ios.posterboard import TendieRow
from src.gui.theme import ColorThemeManager
from src.tweaks.posterboard import posterboard_tweak as pt


def _write_tendie(path: str, entries: dict) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def _legacy_zip(directory: str, name: str = "legacy.tendies") -> str:
    return _write_tendie(os.path.join(directory, name), {
        "descriptors/LEGACY/versions/0/contents/Old.wallpaper/Wallpaper.plist":
            plistlib.dumps({"family": "Marble"}),
        "descriptors/LEGACY/versions/0/contents/Old.wallpaper/bg.ca/index.xml":
            "<plist><dict/></plist>",
    })


def _modern_zip(directory: str, name: str = "modern.tendies") -> str:
    return _write_tendie(os.path.join(directory, name), {
        "descriptors/MODERN/versions/0/contents/New.wallpaper/bg.ca/index.xml":
            "<plist><dict><key>publishedObjectNames</key><array/></dict></plist>",
    })


class ImportDetectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_legacy_families_are_detected_and_the_prompt_answer_is_stored(self):
        answers = []

        def fake_prompt(name, families):
            answers.append((name, list(families)))
            return False

        original = pt.prompt_legacy_convert
        pt.prompt_legacy_convert = fake_prompt
        self.addCleanup(setattr, pt, "prompt_legacy_convert", original)

        tweak = pt.PosterboardTweak()
        self.assertTrue(tweak.add_tendie(_legacy_zip(self._tmp.name), "27.0"))
        tendie = tweak.tendies[-1]

        self.assertEqual(answers, [("legacy.tendies", ["Marble"])])
        self.assertEqual(tendie.legacy_families, ["Marble"])
        self.assertFalse(tendie.auto_convert)
        self.assertTrue(tweak.tendie_needs_conversion(tendie))
        self.assertFalse(tweak.tendie_convert_enabled(tendie))

        tweak.set_tendie_convert(tendie, True)
        self.assertTrue(tweak.tendie_convert_enabled(tendie))

    def test_ios26_stores_the_format_without_prompting(self):
        # iOS 26 cannot use the modern format, so no prompt is raised — but the
        # card still has to know the package is legacy. The preference stays
        # available if the user later selects an iOS 27 device; apply must
        # independently check the current version before converting.
        answers = []
        original = pt.prompt_legacy_convert
        pt.prompt_legacy_convert = lambda name, families: answers.append(name) or True
        self.addCleanup(setattr, pt, "prompt_legacy_convert", original)

        tweak = pt.PosterboardTweak()
        self.assertTrue(tweak.add_tendie(_legacy_zip(self._tmp.name), "26.0"))
        tendie = tweak.tendies[-1]

        self.assertEqual(answers, [])
        self.assertIsNone(tendie.auto_convert)
        self.assertEqual(tendie.legacy_families, ["Marble"])
        self.assertTrue(tweak.tendie_convert_enabled(tendie))

    def test_modern_package_needs_no_conversion(self):
        tweak = pt.PosterboardTweak()
        self.assertTrue(tweak.add_tendie(_modern_zip(self._tmp.name), "27.0"))
        tendie = tweak.tendies[-1]

        self.assertEqual(tendie.legacy_families, [])
        self.assertFalse(tweak.tendie_needs_conversion(tendie))


class TendieRowTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.page = Mock()
        self.page.window.device_manager.get_current_device_version.return_value = '27.0'

    def _row(self, **kwargs):
        tendie = SimpleNamespace(name="Windows_11.tendies", path="/dev/null",
                                 auto_convert=None, legacy_families=["Clownfish"],
                                 **kwargs)
        return tendie, TendieRow(self.page, tendie)

    def test_legacy_row_carries_a_convert_switch(self):
        tendie, row = self._row()
        self.assertIsNotNone(row.convert_switch)
        self.assertTrue(row.convert_switch.isChecked())
        self.assertIn("Converts", row.format_lbl.text())

        row.convert_switch.setChecked(False)
        self.assertIs(tendie.auto_convert, False)
        self.assertEqual(row.format_lbl.text(), "Installs as is")

        row.convert_switch.setChecked(True)
        self.assertIs(tendie.auto_convert, True)
        self.assertIn("Converts", row.format_lbl.text())

    def test_modern_row_offers_no_switch(self):
        tendie = SimpleNamespace(name="Modern.tendies", path="/dev/null",
                                 auto_convert=None, legacy_families=[])
        row = TendieRow(self.page, tendie)
        self.assertIsNone(row.convert_switch)
        self.assertEqual(row.format_lbl.text(), "Modern format")

    def test_conversion_ui_tracks_the_current_device(self):
        version = self.page.window.device_manager.get_current_device_version
        version.return_value = '26.6'
        tendie, row = self._row()
        row.show()
        self.app.processEvents()
        self.assertTrue(row.convert_switch.isHidden())
        self.assertTrue(row.convert_lbl.isHidden())
        self.assertEqual(row.format_lbl.text(), 'Installs as is')
        self.assertIsNone(tendie.auto_convert)

        row.hide()
        version.return_value = '27.0'
        row.show()
        self.app.processEvents()
        self.assertFalse(row.convert_switch.isHidden())
        self.assertIn('Converts', row.format_lbl.text())

        row.hide()
        version.return_value = '26.2'
        row.show()
        self.app.processEvents()
        self.assertTrue(row.convert_switch.isHidden())
        self.assertEqual(row.format_lbl.text(), 'Installs as is')
        row.close()

    def test_retheme_restyles_the_caption(self):
        _, row = self._row()
        row.show()
        self.app.processEvents()
        row.format_lbl.setStyleSheet("")
        ColorThemeManager.instance().theme_changed.emit()
        self.app.processEvents()
        self.assertTrue(row.format_lbl.styleSheet())


class ApplyConversionTests(unittest.TestCase):
    def test_apply_only_converts_for_ios27_even_with_saved_opt_in(self):
        for version in ('26.2', '26.6', '26.9', '27.0', '27.1', ''):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                tweak = pt.PosterboardTweak()
                with patch.object(pt, 'prompt_legacy_convert', return_value=True):
                    self.assertTrue(tweak.add_tendie(_legacy_zip(tmp), '27.0'))
                # Simulate a wallpaper imported and opted into on iOS 27, then
                # applied with a different device selected.
                self.assertTrue(tweak.tendies[0].auto_convert)
                tweak.config_manager = Mock(structure_version=61)
                tweak.config_manager.update_sqlite.return_value = str(Path(tmp) / 'staged.sqlite3')
                template_root = Path(tmp) / 'template'
                template_root.mkdir()
                template = SimpleNamespace(domain='com.apple.PosterBoard', name='Legacy template',
                                           extract=Mock(return_value=str(template_root)))
                with patch.object(tweak, 'create_live_photo_files'), \
                     patch.object(tweak, 'create_video_loop_files'), \
                     patch.object(tweak, 'recursive_add'), \
                     patch.object(pt.posterboard_converter, 'convert_tree', return_value=[]) as convert, \
                     patch.object(pt.posterboard_converter, 'rename_descriptors_to_skeleton', return_value=[]) as rename:
                    tweak.apply_tweak([], tmp, [template], version, False)
                expected = version.startswith('27.')
                self.assertEqual(convert.call_count, 2 if expected else 0)
                self.assertEqual(rename.call_count, 2 if expected else 0)
                if not expected:
                    extracted = Path(tmp).rglob('Wallpaper.plist')
                    self.assertTrue(any(plistlib.loads(path.read_bytes())['family'] == 'Marble'
                                        for path in extracted))


class InvalidImportTests(unittest.TestCase):
    def test_invalid_archive_warns_and_next_wallpaper_still_imports(self):
        from src.gui.ios import posterboard as page
        app = QApplication.instance() or QApplication([])  # noqa: F841 -- keeps the QApplication alive
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / 'broken.tendies'
            invalid.write_text('<html>Download failed</html>')
            valid = _modern_zip(directory)
            tweak = pt.PosterboardTweak()
            owner = SimpleNamespace(
                window=None, refresh_tendies=Mock())
            with patch('PySide6.QtWidgets.QFileDialog.getOpenFileNames',
                       return_value=([str(invalid), valid], '')), \
                 patch('PySide6.QtWidgets.QMessageBox.warning') as warning, \
                 patch.dict(page.tweaks, {page.TweakID.PosterBoard: tweak}):
                page.IOSPosterboardPage.show_add_tendies_dialog(owner)
            warning.assert_called_once()
            self.assertIn('broken.tendies', warning.call_args.args[2])
            self.assertIn('not a valid wallpaper ZIP', warning.call_args.args[2])
            self.assertEqual([item.path for item in tweak.tendies], [valid])
            owner.refresh_tendies.assert_called_once()


if __name__ == '__main__':
    unittest.main()
