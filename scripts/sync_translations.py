#!/usr/bin/env python3
"""
Sync translations from gNugget-i18n submodule to GoldenNugget.

Usage: python sync_translations.py <source_dir> <target_dir>
"""
import argparse
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_ts_file(filepath: Path) -> dict:
    """Parse a .ts file and return dict of {source_text: translation_text}."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        translations = {}
        for context in root.findall('context'):
            name = context.find('name')
            if name is None:
                continue
            context_name = name.text
            for message in context.findall('message'):
                source = message.find('source')
                translation = message.find('translation')
                if source is not None and translation is not None:
                    src_text = source.text or ''
                    trans_text = translation.text or ''
                    if trans_text and translation.get('type') != 'unfinished':
                        translations[(context_name, src_text)] = trans_text
        return translations
    except Exception as e:
        print(f"Warning: Failed to parse {filepath}: {e}", file=sys.stderr)
        return {}


def merge_translations(target_ts: Path, source_translations: dict) -> bool:
    """Merge source translations into target .ts file. Returns True if modified."""
    try:
        tree = ET.parse(target_ts)
        root = tree.getroot()
        modified = False
        
        for context in root.findall('context'):
            name = context.find('name')
            if name is None:
                continue
            context_name = name.text
            
            for message in context.findall('message'):
                source = message.find('source')
                translation = message.find('translation')
                if source is None or translation is None:
                    continue
                
                src_text = source.text or ''
                key = (context_name, src_text)
                
                if key in source_translations:
                    new_trans = source_translations[key]
                    old_trans = translation.text or ''
                    if old_trans != new_trans:
                        translation.text = new_trans
                        if translation.get('type') == 'unfinished':
                            translation.attrib.pop('type', None)
                        modified = True
        
        if modified:
            # Pretty print
            ET.indent(tree, space='    ')
            tree.write(target_ts, encoding='utf-8', xml_declaration=True)
        
        return modified
    except Exception as e:
        print(f"Error merging {target_ts}: {e}", file=sys.stderr)
        return False


def update_submodule():
    """Update the i18n submodule to latest main."""
    try:
        print("Updating i18n submodule...")
        result = subprocess.run(
            ['git', 'submodule', 'update', '--remote', '--merge', 'i18n'],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        if result.returncode != 0:
            print(f"Warning: Submodule update failed: {result.stderr}", file=sys.stderr)
            return False
        print("Submodule updated successfully")
        return True
    except Exception as e:
        print(f"Error updating submodule: {e}", file=sys.stderr)
        return False


def sync_translations(source_dir: Path, target_dir: Path):
    """Sync translations from source to target."""
    source_ts_files = list(source_dir.glob('*.ts'))
    target_ts_files = list(target_dir.glob('*.ts'))
    
    print(f"Found {len(source_ts_files)} source .ts files, {len(target_ts_files)} target .ts files")
    
    # Build mapping of source translations by locale
    source_by_locale = {}
    for ts_file in source_ts_files:
        locale = ts_file.stem.replace('Nugget_', '')
        source_by_locale[locale] = parse_ts_file(ts_file)
        print(f"  Loaded {len(source_by_locale[locale])} translations for {locale}")
    
    # Update target files
    total_modified = 0
    for target_ts in target_ts_files:
        locale = target_ts.stem.replace('Nugget_', '')
        if locale in source_by_locale:
            print(f"Merging {locale}...")
            if merge_translations(target_ts, source_by_locale[locale]):
                total_modified += 1
                print(f"  Updated {target_ts.name}")
            else:
                print(f"  No changes for {target_ts.name}")
        else:
            print(f"  No source for {locale}, skipping")
    
    # Copy new .ts files that don't exist in target
    for source_ts in source_ts_files:
        target_ts = target_dir / source_ts.name
        if not target_ts.exists():
            shutil.copy2(source_ts, target_ts)
            print(f"  Copied new file: {source_ts.name}")
            total_modified += 1
    
    print(f"\nDone. Modified {total_modified} files.")
    return total_modified > 0


def main():
    parser = argparse.ArgumentParser(description='Sync translations from gNugget-i18n submodule')
    parser.add_argument('source_dir', help='Source directory (i18n submodule)', nargs='?', default='i18n')
    parser.add_argument('target_dir', help='Target directory (GoldenNugget src/qt/translations)', nargs='?', default='src/qt/translations')
    parser.add_argument('--no-submodule-update', action='store_true', help='Skip submodule update')
    args = parser.parse_args()
    
    repo_root = Path(__file__).parent.parent
    source = repo_root / args.source_dir
    target = repo_root / args.target_dir
    
    if not source.exists():
        print(f"Error: Source directory not found: {source}", file=sys.stderr)
        sys.exit(1)
    if not target.exists():
        print(f"Error: Target directory not found: {target}", file=sys.stderr)
        sys.exit(1)
    
    if not args.no_submodule_update:
        update_submodule()
    
    changed = sync_translations(source, target)
    sys.exit(0 if changed else 0)


if __name__ == '__main__':
    main()