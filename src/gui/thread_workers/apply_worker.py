from PySide6.QtCore import QCoreApplication, Signal, QThread, QSettings
from PySide6.QtWidgets import QMessageBox
from typing import Optional
# Module-level on purpose: the async workers below (``RestoreCacheThread.
# _restore``, ``ResetPairingThread``) awaited/used ``asyncio`` while only
# importing it inside another method's scope, which is a NameError.
import asyncio
import os
import queue
import traceback
import threading

# Qt-free shared type (kept here for backwards-compatible import paths forwards
# to the same class the backend uses).
from src.utils.alerts import ApplyAlertMessage
from src.exceptions.nugget_exception import NuggetException


class _SudoState:
    """Thread-safe sudo password storage."""
    def __init__(self):
        self._lock = threading.Lock()
        self._pwd: Optional[str] = None

    def get_pwd(self) -> Optional[str]:
        with self._lock:
            pwd = self._pwd
            self._pwd = None
            return pwd

    def set_pwd(self, pwd: Optional[str]):
        with self._lock:
            self._pwd = pwd


_sudo_state = _SudoState()


def get_sudo_pwd() -> Optional[str]:
    return _sudo_state.get_pwd()


def set_sudo_pwd(pwd: Optional[str]):
    _sudo_state.set_pwd(pwd)


