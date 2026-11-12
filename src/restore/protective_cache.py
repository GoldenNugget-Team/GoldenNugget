"""Persistent per-device cache of the protective backup master copy.

The master keeps the FULL Manifest.db (rows for drained payloads stay put)
so mobilebackup2 can run true incremental refreshes against it: after the
first apply, each next apply only uploads what actually changed on the
device. The master is never modified by an apply — each apply builds a
disposable *view* of it (a pruned copy of the manifest plus hardlinks to the
payloads) and restores from that, so a crashed apply cannot leave the master
half-pruned and the next refresh always diffs against a complete manifest.

The master always lives in the persistent app-data store (never the system
temp dir): it is the sole copy of user data between Phase 2 (device wipe)
and Phase 3 (restore), so it must survive reboots and crashes.
"""

import asyncio
import json
import logging
import os
import shutil
import stat as _stat
import tempfile
import time
from pathlib import Path
from typing import Optional

from pymobiledevice3.lockdown import LockdownClient

from src.exceptions.nugget_exception import NuggetException
from src.restore.inject import _is_encrypted_backup, _validate_sqlite_db
from src.restore.storage import cache_base as _cache_base
from src.utils.file_lock import FileLock

_logger = logging.getLogger("GoldenNugget.cache")

CACHE_FILTER_REVISION = 7


def _non_empty_file(path: Path) -> bool:
    """True when ``path`` is a regular file with at least one byte.

    One ``stat`` instead of the ``is_file()`` + ``stat()`` pair this replaces.
    """
    try:
        result = path.stat()
    except OSError:
        return False
    return _stat.S_ISREG(result.st_mode) and result.st_size > 0


def _usable_manifest(master: Path) -> bool:
    """True when a master's Manifest.db is an intact sqlite OR encrypted one.

    An encrypted backup's ``Manifest.db`` is AES-bytes, so it can never be
    validated as SQLite; ``_is_encrypted_backup`` is the only way to tell a
    healthy encrypted manifest from a truncated one. It raises when the
    plist itself is unreadable (a damaged or half-written master), and that
    must mean "not usable" rather than an exception escaping ``locate`` —
    a broken cache is supposed to fall back to a full rebuild, not abort the
    apply.
    """
    if _validate_sqlite_db(master / "Manifest.db"):
        return True
    try:
        return _is_encrypted_backup(master)
    except Exception as error:
        _logger.warning(
            f"Protective backup cache master at {master} has an unreadable "
            f"manifest, rebuilding instead of reusing it: {error}")
        return False


def peek_cache_info(udid: str) -> Optional[dict]:
    """Read the cache info JSON for a UDID without a device session.

    Best-effort: returns the ``created`` timestamp and age (if any)
    regardless of encryption/version matching — the pre-apply summary uses it
    only to display "cache from <date>"; the real matching happens in
    ``ProtectiveBackupCache.locate`` at apply time.
    """
    try:
        temp_base = Path(tempfile.gettempdir()) / "goldennugget_protective_cache"
        persist_base = _cache_base()
    except Exception:
        return None
    now = int(time.time())
    for base in (temp_base, persist_base):
        try:
            with open(base / f"{udid}.json", "r", encoding="utf-8") as f:
                info = json.load(f)
        except Exception:
            continue
        if info.get("udid") != udid:
            continue
        created_ts = int(info.get("created_ts", now))
        return {"created": info.get("created", ""),
                "created_ts": created_ts,
                "age_secs": max(0, now - created_ts),
                "media_afc": bool(info.get("media_afc", False))}
    return None

# The master always lives in the persistent app-data store — a temp-based
# master is the sole copy of user data between Phase 2 (wipe) and Phase 3
# (restore), and a reboot would destroy it.
CACHE_PERSIST_MIN_GB = float(os.environ.get("GOLDENNUGGET_CACHE_PERSIST_MIN_GB", "1"))
# Legacy compatibility constant; apply/reset no longer uses an age-based bypass.
CACHE_REFRESH_SECS = int(os.environ.get("GOLDENNUGGET_CACHE_REFRESH_SECS", "1800"))
# The AFC photo store has its own lifetime: photos change far less often
# than the rest of the protective scope, and re-pulling the whole media tree
# on every apply is the second-largest cost after the Phase 5 push. A store
# younger than this is reused as-is; past it the media tree is re-pulled
# (diffing against what is already local, so only new photos transfer).
CACHE_MEDIA_REFRESH_SECS = int(
    os.environ.get("GOLDENNUGGET_CACHE_MEDIA_REFRESH_SECS", "21600"))


