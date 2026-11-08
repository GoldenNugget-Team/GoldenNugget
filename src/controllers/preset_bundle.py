"""Portable .gnpreset files: JSON plus hashed template/icon assets.

Wallpapers remain excluded by the preset contract. Import never activates a
preset; assets are staged in a unique persistent directory owned by that import.
"""
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from src.controllers.archive_safety import MAX_FILE_BYTES, checked_members

FORMAT = 'GoldenNugget portable preset'
MANIFEST_LIMIT = 4 * 1024 ** 2


def _asset_slots(data):
    for name, entry in data['tweaks'].items():
        if name == 'Templates':
            paths = entry.get('templates', [])
            for index in range(len(paths)):
                yield paths, index
        elif name == 'IconThemes':
            for theme in entry.get('themes', []):
                if theme.get('icon_path'):
                    yield theme, 'icon_path'


def export_bundle(data, destination):
    data = copy.deepcopy(data)
    data['tweaks'].pop('PosterBoard', None)
    files, assets = {}, {}
    for owner, key in _asset_slots(data):
        path = Path(owner[key])
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Preset asset is missing or is a link: {path.name}')
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f'Preset asset is too large: {path.name}')
        # The ZIP name is generated locally; source paths never enter the bundle.
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        name = f'assets/{digest.hexdigest()}{path.suffix.lower()}'
        files[name] = path
        assets[name] = dict(sha256=digest.hexdigest(), size=size)
        owner[key] = 'bundle://' + name
    manifest = dict(format=FORMAT, version=1, preset=data, assets=assets)
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    if len(raw) > MANIFEST_LIMIT:
        raise ValueError('Preset metadata is too large.')
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = stream.name
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', raw)
            for name, path in files.items():
                digest, size = hashlib.sha256(), 0
                with path.open('rb') as src, archive.open(name, 'w') as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        size += len(chunk)
                        if size > MAX_FILE_BYTES:
                            raise ValueError('Preset asset grew beyond the size limit.')
                        digest.update(chunk)
                        dst.write(chunk)
                if size != assets[name]['size'] or digest.hexdigest() != assets[name]['sha256']:
                    raise ValueError(f'Preset asset changed during export: {path.name}')
            checked_members(archive)
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def import_bundle(source, assets_base, validate):
    """Return (rewritten preset, owned asset directory); caller owns rollback."""
    owned = None
    try:
        with zipfile.ZipFile(source) as archive:
            members = checked_members(archive)
            if archive.getinfo('manifest.json').file_size > MANIFEST_LIMIT:
                raise ValueError('Preset manifest is too large.')
            manifest = json.loads(archive.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('version') != 1:
                raise ValueError('Unsupported portable preset format.')
            data, assets = manifest.get('preset'), manifest.get('assets')
            if not validate(data) or not isinstance(assets, dict):
                raise ValueError('Invalid portable preset metadata.')
            names = {info.filename for info in members if not info.is_dir()}
            if names != {'manifest.json', *assets}:
                raise ValueError('Preset contains missing or unlisted assets.')
            references = list(_asset_slots(data))
            used = set()
            for owner, key in references:
                ref = owner[key]
                if not isinstance(ref, str) or not ref.startswith('bundle://assets/'):
                    raise ValueError('Portable assets must use internal bundle references.')
                used.add(ref.removeprefix('bundle://'))
            if used != set(assets):
                raise ValueError('Preset asset references do not match its manifest.')
            os.makedirs(assets_base, exist_ok=True)
            owned = Path(tempfile.mkdtemp(prefix='import-', dir=assets_base))
            for name, metadata in assets.items():
                if not isinstance(metadata, dict) or not name.startswith('assets/') or name.count('/') != 1:
                    raise ValueError('Invalid asset record.')
                basename = name.removeprefix('assets/')
                if not re.fullmatch(r'[a-f0-9]{64}(?:\.[a-z0-9_-]+)?', basename):
                    raise ValueError('Invalid portable asset filename.')
                info = archive.getinfo(name)
                if type(metadata.get('size')) is not int or metadata['size'] != info.file_size:
                    raise ValueError('Preset asset size mismatch.')
                target = owned / name.removeprefix('assets/')
                digest = hashlib.sha256()
                with archive.open(info) as src, target.open('wb') as dst:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        dst.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != metadata.get('sha256'):
                    raise ValueError('Preset asset checksum mismatch.')
            for owner, key in references:
                owner[key] = str(owned / owner[key].removeprefix('bundle://assets/'))
            data['tweaks'].pop('PosterBoard', None)
            return data, owned
    except BaseException:
        if owned is not None:
            shutil.rmtree(owned, ignore_errors=True)
        raise
