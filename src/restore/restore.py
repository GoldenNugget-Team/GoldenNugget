# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "src.restore.skip_setup27",
    "pymobiledevice3.services.installation_proxy",
    "pymobiledevice3.services.lockdown_service",
    "pymobiledevice3.services.mobilebackup2",
)

import asyncio
from src.utils.async_disk import disk_call
import os
import plistlib
import shutil
import ssl
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from src.devicemanagement.progress_status import OperationStatus

from . import backup, perform_restore, reboot_device
from src.utils.file_to_restore import FileToRestore, _FileMode
from src.utils.preference_reset import PreferenceKeyReset
from .lastapply import is_ios27_scaffolding, load_lastapply, sparse_signature
from .skip_setup27 import skip_all_setup27
from .afc_media import (
    afc_media_dir_for, describe_media_store,
    media_store_verified, restore_media_via_afc,
)
from .recovery import RecoverySource, RecoveryBackend, prepare_recovery
from .context import RestoreOptions, RestoreSession
from .inject import _is_encrypted_backup
from .protective import (
    PreparedBackup,
    clean_backup_for_restore,
    discard_restore_view,
    inject_files_into_backup,
    log_error,
    log_warn,
    log_info,
    make_restore_view,
    new_protective_backup_dir,
    perform_protective_backup,
    prune_protective_backups,
    verify_backup_payloads,
    WORKING_COPY_PREFIX,
)
from pymobiledevice3.lockdown import LockdownClient, create_using_usbmux
from pymobiledevice3.services.installation_proxy import InstallationProxyService
from pymobiledevice3.services.lockdown_service import LockdownService
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
from pymobiledevice3.exceptions import ConnectionTerminatedError, PasswordRequiredError, InvalidServiceError, CloudConfigurationAlreadyPresentError

from src.exceptions.nugget_exception import NuggetException
from src.exceptions.device_errors import is_transient_restore_error, is_find_my_error, is_icloud_restore_in_progress
from src.exceptions.device_errors import is_connection_error, is_device_lock_required_error, is_device_locked_error

def concat_regular_file(file: FileToRestore, files_list: list[FileToRestore], last_domain: str, last_path: str):
    path, name = os.path.split(file.restore_path)
    paths = path.split("/")
    new_last_domain = last_domain
    # append the domain first
    if last_domain != file.domain:
        files_list.append(backup.Directory(
            "",
            file.domain,
            owner=file.owner,
            group=file.group
        ))
        last_path = ""
        new_last_domain = file.domain
    # append each part of the path if it is not already there
    full_path = ""
    mode = file.mode
    if mode == None:
        mode = backup.DEFAULT
    for path_item in paths:
        if full_path != "":
            full_path += "/"
        full_path += path_item
        if full_path == "":
            continue
        # compare whole components: "Library/Preferences-x" sorts before
        # "Library/Preferences/..." but does not contain it
        if last_path != full_path and not last_path.startswith(full_path + "/"):
            files_list.append(backup.Directory(
                full_path,
                file.domain,
                owner=file.owner,
                group=file.group,
                mode=mode
            ))
            last_path = full_path
    # finally, append the file
    files_list.append(backup.ConcreteFile(
        f"{full_path}/{name}" if full_path else name,
        file.domain,
        owner=file.owner,
        group=file.group,
        contents=file.contents,
        src_path=file.contents_path,
        mode=mode
    ))
    return new_last_domain, full_path

# merge all files that have duplicates and returns the list without duplicates
def merge_duplicates(original_files: list[FileToRestore]) -> list[FileToRestore]:
    no_dupe_files: list[FileToRestore] = []
    existing_locations: dict[str: int] = {}
    for file in original_files:
        if file.domain == None:
            file_loc = "-"
        else:
            file_loc = file.domain + '-'
        restore_path = file.restore_path
        if file.restore_path.startswith('/'):
            restore_path = restore_path.removeprefix('/')
        file_loc += restore_path
        if file_loc in existing_locations:
            previous = no_dupe_files[existing_locations[file_loc]]
            if isinstance(previous.contents, PreferenceKeyReset) or isinstance(file.contents, PreferenceKeyReset):
                if not (isinstance(previous.contents, PreferenceKeyReset)
                        and isinstance(file.contents, PreferenceKeyReset)):
                    raise ValueError('Cannot combine preference writes and resets for the same file.')
                previous.contents = PreferenceKeyReset(previous.contents.paths + file.contents.paths)
                continue
            if not restore_path.endswith('.plist'):
                print(f'cannot merge duplicate file, ignoring {file_loc}')
                continue
            # merge the data (plist files only)
            print(f'merging duplicate files for {file_loc}')
            initial_data = plistlib.loads(no_dupe_files[existing_locations[file_loc]].contents)
            added_data = plistlib.loads(file.contents)
            initial_data.update(added_data)
            no_dupe_files[existing_locations[file_loc]].contents = plistlib.dumps(initial_data)
            del initial_data, added_data
        else:
            # add it to the no dupes list
            no_dupe_files.append(file)
            existing_locations[file_loc] = len(no_dupe_files) - 1
    return no_dupe_files

# --- iOS 27+ three-phase restore -------------------------------------------
#
# Progress is mapped into per-phase ranges so the GUI bar never jumps
# backwards: Phase 1 (protective backup) 0-40, Phase 2 (sparse restore +
# reboot) 40-60, Phase 3 (reconnect + protective restore) 60-100.
_PHASE_BACKUP_END = 40
_PHASE_TWEAK_END = 60

# How long to wait for the device to come back after the iOS 27 security
# recovery before giving up. Apple logo → reboot → progress bar (like
# Erase All Contents) → full boot can take several minutes.
_RECONNECT_TIMEOUT = 20 * 60

# Tweak files are delivered through Phase 1's backup injection
# (``inject_file_into_backup``) on iOS 27 — the sparse restore clears whatever
# it stages otherwise. On unencrypted prepared backups ALL tweak files are
# injected (see ``inject_all`` in restore_files); encrypted backups fall back
# to the sparse pass since plaintext injection into an encrypted manifest is
# impossible.


