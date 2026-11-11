"""Offline integration regressions for portable presets, reports and CLI plans.

Run with the project dependencies installed; no phone or network is used.
"""
import contextlib
import io
import json
import os
import plistlib
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from src.cli.main import dispatch
from src.controllers.diagnostics import collect_diagnostics, write_diagnostics
from src.controllers.preset_bundle import export_bundle, import_bundle
from src.controllers.preset_manager import PresetManager
from src.controllers.wallpaper_validation import validate_wallpaper

APP = QApplication.instance() or QApplication([])


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def zip(self, name, entries):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            for key, value in entries.items():
                archive.writestr(key, value)
        return path


class PortablePresets(Workspace):
    def setUp(self):
        super().setUp()
        self.template = self.root / 'source.batter'
        self.template.write_bytes(b'example-template')
        self.icon = self.root / 'icon.png'
        self.icon.write_bytes(b'example-icon')
        self.data = {'tweaks': {
            'Templates': {'templates': [str(self.template)]},
            'IconThemes': {'themes': [{'bundle_id': 'com.example.app', 'display_name': 'App', 'icon_path': str(self.icon)}]},
            'SBBuildNumber': {'enabled': True, 'value': True}}, 'metadata': {'description': 'Demo'}}
        self.destination = self.root / 'preset.gnpreset'

    def import_file(self):
        return import_bundle(self.destination, self.root / 'persistent', PresetManager._valid_import_structure)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.destination) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(entries['manifest.json'])
        mutate(manifest, entries)
        entries['manifest.json'] = json.dumps(manifest)
        self.zip('preset.gnpreset', entries)

    def test_round_trip_survives_removed_sources_and_preserves_original(self):
        export_bundle(self.data, self.destination)
        self.template.unlink()
        self.icon.unlink()
        data, owned = self.import_file()
        path = Path(data['tweaks']['Templates']['templates'][0])
        self.assertEqual(path.read_bytes(), b'example-template')
        self.assertTrue(path.is_relative_to(owned))
        self.assertEqual(Path(data['tweaks']['IconThemes']['themes'][0]['icon_path']).read_bytes(), b'example-icon')
        self.assertEqual(self.data['tweaks']['Templates']['templates'][0], str(self.template))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertNotIn(str(self.root), archive.read('manifest.json').decode())

    def test_checksum_mismatch_cleans_staging(self):
        export_bundle(self.data, self.destination)
        self.rewrite(lambda manifest, entries: entries.update({next(iter(manifest['assets'])): b'x' * next(iter(manifest['assets'].values()))['size']}))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.import_file()
        self.assertEqual(list((self.root / 'persistent').iterdir()), [])

    def test_external_references_and_extra_files_are_rejected(self):
        for mutate in (
            lambda manifest, entries: manifest['preset']['tweaks']['Templates'].update(templates=['/etc/passwd']),
            lambda manifest, entries: entries.update({'unlisted': b'no'}),
        ):
            export_bundle(self.data, self.destination)
            self.rewrite(mutate)
            with self.assertRaises(ValueError):
                self.import_file()

    def test_missing_asset_does_not_replace_existing_export(self):
        self.destination.write_bytes(b'previous export')
        self.template.unlink()
        with self.assertRaises(ValueError):
            export_bundle(self.data, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'previous export')

    def test_manager_import_is_atomic_unique_and_does_not_load(self):
        export_bundle(self.data, self.destination)
        pm = object.__new__(PresetManager)
        pm.presets_dir = str(self.root / 'presets')
        Path(pm.presets_dir).mkdir()
        with patch.object(pm, '_apply', side_effect=AssertionError('Import must not activate')):
            first, name = pm.import_preset(str(self.destination), 'Demo')
            second, other = pm.import_preset(str(self.destination), 'Demo')
        self.assertTrue(first and second)
        self.assertNotEqual(name, other)
        self.assertEqual(set(pm.list_presets()), {name, other})
        data = json.loads(Path(pm.get_preset_path(name)).read_text())
        self.assertTrue(Path(data['tweaks']['Templates']['templates'][0]).exists())
        with patch('src.controllers.preset_manager.os.replace', side_effect=OSError('disk full')):
            ok, error = pm.import_preset(str(self.destination), 'Failed')
        self.assertFalse(ok)
        self.assertIn('disk full', error)
        self.assertEqual(len(list((Path(pm.presets_dir) / 'assets').iterdir())), 2)

    def test_preview_preset_does_not_copy_icons_or_parse_templates(self):
        pm = object.__new__(PresetManager)
        with patch('src.tweaks.hidden.current_hidden_tweak_names', return_value=set()), \
             patch('src.tweaks.icon_themes.icon_themes_tweak.IconThemesTweak.store_icon', side_effect=AssertionError('copy')), \
             patch('src.tweaks.posterboard.template_file.TemplateFile.__init__', side_effect=AssertionError('parse')):
            self.assertTrue(pm._apply(self.data, preview_only=True))

    def test_real_template_loads_from_bundle_before_device_selection(self):
        config = dict(options=[], domain='AppDomain-com.example', format_version=2,
                      title='Demo', author='Author', min_version='27.0')
        self.zip('source.batter', {'config.json': json.dumps(config)})
        export_bundle(self.data, self.destination)
        self.template.unlink()
        imported, _ = self.import_file()
        pm = object.__new__(PresetManager)
        with patch('src.tweaks.hidden.current_hidden_tweak_names', return_value=set()), \
             patch('PySide6.QtWidgets.QMessageBox.exec', side_effect=AssertionError('Unexpected dialog')):
            self.assertTrue(pm._apply(imported))
        from src.tweaks.tweaks import TweakID, tweaks
        template = tweaks[TweakID.Templates].templates[0]
        self.assertEqual(template.name, 'Demo')
        self.assertEqual(template.min_version, '27.0')
        with self.assertRaisesRegex(ValueError, 'does not support'):
            tweaks[TweakID.Templates].apply_tweak([], str(self.root), [], '26.2', False)

    def test_gui_transfer_runs_on_worker_and_returns_result(self):
        from PySide6.QtCore import QThread

        from src.gui.dialogs.file_task import run_file_task
        main_thread = QThread.currentThread()
        self.assertTrue(run_file_task(None, 'Local file transfer',
                                     lambda: QThread.currentThread() != main_thread))


