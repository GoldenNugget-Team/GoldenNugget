"""Offline preset catalog regressions: validation, index, submitting and the CI tool."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
import resources_rc  # noqa: F401

from src.controllers import preset_catalog, share_code
from src.controllers.preset_catalog import CatalogEntry, CatalogError
from src.controllers.preset_manager import PresetManager

ON = {'enabled': True, 'value': True}
VALID = PresetManager._valid_import_structure
TOOL = Path(__file__).resolve().parent / 'preset_catalog.py'


def code(**tweaks):
    return share_code.encode(tweaks or {'NoLiquidDock': ON})


SPRINGBOARD = '/var/Managed Preferences/mobile/com.apple.springboard.plist'
TEMPLATE_CONFIG = {'title': 'Dock Tweaks', 'author': 'Someone', 'description': 'Dock things.',
                   'format_version': '3', 'min_version': '26.0', 'tags': ['dock'], 'tweaks': [
                       {'id': 'hide', 'label': 'Hide Dock', 'writes': [
                           {'type': 'plist', 'path': SPRINGBOARD, 'values': {'SBHideDock': True}}]}]}


def batter(path, config=None):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Dock/config.json', json.dumps(config or TEMPLATE_CONFIG))
    return path


def raw(**fields):
    data = {'format': 1, 'name': 'Solid Glass', 'author': 'Team', 'code': code()}
    data.update(fields)
    return data


class Validation(unittest.TestCase):
    def test_valid_entry(self):
        entry = preset_catalog.validate_entry(
            raw(tags=[' Minimal '], ios_min='26.0', description=' Solid dock. '), 'solid-glass', VALID)
        self.assertEqual((entry.id, entry.tags, entry.tweak_count), ('solid-glass', ['minimal'], 1))
        self.assertEqual(entry.description, 'Solid dock.')
        self.assertEqual(entry.ios_range(), '26.0+')

    def test_untested_flag(self):
        self.assertFalse(preset_catalog.validate_entry(raw(), 'solid-glass', VALID).untested)
        entry = preset_catalog.validate_entry(raw(untested=True), 'solid-glass', VALID)
        self.assertTrue(entry.untested)
        self.assertTrue(entry.to_file()['untested'])
        self.assertNotIn('untested', preset_catalog.validate_entry(raw(), 'solid-glass', VALID).to_file())
        with self.assertRaises(CatalogError):
            preset_catalog.validate_entry(raw(untested='yes'), 'solid-glass', VALID)
        index = preset_catalog.build_index([entry], generated=5)
        entries, rejected = preset_catalog.parse_index(json.dumps(index).encode(), VALID)
        self.assertEqual((rejected, entries[0].untested), (0, True), 'the flag survives the index')

    def test_rejections(self):
        cases = [
            (raw(), 'Bad_Name'), (raw(), 'a'), (raw(name=''), 'ok-id'), (raw(author=3), 'ok-id'),
            (raw(name='x' * 61), 'ok-id'), (raw(tags=['t'] * 9), 'ok-id'), (raw(tags=['x' * 25]), 'ok-id'),
            (raw(ios_min='latest'), 'ok-id'), (raw(ios_min='18', ios_max='17'), 'ok-id'),
            (raw(code='see ' + code()), 'ok-id'), (raw(code=None), 'ok-id'), (raw(format=2), 'ok-id'),
        ]
        for data, entry_id in cases:
            with self.subTest(data=data, entry_id=entry_id), self.assertRaises(CatalogError):
                preset_catalog.validate_entry(data, entry_id, VALID)
        with self.assertRaises(share_code.ShareCodeError):
            preset_catalog.validate_entry(raw(code='GN1.AAAA'), 'ok-id', VALID)
        unknown = share_code.PREFIX + share_code.encode({'NoLiquidDock': ON})[4:]
        with mock.patch.object(share_code, 'decode', return_value={'shared_count': 0}), \
                self.assertRaises(CatalogError):
            preset_catalog.validate_entry(raw(code=unknown), 'ok-id', VALID)

    def test_ios_range(self):
        entry = CatalogEntry('a-b', 'n', 'a', 'c', ios_min='17.2', ios_max='18')
        self.assertTrue(entry.supports(''))
        self.assertFalse(entry.supports('17.1'))
        self.assertTrue(entry.supports('17.2'))
        self.assertTrue(entry.supports('18.7.1'), '"18" covers every 18.x release')
        self.assertFalse(entry.supports('26.0'))
        self.assertTrue(CatalogEntry('a-b', 'n', 'a', 'c', ios_max='18.4').supports('18.4.1'))
        self.assertTrue(CatalogEntry('a-b', 'n', 'a', 'c').supports('26.1'))

    def test_search(self):
        entry = CatalogEntry('a-b', 'Battery Saver', 'nuggetfan', 'c', 'Fewer daemons', tags=['battery'])
        self.assertTrue(entry.matches('battery FAN'))
        self.assertTrue(entry.matches(''))
        self.assertFalse(entry.matches('glass'))


class Index(unittest.TestCase):
    def test_round_trip_skips_damaged_rows(self):
        good = preset_catalog.validate_entry(raw(), 'solid-glass', VALID)
        other = preset_catalog.validate_entry(raw(name='Mirror', code=code(RTL=ON)), 'mirror', VALID)
        index = preset_catalog.build_index([good, other], generated=5)
        self.assertEqual([row['id'] for row in index['presets']], ['mirror', 'solid-glass'])
        index['presets'] += [{'id': 'BAD', 'name': 'x'}, 'junk', dict(index['presets'][0])]
        entries, rejected = preset_catalog.parse_index(json.dumps(index).encode(), VALID)
        self.assertEqual([entry.id for entry in entries], ['mirror', 'solid-glass'])
        self.assertEqual(rejected, 3, 'bad id, non-object and duplicate id are skipped')

    def test_unusable_indexes(self):
        for data in (b'not json', b'[]', json.dumps({'format': 2, 'presets': []}).encode(),
                     b' ' * (preset_catalog.MAX_INDEX_BYTES + 1)):
            with self.subTest(data=data[:20]), self.assertRaises(CatalogError):
                preset_catalog.parse_index(data, VALID)

    def test_cache(self):
        preset_catalog.write_cache(b'{"format": 1}')
        data, saved_at = preset_catalog.read_cache()
        self.assertEqual(data, b'{"format": 1}')
        self.assertGreater(saved_at, 0)


class Templates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = batter(Path(self.tmp.name) / 'dock-tweaks.batter')

    def test_entry_round_trips_through_the_index(self):
        entry = preset_catalog.template_entry(self.path, 'dock-tweaks')
        self.assertEqual((entry.name, entry.ios_min, entry.tags, entry.writes),
                         ('Dock Tweaks', '26.0', ['dock'], [('Hide Dock', [SPRINGBOARD])]))
        index = json.dumps(preset_catalog.build_index([], 1, templates=[entry])).encode()
        presets, templates, rejected = preset_catalog.parse_catalog(index)
        self.assertEqual((presets, rejected), ([], 0))
        self.assertEqual(templates[0], entry)
        self.assertTrue(templates[0].url.endswith('/GoldenNugget-Presets/templates/dock-tweaks.batter'))
        self.assertEqual(preset_catalog.parse_index(index), ([], 0), 'old callers ignore templates')

    def test_damaged_rows_are_skipped(self):
        good = preset_catalog.template_entry(self.path, 'dock-tweaks').to_row()
        rows = [dict(good, sha256='x'), dict(good, size=0), dict(good, id='../x'),
                dict(good, tweaks=[{'label': 1}]), good, good]
        _, templates, rejected = preset_catalog.parse_catalog(
            json.dumps({'format': 1, 'presets': [], 'templates': rows}).encode())
        self.assertEqual((len(templates), rejected), (1, 5))

    def test_save_checks_size_and_hash(self):
        entry = preset_catalog.template_entry(self.path, 'dock-tweaks')
        data = self.path.read_bytes()
        with mock.patch.object(preset_catalog, 'templates_dir', return_value=self.tmp.name + '/store'):
            os.makedirs(self.tmp.name + '/store')
            with self.assertRaises(CatalogError):
                preset_catalog.save_template(entry, data + b'x')
            with self.assertRaises(CatalogError):
                preset_catalog.save_template(entry, b'y' * len(data))
            saved = preset_catalog.save_template(entry, data)
        self.assertEqual(Path(saved).read_bytes(), data)
        self.assertEqual(Path(saved).name, 'dock-tweaks.batter')


class Submitting(unittest.TestCase):
    def test_submission_file(self):
        filename, text = preset_catalog.submission(
            'Solid Glass!', 'kik', code(), description='Solid.', ios_min='26.0', tags=['glass', ' ', 'Min'],
            validate=VALID)
        self.assertEqual(filename, 'solid-glass.json')
        data = json.loads(text)
        self.assertEqual(data['tags'], ['glass', 'min'])
        self.assertNotIn('ios_max', data, 'empty fields are left out')
        self.assertEqual(preset_catalog.validate_entry(data, 'solid-glass', VALID).name, 'Solid Glass!')
        with self.assertRaises(CatalogError):
            preset_catalog.submission('Name', '', code(), validate=VALID)

    def test_slug(self):
        self.assertEqual(preset_catalog.slugify('  My  Cool--Setup  '), 'my-cool-setup')
        self.assertTrue(preset_catalog.slugify('Мой пресет').startswith('preset-'))
        self.assertTrue(preset_catalog.ID_PATTERN.match(preset_catalog.slugify('Мой пресет')))

    def test_submit_url(self):
        url, prefilled = preset_catalog.submit_url('a-b.json', '{"name": "A & B"}\n')
        self.assertTrue(prefilled)
        self.assertTrue(url.startswith(preset_catalog.REPO_URL + '/new/main/presets?filename=a-b.json&value='))
        self.assertIn('%26', url)
        self.assertNotIn(' ', url)
        with mock.patch.object(preset_catalog, 'MAX_SUBMIT_URL', 80):
            url, prefilled = preset_catalog.submit_url('a-b.json', 'x' * 100)
        self.assertFalse(prefilled)
        self.assertNotIn('value=', url)


class Tool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'presets').mkdir()
        self.write('solid-glass', raw())
        self.git('init', '-q', '-b', 'main')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def write(self, name, data):
        (self.root / 'presets' / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)

    def test_build_and_check(self):
        out = self.root / 'site' / 'index.json'
        self.assertEqual(self.run_tool('build', str(self.root), str(out)).returncode, 0)
        entries, rejected = preset_catalog.parse_index(out.read_bytes(), VALID)
        self.assertEqual(([entry.id for entry in entries], rejected), (['solid-glass'], 0))
        summary = self.root / 'summary.md'
        result = self.run_tool('check', str(self.root), '--summary', str(summary))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('| `presets/solid-glass.json` | Solid Glass |', summary.read_text())

    def test_check_finds_problems(self):
        self.git('checkout', '-qb', 'pr')
        self.write('copy', raw(name='Copy'))
        self.write('Bad', raw())
        (self.root / 'presets' / 'broken.json').write_text('{', encoding='utf-8')
        (self.root / 'README.md').write_text('hi', encoding='utf-8')
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'pr')
        result = self.run_tool('check', str(self.root), '--changed-since', 'main')
        self.assertEqual(result.returncode, 1)
        for text in ('presets/Bad.json::File names', 'presets/broken.json::Not valid JSON',
                     'presets/copy.json::The same share code', 'README.md::Community pull requests'):
            self.assertIn(text, result.stdout)
        self.assertEqual(self.run_tool('build', str(self.root), str(self.root / 'i.json')).returncode, 1)
        summary = self.root / 'summary.md'
        self.run_tool('check', str(self.root), '--summary', str(summary))
        self.assertNotIn('Batter Builder', summary.read_text())     # only templates get the hint

    def test_templates_are_checked_and_published(self):
        self.git('checkout', '-qb', 'pr')
        (self.root / 'templates').mkdir()
        batter(self.root / 'templates' / 'dock-tweaks.batter')
        bad = dict(TEMPLATE_CONFIG, tweaks=[{'id': 'x', 'label': 'X', 'writes': [
            {'type': 'plist', 'path': '/System/Library/x.plist', 'values': {'a': 1}}]}])
        batter(self.root / 'templates' / 'bad-one.batter', bad)
        self.git('add', '-A')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'pr')
        summary = self.root / 'summary.md'
        result = self.run_tool('check', str(self.root), '--changed-since', 'main', '--summary', str(summary))
        self.assertEqual(result.returncode, 1)
        self.assertIn('templates/bad-one.batter::', result.stdout)
        self.assertNotIn('Community pull requests', result.stdout)
        self.assertIn(f'| Hide Dock | `{SPRINGBOARD}` |', summary.read_text())
        self.assertIn('open it in [Batter Builder](https://github.com/GoldenNugget-Team/GoldenNugget-TemplateBuilder',
                      summary.read_text())
        (self.root / 'templates' / 'bad-one.batter').unlink()
        out = self.root / 'site' / 'index.json'
        self.assertEqual(self.run_tool('build', str(self.root), str(out)).returncode, 0)
        _, templates, _ = preset_catalog.parse_catalog(out.read_bytes(), VALID)
        self.assertEqual([entry.id for entry in templates], ['dock-tweaks'])
        self.assertEqual((self.root / 'site' / 'templates' / 'dock-tweaks.batter').read_bytes(),
                         (self.root / 'templates' / 'dock-tweaks.batter').read_bytes())

    def test_deleting_is_for_maintainers(self):
        self.git('checkout', '-qb', 'pr')
        self.git('rm', '-q', 'presets/solid-glass.json')
        self.git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'rm')
        result = self.run_tool('check', str(self.root), '--changed-since', 'main')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Only maintainers remove presets and templates', result.stdout)


class Dialogs(unittest.TestCase):
    def setUp(self):
        from src.tweaks import tweak_loader
        tweak_loader.load_plist_tweaks()
        tweak_loader.load_daemons()
        self.pm = PresetManager()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pm.presets_dir = self.tmp.name
        old = dict(raw(name='Old Phones', ios_max='18', code=code(RTL=ON)), id='old-phones')
        new = dict(raw(tags=['glass']), id='solid-glass')
        self.index = json.dumps({'format': 1, 'presets': [old, new]}).encode()

    def test_catalog_dialog_filters_and_imports(self):
        from src.gui.dialogs.preset_catalog import CatalogDialog
        with mock.patch.object(preset_catalog, 'read_cache', return_value=(None, 0)):
            dialog = CatalogDialog(self.pm, '26.1', 'iPhone15,3', None, fetch=False)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertTrue(dialog.load_data(self.index))
        self.assertEqual([entry.id for entry in dialog.visible_entries()], ['solid-glass'])
        dialog.compatible_only.setChecked(False)
        self.assertEqual(dialog.list.count(), 2)
        dialog.search.setText('glass')
        self.assertEqual(dialog.list.count(), 1)
        self.assertEqual(dialog.selected_entry().id, 'solid-glass')
        self.assertIsNotNone(dialog.risk_panel)
        self.assertFalse(dialog.load_data(b'junk'), 'a bad download keeps the shown list')
        self.assertEqual(dialog.list.count(), 1)
        with mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'):
            dialog._import()
        self.assertEqual(dialog.imported, ['Solid Glass'])
        stored = self.pm.read_preset('Solid Glass')
        self.assertTrue(stored['tweaks']['NoLiquidDock']['enabled'])
        self.assertFalse(stored['tweaks']['RTL']['enabled'])

    def test_submit_dialog(self):
        from src.gui.dialogs.preset_catalog import SubmitPresetDialog
        self.pm.save_preset('Mine', 'My description')
        dialog = SubmitPresetDialog(self.pm, 'Mine', code())
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.description_edit.toPlainText(), 'My description')
        with self.assertRaises(CatalogError):
            dialog.build()
        dialog.author_edit.setText('kik')
        dialog.tags_edit.setText('glass, minimal')
        filename, text = dialog.build()
        self.assertEqual(filename, 'mine.json')
        self.assertEqual(json.loads(text)['tags'], ['glass', 'minimal'])
        self.assertTrue(json.loads(text)['untested'], 'not tested unless the author says so')
        dialog.tested_check.setChecked(True)
        self.assertNotIn('untested', json.loads(dialog.build()[1]))
        with mock.patch('src.gui.dialogs.preset_catalog.QDesktopServices.openUrl') as opened, \
                mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'):
            dialog._submit()
        url = opened.call_args.args[0].toString(opened.call_args.args[0].ComponentFormattingOption.FullyEncoded)
        self.assertIn('/new/main/presets?filename=mine.json&value=', url)
        self.assertEqual(dialog.submitted, ('mine.json', True))


    def test_templates_tab_downloads_and_adds(self):
        from src.gui.dialogs.preset_catalog import CatalogDialog
        path = batter(Path(self.tmp.name) / 'dock-tweaks.batter')
        entry = preset_catalog.template_entry(path, 'dock-tweaks')
        index = json.dumps(preset_catalog.build_index([], 1, templates=[entry])).encode()
        with mock.patch.object(preset_catalog, 'read_cache', return_value=(None, 0)):
            dialog = CatalogDialog(self.pm, '26.1', 'iPhone15,3', None, fetch=False)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.load_data(index))
        self.assertEqual(dialog.list.count(), 0, 'presets are shown first')
        dialog.kind.setCurrentIndex(1)
        self.assertEqual(dialog.selected_entry().id, 'dock-tweaks')
        self.assertIn(SPRINGBOARD, dialog.writes.text())
        self.assertTrue(dialog.preview_button.isHidden())
        self.assertIsNone(dialog.risk_panel)
        added = []
        dialog.add_template = lambda saved, version: added.append((Path(saved).name, version))
        store = Path(self.tmp.name) / 'store'
        store.mkdir()
        with mock.patch.object(preset_catalog, 'templates_dir', return_value=str(store)), \
                mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'), \
                mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.critical') as critical:
            self.assertFalse(dialog.install_template(entry, b'tampered'))
            critical.assert_called_once()
            self.assertTrue(dialog.install_template(entry, path.read_bytes()))
        self.assertEqual(added, [('dock-tweaks.batter', '26.1')])
        self.assertEqual(dialog.added_templates, [str(store / 'dock-tweaks.batter')])

    def test_templates_page_links_to_batter_builder(self):
        from types import SimpleNamespace

        from src.gui.ios import templates
        page = templates.IOSTemplatesPage(SimpleNamespace(settings=None, device_manager=None))
        self.addCleanup(page.deleteLater)
        card = page.templates_builder_card
        self.assertEqual(page._builder_title.text(), 'Create Your Own Template')
        self.assertEqual(page.templates_layout.indexOf(card), 1, 'right under the import button')
        with mock.patch.object(templates.QDesktopServices, 'openUrl') as open_url:
            card.mousePressEvent(None)
        self.assertIn('GoldenNugget-TemplateBuilder/releases', open_url.call_args[0][0].toString())
        page._load_templates_list()
        self.assertEqual(page.templates_layout.indexOf(card), 1, 'refreshing the list keeps the card')

    def test_catalog_refreshes_the_dedicated_templates_page(self):
        from types import SimpleNamespace

        from src.gui.dialogs.preset_catalog import refresh_template_list
        templates = mock.Mock()
        posterboard = mock.Mock()
        refresh_template_list(SimpleNamespace(ios_templates=templates, ios_posterboard=posterboard))
        templates._load_templates_list.assert_called_once_with()
        posterboard._load_templates_list.assert_not_called()

    def test_templates_page_import_and_empty_refresh(self):
        from types import SimpleNamespace

        from src.gui.ios import templates
        from src.tweaks.posterboard.template_options.templates_tweak import (
            TemplatesTweak,
        )
        holder = TemplatesTweak()
        with mock.patch.dict(templates.tweaks, {templates.TweakID.Templates: holder}):
            page = templates.IOSTemplatesPage(SimpleNamespace(
                device_manager=SimpleNamespace(get_current_device_version=lambda: '26.2')))
            self.addCleanup(page.deleteLater)
            path = batter(Path(self.tmp.name) / 'import.batter')
            with mock.patch('PySide6.QtWidgets.QFileDialog.getOpenFileNames',
                            return_value=([str(path)], '')), \
                    mock.patch('PySide6.QtWidgets.QMessageBox.warning') as warning:
                page.templates_import_btn.click()
            warning.assert_not_called()
            self.assertEqual(len(holder.templates), 1)
            self.assertEqual(holder.templates[0].name, 'Dock Tweaks')
            self.assertTrue(page.templates_placeholder.isHidden())
            self.assertEqual(page.templates_layout.count(), 4)
            holder.templates[0].clean_files()
            holder.templates.clear()
            page._load_templates_list()
            self.assertFalse(page.templates_placeholder.isHidden())
            self.assertEqual(page.templates_layout.count(), 3)

    def test_embedded_page_mode(self):
        from PySide6.QtWidgets import QPushButton, QWidget

        from src.gui.dialogs.preset_catalog import CatalogDialog
        host = QWidget()
        self.addCleanup(host.deleteLater)
        with mock.patch.object(preset_catalog, 'read_cache', return_value=(None, 0)):
            panel = CatalogDialog(self.pm, '26.1', 'iPhone15,3', None, host, fetch=False, embedded=True)
        self.assertFalse(panel.isWindow())
        self.assertNotIn(preset_catalog.QT_TRANSLATE_NOOP('PresetCatalog', 'Close'),
                         [button.text() for button in panel.findChildren(QPushButton)])
        changes = []
        panel.on_change = lambda: changes.append(1)
        panel.load_data(self.index)
        panel.compatible_only.setChecked(False)
        with mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'):
            panel._import()
        self.assertEqual(changes, [1])

    def test_updates_are_marked_and_replace_the_import(self):
        from src.gui.dialogs.preset_catalog import CatalogDialog
        store = Path(self.tmp.name) / 'store'
        store.mkdir()
        patcher = mock.patch.object(preset_catalog, 'templates_dir', return_value=str(store))
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(preset_catalog, 'read_cache', return_value=(None, 0)):
            dialog = CatalogDialog(self.pm, '26.1', 'iPhone15,3', None, fetch=False)
        self.addCleanup(dialog.deleteLater)
        dialog.load_data(self.index)
        with mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'):
            dialog._import()
        self.assertEqual(dialog.status_of(dialog.selected_entry())[0], preset_catalog.INSTALLED)
        self.assertEqual(dialog.import_button.text(), 'Import Again')
        newer = dict(raw(tags=['glass'], code=code(NoLiquidDock=ON, NoLiquidClock=ON)), id='solid-glass')
        dialog.load_data(json.dumps({'format': 1, 'presets': [newer]}).encode())
        self.assertEqual(dialog.update_count(), 1)
        self.assertIn('Update available', dialog.list.currentItem().text())
        self.assertEqual(dialog.import_button.text(), 'Update')
        with mock.patch('src.gui.dialogs.preset_catalog.QMessageBox.information'):
            dialog._import()
        self.assertEqual(self.pm.list_presets(), ['Solid Glass'], 'an update replaces, never copies')
        self.assertTrue(self.pm.read_preset('Solid Glass')['tweaks']['NoLiquidClock']['enabled'])
        self.assertEqual(dialog.update_count(), 0)

    def test_add_template_replaces_an_older_copy(self):
        from src.gui.dialogs.preset_catalog import add_template
        from src.tweaks.tweaks import TweakID, tweaks
        path = str(batter(Path(self.tmp.name) / 'dock-tweaks.batter'))
        holder = tweaks[TweakID.Templates]
        before = list(holder.templates)
        self.addCleanup(setattr, holder, 'templates', before)
        add_template(path, '26.1')
        add_template(path, '26.1')
        self.assertEqual([item.path for item in holder.templates if item.path == path], [path])


if __name__ == '__main__':
    unittest.main()
