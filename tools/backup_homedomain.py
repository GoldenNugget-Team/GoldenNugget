#!/usr/bin/env python3
"""
Backup iOS HomeDomain using Nugget's pymobiledevice3 methods.
Reads files from /var/mobile/ on the device and saves them locally.

Usage:
    python3 backup_homedomain.py [--output DIR] [--udid UDID]

Requires:
    - Device connected via USB and trusted
    - pymobiledevice3 installed
"""

import argparse
import asyncio
import sys
from pathlib import Path

from pymobiledevice3.exceptions import MuxException
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.afc import AfcService


async def connect_device(udid=None):
    """Connect to iOS device via USB."""
    try:
        ld = await create_using_usbmux(serial=udid)
        info = ld.all_values
        print(f"Connected to: {info.get('DeviceName', 'Unknown')} "
              f"(iOS {info.get('ProductVersion', '?')}, UDID: {info.get('UniqueDeviceID', '?')})")
        return ld
    except MuxException as e:
        print(f"Failed to connect to device: {e}")
        sys.exit(1)


async def afc_read_file(afc, device_path):
    """Read a file from device via AFC. Returns bytes or None if failed."""
    try:
        return await afc.get_file_contents(device_path)
    except Exception:
        return None


async def afc_walk(afc, device_path):
    """
    Walk the device filesystem starting at device_path using AFC.
    Yields (current_dir, subdirs, files) tuples similar to os.walk().
    Only works for AFC-accessible paths (typically under /var/mobile/Media/).
    """
    try:
        entries = await afc.listdir(device_path)
    except Exception:
        return

    dirs = []
    files = []
    for entry in entries:
        # Skip . and ..
        if entry in (".", ".."):
            continue
        entry_path = device_path.rstrip("/") + "/" + entry
        try:
            # Try to listdir to check if it's a directory
            await afc.listdir(entry_path)
            dirs.append(entry)
        except Exception:
            files.append(entry)

    yield device_path, dirs, files

    for d in dirs:
        subdir_path = device_path.rstrip("/") + "/" + d
        async for item in afc_walk(afc, subdir_path):
            yield item


async def try_afc_backup(ld, output_dir):
    """
    Attempt to backup via AFC service.
    Note: AFC root service typically only accesses /var/mobile/Media/
    """
    print("\n--- Trying AFC backup (limited to /var/mobile/Media/) ---")
    async with AfcService(lockdown=ld) as afc:
        return await _afc_backup(afc, output_dir)


async def _afc_backup(afc, output_dir):
    # AFC typically maps root to /var/mobile/Media/
    # Let's try to walk from root
    media_path = "/"
    count = 0
    skipped = 0

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    async for current_dir, dirs, files in afc_walk(afc, media_path):
        # Create local directory
        rel_path = current_dir.lstrip("/")
        local_dir = output_dir / rel_path
        local_dir.mkdir(parents=True, exist_ok=True)

        for fname in files:
            device_file_path = current_dir.rstrip("/") + "/" + fname
            local_file_path = local_dir / fname

            contents = await afc_read_file(afc, device_file_path)
            if contents is not None:
                try:
                    local_file_path.write_bytes(contents)
                    count += 1
                    if count % 100 == 0:
                        print(f"  Downloaded {count} files...")
                except Exception as e:
                    print(f"  Failed to write {local_file_path}: {e}")
                    skipped += 1
            else:
                skipped += 1

    print(f"AFC backup complete: {count} files downloaded, {skipped} skipped.")
    return count > 0


def main():
    parser = argparse.ArgumentParser(description="Backup iOS HomeDomain using Nugget methods")
    parser.add_argument("--output", "-o", default="./homedomain_backup",
                        help="Output directory (default: ./homedomain_backup)")
    parser.add_argument("--udid", default=None,
                        help="Device UDID (default: first connected device)")
    asyncio.run(run(parser.parse_args()))


async def run(args):
    print("=== Nugget HomeDomain Backup ===")
    print(f"Output directory: {args.output}")

    # Connect to device
    ld = await connect_device(udid=args.udid)

    try:
        # Try AFC backup (limited scope)
        success = await try_afc_backup(ld, args.output)

        if not success:
            print("\nNote: AFC backup only accesses /var/mobile/Media/.")
            print("For a full HomeDomain backup, you need to use the iOS Backup protocol")
            print("(MobileBackup2 service), which requires the device to be paired and")
            print("may require the user to accept the backup on the device screen.")
            print("\nAlternatively, if the device is jailbroken, you can use SSH.")

    finally:
        try:
            await ld.close()
        except Exception:
            pass

    print("\n=== Backup Complete ===")


if __name__ == "__main__":
    main()
