"""Dump SystemPreferencesDomain from the device via a selective backup.

Large enough to carry FeatureFlags/Global.plist, small enough to skip the
multi-GB photo backup. Answers: is a file at
SystemPreferencesDomain/FeatureFlags/Global.plist on the device right now,
and what does it contain?

Usage:
    python3 tools/dump_sysprefs.py
"""

import asyncio
import os
import plistlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.usbmux import list_devices

from src.restore.protective import _BACKUP_METADATA_FILES, ProtectiveBackupService


def _preserve(file_name: str, device_name: str) -> bool:
    if Path(file_name).name in _BACKUP_METADATA_FILES:
        return True
    if "/" not in device_name:
        return True
    domain, _ = device_name.split("/", 1)
    return domain == "SystemPreferencesDomain"


async def main() -> int:
    devices = await list_devices()
    usb = [d for d in devices if d.is_usb]
    if not usb:
        print("ERROR: no USB device connected")
        return 1
    serial = usb[0].serial

    ld = await create_using_usbmux(serial=serial, autopair=True)
    backup_root = tempfile.mkdtemp(prefix="nugget_sysprefs_")

    def progress(msg):
        if isinstance(msg, str):
            print("   ", msg)

    try:
        print("[1] selective backup of SystemPreferencesDomain...")
        async with ProtectiveBackupService(ld, preserve_file=_preserve) as mb:
            await mb.backup(full=True, backup_directory=backup_root,
                            progress_callback=progress)
    except Exception as e:
        print(f"backup failed: {type(e).__name__}: {e}")
        return 1

    device_dir = Path(backup_root) / serial
    if not (device_dir / "Manifest.db").exists():
        # older layout: backup_root IS the device dir
        for candidate in Path(backup_root).iterdir():
            if candidate.is_dir() and (candidate / "Manifest.db").exists():
                device_dir = candidate
                break
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    rows = conn.execute(
        "SELECT fileID, domain, relativePath, flags FROM Files "
        "WHERE domain LIKE 'SystemPreferencesDomain%' ORDER BY relativePath"
    ).fetchall()
    print(f"[2] {len(rows)} SystemPreferencesDomain rows")
    for file_id, domain, rel, flags in rows:
        print(f"   {domain}/{rel} (flags={flags})")

    target = [r for r in rows if "FeatureFlags/Global.plist" in r[2]]
    if target:
        file_id, domain, rel, flags = target[0]
        payload = device_dir / file_id[:2] / file_id
        if not payload.exists():
            payload = device_dir / file_id
        data = payload.read_bytes()
        print(f"\n[3] {rel}: {len(data)} bytes ->")
        try:
            plist = plistlib.loads(data)
            print(plistlib.dumps(plist, fmt=plistlib.FMT_XML).decode())
        except Exception:
            print(data)
    else:
        print("\n[3] FeatureFlags/Global.plist NOT on device")

    conn.close()
    print(f"\nbackup dir kept: {device_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))