async def _wait_for_device(udid: str, progress_callback,
                           timeout: float = _RECONNECT_TIMEOUT,
                           prompt_choice=None) -> LockdownClient:
    """Wait for the device to return after the iOS 27 security recovery.

    Polls usbmux with capped exponential backoff. Fully async — the caller's
    event loop (and the GUI) stays responsive for the whole wait.

    The pairing record SURVIVES a plain tweak-apply wipe (verified: SideStore
    keeps working), so the connect runs WITHOUT autopair — forcing a re-pair
    crashes with MissingValueError while the device is still finishing recovery
    and has no DevicePublicKey to give. A Reset (purplebuddy erasure) wipes the
    on-device pairing too: lockdownd then rejects the session start and
    create_using_usbmux(autopair=False) returns a SILENTLY UNPAIRED client, so
    we verify ``ld.paired`` and, once a short grace period has passed, attempt
    a full autopair fallback. Only a client whose pairing validated is ever
    returned — otherwise Phase 3's service start would raise NotPairedError.

    Instead of failing the whole restore when the wait times out (the classic
    "device was not unlocked in time after the security recovery" case), the
    caller can pass ``prompt_choice(title, text) -> "abort" | "resume"``: the
    timeout then shows an Abort/Resume prompt, and "resume" simply restarts a
    fresh waiting cycle instead of killing the restore.
    """
    from pymobiledevice3.exceptions import (
        DeviceNotFoundError, PasswordRequiredError, NotPairedError,
        ConnectionFailedError, ConnectionTerminatedError, LockdownError,
        MissingValueError, PairingError, FatalPairingError,
        MuxException,
    )
    while True:
        start = time.monotonic()
        deadline = start + timeout
        delay = 1.0
        last_error = None
        autopair_tried = False
        saw_password_required = False
        while True:
            elapsed = int(time.monotonic() - start)
            if isinstance(last_error, PasswordRequiredError):
                progress_callback(OperationStatus(
                    "Your iPhone is locked. Unlock it and enter its passcode to continue.",
                    "authentication"))
            else:
                progress_callback(
                    f"Waiting for device after reboot "
                    f"({elapsed // 60}:{elapsed % 60:02d} elapsed)...")
            try:
                ld = await create_using_usbmux(serial=udid, autopair=False)
                if not getattr(ld, "paired", False):
                    # The host's pair record still exists but lockdownd rejected
                    # the session start — the erasure wiped the on-device pairing
                    # (typical for Reset, unlike a plain tweak apply where the
                    # record survives). Returning this client would make every
                    # later service start raise NotPairedError. Close it, record
                    # the loss and let the poll continue so the autopair
                    # fallback below re-pairs the device after the grace period.
                    try:
                        await ld.close()
                    except Exception:
                        pass
                    raise NotPairedError()
                return ld
            except NotPairedError as e:
                # pairing genuinely lost — try a full re-pair once, after giving
                # the device time to finish recovery
                last_error = e
                if not autopair_tried and time.monotonic() - start >= 30:
                    autopair_tried = True
                    try:
                        ld = await create_using_usbmux(serial=udid, autopair=True)
                        if getattr(ld, "paired", False):
                            return ld
                        try:
                            await ld.close()
                        except Exception:
                            pass
                        last_error = NotPairedError(
                            "re-pair completed but lockdownd still reports "
                            "the host as unpaired")
                    except (MissingValueError, LockdownError,
                            PairingError, FatalPairingError,
                            DeviceNotFoundError, ConnectionFailedError,
                            ConnectionTerminatedError, MuxException,
                            ConnectionError, OSError, asyncio.TimeoutError) as e2:
                        # PairingError covers the pending/denied trust dialog;
                        # FatalPairingError a rejected re-pair. None of these
                        # should kill the wait — the device may still be
                        # finishing recovery, so keep polling. USB transport
                        # drops during re-pairing need the same retry too.
                        last_error = e2
            except (DeviceNotFoundError, PasswordRequiredError,
                    ConnectionFailedError, ConnectionTerminatedError,
                    MuxException,
                    ConnectionError, OSError, asyncio.TimeoutError,
                    LockdownError) as e:
                # LockdownError covers MissingValueError and every other
                # lockdown-level complaint the recovering device may emit.
                # MuxException is separate from ConnectionError/OSError and
                # covers usbmux sockets torn down during a reboot.
                last_error = e
                if isinstance(e, PasswordRequiredError):
                    saw_password_required = True
                    progress_callback(OperationStatus(
                        "Your iPhone is locked. Unlock it and enter its passcode to continue.",
                        "authentication"))
            if time.monotonic() + delay > deadline:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)
        # inner wait cycle exhausted — offer Abort/Resume instead of aborting
        err = DeviceNotFoundError(
            f"Device {udid} not reachable after reboot "
            f"({int(timeout // 60)} min timeout). Unlock the device and make "
            f"sure it is connected via USB. Last error: {last_error}"
        )
        if prompt_choice is None:
            raise err
        title = QCoreApplication.tr("Device took too long to unlock")
        if saw_password_required:
            text = QCoreApplication.tr(
                "The device has not been unlocked for too long after the "
                "security recovery \u2014 it keeps asking for your passcode.\n\n"
                "Unlock it, enter the passcode and tap \"Trust\" if prompted, "
                "then choose:\n\n"
                "  \u2022 Resume \u2014 keep waiting (restarts the \"Waiting for "
                "device to reconnect after security recovery\" cycle).\n"
                "  \u2022 Abort \u2014 stop now. Tweaks may not be applied and "
                "data protection stays incomplete.")
        else:
            text = QCoreApplication.tr(
                "The device has not been unlocked for too long after the "
                "security recovery.\n\n"
                "Unlock it, enter the passcode, tap \"Trust\" if the computer "
                "trust prompt appears, and make sure it stays connected via "
                "USB, then choose:\n\n"
                "  \u2022 Resume \u2014 keep waiting (restarts the \"Waiting for "
                "device to reconnect after security recovery\" cycle).\n"
                "  \u2022 Abort \u2014 stop now. Tweaks may not be applied and "
                "data protection stays incomplete.")
        log_info("Reconnect wait timed out; asking the user whether to resume or abort")
        try:
            decision = prompt_choice(title, text)
        except Exception as e:
            log_warn(f"Reconnect prompt failed ({e}) — aborting")
            raise err
        if decision != "resume":
            raise err
        log_info("User chose to resume — restarting the reconnect wait cycle")


class _Mobilebackup2NoEscrow(Mobilebackup2Service):
    """mobilebackup2 started WITHOUT the escrow bag.

    After the iOS 27 safe-state wipe, _wait_for_device() re-pairs the
    device. The fresh pair record carries no EscrowBag (one is only
    issued when pairing a passcode-protected device), so the stock
    Mobilebackup2Service — which hardcodes include_escrow_bag=True —
    dies with KeyError: 'EscrowBag'.
    """

    def __init__(self, lockdown: LockdownClient) -> None:
        LockdownService.__init__(self, lockdown, self.SERVICE_NAME,
                                 include_escrow_bag=False)


def _start_mobilebackup2(lc: LockdownClient) -> Mobilebackup2Service:
    """Pick the mobilebackup2 variant matching the pair record's escrow state."""
    pair_record = getattr(lc, "pair_record", None)
    if pair_record is not None and "EscrowBag" not in pair_record:
        log_warn("Pair record has no EscrowBag (fresh re-pair after the "
                 "wipe) — starting mobilebackup2 without it")
        return _Mobilebackup2NoEscrow(lc)
    return Mobilebackup2Service(lc)


async def _restore_protective_backup(lc: LockdownClient, backup_root: str,
                                      udid: str, reboot: bool,
                                      progress_callback, backup_password: str = "",
                                      skip_apps: bool = True,
                                      copy_backup: bool = True) -> None:
    """Phase 3: restore the pruned protective backup.

    Retries while SpringBoard / mobilebackup2 are still coming up after the
    security recovery (they can take minutes on iOS 27).

    The progress_callback is already pre-scaled by the caller.
    """
    from src.utils.async_retry import async_retry

    max_retries = 18

    from src.restore.find_my_wait import current_find_my_wait, ApplyCancelledError
    wait_control = current_find_my_wait.get()
    restore_started = False

    async def _perform_restore(client):
        nonlocal restore_started
        restore_started = False

        def report_progress(value):
            nonlocal restore_started
            if isinstance(value, (int, float)) and value > 0:
                restore_started = True
                if wait_control is not None:
                    wait_control.finish()
            progress_callback(value)
        async with _start_mobilebackup2(client) as mb:
            await mb.restore(
                backup_root,
                system=True, copy=copy_backup, remove=False,
                reboot=reboot, source=udid,
                skip_apps=skip_apps,
                progress_callback=report_progress,
                password=backup_password,
            )
        if wait_control is not None:
            wait_control.finish()

    async def _restore_once():
        blocked_by_find_my = False
        while True:
            try:
                if blocked_by_find_my:
                    from src.devicemanagement.session import lockdown_session
                    async with lockdown_session(udid, autopair=False, connection_type="USB") as fresh:
                        await _perform_restore(fresh)
                else:
                    await _perform_restore(lc)
                return
            except ApplyCancelledError:
                raise
            except Exception as error:
                if wait_control is None:
                    raise
                if is_find_my_error(error):
                    blocked_by_find_my = True
                    progress_callback(QCoreApplication.tr(
                        "Waiting for Find My to be turned off. Keep the device connected and unlocked. "
                        "Restoration will retry automatically."))
                elif (blocked_by_find_my and not restore_started
                      and (is_transient_restore_error(error) or is_connection_error(error)
                           or is_device_lock_required_error(error) or is_device_locked_error(error))):
                    progress_callback(QCoreApplication.tr(
                        "Waiting for the device while Find My is checked. Keep it connected and unlocked."))
                else:
                    wait_control.finish()
                    raise
                await wait_control.wait_for_retry()

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        progress_callback(
            f"Device not ready, retrying ({attempt}/{max_retries})..."
        )

    def _on_failure(e: Exception) -> None:
        if is_icloud_restore_in_progress(e):
            raise NuggetException('The iPhone reports an iCloud restore in progress. Wait for it to finish before retrying. Existing protective backups are retained.') from e
        if isinstance(e, ApplyCancelledError):
            raise e
        # Like Nugget-Mobile, classify Find My from the restore failure text;
        # the restore service does not expose a dependable preflight setting.
        # Inspect chained causes too, since pymobiledevice3 may wrap the
        # underlying lockdown error before it reaches this retry boundary.
        if is_find_my_error(e):
            raise NuggetException(
                QCoreApplication.tr("Find My must be disabled in order to use this tool."),
                detailed_text=QCoreApplication.tr(
                    "The device's restore service reported a Find My protection error. "
                    "Turn off Find My iPhone in Settings → [your name] → Find My, "
                    "then retry the restore. Your protective backup remains on this computer.")) from e
        # The device already told us which file it stubbed on — cross-check
        # the pruned manifest on disk so the log shows exactly which rows
        # are missing their payload (MBErrorDomain/205 post-mortem).
        if not is_transient_restore_error(e):
            try:
                missing = verify_backup_payloads(backup_root, udid, backup_password)
                if missing:
                    log_error(f"MBErrorDomain/205 context: {len(missing)} manifest rows "
                              f"lack payloads (e.g. {missing[:5]})")
            except Exception:
                pass
        if isinstance(e, InvalidServiceError):
            raise NuggetException(
                "The iPhone would not start the restore service "
                "(mobilebackup2) even after several minutes of retries.",
                detailed_text=(
                    "The backup/restore service was unavailable. This does not establish "
                    "whether Developer Mode is enabled. The device may still be booting or locked. "
                    "Unlock the iPhone, keep the screen on, wait for "
                    "it to reach the home screen, then apply again. "
                    "Your data was not lost - the protective backup is "
                    "kept on this computer and will be restored on the "
                    "next run."
                ),
            )
        # The password gate (handled separately by the caller) and already
        # user-friendly errors must pass through untouched. Anything else that
        # survived the retry loop is an opaque device/protocol failure — surface
        # it as clear guidance instead of a bare traceback: the protective
        # backup is the ONLY copy of the user's data after Phase 2 wiped it.
        if isinstance(e, (PasswordRequiredError, NuggetException)):
            raise e
        raise NuggetException(
            QCoreApplication.tr(
                "The protective backup could not be restored to the iPhone."),
            detailed_text=QCoreApplication.tr(
                "The device dropped the connection during the data restore.\n\n"
                "Your data is not lost — the protective backup taken before "
                "the wipe is kept on this computer.\n\n"
                "This connection error can have several causes. Keep the iPhone "
                "unlocked with the screen on and connected by USB. If the device "
                "reported a Find My protection error, turn Find My off before retrying.\n\n"
                "Do not erase the phone or set it up as new — the protective "
                "backup on this computer is the only copy of your data.")
        ) from e

    await async_retry(
        _restore_once,
        max_retries,
        retry_if=is_transient_restore_error,
        fixed_delay=3,
        on_retry=_on_retry,
        on_failure=_on_failure,
    )


