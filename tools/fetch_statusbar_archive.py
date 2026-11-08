"""Pull the device's StatusBarOverrides.archive and print its schema.

Research tool for the iOS 27 status bar work -- it is NOT part of the apply
flow and nothing in the app calls it.

Why: `src/tweaks/status_bar/statusbar_archive.py` can only write the two
carrier-name entries, because the rest of the record's key names are not
knowable from source. SpringBoard rewrites that archive in its own canonical
form whenever it applies an override, so a dump taken after one apply/reboot
contains the real class names and keys -- which is exactly what the writer
needs to stop guessing.

    # 1. apply the carrier-name tweak in the app, let it reboot
    # 2. then run this
    python3 tools/fetch_statusbar_archive.py

If the device has never had an override applied there is no archive to read
and this says so -- that is a normal answer, not a failure. SpringBoard
unlinks a record that carries no overrides.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymobiledevice3.usbmux import list_devices  # noqa: E402

from src.restore.statusbar_fetch import (  # noqa: E402
    describe,
    dump_path,
    targeted_statusbar_archive_fetch,
)


async def main() -> int:
    devices = await list_devices()
    usb = [d for d in devices if d.is_usb]
    if not usb:
        print("ERROR: no USB device connected")
        return 1
    if len(usb) > 1:
        print("note: several USB devices, using the first")
    udid = usb[0].serial
    print(f"device: {udid}")

    def label(msg):
        print(f"   {msg}")

    def progress(msg):
        if isinstance(msg, str):
            print(f"   {msg}")

    print("[1] targeted backup of Library/SpringBoard/StatusBarOverrides.archive...")
    try:
        found = await targeted_statusbar_archive_fetch(
            udid, update_label=label, update_progress=progress)
    except Exception as e:
        print(f"fetch failed: {type(e).__name__}: {e}")
        return 1

    if not found:
        print("\n[2] NO archive on the device.")
        print("    Nothing to research yet. To make one appear:")
        print("      1. apply the carrier-name tweak in GoldenNugget (iOS 27)")
        print("      2. let the device reboot into SpringBoard")
        print("      3. run this again")
        print("    (SpringBoard only keeps the file while an override is active --")
        print("     a record with no overrides gets unlinked on sight.)")
        return 2

    payload = Path(found).read_bytes()
    print(f"\n[2] {found} ({len(payload)} bytes)")
    print(f"    default location: {dump_path(udid)}")
    print("\n[3] schema:")
    try:
        print(describe(payload))
    except Exception as e:
        print(f"    could not decode as a status bar archive: {type(e).__name__}: {e}")
        print(f"    raw bytes kept at {found} -- hand them over as-is.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
