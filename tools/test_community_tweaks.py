"""Community tweaks in .batter templates: parsing, merging, presets and validation."""
import json
import os
import plistlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'qt'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

APP = QApplication.instance() or QApplication([])
import resources_rc  # noqa: F401

from src.controllers.preset_manager import PresetManager
from src.controllers.wallpaper_validation import validate_wallpaper
from src.devicemanagement.device_manager import DeviceManager
from src.exceptions.nugget_exception import NuggetException
from src.tweaks.posterboard.community_tweaks import (
    CommunityTweakError,
    check_path,
    collect,
    parse_tweaks,
)
from src.tweaks.posterboard.template_file import TemplateFile
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.utils.file_to_restore import FileToRestore

SPRINGBOARD = '/var/Managed Preferences/mobile/com.apple.springboard.plist'


def no_sources(name):
    raise AssertionError(name)


def tweak(**fields):
    data = {'id': 'dock', 'label': 'Hide Dock',
            'writes': [{'type': 'plist', 'path': SPRINGBOARD, 'values': {'SBHideDock': True}}]}
    data.update(fields)
    return data


class Parsing(unittest.TestCase):
    def test_plist_tweak(self):
        [item] = parse_tweaks([tweak(default=True)], no_sources)
        self.assertTrue(item.enabled)
        self.assertEqual(item.paths(), [SPRINGBOARD])

    def test_paths_must_map_to_a_domain(self):
        for path in ('/System/Library/x.plist', 'var/mobile/x', '/var/mobile/../root/x',
                     '/var/mobile//x', '/var/tmp/x', '/var/mobile/', '/var/root/Library/Lockdown/data_ark.plist'):
            with self.subTest(path=path), self.assertRaises(CommunityTweakError):
                check_path(path)
        self.assertEqual(check_path('/var/db/com.apple.xpc.launchd/disabled.plist'),
                         '/var/db/com.apple.xpc.launchd/disabled.plist')

    def test_bad_entries(self):
        bad = [
            tweak(id='bad id'), tweak(label=''), tweak(writes=[]), tweak(default='yes'),
            tweak(writes=[{'type': 'plist', 'path': SPRINGBOARD, 'values': {'a': None}}]),
            tweak(writes=[{'type': 'shell', 'path': SPRINGBOARD}]),
            tweak(writes=[{'type': 'file', 'path': '/var/mobile/a', 'source': '../x'}]),
            tweak(writes=[{'type': 'empty', 'path': '/var/mobile/a', 'owner': 7}]),
            tweak(control={'type': 'slider', 'min': 2, 'max': 1}),
            tweak(control={'type': 'choice', 'choices': []}),
            tweak(min_version='latest'),
        ]
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(CommunityTweakError):
                parse_tweaks([entry], no_sources)
        with self.assertRaises(CommunityTweakError):
            parse_tweaks([tweak(), tweak()], no_sources)

    def test_value_token_and_clamp(self):
        [item] = parse_tweaks([tweak(default=True, control={'type': 'slider', 'min': 0, 'max': 10, 'default': 4},
                                     writes=[{'type': 'plist', 'path': SPRINGBOARD,
                                              'values': {'Size': '$value', 'Nested': ['$value']}}])],
                              no_sources)
        item.value = 99
        [write] = item.active_writes()
        self.assertEqual(write.values, {'Size': 10, 'Nested': [10]})
        item.restore_state({'enabled': True, 'value': 'x'})
        self.assertEqual(item.value, 4)

    def test_choice_and_off_writes(self):
        [item] = parse_tweaks([tweak(control={'type': 'choice', 'default': 1, 'choices': [
            {'label': 'Small', 'value': 1}, {'label': 'Big', 'value': 2}]},
            writes=[{'type': 'plist', 'path': SPRINGBOARD, 'values': {'Size': '$value'}}],
            writes_off=[{'type': 'plist', 'path': SPRINGBOARD, 'values': {'Size': 0}}])], no_sources)
        self.assertEqual(item.value, 2)
        self.assertEqual(item.active_writes()[0].values, {'Size': 0})
        item.enabled = True
        self.assertEqual(item.active_writes()[0].values, {'Size': 2})


class Collect(unittest.TestCase):
    def test_merges_plists_and_skips_unsupported(self):
        first = parse_tweaks([tweak(default=True)], no_sources)
        second = parse_tweaks([tweak(id='b', default=True, writes=[
            {'type': 'plist', 'path': SPRINGBOARD, 'values': {'Other': 1}}])], no_sources)
        old = parse_tweaks([tweak(id='c', default=True, max_version='18')], no_sources)
        plists, files = collect([('A', first), ('B', second), ('C', old)], '26.1')
        self.assertEqual(plists, {SPRINGBOARD: ({'SBHideDock': True, 'Other': 1}, 501)})
        self.assertEqual(files, {})

    def test_whole_file_conflicts(self):
        one = parse_tweaks([tweak(default=True, writes=[{'type': 'empty', 'path': SPRINGBOARD}])], no_sources)
        two = parse_tweaks([tweak(default=True)], no_sources)
        with self.assertRaises(CommunityTweakError):
            collect([('A', one), ('B', two)])


