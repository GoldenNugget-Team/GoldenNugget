#!/usr/bin/env python3
"""Restore a protective backup to the device (cache master or live run).

After a failed/wedged apply (e.g. the iPhone was not unlocked in time and
Phase 3 was aborted), the protective backup that protects the user's data is
kept on disk. Normally it is only restored automatically as part of a full
apply. This script lets you restore it standalone, so you can recover the
user's data after the iOS 27 "safe state recovery" wipe without re-running a
whole apply.

It does the same thing GoldenNugget does internally for a restore:
  1. locate the backup source for the device:
     - cache master (temp, or the persistent ``backup_cache`` base which
       honours the Settings → Backup → "Backup/Cache Location" custom dir),
     - or the newest live protective backup run
     (``--source auto`` picks cache first, then a live run),
  2. build a throwaway hardlink working copy,
  3. prune Manifest.db down to the protective payloads (so rows that were
     drained mid-stream and have no payload cannot fail with MBErrorDomain/205),
  4. wait for the device to be reachable and unlocked,
  5. restore via mobilebackup2, retrying and waiting for the unlock while
     the user unlocks the phone,
  6. push any AFC-media store (cache ``media/<udid>`` or live run ``afc_media``)
     back over AFC, then skip-setup + reboot like Phase 5.

Usage:
    python3 restore_cache.py                 # restore for the first connected device
    python3 restore_cache.py --udid UDID     # restore for a specific device
    python3 restore_cache.py --source live   # use the newest live backup run
    python3 restore_cache.py --source cache  # use only the cache master
    python3 restore_cache.py --password XXXX # backup password (encrypted caches)
    python3 restore_cache.py --cache-root /path  # override cache base (debug)
    python3 restore_cache.py --timeout 20    # minutes to wait for unlock
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pymobiledevice3 import usbmux  # noqa: E402
from pymobiledevice3.exceptions import (  # noqa: E402
    ConnectionFailedError,
    ConnectionTerminatedError,
    DeviceNotFoundError,
    NotPairedError,
    PasswordRequiredError,
    PyMobileDevice3Exception,
)
from pymobiledevice3.lockdown import create_using_usbmux  # noqa: E402
from PySide6 import QtCore  # noqa: E402  (QStandardPaths used by the cache)

from src.restore import reboot_device  # noqa: E402
from src.restore.afc_media import (  # noqa: E402
    describe_media_store,
    media_store_verified,
    recovery_media_dir,
    restore_media_via_afc,
)
from src.restore.protective import (  # noqa: E402
    clean_backup_for_restore,
    discard_protective_working_copy,
    find_latest_protective_backup,
    log_error,
    log_info,
    make_protective_working_copy,
    mark_restore_ok,
    protective_persistent_base,
    verify_backup_payloads,
)
from src.restore.restore import (  # noqa: E402
    _restore_protective_backup,
)
from src.restore.skip_setup27 import skip_all_setup27  # noqa: E402
from src.restore.storage import (  # noqa: E402
    cache_base,
    is_custom_backup_dir,
)


async def _list_connected_devices_async() -> list:
    """Return the UDIDs of every device visible to usbmuxd (awaitable)."""
    try:
        devs = [d for d in await usbmux.list_devices()]
    except Exception:
        devs = []
    out = []
    for d in devs:
        udid = getattr(d, "udid", None) or getattr(d, "serial", None)
        if udid:
            out.append(udid)
    return sorted(set(out))


def _list_connected_devices() -> list:
    """Synchronous wrapper of ``_list_connected_devices_async``.

    Only for callers OUTSIDE a running event loop (skip_setup.py,
    apply_wallpaper.py). Code inside an async function must use
    ``await _list_connected_devices_async()`` instead.
    """
    return asyncio.run(_list_connected_devices_async())


def _live_backup_udids() -> list:
    """UDIDs that have at least one live protective backup run on disk."""
    root = protective_persistent_base()
    if not root.is_dir():
        return []
    return sorted(u.name for u in root.iterdir()
                  if u.is_dir() and any(
                      (u / entry / "device_backup" / u.name / "Manifest.db").is_file()
                      for entry in u.iterdir()))


async def _find_cache_udid(preferred: str, cache_root: str | None,
                           source: str = "auto"):
    """Pick a candidate udid to attempt restoring from.

    Candidates come from the cache bases (json + master dirs) AND the live
    protective backup store, so ``--source live`` / ``auto`` can pick a device
    that only has a live run (no cache). ``source`` only affects preference
    order; the actual source root is resolved in ``_resolve_source``.
    """
    bases = []
    if cache_root:
        bases.append(Path(cache_root))
    else:
        bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        bases.append(cache_base())
        if is_custom_backup_dir():
            # A cache created under the previous default location may still
            # exist there; keep it reachable for standalone recovery.
            bases.append(Path(QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")

    # candidates for udid
    cached_udids = []
    for base in bases:
        info_dir = base
        if info_dir.is_dir():
            for p in sorted(info_dir.glob("*.json")):
                # filename is <udid>.json
                cached_udids.append(p.stem)
        master_dir = base / "master"
        if master_dir.is_dir():
            for udid_dir in master_dir.iterdir():
                if udid_dir.is_dir():
                    cached_udids.append(udid_dir.name)
    cached_udids = list(dict.fromkeys(cached_udids))
    live_udids = _live_backup_udids()

    connected = await _list_connected_devices_async()

    if preferred:
        return preferred
    # Order the candidate pools by the requested source.
    if source == "live":
        pools = [live_udids, cached_udids]
    elif source == "cache":
        pools = [cached_udids, live_udids]
    else:  # auto — cache first, then live runs
        pools = [cached_udids, live_udids]
    # prefer a udid that is also connected
    for pool in pools:
        for u in pool:
            if u in connected:
                return u
    # any connected device
    if connected:
        return connected[0]
    # only a stored udid exists (device not enumerated yet)
    for pool in pools:
        if pool:
            return pool[0]
    return None


def _resolve_source(cache_root: str | None, udid: str, source: str) -> tuple:
    """Resolve the backup source root + its media dir for ``udid``.

    Returns ``(source_root, media_dir, label)``:
    - a cache master → ``<base>/master`` with its ``media/<udid>`` store
      (when the selected cache's metadata says the media rides AFC);
    - the newest live backup run → its ``device_backup`` root with the run's
      ``afc_media`` dir as the media store.
    ``media_dir`` is "" when the source has no AFC media store. Raises
    ``RuntimeError`` when nothing is found for the requested source.
    """
    candidates = []
    if source in ("cache", "auto"):
        base = _pick_base(cache_root, udid)
        if base is not None:
            media_dir = recovery_media_dir(str(Path(base) / "master"), udid, cache_base=base)
            candidates.append((str(Path(base) / "master"), media_dir,
                               f"cache master ({base})"))
    if source in ("live", "auto"):
        live_root = find_latest_protective_backup(udid)
        if live_root is not None:
            candidates.append((live_root, recovery_media_dir(live_root, udid),
                               "live backup run"))
    if not candidates:
        raise RuntimeError(
            f"no protective {'cache' if source == 'cache' else 'backup'} "
            f"found for {udid}.")
    # auto prefers the cache master (fast, incremental); live runs are the
    # fallback after a wedged apply.
    source_root, media_dir, label = candidates[0]
    if source == "auto" and len(candidates) > 1:
        log_info("Found both a cache master and a live run — using the cache "
                 "master. Pass --source live to force the live run.")
    return source_root, media_dir, label


def _pick_base(cache_root: str | None, udid: str):
    bases = []
    if cache_root:
        bases.append(Path(cache_root))
    else:
        bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        bases.append(cache_base())
        if is_custom_backup_dir():
            # A cache created under the previous default location may still
            # exist there; keep it reachable for standalone recovery.
            bases.append(Path(QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")
    for base in bases:
        json_path = base / f"{udid}.json"
        if json_path.is_file():
            return base
    # master may exist without json
    for base in bases:
        if (base / "master" / udid / "Manifest.db").is_file():
            return base
    return None


async def _restore_with_wait(lc, backup_root: str, udid: str, backup_password: str,
                             unlock_timeout_min: int, progress_callback):
    """Restore, retrying on transient errors and WAITING for the unlock.

    This is the standalone version of Phase 3 that does not give up on the
    first PasswordRequiredError — it keeps waiting up to ``unlock_timeout_min``
    for the user to unlock the device, since an iOS 27 wipe restore needs the
    phone unlocked to run.
    """
    import ssl
    import time

    from src.exceptions.device_errors import is_transient_restore_error

    start = time.monotonic()
    deadline = start + unlock_timeout_min * 60
    attempt = 0
    transmit = (DeviceNotFoundError, NotPairedError, ConnectionFailedError,
                ConnectionTerminatedError, PyMobileDevice3Exception,
                ssl.SSLError, OSError)
    while True:
        attempt += 1
        try:
            await _restore_protective_backup(
                lc, backup_root, udid, reboot=False,
                progress_callback=progress_callback,
                backup_password=backup_password,
                skip_apps=True)
            mark_restore_ok(udid)
            return
        except PasswordRequiredError:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise
            progress_callback(
                f"iPhone is LOCKED - unlock it to continue "
                f"(waiting up to {remaining // 60}:{remaining % 60:02d} remaining)...")
            # reconnect after unlocking (the lockdown service may drop)
            try:
                lc.close()
            except Exception:
                pass
            await asyncio.sleep(5)
            try:
                lc = await create_using_usbmux(serial=udid, autopair=False)
            except Exception:
                lc = await create_using_usbmux(serial=udid, autopair=True)
            continue
        except transmit as e:
            if not is_transient_restore_error(e):
                progress_callback(f"Restore error ({type(e).__name__}): {e}")
                raise
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise
            progress_callback(
                f"Device not ready, retrying... ({attempt}) "
                f"({remaining // 60}:{remaining % 60:02d} remaining)")
            await asyncio.sleep(3)


async def run(args) -> int:
    udid = args.udid
    udid = await _find_cache_udid(udid, args.cache_root, args.source)
    if not udid:
        print("ERROR: no device and no stored backup found.")
        print("Connect the iPhone over USB or pass --udid.")
        return 1
    print(f"Using UDID: {udid}")

    try:
        source_root, media_dir, label = _resolve_source(
            args.cache_root, udid, args.source)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"Source: {label}")
    print(f"Backup root: {source_root}")
    if media_dir:
        print(f"AFC media store: {describe_media_store(media_dir)}")

    # build a restorable (pruned) working copy from the master
    try:
        working_root = await asyncio.to_thread(
            make_protective_working_copy, source_root, udid)
    except Exception as e:
        print(f"ERROR: could not copy backup source: {e}")
        return 1
    print(f"Working copy: {working_root}")

    # prune manifest to protective payloads so no mid-stream-drained row can
    # fail the restore with MBErrorDomain/205. When an AFC media store exists,
    # the DCIM/PhotoStreamsData rows are also pruned here — their payloads were
    # never uploaded to the backup and get pushed back over AFC instead.
    from src.exceptions.nugget_exception import NuggetException
    from src.restore.recovery import RecoveryBackend, RecoverySource, prepare_recovery
    try:
        prepared = await prepare_recovery(
            RecoverySource(working_root, udid, args.password or "", media_dir=media_dir),
            RecoveryBackend(clean_backup_for_restore, verify_backup_payloads, media_store_verified))
    except NuggetException as exc:
        log_error(str(exc))
        return 1
    print(f"Pruned: -{prepared.removed_rows} manifest rows, -{prepared.removed_files} payload files")

    def progress_cb(value):
        if isinstance(value, str):
            print(f"  {value}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            print(f"  {value:.1f}%")

    print("Waiting for device (unlock it when prompted)...")
    lc = None
    try:
        print("Connecting to the device...")
        try:
            lc = await create_using_usbmux(serial=udid, autopair=False)
        except Exception:
            lc = await create_using_usbmux(serial=udid, autopair=True)
        print("Connected. Restoring protective backup...")
        await _restore_with_wait(lc, working_root, udid,
                                 args.password or "", args.timeout,
                                 progress_cb)
        if media_dir:
            print("Restoring photos/videos over AFC...")
            # diff=False: an explicit recovery restore — the store's copy must
            # win over whatever the device holds, even at the same size.
            pushed = await restore_media_via_afc(lc, media_dir,
                                                 progress_callback=progress_cb,
                                                 diff=False)
            if pushed.get('failed') or not pushed.get('files'):
                raise RuntimeError("AFC photo/video restore is incomplete; backup kept on this computer")
            print("Photos/videos restored over AFC.")
        print("\nSUCCESS: protective backup restored.")
        # Phase 5 (mirrors _restore_ios27): skip setup panes, then reboot so
        # the restored data + skip-setup actually take effect on iOS 27+.
        try:
            if not args.no_skip_setup:
                print("Applying skip setup panes...")
                await skip_all_setup27(lc, udid)
                print("Skip setup applied.")
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: skip setup failed (data is still restored): {type(e).__name__}: {e}")
        if not args.no_reboot:
            print("Rebooting device...")
            try:
                await reboot_device(reboot=True, lockdown_client=lc)
                print("Reboot command sent.")
            except Exception as e:  # noqa: BLE001
                print(f"WARNING: reboot failed, please reboot manually: {type(e).__name__}: {e}")
        print("Your device should now be back at the lock screen with your data.")
        discard_protective_working_copy(working_root)
        return 0
    except DeviceNotFoundError as e:
        print(f"\nERROR: device not reachable: {e}")
        print("Make sure it is connected via USB and the screen is unlocked.")
        return 2
    except PasswordRequiredError as e:
        print(f"\nERROR: timed out waiting for unlock: {e}")
        print("The backup is preserved on disk - unlock the phone and run this "
              "script again to finish restoring.")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"\nERROR: restore failed: {type(e).__name__}: {e}")
        return 4
    finally:
        if lc is not None:
            try:
                await lc.close()
            except Exception:
                pass  # A reboot can terminate the connection before close.


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", help="device UDID (default: auto-detect)")
    parser.add_argument("--source", choices=("auto", "cache", "live"),
                        default="auto",
                        help="backup source: cache master, newest live run, or "
                             "auto (cache first, then a live run) (default: auto)")
    parser.add_argument("--password", help="backup password (for encrypted caches)")
    parser.add_argument("--cache-root", help="override cache base directory")
    parser.add_argument("--timeout", type=int, default=20,
                        help="minutes to wait for the unlock (default: 20)")
    parser.add_argument("--no-skip-setup", action="store_true",
                        help="do not apply skip-setup panes after restoring (Phase 5)")
    parser.add_argument("--no-reboot", action="store_true",
                        help="do not reboot the device after restoring (Phase 5)")
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    # Bootstraps Qt the same way the GUI does so QStandardPaths.AppDataLocation
    # matches the app's real persistent store (otherwise it resolves one level
    # up, without the application name, and live backups / the cache master are
    # never found).
    import os as _os
    if not _os.environ.get("QT_QPA_PLATFORM") and _os.name != "nt" and not _os.environ.get("DISPLAY"):
        _os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv)
    QCoreApplication.setOrganizationDomain("com.leemin")
    QCoreApplication.setApplicationName("GoldenNugget")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