class ApplyThread(QThread):
    progress = Signal(str)
    alert = Signal(object)  # ApplyAlertMessage or None for sudo prompt
    finished_with_result = Signal(bool, str)  # success, error_message
    request_text = Signal(str, str, object)  # title, label, result box (main-thread prompt)
    choice_prompt = Signal(str, str, object)  # title, text, result box ("abort"/"resume", main-thread prompt)

    # Only the password prompt is guarded by a timeout. The apply/restore itself
    # is allowed to run to completion: a three-phase protective restore can
    # legitimately exceed 10 minutes waiting for the device to reboot, and
    # forcibly terminating the worker thread mid-restore (QThread.terminate)
    # would corrupt the device state.
    _PROMPT_TIMEOUT_SEC = 10 * 60

    def __init__(self, manager, settings: QSettings, reset_pages=None):
        super().__init__()
        self.manager = manager
        self.settings = settings
        self.reset_pages = reset_pages
        self.success = False
        self._error_msg: str = ""

    def prompt_password(self, title: str, label: str) -> Optional[str]:
        # Modal dialogs must be built on the main thread (macOS raises
        # NSInternalInconsistencyException otherwise), so relay the request
        # through a queued signal while this worker thread blocks on a queue.
        box = queue.Queue(maxsize=1)
        self.request_text.emit(title, label, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return None

    def prompt_user_choice(self, title: str, text: str) -> str:
        """Ask the user for a two-way decision on the main thread.

        Queued signal, same pattern as ``prompt_password``. Returns the
        decision the main-thread dialog boxed up: "abort" or "resume"
        ("abort" on timeout so a stale worker never hangs the restore
        forever).
        """
        box = queue.Queue(maxsize=1)
        self.choice_prompt.emit(title, text, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return "abort"

    def run(self):
        import logging
        from src.controllers.nugget_logger import log_context
        self._log = logging.getLogger("GoldenNugget.apply")
        mode = "reset" if self.reset_pages is not None else "apply"
        try:
            log_context(f"START {mode}",
                        name=self.manager.get_current_device_name() or "unknown",
                        model=self.manager.get_current_device_model() or "unknown",
                        ios=self.manager.get_current_device_version() or "unknown",
                        build=self.manager.get_current_device_build() or "unknown",
                        udid=self.manager.get_current_device_udid() or "unknown")
            self._do_work()
            self.success = True
            self._error_msg = ""
            log_context(f"FINISH {mode} OK")
            from src.controllers.apply_history import record_operation
            record_operation(self.manager, mode, True)
            self.finished_with_result.emit(True, "")
        except Exception as e:
            self.success = False
            self._error_msg = f"{type(e).__name__}: {e}"
            traceback_str = traceback.format_exc()
            self._log.error("%s failed: %s\n%s", mode, e, traceback_str)
            from src.controllers.apply_history import record_operation
            record_operation(self.manager, mode, False, self._error_msg)
            self.alert.emit(ApplyAlertMessage(
                f"Operation failed: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
                exc_type=type(e),
                exc_value=e,
            ))
            self.finished_with_result.emit(False, self._error_msg)

    def update_label(self, txt: str):
        if txt == 'sudo_pwd':
            self.alert.emit(None)
        else:
            self._log.info("progress: %s", txt)
            self.progress.emit(txt)

    def alert_window(self, msg: ApplyAlertMessage):
        if msg is not None:
            self._log.info("alert: %s | %s", getattr(msg, "title", ""), getattr(msg, "txt", ""))
        self.alert.emit(msg)

    def _do_work(self):
        if self.reset_pages is None:
            self.manager.apply_changes(self.update_label, self.alert_window,
                                       self.prompt_password, self.prompt_user_choice)
        else:
            self.manager.reset_tweaks(self.reset_pages, self.settings, self.update_label,
                                      self.alert_window, self.prompt_user_choice)


class RestoreCacheThread(QThread):
    """Restore the last protective backup cache (post-failure data recovery).

    Mirrors ``apply_changes``' Phase 1+3 so a protective backup that was kept
    on disk after a wedged/failed apply can be restored standalone — e.g. when
    the iPhone was not unlocked in time and Phase 3 was aborted. Runs in a
    background thread to keep the UI responsive (the restore waits for the
    device and for the user to unlock).
    """
    progress = Signal(str)
    alert = Signal(object)
    finished_with_result = Signal(bool, str)
    choice_prompt = Signal(str, str, object)  # title, text, result box ("abort"/"resume", main-thread prompt)

    # Same guard as ApplyThread: a stale worker must never block the recovery
    # forever. The media push itself is NOT force-terminated — this only bounds
    # how long the dialog waits for the user.
    _PROMPT_TIMEOUT_SEC = 10 * 60

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def prompt_user_choice(self, title: str, text: str) -> str:
        """Ask the user for a two-way decision on the main thread.

        Same queued-signal pattern as ``ApplyThread.prompt_user_choice``:
        modal dialogs must be built on the main thread, so the request is
        relayed and this worker blocks on the boxed result. Returns "abort" or
        "resume" ("abort" on timeout).
        """
        box = queue.Queue(maxsize=1)
        self.choice_prompt.emit(title, text, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return "abort"

    def update_label(self, txt: str):
        self.progress.emit(txt)

    def run(self):
        import logging
        from src.controllers.nugget_logger import log_context
        log = logging.getLogger("GoldenNugget.restore_cache")
        try:
            log_context("START restore-cache",
                        udid=self.manager.get_current_device_udid() or "unknown")
            self._do_work()
            log_context("FINISH restore-cache OK")
            self.finished_with_result.emit(True, "")
        except Exception as e:
            traceback_str = traceback.format_exc()
            log.error("restore-cache failed: %s\n%s", e, traceback_str)
            self.alert.emit(ApplyAlertMessage(
                f"Failed to restore data from backup: {e}",
                title="Restore data",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
                exc_type=type(e),
                exc_value=e,
            ))
            self.finished_with_result.emit(False, f"{type(e).__name__}: {e}")

    def _do_work(self):
        import asyncio
        asyncio.run(self._restore())

    async def _restore(self):
        import tempfile
        from pathlib import Path
        from src.restore.protective import (
            make_protective_working_copy,
            clean_backup_for_restore,
            verify_backup_payloads,
            find_latest_protective_backup,
        )
        from src.restore.restore import _restore_protective_backup
        from src.restore.afc_media import (
            afc_media_dir_for, describe_media_store, media_store_verified,
            restore_media_via_afc,
        )
        from src.devicemanagement.session import lockdown_session

        udid = self.manager.get_current_device_udid()
        if not udid:
            raise RuntimeError("No device selected.")
        self.update_label("Locating protective backup...")
        # Prefer the cache master. Fall back to a live protective backup left
        # behind by an interrupted apply — after Phase 2 wiped the device that
        # directory is the only copy of the user's data, so the recovery path
        # has to be able to reach it.
        base = self._find_cache_base(udid)
        source_root = str(base / "master") if base is not None else None
        if source_root is None:
            source_root = find_latest_protective_backup(udid)
        if source_root is None:
            raise RuntimeError(
                "No protective backup found for this device. Live backups are "
                "kept in the app data folder; cache masters live in a temp "
                "folder and are lost on reboot.")
        # Pre-flight: refuse a half-written source manifest up front instead of
        # failing mid-device-restore with an opaque MBErrorDomain/205. The
        # restore only ever prunes/injects on a temp working copy, so a corrupt
        # Manifest.db here means an earlier apply/restore left the source
        # damaged; an encrypted manifest is skipped (it is not valid sqlite
        # until decrypted with the password below).
        if not self._backup_password():
            from src.restore.protective import _validate_sqlite_db
            src_manifest = Path(source_root) / udid / "Manifest.db"
            if not src_manifest.is_file():
                src_manifest = Path(source_root) / "Manifest.db"
            if not _validate_sqlite_db(src_manifest):
                raise RuntimeError(
                    "The protective backup's Manifest.db is corrupted or "
                    "incomplete (left half-written by an interrupted restore). "
                    "Apply tweaks again to rebuild a fresh backup, or remove "
                    "the cached backup from Settings → Backup Cache.")
        self.update_label("Building working copy of the backup...")
        working_root = await asyncio.to_thread(
            make_protective_working_copy, source_root, udid)
        # A live backup taken with the AFC channel kept bulk photo trees beside
        # the run dir (never uploaded to mobilebackup2), so its manifest rows
        # for those trees must be pruned the same way or the restore fails with
        # payload-missing rows. A cache master now carries photos the same way:
        # its Persistent per-device media store lives at
        # ``<base>/media/<udid>``. Either way, only a media dir whose last pull
        # finished cleanly is treated as the AFC source — "the folder has files
        # in it" is not enough, because a partial pull would then let the prune
        # below delete the backup's own copy of the photos.
        media_dir = afc_media_dir_for(source_root)
        from src.restore.protective_cache import peek_cache_info
        cache_info = peek_cache_info(udid)
        if cache_info is not None and cache_info.get("media_afc"):
            from pathlib import Path as _Path
            try:
                base = _Path(source_root).parent.parent  # <base>/master/<udid> -> <base>
            except Exception:
                base = None
            if base is not None:
                media_dir = str(base / "media" / udid)
        media_has_content = media_store_verified(media_dir)
        removed_rows, removed_files = await asyncio.to_thread(
            clean_backup_for_restore, working_root, udid,
            include_keychain=bool(self._backup_password()),
            manifest_password=self._backup_password(),
            exclude_afc_media_trees=media_has_content)
        self.update_label(
            f"Prepared backup (-{removed_rows} pruned rows). Connecting to device...")
        missing = await asyncio.to_thread(
            verify_backup_payloads, working_root, udid,
            self._backup_password())
        if missing:
            raise RuntimeError(
                f"{len(missing)} manifest rows lack payloads; the backup is "
                f"incomplete and cannot be restored. Remove the cache and apply "
                f"again to rebuild it.")

        lc = None
        async with lockdown_session(udid) as _ld:
            lc = _ld
            # the retry loop inside _restore_protective_backup reconnects as
            # needed after the wipe-induced lock and drops
            await _restore_protective_backup(
                lc, working_root, udid, reboot=False,
                progress_callback=self._progress_cb,
                backup_password=self._backup_password(),
                skip_apps=True)
            # Photos/videos taken through the AFC channel live beside the
            # source dir: a live backup keeps them next to the device_backup
            # dir, a cache master at ``<base>/media/<udid>``. Either way the
            # media dir rides the same AFC-located store and has to be pushed
            # back over AFC after the restore.
            if media_dir:
                if not os.path.isdir(media_dir) or not os.listdir(media_dir):
                    raise NuggetException(
                        f"AFC media store is missing or empty ({media_dir}) — "
                        f"the photos were not backed up before the wipe. "
                        f"Aborting instead of pretending the restore finished.")
                # the store is the ONLY copy of the photos once the wipe is
                # done, so an incomplete push must abort the apply instead of
                # letting it report success with missing media
                self.update_label(
                    f"Restoring photos/videos over AFC ({describe_media_store(media_dir)})...")
                pushed = await restore_media_via_afc(
                    lc, media_dir, progress_callback=self._progress_cb,
                    prompt_choice=self.prompt_user_choice,
                    unlock_prompt=(
                        QCoreApplication.tr("Device stayed locked"),
                        QCoreApplication.tr(
                            "The device has not been unlocked long enough to "
                            "push your photos and videos back.\n\n"
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
        self.update_label("Data restored successfully.")

    def _progress_cb(self, value):
        if isinstance(value, str):
            self.update_label(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self.update_label(f"Restoring... {value:.1f}%")

    def _backup_password(self) -> str:
        try:
            return self.manager._get_backup_password()
        except Exception:
            return ""

    def _find_cache_base(self, udid: str):
        import tempfile
        from pathlib import Path
        from src.restore.storage import cache_base, is_custom_backup_dir
        bases = []
        try:
            bases.append(Path(tempfile.gettempdir()) / "goldennugget_protective_cache")
        except Exception:
            pass
        bases.append(cache_base())
        if is_custom_backup_dir():
            # A cache created under the previous default location may still
            # exist there; read it so it can be migrated on the next refresh.
            from PySide6.QtCore import QStandardPaths
            try:
                bases.append(Path(QStandardPaths.writableLocation(
                    QStandardPaths.AppDataLocation)) / "GoldenNugget" / "backup_cache")
            except Exception:
                pass
        for base in bases:
            if (base / "master" / udid / "Manifest.db").is_file():
                return base
            if (base / f"{udid}.json").is_file():
                return base
        return None


class CacheUpdateThread(QThread):
    """Force a refresh of the backup cache master (pre-apply "Update Cache").

    Runs ``device_manager.refresh_backup_cache`` in a background thread so
    the pre-apply summary can freshen the cache (and its creation date) before
    the user confirms the apply. Unlike ``ApplyThread`` it never applies tweaks
    and never teleports to a restore.
    """
    progress = Signal(str)
    alert = Signal(object)  # ApplyAlertMessage
    finished_with_result = Signal(bool, str)  # success, error_message

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.success = False
        self._error_msg = ""

    def update_label(self, txt: str):
        self.progress.emit(txt)

    def run(self):
        import logging
        import asyncio
        from src.controllers.nugget_logger import log_context
        log = logging.getLogger("GoldenNugget.cache_update")
        try:
            log_context("START cache-update",
                        udid=self.manager.get_current_device_udid() or "unknown")
        except Exception:
            pass
        try:
            asyncio.run(self.manager.refresh_backup_cache(self.update_label))
            self.success = True
            self._error_msg = ""
            log.info("cache update finished OK")
        except Exception as e:
            self.success = False
            self._error_msg = f"{type(e).__name__}: {e}"
            traceback_str = traceback.format_exc()
            log.error("cache update failed: %s\n%s", e, traceback_str)
            self.alert.emit(ApplyAlertMessage(
                f"Failed to update the backup cache: {e}",
                title="Update Cache",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
                exc_type=type(e),
                exc_value=e,
            ))
        self.finished_with_result.emit(self.success, self._error_msg)


class RefreshDevicesThread(QThread):
    alert = Signal(object)

    def __init__(self, manager, settings):
        super().__init__()
        self.manager = manager
        self.settings = settings

    def alert_window(self, msg: ApplyAlertMessage):
        self.alert.emit(msg)

    def run(self):
        import logging
        log = logging.getLogger("GoldenNugget.refresh")
        try:
            self.manager.get_devices(self.settings, self.alert_window)
        except Exception as e:
            traceback_str = traceback.format_exc()
            log.error("refresh devices failed: %s\n%s", e, traceback_str)
            self.alert.emit(ApplyAlertMessage(
                f"Failed to refresh devices: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
                exc_type=type(e),
                exc_value=e,
            ))


class ResetPairingThread(QThread):
    """Ran-no-device-io pair reset (unpair + pair) on a worker thread so the
    settings page keeps painting while lockdown talks to the device."""

    done = Signal(bool, str)  # success, error message

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def run(self):
        import logging
        import asyncio
        log = logging.getLogger("GoldenNugget.pairing")
        try:
            asyncio.run(self.manager._reset_device_pairing())
        except Exception as e:
            traceback_str = traceback.format_exc()
            log.error("reset pairing failed: %s\n%s", e, traceback_str)
            self.done.emit(False, str(e))
            return
        self.done.emit(True, "")
