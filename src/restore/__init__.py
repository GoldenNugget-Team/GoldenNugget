# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "pymobiledevice3.lockdown",
    "pymobiledevice3.services.mobilebackup2",
    "pymobiledevice3.services.diagnostics",
)

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from pymobiledevice3.exceptions import PyMobileDevice3Exception
from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from pymobiledevice3.services.diagnostics import DiagnosticsService
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from . import backup


async def reboot_device(reboot: bool = False, lockdown_client: LockdownClient = None):
    if reboot and lockdown_client != None:
        print("Success! Rebooting your device...")
        async with DiagnosticsService(lockdown_client) as diagnostics_service:
            await diagnostics_service.restart()
        print("Remember to turn Find My back on!")

async def perform_restore(backup: backup.Backup, reboot: bool = False, lockdown_client: LockdownClient = None, progress_callback = lambda x: None, udid: str = None):
    own_lockdown = (lockdown_client is None)
    try:
        with TemporaryDirectory() as backup_dir:
            backup.write_to_directory(Path(backup_dir))

            # GOLDENNUGGET_KEEP_SPARSE=1 keeps a copy of exactly what was sent
            # to the device — invaluable when the restore is rejected.
            if os.environ.get("GOLDENNUGGET_KEEP_SPARSE") == "1":
                import shutil
                keep = Path(os.environ.get("GOLDENNUGGET_LOG_FILE", "/tmp/gn_sparse_debug")).parent / "gn_sparse_debug"
                shutil.rmtree(keep, ignore_errors=True)
                shutil.copytree(backup_dir, keep)
                print(f"[KEEP_SPARSE] sparse backup copy kept at: {keep}")

            if own_lockdown:
                # Without a serial usbmux hands back the first device, which
                # is not necessarily the one being restored.
                lockdown_client = await create_using_usbmux(serial=udid)
            async with Mobilebackup2Service(lockdown_client) as mb:
                # PosterBoard (the only tweak using AppDomain-*) must be
                # registered in Manifest.plist's Applications dict to avoid
                # MBErrorDomain/205. skip_apps only governs the post-restore
                # app re-installation step — AppDomain data is restored
                # either way (verified on iOS 27 beta 6).
                # Note: may trigger an iOS passcode prompt — unlock the
                # device to proceed.
                await mb.restore(backup_dir, system=True, reboot=False, copy=False, source=".", progress_callback=progress_callback, skip_apps=False)
            # reboot the device
            await reboot_device(reboot, lockdown_client)
    except PyMobileDevice3Exception as e:
        if "Find My" in str(e):
            print("Find My must be disabled in order to use this tool.")
            print("Disable Find My from Settings (Settings -> [Your Name] -> Find My) and then try again.")
            raise e
        elif "crash_on_purpose" not in str(e):
            raise e
        else:
            await reboot_device(reboot, lockdown_client)
    finally:
        # If we created this lockdown_client ourselves, close it safely.
        # After a device reboot the connection is severed and close() will
        # raise ConnectionTerminatedError — suppress it to avoid misleading
        # "Connection Lost" errors in upstream callers.
        if own_lockdown and lockdown_client is not None:
            try:
                await lockdown_client.close()
            except Exception:
                pass
