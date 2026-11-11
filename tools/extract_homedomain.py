#!/usr/bin/env python3
"""
Extract domain files from an iOS backup (Manifest.db format).
No device connection needed - works entirely offline.

Usage:
    .env/bin/python3 extract_homedomain.py my_backup/00008130... ./output
    .env/bin/python3 extract_homedomain.py my_backup/00008130... ./output HomeDomain
"""

import plistlib
import shutil
import sqlite3
import sys
from pathlib import Path

S_IFDIR  = 0o0040000
S_IFREG  = 0o0100000


def parse_mode(entry_blob: bytes) -> int:
    """Parse the Mode field from the NSKeyedArchiver plist blob."""
    try:
        plist = plistlib.loads(entry_blob)
        objects = plist.get("$objects", [])
        # NSKeyedArchiver format: $top -> root -> keyed values
        if not objects:
            return 0
        root = objects[1] if len(objects) > 1 else {}
        if isinstance(root, dict):
            # direct keyed archive
            return root.get("Mode", 0)
        # Navigate the object graph
        for obj in objects:
            if isinstance(obj, dict) and "Mode" in obj:
                return obj["Mode"]
        return 0
    except Exception:
        return 0


def extract_domain(backup_dir: Path, domain: str, output_dir: Path) -> int:
    """Extract all files from a specific domain in the backup."""
    manifest_db = backup_dir / "Manifest.db"
    if not manifest_db.exists():
        print(f"ERROR: {manifest_db} not found.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(manifest_db))
    rows = conn.execute(
        "SELECT relativePath, fileID, file FROM Files WHERE domain=? ORDER BY relativePath",
        (domain,)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"No entries found for domain '{domain}'.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    # Separate directories and files by parsing Mode from metadata
    dirs = set()
    file_entries = []

    for relative_path, file_id, entry_blob in rows:
        mode = parse_mode(entry_blob) if entry_blob else 0
        if mode & S_IFDIR:
            # Directory entry
            if relative_path:
                dirs.add(relative_path)
        elif mode & S_IFREG:
            file_entries.append((relative_path, file_id))
        # else: symlink or other, skip for now

    # Create all directories first (sorted by depth)
    sorted_dirs = sorted(dirs, key=lambda p: p.count("/"))
    for d in sorted_dirs:
        (output_dir / d).mkdir(parents=True, exist_ok=True)

    # Copy all files
    count = 0
    print(f"Extracting {len(file_entries)} files from '{domain}' to {output_dir}/")
    print(f"  Created {len(dirs)} directories")

    for relative_path, file_id in file_entries:
        src = backup_dir / file_id[:2] / file_id
        dest = output_dir / relative_path

        try:
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))
                count += 1

            if count % 100 == 0:
                print(f"  {count}/{len(file_entries)} files...", end="\r")
        except OSError as e:
            print(f"\n  SKIP: {relative_path}: {e}")

    print(f"\nDone: {count}/{len(file_entries)} files extracted.")
    return count


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    backup_dir = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    domain = sys.argv[3] if len(sys.argv) > 3 else "HomeDomain"

    extract_domain(backup_dir, domain, output_dir)


if __name__ == "__main__":
    main()