async def _deliver_sparse_phase(back, lockdown_client, udid, progress_callback, options):
    """Deliver sparse files, returning a zero-progress failure for final reporting."""
    merge_phases = options.merge_phases
    stage_callback = options.stage_callback
    sparse_failure = None
    # === Phase 2: apply tweaks → reboot (40-60%) ===
    if len(back.files) == 0:
        # Nothing left for the sparse/partial pass: every tweak payload was
        # diverted to inject_files (delivered by Phase 3's protective
        # restore), so the device never needs the security-recovery reboot
        # here — go straight to Phase 3.
        log_info("Phase 2: nothing to sparse-restore — skipping the partial "
                 "restore; tweaks are delivered by the protective "
                 "restore (Phase 3)")
        progress_callback(100)
    else:
        if stage_callback:
            stage_callback("tweaks", "")
        progress_callback(0)
        log_info(f"Phase 2: Applying tweaks via sparse restore ({len(back.files)} files)")
        sparse_progress = {"last": None, "calls": 0}

        def _tracking_callback(value):
            # remember how far the sparse restore actually got before any
            # connection drop — a drop at 0% means it was rejected, not applied
            sparse_progress["calls"] += 1
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sparse_progress["last"] = value
            progress_callback(value)

        # The cache session finishes right before Phase 2 starts; on some
        # devices backupd needs a moment before accepting another mobilebackup2
        # client — a drop at 0% is that wedge, not a rejection. Cool down and
        # retry once on a fresh connection.
        max_sparse_attempts = 2
        for sparse_attempt in range(max_sparse_attempts):
            sparse_progress["last"] = None
            sparse_progress["calls"] = 0
            try:
                await perform_restore(
                    # Merged mode skips the security-recovery reboot: the
                    # device stays up, iOS never enters safe-state recovery
                    # and never wipes, and Phase 3's protective restore
                    # lands on the LATER-STILL-LIVE device (the same
                    # delivery the PosterBoard-only path already uses).
                    backup=back, reboot=not merge_phases,
                    lockdown_client=lockdown_client if sparse_attempt == 0 else None,
                    progress_callback=_tracking_callback, udid=udid)
                log_info(f"Phase 2: sparse restore completed cleanly "
                         f"({sparse_progress['calls']} progress events)")
                break
            except (ConnectionTerminatedError, ssl.SSLEOFError,
                    ConnectionAbortedError, ConnectionResetError) as e:
                no_progress = sparse_progress["last"] is None or sparse_progress["last"] <= 0
                if no_progress and sparse_attempt + 1 < max_sparse_attempts:
                    log_warn("Phase 2: connection dropped at 0% right after the cache "
                             "session — cooling down 25s and retrying once on a "
                             "fresh connection")
                    await asyncio.sleep(25)
                    continue
                if no_progress:
                    sparse_failure = e
                    log_error("Phase 2: connection dropped with ZERO restore progress "
                              "on every attempt — the sparse restore was likely "
                              "REJECTED. Security state recovery will not trigger; "
                              "tweaks are NOT applied.")
                else:
                    log_info(f"Phase 2: Device rebooted during sparse restore "
                             f"(expected; last progress {sparse_progress['last']:.1f}%)")
                break
        progress_callback(100)

    return sparse_failure


async def _restore_protective_phase(session, lockdown_client, udid, backup_root,
                                    inject_files, progress_callback, options):
    """Restore protective data, preserving resume and merged-session fallback."""
    backup_password = options.backup_password
    skip_protective_backup = options.skip_protective_backup
    merge_phases = options.merge_phases
    prompt_choice = options.prompt_choice
    merge_fallback_done = False
    if merge_phases:
        # Merged mode: the sparse restore never rebooted, so there is no
        # security recovery to wait for — the device is still connected and
        # its data was never wiped. Reuse the SAME session for the
        # protective restore, exactly like the PosterBoard-only path does
        # (that path proves a protective restore over a live, un-wiped
        # device works — to iOS it looks like a normal full restore).
        log_info("Phase 3: merged mode — device never rebooted, restoring "
                 "protective backup on the live session (no security "
                 "recovery, no data wipe)")
        lc = lockdown_client
        await asyncio.sleep(1)
    else:
        log_info("Phase 3: Waiting for device to reconnect after security recovery")
        lc = await _wait_for_device(udid, progress_callback,
                                    prompt_choice=prompt_choice)
    try:
        # brief settle time after reconnect — _restore_protective_backup
        # retries handle any remaining startup delay
        await asyncio.sleep(1)
        if skip_protective_backup or not session.backup_complete:
            log_warn("Phase 3: skipping protective restore (user opted out "
                     "of data protection)")
        else:
            # A bootlooping daemon keeps the device stuck on the passcode
            # screen — mobilebackup2 refuses to start with
            # PasswordRequiredError before a single retry. Offer the same
            # Abort/Resume choice as the reconnect wait instead of crashing.
            while True:
                try:
                    await _restore_protective_backup(
                        lc, backup_root, udid, False,
                        progress_callback,
                        backup_password=backup_password,
                        skip_apps=not any(
                            getattr(f, "domain", "").startswith("AppDomain")
                            for f in (inject_files or [])))
                    break
                except PasswordRequiredError:
                    if prompt_choice is None:
                        raise
                    log_info("Phase 3: protective restore blocked — device "
                             "locked (bootloop signature); asking user to "
                             "resume or abort")
                    title = QCoreApplication.tr("Device locked — cannot restore backup")
                    text = QCoreApplication.tr(
                        "The phone is asking for a passcode to start the "
                        "restore service. This usually means the applied "
                        "tweaks are preventing it from booting properly.\n\n"
                        "  \u2022 Resume \u2014 unlock the device, then keep "
                        "trying to restore the backup.\n"
                        "  \u2022 Abort \u2014 stop now. The protective backup "
                        "is kept on this computer for a later restore.")
                    try:
                        decision = prompt_choice(title, text)
                    except Exception:
                        raise
                    if decision != "resume":
                        raise
                    log_info("Phase 3: user chose resume — reconnecting and retrying")
                    try:
                        await lc.close()
                    except Exception:
                        pass
                    lc = await _wait_for_device(udid, progress_callback,
                                                prompt_choice=prompt_choice)
                except NuggetException as e:
                    # `_on_failure` wraps the last retry error into a
                    # NuggetException (raise ... from e), so a merged-mode
                    # self-reboot surfaces here wrapped instead of as a raw
                    # ConnectionTerminatedError/OSError. Unwrap and route
                    # connection drops through the classic reconnect path
                    # too; anything else (device-locked, invalid service,
                    # real protocol errors) keeps its friendly message.
                    cause = e.__cause__ or e.__context__ or e
                    if not is_connection_error(cause):
                        raise
                    if not merge_phases or merge_fallback_done:
                        raise
                    log_warn(f"Phase 3: merged-mode session dropped "
                             f"({type(cause).__name__}: {cause}) — falling "
                             "back to the classic reconnect path")
                    try:
                        await lc.close()
                    except Exception:
                        pass
                    lc = await _wait_for_device(udid, progress_callback,
                                                prompt_choice=prompt_choice)
                    merge_fallback_done = True
                except (ConnectionTerminatedError, ConnectionError,
                        OSError, asyncio.TimeoutError) as e:
                    # Merged mode reuses the Phase 2 session; if the device
                    # rebooted itself anyway (a tweak that demands the
                    # security-recovery wipe), that client is now dead —
                    # fall back to the classic reconnect + fresh session
                    # instead of failing the whole apply.
                    if not merge_phases or merge_fallback_done:
                        raise
                    log_warn(f"Phase 3: merged-mode session dropped "
                             f"({type(e).__name__}: {e}) — falling back to "
                             "the classic reconnect path")
                    try:
                        await lc.close()
                    except Exception:
                        pass
                    lc = await _wait_for_device(udid, progress_callback,
                                                prompt_choice=prompt_choice)
                    merge_fallback_done = True
            log_info("Phase 3: Protective backup restored successfully")

    finally:
        session.client = lc


