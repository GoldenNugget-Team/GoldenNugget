"""``Nugget backup`` — create / inspect the live protective backups.

The protective backup is the selective device backup GoldenNugget keeps so a
"safe state recovery" wipe (iOS 27 Phase 2) does not destroy the user's photos,
Apple ID and settings. These commands run it standalone and list the stored runs.
"""

import argparse
import asyncio
import sys


def add_parser(subp):
    parser = subp.add_parser(
        "backup",
        help="Create / list protective backups",
        description="Manage GoldenNugget's live protective backups (the selective "
                    "device backup that protects photos/Apple ID/settings through "
                    "an iOS 27 wipe).",
    )
    sub = parser.add_subparsers(dest="backup_sub", required=True)

    p = sub.add_parser("create", help="Take a protective backup of the device")
    p.add_argument("--udid", default=None, help="target device UDID")
    p.add_argument("--no-photos", action="store_true", help="exclude photos/media")
    p.add_argument("--no-posterboard", action="store_true",
                   help="exclude the PosterBoard container")
    p.set_defaults(func=_run_create)

    p = sub.add_parser("list", help="List stored protective backups")
    p.add_argument("--udid", default=None, help="restrict to this UDID")
    p.set_defaults(func=_run_list)
    return parser


async def _create(udid, include_photos, include_posterboard) -> dict:
    from pymobiledevice3.lockdown import create_using_usbmux

    from src.restore.protective import (
        list_protective_backups,
        new_protective_backup_dir,
        perform_protective_backup,
        prune_protective_backups,
    )

    backup_root = new_protective_backup_dir(udid)
    print(f"Backup dir: {backup_root}")

    def cb(value):
        if isinstance(value, str):
            print(" ", value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            print(f"  {value:.1f}%")

    lc = None
    try:
        lc = await create_using_usbmux(serial=udid, autopair=False)
    except Exception:
        lc = await create_using_usbmux(serial=udid, autopair=True)
    try:
        encrypted = await perform_protective_backup(
            lc, backup_root, progress_callback=cb,
            include_photos=include_photos,
            include_posterboard=include_posterboard,
            include_keychain=None)
        print("Backup complete.",
              "encrypted: yes (restoring this backup needs its password)"
              if encrypted else "encrypted: no")
    finally:
        try:
            await lc.close()
        except Exception:
            pass

    try:
        kept = prune_protective_backups(udid)
        print(f"Pruned old runs (kept {kept}).")
    except Exception as e:
        print(f"note: prune skipped ({e})")

    runs = list_protective_backups(udid)
    if runs:
        print(f"{len(runs)} stored backup(s) for {udid}.")
    return dict(udid=udid, path=backup_root, encrypted=encrypted)


def _run_create(args) -> int:
    from src.cli.common import bootstrap, ensure_device, make_device_manager
    settings = bootstrap()
    dm = make_device_manager(settings)
    device = ensure_device(dm, settings, args.udid)
    udid = getattr(device, "udid", None)
    if not udid:
        print("ERROR: no UDID.", file=sys.stderr)
        return 1
    print(f"Backing up {getattr(device, 'name', udid)} "
          f"(iOS {getattr(device, 'version', '?')})...")
    try:
        result = asyncio.run(_create(udid, not args.no_photos, not args.no_posterboard))
        from src.cli.output import set_result
        set_result(result)
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


def _run_list(args) -> int:
    from src.cli.common import bootstrap, ensure_device, make_device_manager
    settings = bootstrap()
    dm = make_device_manager(settings)

    udid = args.udid
    try:
        device = ensure_device(dm, settings, udid)
        udid = udid or getattr(device, "udid", None)
    except SystemExit as e:
        if udid:
            pass  # device offline but udid given — still list its backups
        else:
            raise e

    from src.restore.protective import (
        find_latest_protective_backup,
        list_protective_backups,
    )
    runs = list_protective_backups(udid)
    from src.cli.output import set_result
    set_result(dict(udid=udid, backups=[dict(path=str(run), modified_at=run.stat().st_mtime) for run in runs]))
    if not runs:
        print(f"No protective backups stored for {udid}.")
        return 0
    import datetime
    from pathlib import Path
    latest_root = find_latest_protective_backup(udid)
    latest_parent = str(Path(latest_root).parent) if latest_root else ""
    print(f"Protective backups for {udid} ({len(runs)}):")
    for run in runs:
        mtime = datetime.datetime.fromtimestamp(run.stat().st_mtime)
        marker = "  <-- latest" if str(run) == latest_parent else ""
        print(f"  {mtime.isoformat()}  {run}{marker}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="sub", required=True)
    add_parser(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