class ProtectiveBackupCache:
    """Persistent per-device cache of the protective backup master copy.

    The master keeps the FULL Manifest.db (rows for drained payloads stay put)
    so mobilebackup2 can run true incremental refreshes against it: after the
    first apply, each next apply only uploads what actually changed on the
    device. The master is never modified by an apply — each apply builds a
    disposable view of it and restores from that, so the master stays a
    pristine full-manifest mirror whatever happens during the restore.
    """

    def __init__(self, udid: str, product_version: str, encrypted: bool = False):
        self.udid = udid
        self.product_version = product_version
        self.encrypted = encrypted
        self._temp_base = Path(tempfile.gettempdir()) / "goldennugget_protective_cache"
        self._persist_base = _cache_base()
        # Always use the persistent store: the master is the sole copy of the
        # user's data between Phase 2 (device wipe) and Phase 3 (restore).  A
        # reboot would destroy a temp-based master, turning a recoverable
        # failure into permanent data loss.  The old temp-based location is
        # still searched by ``locate()`` for migration of existing caches.
        self.base = self._persist_base
        self.master_root = self.base / "master"
        self.device_dir = self.master_root / self.udid
        self.info_path = self.base / f"{self.udid}.json"
        # Persistent per-device media store: the bulk photo trees (DCIM,
        # PhotoStreamsData) pulled over AFC live here so a diff refresh can
        # compare against what is already local and pull only the new/changed
        # objects. It sits OUTSIDE ``master_root`` so working copies and the
        # manifest prune never touch it.
        self.media_dir = self.base / "media" / self.udid
        # Per-apply restore views live here. Deliberately on the SAME
        # filesystem as the master so the view's payload hardlinks stay links
        # instead of degrading into full copies of every payload.
        self.view_root = self.base / "view"


    def locate(self) -> Optional[dict]:
        """Find an existing master across both bases; point homes at it.

        Returns dict(base, info, age_secs) or None when no usable master.
        """
        now = int(time.time())
        for base in (self._temp_base, self._persist_base):
            info_path = base / f"{self.udid}.json"
            try:
                with open(info_path, "r", encoding="utf-8") as f:
                    info = json.load(f)
            except Exception:
                continue
            if info.get("udid") != self.udid or info.get("product_version") != self.product_version:
                continue
            if info.get('filter_revision') != CACHE_FILTER_REVISION:
                continue
            if bool(info.get("encrypted", False)) != self.encrypted:
                continue
            master = base / "master" / self.udid
            required = ("Manifest.db", "Manifest.plist", "Status.plist")
            # Non-empty, exactly like ``_has_incremental_backup_metadata``:
            # a full run drops Manifest.plist to a 0-byte placeholder before
            # the device re-sends it, so an interrupted rebuild must not look
            # like a usable master. One stat per file (the old check did
            # is_file() and then stat()).
            if not all(_non_empty_file(master / n) for n in required):
                continue
            # An ENCRYPTED backup's Manifest.db is AES-encrypted, so it never
            # reads as SQLite. Requiring a readable sqlite here made an
            # encrypted master permanently unusable: locate() returned None,
            # the refresh fell back to ``full=True`` and every single apply
            # re-uploaded the whole device (255k+ files, hours of transfer)
            # instead of diffing against the master. Mirror
            # ``list_protective_backups``: either an intact sqlite manifest or
            # a recognised encrypted manifest is a usable master. (issue #81)
            if not _usable_manifest(master):
                continue
            self.base = base
            self.master_root = base / "master"
            self.device_dir = master
            self.info_path = info_path
            # The media store is the only copy of the photos between the wipe
            # and Phase 3 — it NEVER lives under the legacy temp base, even
            # when the master itself was found there.
            self.media_dir = self._persist_base / "media" / self.udid
            self.view_root = base / "view"
            created = int(info.get("created_ts", now))
            # A cache written before the media store got its own clock has no
            # ``media_ts`` — treat its media as the same age as the master, so
            # it is refreshed rather than trusted indefinitely.
            media_created = int(info.get("media_ts", created))
            return {"base": base, "info": info,
                    "age_secs": max(0, now - created),
                    "media_age_secs": max(0, now - media_created)}
        return None

    def previous_root(self) -> Path:
        """Snapshot of the last good master, kept until a restore finishes."""
        return self.base / "previous"

    def _previous_device_dir(self) -> Path:
        return self.previous_root() / self.udid

    def retain_previous_master(self) -> bool:
        """Copy the valid master aside before an in-place refresh overwrites it.

        An existing snapshot is left in place. Replacing it would delete the
        last good copy before the restore that still needs it has finished.
        Returns True when a snapshot is on disk afterwards.
        """
        if not (self.device_dir / "Manifest.db").is_file():
            return False
        dest = self._previous_device_dir()
        if (dest / "Manifest.db").is_file():
            _logger.info("Keeping the existing previous protective backup; "
                         "a restore has not finished")
            return True
        dest.parent.mkdir(parents=True, exist_ok=True)
        from src.restore.backup_store import _copy_backup_tree
        try:
            _copy_backup_tree(self.device_dir, dest)
            if self.info_path.is_file():
                shutil.copy2(self.info_path, self.previous_root() / f"{self.udid}.json")
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        _logger.info(f"Retained the previous protective backup at {dest}")
        return True

    def rollback_master_from_previous(self) -> bool:
        """Put the retained master's metadata back after a failed refresh.

        Payload files are not rewritten here. The snapshot hardlinks them, and
        a backup that truncated those same inodes would have damaged the copy
        too. Metadata is a real copy, so a failed refresh can at least restore
        the manifest the previous backup was verified with.
        """
        src = self._previous_device_dir()
        if not (src / "Manifest.db").is_file():
            return False
        self.device_dir.mkdir(parents=True, exist_ok=True)
        names = ("Manifest.db", "Manifest.plist", "Status.plist", "Info.plist",
                 "Manifest.db-wal", "Manifest.db-shm", "backup_manifest.db")
        for name in names:
            src_file = src / name
            dst_file = self.device_dir / name
            if src_file.is_file():
                shutil.copy2(src_file, dst_file)
            else:
                dst_file.unlink(missing_ok=True)
        info_src = self.previous_root() / f"{self.udid}.json"
        if info_src.is_file():
            self.base.mkdir(parents=True, exist_ok=True)
            shutil.copy2(info_src, self.info_path)
        _logger.info(f"Restored protective backup metadata from {src}")
        return True

    def _drop_marker(self) -> None:
        try:
            self.info_path.unlink(missing_ok=True)
        except OSError as error:
            _logger.warning(f"Could not invalidate the cache marker {self.info_path}: {error}")

    def _set_home(self, base: Path):
        self.base = base
        self.master_root = base / "master"
        self.device_dir = self.master_root / self.udid
        self.info_path = base / f"{self.udid}.json"
        self.media_dir = base / "media" / self.udid
        self.view_root = base / "view"

    def relocate_by_size(self):
        """Legacy no-op (kept for the placement test tool).

        The master always lives in the persistent app-data store — moving it
        to the system temp on size grounds made the sole copy of user data
        volatile: a reboot between Phase 2 (wipe) and Phase 3 (restore) lost
        it forever.  There is nothing to relocate anymore.
        """

    def has_valid_master(self) -> bool:
        return self.locate() is not None

    def build_view(self) -> str:
        """Build the per-apply restore view of the master.

        Returns the view's parent directory (the layout the restore code
        expects: ``<parent>/<udid>/Manifest.db``). The master is left
        untouched — the view is what gets pruned and tweak-injected.
        """
        from src.restore.protective import make_restore_view
        return make_restore_view(str(self.master_root), self.udid,
                                 str(self.view_root))

    def discard_view(self) -> None:
        """Remove the per-apply restore view (it is disposable)."""
        from src.restore.protective import discard_restore_view
        discard_restore_view(str(self.view_root), self.udid)

    async def refresh(self, lockdown_client: LockdownClient, progress_callback=None,
                      include_photos: bool = True, include_posterboard: bool = False,
                      include_keychain: bool = False,
                      include_afc_media: bool = False) -> str:
        """Bring the master up to the device's current state (full or incremental).

        With ``include_posterboard`` the PosterBoard container rides along, so
        after this call ``extract_posterboard_db`` yields the live on-device
        database — refreshed BEFORE extraction, never a stale copy.

        With ``include_afc_media`` the bulk photo trees go over AFC into the
        persistent per-device media store (``media_dir``), pulled as a diff
        (only new/changed objects) — the cache photo store.
        """
        from src.restore.protective import perform_protective_backup

        # Two processes refreshing one master (app + restore_cache.py, or two
        # app instances) interleave mobilebackup2 uploads into a torn
        # manifest/payload mix. Serialize the refresh itself; a second caller
        # that cannot get the lock fails loudly instead of corrupting.
        lock = FileLock(str(self.base / f".refresh-{self.udid}.lock"))
        if not await asyncio.to_thread(lock.tryLock, 10_000):
            raise NuggetException(
                "Another GoldenNugget process is refreshing the backup cache "
                "for this device. Wait for it to finish, then try again.")
        try:
            return await self._refresh_locked(
                lockdown_client, progress_callback,
                include_photos=include_photos, include_posterboard=include_posterboard,
                include_keychain=include_keychain,
                include_afc_media=include_afc_media)
        finally:
            lock.unlock()

    async def _refresh_locked(self, lockdown_client: LockdownClient, progress_callback=None,
                              include_photos: bool = True, include_posterboard: bool = False,
                              include_keychain: bool = False,
                              include_afc_media: bool = False) -> str:
        """Refresh body, runs under the per-device refresh lock."""
        from src.restore.protective import perform_protective_backup

        valid = self.has_valid_master()
        mode = "incremental" if valid else "full"
        _logger.info(f"Protective backup cache: {mode} refresh for {self.udid}")
        # The refresh writes into the master. Keep an independent copy of the
        # current good master first, and do not replace one that is still
        # waiting for its restore to finish.
        retained = self.retain_previous_master() if valid else False
        try:
            is_encrypted = await perform_protective_backup(
                lockdown_client, str(self.master_root), progress_callback,
                include_photos=include_photos, include_posterboard=include_posterboard,
                include_keychain=include_keychain,
                incremental_ok=valid,
                include_afc_media=include_afc_media,
                media_root=str(self.media_dir),
                afc_media_diff=True)
        except BaseException:
            # A refresh that dies mid-transfer leaves the master's metadata in
            # an indeterminate state: a full run has already dropped
            # Manifest.plist and reset Status.plist to "new". Put the retained
            # copy's metadata back when we have one. Otherwise drop only the
            # marker so the next refresh rebuilds instead of diffing a truncated
            # mirror. Payload files stay on disk either way.
            if retained and self.rollback_master_from_previous():
                _logger.info("Failed refresh rolled back to the retained previous backup")
            else:
                self._drop_marker()
            raise

        self.base.mkdir(parents=True, exist_ok=True)
        now = int(time.time())
        # Preserve the media timestamp when this refresh did NOT touch the
        # photo store — the media tree has its own, much longer lifetime.
        media_ts = now if include_afc_media else self._last_media_ts()
        with open(self.info_path, "w", encoding="utf-8") as f:
            json.dump({"udid": self.udid,
                       "filter_revision": CACHE_FILTER_REVISION,
                       "product_version": self.product_version,
                       "encrypted": is_encrypted,
                       "media_afc": include_afc_media,
                       "created_ts": now,
                       "media_ts": media_ts,
                       "created": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        return str(self.master_root)

    def _last_media_ts(self) -> int:
        """Timestamp of the last media pull (0 when it never happened)."""
        try:
            with open(self.info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            return int(info.get("media_ts", 0))
        except Exception:
            return 0

    def media_age_secs(self) -> int:
        """Age of the AFC photo store in seconds (0 when it never happened)."""
        ts = self._last_media_ts()
        if not ts:
            return 0
        return max(0, int(time.time()) - ts)
    async def refresh_media(self, lockdown_client: LockdownClient,
                            progress_callback=None) -> str:
        """Re-pull the AFC photo store without touching the master.

        The photo store is the safety net for the device's media, so it has
        its own freshness window. When the master is still fresh but the photo
        store has aged out, this pulls the photos (as a diff — only new or
        changed objects transfer) instead of forcing a full master refresh
        that would re-read the whole protective scope as well.
        """
        from src.restore.afc_media import backup_media_via_afc

        self.media_dir.mkdir(parents=True, exist_ok=True)
        await backup_media_via_afc(lockdown_client, str(self.media_dir),
                                    progress_callback=progress_callback,
                                    diff=True)
        now = int(time.time())
        # Update only the media timestamp — the rest of the record (udid,
        # product_version, encryption) must survive, or the cache would no
        # longer be locatable and the next refresh would start from scratch.
        info = {}
        try:
            with open(self.info_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                info = loaded
        except Exception:
            info = {}
        info.setdefault("udid", self.udid)
        info.setdefault("product_version", self.product_version)
        info.setdefault("encrypted", self.encrypted)
        info.setdefault("media_afc", True)
        info["media_ts"] = now
        info.setdefault("created_ts", now)
        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.info_path, "w", encoding="utf-8") as f:
            json.dump(info, f)
        return str(self.media_dir)


def discard_previous_master(master_root: str) -> None:
    """Drop the pre-refresh snapshot once the restore that replaced it has finished."""
    if not master_root:
        return
    previous = Path(master_root).parent / "previous"
    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
        _logger.info(f"Removed the retained previous backup after the restore finished ({previous})")