async def _finish_restore_phases(session, udid, media_dir, progress_callback, options):
    """Reboot, reconnect, deliver media, skip setup, then perform the final reboot."""
    reboot = options.reboot
    skip_setup = options.skip_setup
    supervised = options.supervised
    organization_name = options.organization_name
    prompt_choice = options.prompt_choice
    stage_callback = options.stage_callback
    lc = session.client
    try:
        # === Phase 4: reboot before the media restore + setup skip (90-95%) ===
        # Swapped with the old skip-setup phase: on a merged (never-rebooted)
        # live session the device still carries its cloud configuration and
        # SetCloudConfiguration only raises AlreadyPresent. Rebooting first
        # gives the media restore and skip_all_setup27 a freshly-booted
        # device (Phase 5) and the final reboot (Phase 6) lets the skip take
        # effect on the next boot.
        if stage_callback:
            stage_callback("restore", "restart" if reboot and skip_setup else "waiting")
        pre_skip_reboot = reboot and skip_setup
        if pre_skip_reboot:
            progress_callback("Rebooting device...")
            log_info("Phase 4: Rebooting device before skipping setup")
            await reboot_device(reboot=True, lockdown_client=lc)
            log_info("Phase 4: Reboot command sent")


        # === Phase 5: reconnect (if rebooted) + push media + skip setup (95-98%) ===
        if pre_skip_reboot:
            try:
                await lc.close()
            except Exception:
                pass
            lc = await _wait_for_device(udid, progress_callback,
                                        prompt_choice=prompt_choice)

        # Photos/videos pulled over AFC are pushed back now that the device
        # is back up and accepting AFC connections (after the Phase 4
        # reboot, on the freshly-reconnected session; or straight on the
        # live session when no reboot happened). This is the ONLY channel
        # that carries them on an AFC apply — the protective restore ships
        # only the non-media scope (media rows were not in its backup).
        if media_dir:
            # The media store is the ONLY copy of the photos at this point
            # (the device was just wiped), so anything short of a complete
            # push is a data-loss event and must abort loudly rather than
            # let the apply report success.
            if not os.path.isdir(media_dir) or not os.listdir(media_dir):
                raise NuggetException(
                    f"AFC media store is missing or empty ({media_dir}) — "
                    f"the photos were not backed up before the wipe. "
                    f"Aborting instead of pretending the restore finished.")
            if stage_callback:
                stage_callback("media", "photos")
            progress_callback(0)
            log_info(f"Phase 5: Pushing photos/videos back over AFC "
                     f"({describe_media_store(media_dir, verify=False)})")
            pushed = await restore_media_via_afc(
                lc, media_dir,
                include_historical=False,
                progress_callback=progress_callback,
                prompt_choice=prompt_choice,
                unlock_prompt=(
                    QCoreApplication.tr("Device stayed locked"),
                    QCoreApplication.tr(
                        "The device has not been unlocked long enough to "
                        "push your photos and videos back after the "
                        "reboot.\n\n"
                        "Unlock it, enter your passcode, and keep it "
                        "connected via USB, then choose:\n\n"
                        "  \u2022 Resume \u2014 keep waiting for the device "
                        "to be unlocked and push your photos.\n"
                        "  \u2022 Abort \u2014 stop now. Your photos are "
                        "still safe in the backup cache on this computer, "
                        "but they will not be on the device yet.")
                ))
            if pushed.get("failed"):
                raise NuggetException(
                    f"AFC media restore failed for {len(pushed['failed'])} "
                    f"file(s) (e.g. {pushed['failed'][:3]}) — the photos on "
                    f"the device are incomplete")
            log_info("Phase 5: Media restored over AFC")

        if skip_setup:
            if stage_callback:
                stage_callback("setup", "settings")
            progress_callback("Skipping setup panes...")
            log_info("Phase 5: Skipping setup panes via MobileConfigService")
            try:
                await skip_all_setup27(lc, udid, supervised=supervised,
                                       organization_name=organization_name,
                                       progress_callback=progress_callback)
            except CloudConfigurationAlreadyPresentError:
                log_info("Phase 5: device already has a cloud configuration "
                         "— setup already handled, nothing to skip")
            else:
                log_info("Phase 5: Setup panes skipped successfully")
            progress_callback(98)

        # === Phase 6: final reboot so the skipped setup takes effect (98-100%) ===
        if reboot:
            if stage_callback:
                stage_callback("setup", "restart")
            progress_callback("Rebooting device...")
            log_info("Phase 6: Rebooting device")
            await reboot_device(reboot=True, lockdown_client=lc)
            log_info("Phase 6: Reboot command sent")
        progress_callback(100)
    finally:
        session.client = lc


