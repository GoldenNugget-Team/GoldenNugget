"""Offline wallpaper/template inspection; never extracts or executes a package."""
# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "xml.etree.ElementTree",
)

import json
import plistlib
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

from src.controllers.archive_safety import checked_members

TEXT_LIMIT = 4 * 1024 ** 2
MAX_ISSUES = 200


def validate_wallpaper(path, ios_version=None):
    report = dict(schema=1, package=Path(path).name, valid=False, files=0,
                  unpacked_bytes=0, descriptors=0, families=[], issues=[],
                  target_ios=ios_version, compatibility='unknown')

    def issue(level, code, message, member=''):
        if len(report['issues']) < MAX_ISSUES:
            report['issues'].append(dict(level=level, code=code, message=message, path=member))
        if level == 'error':
            report['_has_errors'] = True

    try:
        with zipfile.ZipFile(path) as archive:
            members = checked_members(archive)
            files = [entry for entry in members if not entry.is_dir()
                     and not entry.filename.lower().startswith('__macosx/')]
            report['files'] = len(files)
            report['unpacked_bytes'] = sum(entry.file_size for entry in files)
            descriptors, families, configs = set(), set(), []
            for entry in files:
                name = entry.filename
                match = re.search(r'(?:^|/)(?:descriptor|descriptors)/([^/]+)/', name, re.I)
                if match:
                    descriptors.add(match.group(1))
                if Path(name).name == 'PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3':
                    issue('warning', 'embedded_database',
                          'Contains a device-specific PosterBoard database; review before applying.', name)
                suffix = Path(name).suffix.lower()
                parse = suffix in ('.plist', '.json', '.xml', '.caml')
                if entry.file_size == 0:
                    if parse:
                        issue('error', 'empty_document', 'Structured document is empty.', name)
                    continue
                if parse and entry.file_size > TEXT_LIMIT:
                    issue('warning', 'document_limit', 'Document exceeds the parser size limit; syntax was not checked.', name)
                    parse = False
                # Read every entry through ZipExtFile to verify its CRC with
                # bounded memory, including media that needs no syntax parser.
                data = bytearray() if parse else None
                with archive.open(entry) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        if data is not None:
                            data.extend(chunk)
                if data is None:
                    continue
                try:
                    if suffix == '.plist':
                        document = plistlib.loads(bytes(data))
                        if Path(name).name.lower() == 'wallpaper.plist' and isinstance(document, dict):
                            family = document.get('family')
                            if isinstance(family, str):
                                families.add(family)
                    elif suffix == '.json':
                        document = json.loads(data)
                        if Path(name).name.lower() == 'config.json':
                            configs.append((name, document))
                    else:
                        root = ET.fromstring(data)
                        if any(node.tag.rsplit('}', 1)[-1] == 'scriptObject' and node.get('src')
                               for node in root.iter()):
                            issue('warning', 'external_script',
                                  'External script reference may crash the iOS 27 wallpaper renderer.', name)
                except (ValueError, TypeError, OverflowError, ET.ParseError, plistlib.InvalidFileException) as exc:
                    issue('error', 'invalid_document', f'Cannot parse document: {exc}', name)
            report['descriptors'] = len(descriptors)
            report['families'] = sorted(families)
            if not files:
                issue('error', 'empty_archive', 'Archive contains no package files.')
            if len(descriptors) > 10:
                issue('error', 'descriptor_limit', 'Package contains more than ten descriptors.')
            if not descriptors and not configs:
                issue('warning', 'unrecognized_layout', 'No descriptor directory or template config was found.')
            for name, config in configs:
                if not isinstance(config, dict):
                    issue('error', 'invalid_template', 'Template config must be an object.', name)
                    continue
                # templates with community tweaks (format 3) may skip options and domain
                required = ('format_version', 'title', 'author') + (
                    () if 'tweaks' in config else ('options', 'domain'))
                if any(key not in config for key in required) \
                        or not isinstance(config.get('options', []), list):
                    issue('error', 'invalid_template', 'Template config is missing required fields or options.', name)
                if str(config.get('format_version')) not in ('1', '2', '3'):
                    issue('error', 'template_version', 'Unsupported template format version.', name)
                if 'tweaks' in config:
                    _check_tweaks(archive, name, config, issue)
                if ios_version and (config.get('min_version') or config.get('max_version')):
                    # packaging is already a runtime dependency of the app.
                    from packaging.version import InvalidVersion, Version
                    try:
                        version = Version(ios_version)
                        if ((config.get('min_version') and version < Version(config['min_version']))
                                or (config.get('max_version') and version > Version(config['max_version']))):
                            issue('error', 'ios_version', 'Template does not support the selected iOS version.', name)
                            report['compatibility'] = 'incompatible'
                    except (InvalidVersion, TypeError):
                        issue('error', 'invalid_version', 'Invalid iOS version in template metadata or target.', name)
            if families and any(family != 'Clownfish' for family in families):
                issue('warning', 'legacy_family', 'Legacy wallpaper families may need conversion on iOS 27.')
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError, NotImplementedError, zlib.error) as exc:
        issue('error', 'archive_error', str(exc))
    report['valid'] = not report.pop('_has_errors', False)
    report['issues_truncated'] = len(report['issues']) >= MAX_ISSUES
    report['note'] = 'Static inspection only. Device/model compatibility and rendering effects are not verified.'
    return report


def _check_tweaks(archive, config_name, config, issue):
    """Validate a format 3 ``tweaks`` list with the rules the app loads it by."""
    from src.tweaks.posterboard.community_tweaks import (
        MAX_SOURCE_BYTES,
        CommunityTweakError,
        parse_tweaks,
    )
    if str(config.get('format_version')) != '3':
        issue('error', 'template_version', 'Templates with tweaks need format_version 3.', config_name)
    base = config_name[:-len('config.json')]
    names = set(archive.namelist())

    def read(relative):
        member = base + relative
        if member not in names:
            raise CommunityTweakError(f'Missing file in template: {relative}')
        if archive.getinfo(member).file_size > MAX_SOURCE_BYTES:
            raise CommunityTweakError(f'Template file is too large: {relative}')
        return archive.read(member)
    try:
        loaded = parse_tweaks(config['tweaks'], read)
    except CommunityTweakError as exc:
        issue('error', 'invalid_tweak', str(exc), config_name)
        return
    for tweak in loaded:
        for path in tweak.paths():
            issue('info', 'tweak_write', f'Tweak "{tweak.id}" writes {path}.', config_name)


def validation_text(report):
    lines = [report['package'], 'Checks passed' if report['valid'] else 'Checks failed',
             f"Files: {report['files']} · Unpacked bytes: {report['unpacked_bytes']} · Descriptors: {report['descriptors']}"]
    if report['families']:
        lines.append('Families: ' + ', '.join(report['families']))
    for item in report['issues']:
        lines.append(f"[{item['level'].upper()}] {item['path']}: {item['message']}")
    lines.extend(['', report['note']])
    return '\n'.join(lines)