class WallpaperReports(Workspace):
    def test_valid_package_and_legacy_script_warnings(self):
        path = self.zip('legacy.tendies', {
            'descriptors/ABC/versions/0/contents/Old.wallpaper/Wallpaper.plist': plistlib.dumps({'family': 'Marble'}),
            'descriptors/ABC/main.caml': '<caml><scriptObject src="old.js"/></caml>',
        })
        report = validate_wallpaper(path, '27.0')
        self.assertTrue(report['valid'])
        self.assertEqual(report['descriptors'], 1)
        self.assertEqual(report['families'], ['Marble'])
        self.assertEqual({item['code'] for item in report['issues']}, {'external_script', 'legacy_family'})

    def test_rejects_traversal_links_duplicates_and_broken_documents(self):
        for entry in ('../escape', '/absolute', 'C:/windows', 'a\\b'):
            path = self.zip('bad.tendies', {entry: b'bad'})
            if entry == 'a\\b' and zipfile.ZipInfo(entry).filename != entry:
                # zipfile itself folds the OS separator at read time on
                # Windows ('a\b' becomes 'a/b'), so the hostile byte can
                # never reach the name check there — nothing to assert.
                continue
            self.assertFalse(validate_wallpaper(path)['valid'], entry)
        path = self.zip('bad.tendies', {'descriptors/A/bad.plist': b'not a plist'})
        self.assertFalse(validate_wallpaper(path)['valid'])
        link = zipfile.ZipInfo('link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(link, '../target')
        self.assertFalse(validate_wallpaper(path)['valid'])
        path = self.zip('bad.tendies', {'File.plist': b'a', 'file.plist': b'b'})
        self.assertFalse(validate_wallpaper(path)['valid'])

    def test_crc_damage_is_detected_in_media(self):
        path = self.zip('bad.tendies', {'descriptors/A/media.bin': b'unique-media-content'})
        raw = path.read_bytes().replace(b'unique-media-content', b'broken-media-content', 1)
        path.write_bytes(raw)
        self.assertFalse(validate_wallpaper(path)['valid'])

    def test_template_version_constraints(self):
        config = dict(options=[], domain='AppDomain-com.apple.PosterBoard', format_version=2,
                      title='Demo', author='Author', min_version='27.0')
        path = self.zip('template.batter', {'config.json': json.dumps(config)})
        self.assertFalse(validate_wallpaper(path, '26.2')['valid'])
        self.assertTrue(validate_wallpaper(path, '27.0')['valid'])

    def test_background_dialog_completes_and_allows_closing(self):
        from src.gui.dialogs.wallpaper_validation import WallpaperValidationDialog
        path = self.zip('example.tendies', {'descriptors/A/file.bin': b'hello'})
        dialog = WallpaperValidationDialog(str(path), '27.0')
        self.assertTrue(dialog._thread.wait(5000))
        APP.processEvents()
        self.assertTrue(dialog.save.isEnabled())
        self.assertIn('Checks passed', dialog.details.toPlainText())
        dialog.reject()


class Diagnostics(Workspace):
    def test_redaction_allowlist_and_archive_preview_match(self):
        udid, password = '00008110-0012345678901234', 'a private password'
        path = self.root / 'session.log'
        path.write_text(f'{udid} user@example.com {Path.home()}\npassword="{password}"\nAuthorization: Bearer abc123\n--password "other secret"\n')
        values = dict(backup_password=password, auto_reboot=True, organization_name='Private Org', unknown='never export')
        settings = SimpleNamespace(allKeys=lambda: list(values), contains=lambda key: key in values,
                                   value=lambda key, default=None, **kw: values.get(key, default))
        report = collect_diagnostics(settings, log_path=path)
        serialized = json.dumps(report)
        for private in (udid, password, 'user@example.com', str(Path.home()), 'abc123', 'other secret', 'never export'):
            self.assertNotIn(private, serialized)
        self.assertEqual(report['preferences'], dict(auto_reboot=True))
        report['log'] = 'edited preview'
        destination = self.root / 'diagnostics.zip'
        write_diagnostics(destination, report)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.namelist(), ['diagnostics.json', 'session.log'])
            self.assertEqual(archive.read('session.log'), b'edited preview')
            self.assertNotIn('log', json.loads(archive.read('diagnostics.json')))

    def test_missing_log_is_reported_without_failure(self):
        report = collect_diagnostics(log_path=self.root / 'missing')
        self.assertEqual(report['log_status'], 'unavailable')