async def _restore_ios27(back: backup.Backup, reboot: bool,
                          lockdown_client: LockdownClient, progress_callback,
                          backup_password: str = "",
                          prepared_backup_root: PreparedBackup = None,
                          inject_files: list = None,
                          skip_setup: bool = True,
                           skip_protective_backup: bool = False,
                          include_keychain: bool = False,
                          prompt_choice=None,
                          afc_media: bool = False,
                          merge_phases: bool = True,
                          supervised: bool = False,
                          organization_name: str = "", stage_callback=None):
    """iOS 27+ restore: backup → tweak → wipe → restore → skip setup → reboot.

    Phase 1 (0-40%):  Selective backup of photos, Apple ID, user
                      settings, and Messages. Non-protective data is drained
                      mid-stream, so no multi-GB full backup ever hits the
                      disk. KeychainDomain rides along only when the backup
                      is encrypted (see include_keychain). With
                      ``prepared_backup_root`` the backup already happened
                      earlier in the apply flow (fresh Phase-0 live
                      backup, or the persistent cache master + incremental
                      refresh): a fresh live run is pruned IN PLACE, a cache
                      master is restored from a disposable view (pruned and
                      tweak-injected there), so the master itself is never
                      modified. With ``skip_protective_backup`` the whole phase
                      (and Phase 3) is skipped — the user opted out on low
                      disk space.
    Phase 2 (40-60%): Apply tweaks via sparse restore → reboot, which
                      triggers the iOS 27 "safe state recovery" wipe. By
                      default (``merge_phases``) the reboot is skipped: the
                      device stays up and never enters safe-state recovery,
                      so no wipe happens — the protective restore lands on
                      the still-live device (the same delivery the
                      PosterBoard-only path already uses). On unencrypted
                      prepared backups every tweak file is injected into the
                      protective backup instead, so this phase has nothing
                      left to sparse-restore and is skipped entirely. Set
                      GOLDENNUGGET_NO_MERGE_PHASES=1 to restore the classic
                      reboot-then-wipe flow.
    Phase 3 (60-90%):  Reconnect and restore the pruned Phase 1 backup so
                      user data survives the wipe. The restore itself does
                      not reboot; that happens after setup skip. In merged
                      mode there is no reconnect — the live session from
                      Phase 2 is reused (the device was never rebooted).
    Phase 4 (90-95%): Reboot the device so it boots fresh before the media
                      restore and the setup skip (a merged still-live session
                      would otherwise already carry a cloud configuration and
                      Phase 5's SetCloudConfiguration only raises AlreadyPresent).
    Phase 5 (95-98%): Reconnect (only after a Phase 4 reboot; the reused live
                      session is closed first), push the AFC-pulled
                      photos/videos back over AFC, then skip the iOS setup
                      panes via cloud configuration.
    Phase 6 (98-100%): Reboot again so the skipped setup takes effect on the
                       next boot.
    """
    options = RestoreOptions(
        backup_password=backup_password, reboot=reboot, skip_setup=skip_setup, skip_protective_backup=skip_protective_backup,
        include_keychain=include_keychain, merge_phases=merge_phases,
        supervised=supervised, organization_name=organization_name,
        prompt_choice=prompt_choice, stage_callback=stage_callback)
    udid = lockdown_client.udid
    started = time.monotonic()
    # Per-phase timings, logged as the apply progresses. Without them the
    # dominant cost of an apply is invisible — which is exactly why the cache
    # looked like it did nothing.
    phase_started = started

    def mark_phase(name: str) -> None:
        """Log the elapsed time of the phase that just finished."""
        nonlocal phase_started
        now = time.monotonic()
        log_info(f"Phase timing — {name}: {now - phase_started:.1f}s "
                 f"({now - started:.1f}s into the apply)")
        phase_started = now

    using_cache = prepared_backup_root is not None
    # Media pulled over AFC (sibling of the run's device_backup, or the caller's
    # prepared run) is pushed back in Phase 5, after the Phase 4 reboot and
    # reconnect, once the protective restore that carries everything else has
    # landed (Phase 3). Empty when media rides the mobilebackup2 backup itself
    # (cache master, or AFC disabled) — then Phase 3 already ships it.
    media_dir = ""
    if prepared_backup_root is not None and getattr(prepared_backup_root, "media_src", ""):
        media_dir = prepared_backup_root.media_src
    # The prune password comes from whichever Phase-0 path built the backup:
    #  - cache master: captured when the master was built (manifest_password);
    #  - Phase-0 LIVE backup: none is stored (it never prompts), so fall back to
    #    the Phase 3 restore password, which the user just typed for the
    #    encrypted restore and IS the same manifest password.
    # Leaving it "" skips pruning entirely and makes Phase 3 try to download the
    # rows that were drained mid-stream → MBErrorDomain/205.
    manifest_password = ((prepared_backup_root.manifest_password if using_cache else "")
                         or backup_password)
    protective_dir = None
    # Per-apply restore view of the cache master ('' when this run restores
    # from a live backup instead). Disposable: dropped in the ``finally`` below.
    view_dir = None
    # A cache master is the pristine incremental store AND the diff base of the
    # next refresh, so the apply must never prune or tweak-inject it. The prune
    # and the injection run against a disposable *view* of it (hardlinked
    # payloads, real-copied metadata) and Phase 3 restores from that view, so
    # the master stays intact even if the apply dies between Phase 2 and 3.
    if using_cache and prepared_backup_root.master:
        # The view must sit on the master's filesystem or the payload hardlinks
        # degrade into full copies (the caller normally supplies this path).
        view_root = (prepared_backup_root.view_root
                     or str(Path(prepared_backup_root.root).parent / "view"))
        view_dir = await disk_call(
            make_restore_view, prepared_backup_root.root, udid, view_root)
        log_info('Cache restore view prepared; the master stays pristine and '
                 'is reused by the next refresh')
        backup_root = view_dir
        # No protective_dir: a cache master must never be rmtree'd (it is the
        # incremental store + the only copy of user data between Phase 2 and 3).
    elif using_cache:
        # A fresh Phase-0 live backup is disposable by nature — prune it in
        # place, no /tmp copy (a hardlink copy can spill onto another volume
        # via copy2 and OSError with ENOSPC, and a real full backup on a tight
        # disk is exactly the case this path must survive).
        backup_root = prepared_backup_root.root
        protective_dir = os.path.dirname(backup_root)
    else:
        # Live backup taken here rather than pre-prepared. It still has to go
        # to persistent storage: Phase 2 is about to wipe the device, after
        # which this directory is the sole copy of the user's data. A temp dir
        # would be swept by the cleanup below (or lost on reboot).
        backup_root = new_protective_backup_dir(udid)
        protective_dir = os.path.dirname(backup_root)
        if afc_media and not skip_protective_backup:
            media_dir = afc_media_dir_for(backup_root)
            log_info(f"AFC media for this run will be pulled into: {media_dir}")
    backup_complete = False
    sparse_failure = None
    try:
        log_info(f"Starting iOS 27 restore for device {udid}")
        log_info(f"Protective backup directory: {protective_dir or backup_root}")

        # Clean up stale working copies from crashed runs (>1h old).
        #
        # ONLY working copies — those are rebuilt from the backup on every run.
        # Live protective backups live outside the temp dir under their own
        # tree (see protective_persistent_base); after Phase 2 has wiped the
        # device they are the sole copy of the user's data, so sweeping them
        # here would turn a recoverable failure into permanent loss. The
        # prefix is the guard, and the check below makes it fail safe.
        import glob as _glob
        from .protective import protective_persistent_base
        _persistent_base = str(protective_persistent_base())
        for stale in sorted(_glob.glob(os.path.join(
                tempfile.gettempdir(), WORKING_COPY_PREFIX + "*"))):
            try:
                if stale == protective_dir:
                    continue
                if os.path.abspath(stale).startswith(_persistent_base):
                    log_error(f"Refusing to sweep {stale}: inside the persistent "
                              f"protective backup store")
                    continue
                age_h = (time.time() - os.path.getctime(stale)) / 3600
                if age_h > 1:
                    shutil.rmtree(stale, ignore_errors=True)
                    log_info(f"Cleaned stale working copy: {stale} ({age_h:.0f}h old)")
            except OSError:
                pass

        # === Phase 1: selective protective backup (0-40%) ===
        if stage_callback:
            stage_callback("backup", "")
        progress_callback(0)
        if using_cache:
            log_info("Phase 1: Using prepared protective backup "
                     "(cache master restored through a disposable view, "
                     "or the fresh Phase-0 live backup pruned in place)")
        elif skip_protective_backup:
            log_warn("Phase 1: protective backup SKIPPED at the user's request "
                     "(no data protection for this apply)")
        else:
            log_info("Phase 1: Starting protective backup (photos, Apple ID, settings, home screen)")
            await perform_protective_backup(
                lockdown_client, backup_root,
                progress_callback=progress_callback,
                include_photos=True,
                include_keychain=include_keychain,
                include_afc_media=bool(media_dir),
            )
            # Only retire the previous run once this one is solid (see the same
            # after-success prune in device_manager._live_backup).
            prune_protective_backups(udid)
        backup_complete = not skip_protective_backup

        if backup_complete:
            removed_rows, removed_files = await asyncio.to_thread(
                clean_backup_for_restore, backup_root, udid,
                include_keychain=include_keychain,
                manifest_password=manifest_password,
                # AFC trees are pruned from the manifest only when the media
                # store is a *verified* copy of them. "The directory is not
                # empty" is not proof: an interrupted pull leaves a partial tree
                # behind, and pruning on that would delete the backup's only
                # copy of the photos and restore a fragment. When the store is
                # unverified the media rows stay in the manifest, so the restore
                # fails loudly on a missing payload instead of silently losing
                # the library's files.
                exclude_afc_media_trees=media_store_verified(media_dir)
            )
        log_info(f"Phase 1: Pruned backup: -{removed_rows} manifest rows, -{removed_files} payload files "
                 f"({time.monotonic() - started:.1f}s into the run)")
        mark_phase("1 prune + prepare")


        # Tweak files ride the protective restore on beta 6+, since AppDomain
        # sparse restores are rejected there — see the pb_via_protective note
        # in restore_files. On unencrypted backups ALL tweak files are injected
        # here (see restore_files); the sparse phase (Phase 2) then has nothing
        # left to deliver. The batch keeps Phase 1 fast for large payloads: one
        # Manifest.db transaction, one inode scan, cached donor/directory state
        # (see inject_files_into_backup).
        if backup_complete:
            batch = []
            for f in (inject_files or []):
                rel = f.restore_path.lstrip("/")
                data = f.contents
                if data is None and f.contents_path:
                    with open(f.contents_path, "rb") as fh:
                        data = fh.read()
                if isinstance(data, str):
                    data = data.encode("utf-8")
                batch.append((f.domain, rel, data,
                              _FileMode.S_IFREG | 0o644, f.owner, f.group))
            if batch:
                injected, unchanged, failed = await asyncio.to_thread(
                    inject_files_into_backup, backup_root, udid, batch,
                    manifest_password)
                log_info(f"Tweak files delivered via protective restore: "
                         f"{injected} ok, {unchanged} unchanged, {failed} failed")
                if failed:
                    raise NuggetException(
                        f"Could not prepare {failed} tweak file(s) for restore. "
                        "The device has not been modified.")

            # Last line of defence against MBErrorDomain/205: the device requests
            # every regular-file row's payload — a single missing one aborts the
            # whole Phase 3 restore.
            missing_payloads = await asyncio.to_thread(
                verify_backup_payloads, backup_root, udid, manifest_password)
            if missing_payloads:
                raise NuggetException(
                    f"{len(missing_payloads)} manifest rows lack payloads "
                    f"(e.g. {missing_payloads[:5]}). Restore stopped before modifying the device.")
            mark_phase("1 inject tweaks")

        progress_callback(100)

        sparse_failure = await _deliver_sparse_phase(
            back, lockdown_client, udid, progress_callback, options)
        if stage_callback:
            stage_callback("restore", "media_pending" if media_dir else "")
        progress_callback(0)
        # === Phase 3: reconnect + restore protective backup (60-90%) ===
        merge_fallback_done = False
        mark_phase("2 sparse restore")
        if merge_phases:
            # Merged mode: the sparse restore never rebooted, so there is no
            # security recovery to wait for — the device is still connected and
            # its data was never wiped. Reuse the SAME session for the
            # protective restore, exactly like the PosterBoard-only path does
            # (that path proves a protective restore over a live, un-wiped
            # device works — to iOS it looks like a normal full restore).
            log_info("Phase 3: merged mode — device never rebooted, restoring "
                     "protective backup on the live session (no security "
                     "recovery, no data wipe)")
            lc = lockdown_client
            await asyncio.sleep(1)
        else:
            log_info("Phase 3: Waiting for device to reconnect after security recovery")
            lc = await _wait_for_device(udid, progress_callback,
                                        prompt_choice=prompt_choice)
        try:
            # brief settle time after reconnect — _restore_protective_backup
            # retries handle any remaining startup delay
            await asyncio.sleep(1)
            if skip_protective_backup or not backup_complete:
                log_warn("Phase 3: skipping protective restore (user opted out "
                         "of data protection)")
            else:
                # A bootlooping daemon keeps the device stuck on the passcode
                # screen — mobilebackup2 refuses to start with
                # PasswordRequiredError before a single retry. Offer the same
                # Abort/Resume choice as the reconnect wait instead of crashing.
                while True:
                    try:
                        await _restore_protective_backup(
                            lc, backup_root, udid, False,
                            progress_callback,
                            backup_password=backup_password,
                            skip_apps=not any(
                                getattr(f, "domain", "").startswith("AppDomain")
                                for f in (inject_files or [])))
                        break
                    except PasswordRequiredError:
                        if prompt_choice is None:
                            raise
                        log_info("Phase 3: protective restore blocked — device "
                                 "locked (bootloop signature); asking user to "
                                 "resume or abort")
                        title = QCoreApplication.tr("Device locked — cannot restore backup")
                        text = QCoreApplication.tr(
                            "The phone is asking for a passcode to start the "
                            "restore service. This usually means the applied "
                            "tweaks are preventing it from booting properly.\n\n"
                            "  \u2022 Resume \u2014 unlock the device, then keep "
                            "trying to restore the backup.\n"
                            "  \u2022 Abort \u2014 stop now. The protective backup "
                            "is kept on this computer for a later restore.")
                        try:
                            decision = prompt_choice(title, text)
                        except Exception:
                            raise
                        if decision != "resume":
                            raise
                        log_info("Phase 3: user chose resume — reconnecting and retrying")
                        try:
                            await lc.close()
                        except Exception:
                            pass
                        lc = await _wait_for_device(udid, progress_callback,
                                                    prompt_choice=prompt_choice)
                    except NuggetException as e:
                        # `_on_failure` wraps the last retry error into a
                        # NuggetException (raise ... from e), so a merged-mode
                        # self-reboot surfaces here wrapped instead of as a raw
                        # ConnectionTerminatedError/OSError. Unwrap and route
                        # connection drops through the classic reconnect path
                        # too; anything else (device-locked, invalid service,
                        # real protocol errors) keeps its friendly message.
                        cause = e.__cause__ or e.__context__ or e
                        if not is_connection_error(cause):
                            raise
                        if not merge_phases or merge_fallback_done:
                            raise
                        log_warn(f"Phase 3: merged-mode session dropped "
                                 f"({type(cause).__name__}: {cause}) — falling "
                                 "back to the classic reconnect path")
                        try:
                            await lc.close()
                        except Exception:
                            pass
                        lc = await _wait_for_device(udid, progress_callback,
                                                    prompt_choice=prompt_choice)
                        merge_fallback_done = True
                    except (ConnectionTerminatedError, ConnectionError,
                            OSError, asyncio.TimeoutError) as e:
                        # Merged mode reuses the Phase 2 session; if the device
                        # rebooted itself anyway (a tweak that demands the
                        # security-recovery wipe), that client is now dead —
                        # fall back to the classic reconnect + fresh session
                        # instead of failing the whole apply.
                        if not merge_phases or merge_fallback_done:
                            raise
                        log_warn(f"Phase 3: merged-mode session dropped "
                                 f"({type(e).__name__}: {e}) — falling back to "
                                 "the classic reconnect path")
                        try:
                            await lc.close()
                        except Exception:
                            pass
                        lc = await _wait_for_device(udid, progress_callback,
                                                    prompt_choice=prompt_choice)
                        merge_fallback_done = True
                log_info("Phase 3: Protective backup restored successfully")
                mark_phase("3 protective restore")

            # === Phase 4: reboot before the media restore + setup skip (90-95%) ===
            # Swapped with the old skip-setup phase: on a merged (never-rebooted)
            # live session the device still carries its cloud configuration and
            # SetCloudConfiguration only raises AlreadyPresent. Rebooting first
            # gives the media restore and skip_all_setup27 a freshly-booted
            # device (Phase 5) and the final reboot (Phase 6) lets the skip take
            # effect on the next boot.
            if stage_callback:
                stage_callback("restore", "restart" if reboot and skip_setup else "waiting")
            pre_skip_reboot = reboot and skip_setup
            if pre_skip_reboot:
                progress_callback("Rebooting device...")
                log_info("Phase 4: Rebooting device before skipping setup")
                await reboot_device(reboot=True, lockdown_client=lc)
                log_info("Phase 4: Reboot command sent")


            # === Phase 5: reconnect (if rebooted) + push media + skip setup (95-98%) ===
            if pre_skip_reboot:
                try:
                    await lc.close()
                except Exception:
                    pass
                lc = await _wait_for_device(udid, progress_callback,
                                            prompt_choice=prompt_choice)

            # Photos/videos pulled over AFC are pushed back now that the device
            # is back up and accepting AFC connections (after the Phase 4
            # reboot, on the freshly-reconnected session; or straight on the
            # live session when no reboot happened). This is the ONLY channel
            # that carries them on an AFC apply — the protective restore ships
            # only the non-media scope (media rows were not in its backup).
            if media_dir:
                # The media store is the ONLY copy of the photos at this point
                # (the device was just wiped), so anything short of a complete
                # push is a data-loss event and must abort loudly rather than
                # let the apply report success.
                if not os.path.isdir(media_dir) or not os.listdir(media_dir):
                    raise NuggetException(
                        f"AFC media store is missing or empty ({media_dir}) — "
                        f"the photos were not backed up before the wipe. "
                        f"Aborting instead of pretending the restore finished.")
                if stage_callback:
                    stage_callback("media", "photos")
                progress_callback(0)
                log_info(f"Phase 5: Pushing photos/videos back over AFC "
                         f"({describe_media_store(media_dir)})")
                pushed = await restore_media_via_afc(
                    lc, media_dir,
                    progress_callback=progress_callback,
                    prompt_choice=prompt_choice,
                    unlock_prompt=(
                        QCoreApplication.tr("Device stayed locked"),
                        QCoreApplication.tr(
                            "The device has not been unlocked long enough to "
                            "push your photos and videos back after the "
                            "reboot.\n\n"
                            "Unlock it, enter your passcode, and keep it "
                            "connected via USB, then choose:\n\n"
                            "  \u2022 Resume \u2014 keep waiting for the device "
                            "to be unlocked and push your photos.\n"
                            "  \u2022 Abort \u2014 stop now. Your photos are "
                            "still safe in the backup cache on this computer, "
                            "but they will not be on the device yet.")
                    ))
                if pushed.get("failed"):
                    raise NuggetException(
                        f"AFC media restore failed for {len(pushed['failed'])} "
                        f"file(s) (e.g. {pushed['failed'][:3]}) — the photos on "
                        f"the device are incomplete")
                log_info(f"Phase 5: Media restored over AFC "
                         f"({pushed.get('files', 0)} pushed, "
                         f"{pushed.get('skipped', 0)} already on the device)")
                mark_phase("5 media push")

            if skip_setup:
                if stage_callback:
                    stage_callback("setup", "settings")
                progress_callback("Skipping setup panes...")
                log_info("Phase 5: Skipping setup panes via MobileConfigService")
                try:
                    await skip_all_setup27(lc, udid, supervised=supervised,
                                           organization_name=organization_name,
                                           progress_callback=progress_callback)
                except CloudConfigurationAlreadyPresentError:
                    log_info("Phase 5: device already has a cloud configuration "
                             "— setup already handled, nothing to skip")
                else:
                    log_info("Phase 5: Setup panes skipped successfully")
                progress_callback(98)

            # === Phase 6: final reboot so the skipped setup takes effect (98-100%) ===
            if reboot:
                if stage_callback:
                    stage_callback("setup", "restart")
                progress_callback("Rebooting device...")
                log_info("Phase 6: Rebooting device")
                await reboot_device(reboot=True, lockdown_client=lc)
                log_info("Phase 6: Reboot command sent")
            progress_callback(100)
        finally:
            # ``lc`` owns the current session — it is replaced on every
            # reconnect above, so close that client, not the stale Phase-0 one.
            # A failure here must be logged: silently swallowing it leaks the
            # lockdown session and hides the bug (that is exactly how the old
            # ``session.client.close()`` NameError stayed invisible).
            try:
                await lc.close()
            except Exception as close_err:
                log_warn(f"Could not close the restore session: {close_err}")
        if sparse_failure is not None:
            raise NuggetException(
                "The protective data restore completed, but the device rejected "
                "the tweak transfer without progress. Tweaks were not applied.") from sparse_failure
    except BaseException as e:
        if backup_complete:
            kept = backup_root if not using_cache else prepared_backup_root.root
            log_error(f"Restore failed; protective backup kept at: {kept}")
            try:
                e.add_note(f"Protective backup kept at: {kept}")
            except AttributeError:
                pass
            raise
        log_error(f"Restore failed before backup completed: {e}")
        if protective_dir:
            shutil.rmtree(protective_dir, ignore_errors=True)
        raise
    finally:
        # The restore view is disposable — the master it was built from is
        # untouched, so dropping the view never loses data.
        if view_dir:
            try:
                await asyncio.to_thread(
                    discard_restore_view, view_dir, udid)
            except Exception as view_err:
                log_warn(f"Could not remove the cache restore view: {view_err}")

    if skip_protective_backup:
        # user opted out of data protection — nothing was kept
        if protective_dir:
            shutil.rmtree(protective_dir, ignore_errors=True)
    else:
        # A cache master is kept (it is the next apply's incremental store and
        # the recovery source); a live backup is kept at its own directory.
        kept_at = protective_dir or (prepared_backup_root.root
                                     if prepared_backup_root else backup_root)
        log_info(f"Protective backup kept at: {kept_at}")
    log_info(f"iOS 27 restore completed successfully in {time.monotonic() - started:.1f}s")
    progress_callback(100)


