#!/usr/bin/env python3
"""Create a full or incremental iTunes-style backup with the current async API."""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from src.devicemanagement.session import lockdown_session


def progress_callback(message):
    if isinstance(message, (int, float)):
        print(f"\rProgress: {message:.1f}%", end="", flush=True)
    else:
        print(f"\n{message}")


async def run(args):
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")
    async with lockdown_session(args.udid) as ld:
        info, udid = ld.all_values, ld.udid
        print(f"Connected: {info.get('DeviceName', 'Unknown')} ({udid})")
        async with Mobilebackup2Service(ld) as mb2:
            if await mb2.get_will_encrypt():
                print("WARNING: backup encryption is enabled. Keep the password for recovery.")
            full = not args.incremental or not (output_dir / udid).exists()
            print("Starting FULL backup..." if full else "Starting INCREMENTAL backup...")
            started = time.monotonic()
            await mb2.backup(full=full, backup_directory=output_dir,
                             progress_callback=progress_callback)
    print(f"\nBackup complete in {time.monotonic() - started:.1f}s: {output_dir / udid}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', '-o', default='./ios_backup')
    parser.add_argument('--udid', default=None)
    parser.add_argument('--incremental', action='store_true')
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nBackup cancelled.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Backup failed: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