class CLI(Workspace):
    def command(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = dispatch([*argv, '--json'])
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        document = json.loads(out.getvalue())
        self.assertEqual(document['exit_code'], code)
        return code, document

    def test_offline_dry_run_never_connects_restores_or_saves(self):
        from src.tweaks.tweaks import tweaks
        for tweak in tweaks.values():
            tweak.enabled = False
        with patch('src.cli.common.ensure_device', side_effect=AssertionError('connect')), \
             patch('src.devicemanagement.device_manager.DeviceManager.apply_changes', side_effect=AssertionError('restore')), \
             patch.object(PresetManager, 'save_preset', side_effect=AssertionError('save')):
            code, document = self.command(['apply', '--dry-run', '--ios-version', '27.0', '--model', 'iPhone16,1',
                                           '--preset', 'none', '--set', 'SBBuildNumber=false'])
        self.assertEqual(code, 0, document)
        self.assertIs(document['data']['preview']['entries']['SBBuildNumber']['value'], False)
        self.assertTrue(document['data']['dry_run'])

    def test_unknown_command_and_parser_error_stay_json(self):
        for args in (['unknown'], ['apply', '--invalid']):
            code, document = self.command(args)
            self.assertNotEqual(code, 0)
            self.assertFalse(document['success'])
            self.assertTrue(document['error'])

    def test_validation_returns_structured_failure(self):
        code, document = self.command(['wallpaper', 'validate', str(self.root / 'missing')])
        self.assertEqual(code, 1)
        self.assertFalse(document['data']['valid'])

    def test_registry_output_has_typed_fields(self):
        code, document = self.command(['tweaks', 'list', '--all'])
        self.assertEqual(code, 0)
        row = document['data']['tweaks'][0]
        self.assertIsInstance(row['enabled'], bool)
        self.assertIn('plist', row)

    def test_conflicting_dry_run_returns_failure(self):
        from src.tweaks.tweaks import tweaks
        for tweak in tweaks.values():
            tweak.enabled = False
        code, document = self.command(['apply', '--dry-run', '--ios-version', '27.0', '--model', 'iPhone16,1',
                                       '--preset', 'none', '--enable', 'RTL', '--enable', 'LTR'])
        self.assertEqual(code, 1)
        self.assertTrue(document['data']['conflicts'])

    def test_apply_failure_has_nonzero_status(self):
        device = SimpleNamespace(udid='offline', name='Example', version='27.0', build='')
        with patch('src.cli.common.ensure_device', return_value=device), \
             patch('src.devicemanagement.device_manager.DeviceManager.apply_changes', return_value=False):
            code, document = self.command(['apply', '--preset', 'none'])
        self.assertEqual(code, 1)
        self.assertIs(document['data']['applied'], False)


if __name__ == '__main__':
    unittest.main()