def _is_ios27_scaffolding(file) -> bool:
    """True for the incidental iOS 27 scaffolding files (thin wrapper around
    ``lastapply.is_ios27_scaffolding`` that accepts both the raw
    ``FileToRestore`` objects and the ``backup.Directory``/``backup.ConcreteFile``
    rows built by ``concat_regular_file`` — the latter carry the path in
    ``path`` instead of ``restore_path``)."""
    path = getattr(file, "path", None)
    if path is None:
        path = getattr(file, "restore_path", "")
    return is_ios27_scaffolding(file.domain, path.lstrip("/"))


# files is a list of FileToRestore objects
async def restore_files(files: list[FileToRestore], reboot: bool = False, lockdown_client: LockdownClient = None, progress_callback = lambda x: None, backup_password: str = "", prepared_backup_root: PreparedBackup = None, skip_setup: bool = True, skip_protective_backup: bool = False, include_keychain: bool = False, prompt_choice=None, afc_media: bool = False, merge_phases: bool = True, supervised: bool = False, organization_name: str = "", stage_callback=None):
    # create the files to be backed up
    files_list = [
    ]
    apps_list = []
    active_bundle_ids = []
    apps = None
    sorted_files = sorted(merge_duplicates(files), key=lambda x: (x.domain or "", x.restore_path or ""), reverse=False)
    # add the file paths
    last_domain = ""
    last_path = ""
    exploit_only = True
    # iOS 27 dev beta 6 / public beta 4 reject sparse restores that contain
    # AppDomain-* domains: the device drops the connection at 0% and no
    # security recovery triggers. With a prepared protective backup we can
    # deliver tweak files through Phase 3's native restore instead — injected
    # into the backup Phase 3 restores (a cache master goes through a
    # disposable restore view that is pruned and tweak-injected, so the master
    # itself is never touched; a fresh Phase-0 live run is pruned in place). ALL
    # tweak files ride that channel when the backup is unencrypted (plaintext
    # injection;
    # encrypted backups fill their rows with wrapped per-file keys, so a
    # locally injected payload would fail the Phase 3 decrypt with
    # MBErrorDomain/205 — those keep the sparse delivery).
    # GOLDENNUGGET_PB_SPARSE=1 forces the old sparse delivery.
    pb_via_protective = (prepared_backup_root is not None
                         and not skip_protective_backup
                         and os.environ.get("GOLDENNUGGET_NO_PROTECTIVE_BACKUP") != "1"
                         and os.environ.get("GOLDENNUGGET_PB_SPARSE") != "1")
    inject_all = False
    if pb_via_protective:
        udid = getattr(lockdown_client, "udid", "")
        dev_dir = Path(prepared_backup_root.root) / udid
        if not dev_dir.is_dir() and (Path(prepared_backup_root.root) / "Manifest.db").exists():
            dev_dir = Path(prepared_backup_root.root)
        inject_all = not _is_encrypted_backup(dev_dir)
        if not inject_all:
            log_warn("Prepared backup is encrypted — injecting tweaks is "
                     "impossible (MBErrorDomain/205); falling back to sparse "
                     "restore delivery")
    from src.tweaks.siri_ai import require_protective_delivery
    if any(isinstance(file.contents, PreferenceKeyReset) for file in sorted_files) and not inject_all:
        raise NuggetException('Targeted preference reset requires an unencrypted protective backup. No reset was started.')
    require_protective_delivery(sorted_files, inject_all)
    inject_files = []
    for file in sorted_files:
        if file.domain == "" or file.domain == "z":
            # Files without a real domain were only ever delivered via the
            # pre-iOS-18 path-traversal exploit, which iOS 26.2+ sparse
            # restore cannot use — they are dropped.
            continue
        else:
            if pb_via_protective and inject_all:
                inject_files.append(file)
                continue
            last_domain, last_path = concat_regular_file(file, files_list, last_domain, last_path)
            exploit_only = False
            # add the app bundle to the list
            if last_domain.startswith("AppDomain"):
                bundle_id = last_domain.removeprefix("AppDomain-")
                if bundle_id in active_bundle_ids:
                    continue
                # All AppDomain-* bundles MUST be registered in
                # Manifest.plist's Applications dictionary, otherwise
                # the device-side restore daemon will reject the domain
                # with MBErrorDomain/205 ("Unknown domain name").
                # This includes system apps like com.apple.PosterBoard.
                if apps is None:
                    # A failed lookup here would abort the whole sparse
                    # restore later — retry hard, then fail loudly.
                    from src.utils.async_retry import async_retry

                    async def _get_apps():
                        async with InstallationProxyService(lockdown=lockdown_client) as ips:
                            return await ips.get_apps(application_type="Any", calculate_sizes=False)

                    try:
                        apps = await async_retry(
                            _get_apps, 3,
                            exp_cap=8,
                            on_retry=lambda attempt, total, e, delay: log_warn(
                                f"InstallationProxy query failed (attempt {attempt}/3): {e}"
                            ),
                        )
                    except Exception as e:
                        raise NuggetException(
                            "Could not query installed apps from the device "
                            f"(needed to register {bundle_id} for the restore). "
                            f"Last error: {e}") from e
                try:
                    app_info = apps[bundle_id]
                except KeyError:
                    log_warn(f"AppDomain bundle '{bundle_id}' not found in installation proxy; "
                             "the device may reject this restore")
                    active_bundle_ids.append(bundle_id)
                else:
                    active_bundle_ids.append(bundle_id)
                    # NOTE: `Path` must be the APP BUNDLE path (/Applications/X.app),
                    # exactly like in real iTunes backups — pointing it at the data
                    # container makes the restore agent abort at 0%.
                    apps_list.append(backup.AppBundle(
                        identifier=bundle_id,
                        path=app_info.get("Path") or app_info["Container"],
                        version=str(app_info.get("CFBundleVersion", "1.0")),
                        container_content_class="Data/Application"
                    ))
                    log_info(f"Registered AppDomain bundle for restore: {bundle_id} "
                             f"({apps_list[-1].path})")

    # Phase 2 (sparse / partial restore) is skipped when it has nothing new to
    # deliver and the protective restore (Phase 3) already carries what this
    # apply adds:
    #   - Inject-all applies: every real payload is diverted to inject_files
    #     (delivered by the protective restore), so the sparse pass only has the
    #     incidental iOS 27 scaffolding files — which are dropped with it.
    #     (The HomeDomain .GlobalPreferences copy is empty on such an apply and
    #     skip-setup is re-applied natively by Phase 5.)
    #   - Unchanged tweaks + added wallpapers: the sparse payload is identical to
    #     the last successfully applied one (lastapply.json) and only wallpapers
    #     are new — Phase 3 delivers them, the device already carries the tweaks.
    # Directory rows (path scaffolding for the concrete files) never count as
    # payload.
    skip_sparse = False
    if inject_files:
        if not any(
                isinstance(f, backup.ConcreteFile) and not _is_ios27_scaffolding(f)
                for f in files_list):
            skip_sparse = True
        else:
            udid = getattr(lockdown_client, "udid", None)
            if udid:
                prev = load_lastapply(udid)
                if prev and prev == sparse_signature(files):
                    skip_sparse = True
    if skip_sparse:
        log_info("Phase 2 sparse/partial pass skipped: no new tweak payload "
                 "rides the sparse restore on this apply — the protective "
                 "restore (Phase 3) delivers the tweak/wallpaper files "
                 "directly")
        files_list = []

    # create the backup
    values = getattr(lockdown_client, "all_values", {}) or {}
    device_manifest = {k: values[k] for k in (
        "ProductVersion", "ProductType", "DeviceClass", "BuildVersion",
        "UniqueDeviceID", "SerialNumber", "DeviceName") if k in values}

    from src.devicemanagement.constants import Version as _V
    device_ver = _V(lockdown_client.product_version)
    # iOS 26.x mobilebackup2 expects the legacy MBDB backup format
    # (Status.plist 2.4 / Manifest.mbdb / Manifest.plist 9.1/20.0); iOS 27+
    # uses the modern sqlite format (3.3 / Manifest.db / 10.0/24.0). Gated on
    # the device version so the iOS 27 rework never changes what iOS 26 reads.
    manifest_ios27 = device_ver >= _V("27.0")
    back = backup.Backup(files=files_list, apps=apps_list,
                         device_manifest=device_manifest,
                         manifest_ios27=manifest_ios27)

    if merge_phases and os.environ.get("GOLDENNUGGET_NO_MERGE_PHASES") == "1":
        # Kill switch: fall back to the classic three-phase flow with the
        # security-recovery reboot between tweaks and the data restore.
        merge_phases = False
        log_warn("GOLDENNUGGET_NO_MERGE_PHASES=1 — restoring the classic "
                 "reboot-then-wipe flow (sparse restore reboots the device "
                 "and iOS fully wipes before the protective restore)")

    if os.environ.get("GOLDENNUGGET_NO_PROTECTIVE_BACKUP") == "1":
        # Kill switch: force the iOS 26-style apply — a single-pass sparse
        # restore with NO three-phase restore at all (no Phase 0/1/3 backup,
        # no security-recovery wipe). Handy for fast iteration (e.g. daemon
        # bootloop testing). skip_setup then rides on reconnect + cloud config
        # instead of the legacy crash_on_purpose trick.
        skip_protective_backup = True
        log_warn("GOLDENNUGGET_NO_PROTECTIVE_BACKUP=1 — forcing iOS 26-style "
                 "single-pass sparse restore (no protective backups, no "
                 "security-recovery wipe)")

    if device_ver >= _V("27.0"):
        if skip_protective_backup:
            if stage_callback:
                stage_callback("backup", "skipped")
                stage_callback("restore", "skipped")
                stage_callback("media", "skipped")
                stage_callback("tweaks", "")
            # Raw sparse mode (GOLDENNUGGET_NO_PROTECTIVE_BACKUP=1): the iOS 27
            # three-phase restore would trigger Apple's security-recovery erasure
            # and restore an empty backup — exactly what bootloop-testing must
            # avoid. Run the plain sparse pass instead; the reboot to apply the
            # tweaks happens inside perform_restore (reboot=True).
            try:
                await perform_restore(backup=back, reboot=reboot,
                                      lockdown_client=lockdown_client,
                                      progress_callback=progress_callback)
            except (ConnectionTerminatedError, ssl.SSLEOFError,
                    ConnectionAbortedError, ConnectionResetError):
                log_info("Device disconnected during restore — expected on reboot")
            if reboot and skip_setup:
                if stage_callback:
                    stage_callback("setup", "waiting")
                lc = await _wait_for_device(lockdown_client.udid,
                                            progress_callback,
                                            prompt_choice=prompt_choice)
                log_info("Raw sparse: skipping setup panes via MobileConfigService")
                if stage_callback:
                    stage_callback("setup", "settings")
                await skip_all_setup27(lc, lockdown_client.udid,
                                       supervised=supervised,
                                       organization_name=organization_name,
                                       progress_callback=progress_callback)
                progress_callback(95)
        else:
            # iOS 27 era: three-phase protective backup + restore
            await _restore_ios27(back, reboot, lockdown_client, progress_callback,
                                 backup_password=backup_password,
                                 prepared_backup_root=prepared_backup_root,
                                 inject_files=inject_files,
                                 skip_setup=skip_setup,
                                 skip_protective_backup=skip_protective_backup,
                                 include_keychain=include_keychain,
                                 prompt_choice=prompt_choice,
                                 afc_media=afc_media,
                                 merge_phases=merge_phases,
                                 supervised=supervised,
                                 organization_name=organization_name,
                                 stage_callback=stage_callback)
    else:
        # iOS 26.x: plain sparse restore — no security recovery wipe,
        # no protective backup needed.  When all files use the path-traversal
        # exploit (no AppDomain files), crash the restore to skip setup — the
        # device reboots without showing the setup assistant.
        if exploit_only and skip_setup:
            files_list.append(backup.ConcreteFile(
                "", "SysContainerDomain-../../../../../../../.." + "/crash_on_purpose",
                contents=b""))
            back = backup.Backup(files=files_list, apps=apps_list,
                                 device_manifest=device_manifest,
                                 manifest_ios27=False)
        try:
            await perform_restore(backup=back, reboot=reboot,
                                  lockdown_client=lockdown_client,
                                  progress_callback=progress_callback)
        except (ConnectionTerminatedError, ssl.SSLEOFError,
                ConnectionAbortedError, ConnectionResetError):
            log_info("Device disconnected during restore — expected on reboot")