def make_batter(folder, config, extra=None):
    path = Path(folder) / 'tweaks.batter'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Pack/config.json', json.dumps(config))
        for name, data in (extra or {}).items():
            archive.writestr(f'Pack/{name}', data)
    return str(path)


CONFIG = {'title': 'Pack', 'author': 'Someone', 'format_version': '3', 'tweaks': [
    tweak(default=True),
    {'id': 'blob', 'label': 'Blob', 'default': True,
     'writes': [{'type': 'file', 'path': '/var/mobile/Library/Blob.bin', 'source': 'files/blob.bin'}]},
]}


class Templates(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = make_batter(self.folder.name, CONFIG, {'files/blob.bin': b'\x01\x02'})

    def test_loads_without_domain_or_options(self):
        template = TemplateFile(self.path)
        self.assertEqual(template.domain, '')
        self.assertEqual([item.id for item in template.tweaks], ['dock', 'blob'])
        self.assertEqual(template.tweaks[1].writes[0].data, b'\x01\x02')

    def test_needs_format_3_and_present_sources(self):
        old = dict(CONFIG, format_version='2')
        with self.assertRaises(Exception):
            TemplateFile(make_batter(self.folder.name, old, {'files/blob.bin': b'x'}))
        with self.assertRaises(Exception):
            TemplateFile(make_batter(self.folder.name, CONFIG))

    def test_states_round_trip_through_a_preset(self):
        holder = TemplatesTweak()
        holder.templates = [TemplateFile(self.path)]
        holder.templates[0].tweaks[0].enabled = False
        states = holder.tweak_states()
        self.assertEqual(states, [{'dock': {'enabled': False}, 'blob': {'enabled': True}}])
        fresh = TemplatesTweak()
        fresh.templates = [TemplateFile(self.path)]
        fresh.restore_tweak_states(states, [self.path])
        self.assertFalse(fresh.templates[0].tweaks[0].enabled)
        self.assertTrue(fresh.uses_domains())
        entry = {'version': 1, 'tweaks': {'Templates': {'enabled': False, 'templates': [self.path],
                                                        'tweak_states': states}}}
        self.assertTrue(PresetManager._valid_import_structure(entry))
        entry['tweaks']['Templates']['tweak_states'] = {'x': 1}
        self.assertFalse(PresetManager._valid_import_structure(entry))

    def test_card_shows_switches(self):
        template = TemplateFile(self.path)
        host = QWidget()
        layout = QVBoxLayout(host)
        window = SimpleNamespace(device_manager=SimpleNamespace(get_current_device_version=lambda: '26.2'))
        template.create_ui(window, TemplatesTweak(), {}, layout)
        self.assertTrue(template.loaded)
        from PySide6.QtWidgets import QCheckBox
        boxes = {box.text(): box for box in host.findChildren(QCheckBox)}
        self.assertEqual(set(boxes), {'Hide Dock', 'Blob'})
        boxes['Hide Dock'].setChecked(False)
        self.assertFalse(template.tweaks[0].enabled)

    def test_validator_accepts_and_lists_writes(self):
        report = validate_wallpaper(self.path, '26.2')
        self.assertTrue(report['valid'], report['issues'])
        writes = [item['message'] for item in report['issues'] if item['code'] == 'tweak_write']
        self.assertEqual(len(writes), 2)
        broken = make_batter(self.folder.name, dict(CONFIG, tweaks=[tweak(id='?')]))
        self.assertFalse(validate_wallpaper(broken)['valid'])


class Restore(unittest.TestCase):
    def manager(self):
        return DeviceManager.__new__(DeviceManager)

    def test_adds_files_and_ios27_mirror(self):
        files = []
        self.manager()._add_community_files({SPRINGBOARD: ({'A': 1}, 501)},
                                            {'/var/db/x.plist': (b'', 0)}, files, True)
        found = {(item.domain, item.restore_path): item for item in files}
        self.assertEqual(plistlib.loads(found['ManagedPreferencesDomain', 'mobile/com.apple.springboard.plist']
                                        .contents), {'A': 1})
        self.assertIn(('HomeDomain', 'Library/Preferences/com.apple.springboard.plist'), found)
        self.assertEqual(found['DatabaseDomain', 'x.plist'].owner, 0)

    def test_refuses_to_replace_a_file_goldennugget_writes(self):
        files = [FileToRestore(contents=b'', restore_path='x.plist', domain='DatabaseDomain')]
        with self.assertRaises(NuggetException):
            self.manager()._add_community_files({}, {'/var/db/x.plist': (b'1', 0)}, files, False)


class Safety(unittest.TestCase):
    def test_empty_plist_is_a_valid_plist(self):
        [item] = parse_tweaks([tweak(writes=[{'type': 'empty', 'path': SPRINGBOARD},
                                             {'type': 'empty', 'path': '/var/mobile/Library/x.db'}])], no_sources)
        self.assertEqual(plistlib.loads(item.writes[0].data), {})
        self.assertEqual(item.writes[1].data, b'')

    def test_risk_levels(self):
        from src.controllers.risk_assessment import RiskLevel, community_factors
        from src.tweaks.posterboard.community_tweaks import active
        tweaks_ = parse_tweaks([
            tweak(id='keys', default=True),
            tweak(id='home', default=True, writes=[{'type': 'plist', 'path': '/var/mobile/Library/Preferences/a.plist',
                                                     'values': {'A': 1}}]),
            tweak(id='sys', default=True, writes=[{'type': 'plist', 'path': '/var/db/x.plist', 'values': {'A': 1}}]),
            tweak(id='off')], no_sources)
        found = active([('Pack', tweaks_)], '26.2')
        self.assertEqual([item.id for _, item, _ in found], ['keys', 'home', 'sys'])
        levels = sorted(factor.level for factor in community_factors(found))
        self.assertEqual(levels, [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH])

    def test_preview_lists_each_tweak(self):
        from src.controllers.apply_preview import capture_preview, preview_lines
        from src.tweaks.tweaks import TweakID, tweaks
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        holder = tweaks[TweakID.Templates]
        before = list(holder.templates)
        self.addCleanup(setattr, holder, 'templates', before)
        holder.templates = [TemplateFile(make_batter(folder.name, CONFIG, {'files/blob.bin': b'x'}))]
        manager = SimpleNamespace(get_current_device_version=lambda: '26.2',
                                  get_current_device_model=lambda: 'iPhone16,2',
                                  pref_manager=SimpleNamespace(settings=None))
        preview = capture_preview(manager)
        keys = [key for key in preview['entries'] if key.startswith('Community/')]
        self.assertEqual(keys, ['Community/tweaks.batter/dock', 'Community/tweaks.batter/blob'])
        self.assertTrue(any('Pack — Hide Dock' in line for line in preview_lines(preview, None)))


class ResetRecord(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        from unittest import mock
        patcher = mock.patch('src.restore.lastapply.lastapply_path',
                             side_effect=lambda udid: os.path.join(self.folder.name, udid + '.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_merges_and_plans_reset(self):
        from src.tweaks.posterboard.community_tweaks import (
            clear_record,
            load_record,
            reset_plan,
            write_record,
        )
        write_record('U', {SPRINGBOARD: ({'A': 1}, 501)}, {})
        write_record('U', {SPRINGBOARD: ({'B': 1}, 501), '/var/mobile/Library/Preferences/a.plist': ({'C': 1}, 501)},
                     {'/var/mobile/x.bin': (b'', 501)})
        record = load_record('U')
        self.assertEqual(record['plists'][SPRINGBOARD], ['A', 'B'])
        self.assertEqual(reset_plan(record), ([SPRINGBOARD], ['/var/mobile/Library/Preferences/a.plist',
                                                              '/var/mobile/x.bin']))
        clear_record('U')
        self.assertEqual(load_record('U'), {})

    def test_reset_page_appears_and_empties_managed_files(self):
        import asyncio

        from src.tweaks.posterboard.community_tweaks import load_record, write_record
        from src.utils.pages import Page, get_resettable_pages
        dm = DeviceManager.__new__(DeviceManager)
        dm.get_current_device_udid = lambda: 'U'
        self.assertNotIn(Page.Templates, get_resettable_pages(dm))
        write_record('U', {SPRINGBOARD: ({'A': 1}, 501)}, {'/var/mobile/x.bin': (b'', 501)})
        self.assertIn(Page.Templates, get_resettable_pages(dm))
        written, labels = [], []
        dm._raise_if_unsupported = lambda: None
        dm.get_current_device_version = lambda: '27.0'

        async def skip(files, uses):
            return None

        async def restore(files, update_label, **kwargs):
            written.extend((item.domain, item.restore_path, item.contents) for item in files)
        dm.add_skip_setup = skip
        dm.start_restore = restore
        from unittest import mock
        with mock.patch('src.restore.lastapply.clear_lastapply'), \
                mock.patch('src.controllers.apply_preview.clear_preview'):
            ok = asyncio.run(dm._reset_tweaks([Page.Templates], None, labels.append))
        self.assertTrue(ok)
        self.assertIn(('ManagedPreferencesDomain', 'mobile/com.apple.springboard.plist', plistlib.dumps({})), written)
        self.assertTrue(any('/var/mobile/x.bin' in text for text in labels))
        self.assertEqual(load_record('U'), {})


if __name__ == '__main__':
    unittest.main()
