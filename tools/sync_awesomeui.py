#!/usr/bin/env python3
"""Vendor the standalone awesomeUI package from a local checkout."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('__init__.py', 'controls.py', 'theme.py', 'widgets.py', 'phone_frame.py',
         'multicombobox.py', 'resizable_image_label.py', 'LICENSE')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent / 'awesomeUI')
    parser.add_argument('--check', action='store_true', help='Verify without writing')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    destination = ROOT / 'awesomeui'
    manifest = destination / 'upstream.json'
    hashes = {}
    for name in FILES:
        data = (source / 'awesomeui' / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        if args.check:
            if not (destination / name).is_file() or (destination / name).read_bytes() != data:
                raise SystemExit(f'awesomeUI differs: {name}; run tools/sync_awesomeui.py')
    if args.check:
        if json.loads(manifest.read_text())['sha256'] != hashes:
            raise SystemExit('awesomeUI manifest is stale')
        print('awesomeUI package and manifest match the source checkout')
        return
    destination.mkdir(exist_ok=True)
    for name in FILES:
        shutil.copy2(source / 'awesomeui' / name, destination / name)
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    manifest.write_text(json.dumps({
        'project': 'awesomeUI', 'source_commit': commit,
        'note': 'Hashes record working-tree contents, including uncommitted package changes.',
        'sha256': hashes,
    }, indent=2) + '\n')
    print(f'Vendored {len(FILES)} awesomeUI files')


if __name__ == '__main__':
    main()
