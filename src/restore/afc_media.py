"""
AFC-backed parallel media backup/restore channel.

On iOS 27 the three-phase restore wipes the device (security recovery), so
photos/videos must survive on this computer between Phase 2 and Phase 3. They
are normally carried inside the protective mobilebackup2 backup, which is
slow (the whole Media tree uploads through DeviceLink). When
``use_afc_media`` is on, the *bulk* photo trees (``DCIM``,
``PhotoStreamsData`` — the actual photo/video files) are instead pulled over
plain ``com.apple.afc`` in *parallel* with the mobilebackup2 backup of
everything else, and pushed back over the same channel during Phase 5
(after the Phase 4 reboot and reconnect, on the freshly-booted device).

The scope is deliberately narrow: only the top-level Media trees in
``AFC_MEDIA_TREES`` go over AFC. ``PhotoData`` — the photo library database
(CPLAssets) plus its protected metadata (``PhotoData/UBF`` is NOT listable
over the media AFC service; it fails with AFC error 10 / PERM_DENIED on
iOS 27) — stays inside the mobilebackup2 backup, which reads it natively.
The mobilebackup2 upload filter and the manifest prune both exclude the same
``AFC_MEDIA_TREES`` so the split stays coherent end-to-end (no wasted
uploads, no manifest rows pointing at payloads that were never written).

Design rules:
- Progress is reported as strings only (never numbers): the mobilebackup2
  numbers drive the progress bar, and a concurrent numeric feed would corrupt
  it.
- Pull-side failures are fatal by default: the media dir is the ONLY copy of
  the user's photos after Phase 2 wipes the device, so a silent drop is data
  loss. Callers that need best-effort pass ``on_error="warn"``.
- Symlinks are skipped (never copied as files): following them could escape
  the Media tree and would duplicate content.
"""

import asyncio
import json
import os
import posixpath
import time
from contextlib import asynccontextmanager

from pymobiledevice3.services.afc import MAXIMUM_READ_SIZE, AfcService

from src.exceptions.device_errors import (
    is_connection_error,
    is_device_lock_required_error,
)
from src.exceptions.nugget_exception import NuggetException
from src.utils.log_util import log_info, log_warn, log_error

AFC_MEDIA_DIRNAME = "afc_media"

# Marker written next to a media store once a pull has completed end to end.
# The store is the ONLY copy of the user's photos between the wipe and Phase 5,
# so "the folder is not empty" is NOT proof that it is intact: a cancelled or
# interrupted pull leaves a partial tree behind that looks perfectly usable.
# Everything that decides whether the media trees may be dropped from the backup
# must consult this marker instead.
MEDIA_STATE_FILE = ".media_state.json"

# Top-level Media trees moved to the AFC channel. Everything else under
# /var/mobile/Media (notably PhotoData/) stays in the mobilebackup2 backup:
# some of its subdirectories (PhotoData/UBF on iOS 27) are unlistable over the
# media AFC service, and restoring the photo library DB via mobilebackup2
# keeps the library consistent with the DCIM originals we push back over AFC.
AFC_MEDIA_TREES = frozenset({"DCIM", "PhotoStreamsData"})


def afc_media_enabled(pref_enabled: bool = True) -> bool:
    """Whether the AFC media channel is active for a given apply.

    The environment ``GOLDENNUGGET_NO_AFC_MEDIA=1`` kill switch always wins —
    it force-disables the channel the way ``GOLDENNUGGET_NO_BACKUP_CACHE``
    force-disables the backup cache.
    """
    return pref_enabled and os.environ.get("GOLDENNUGGET_NO_AFC_MEDIA") != "1"


def afc_media_dir_for(backup_root: str) -> str:
    """Media directory paired with a protective backup run.

    ``backup_root`` is ``<run dir>/device_backup``; the media tree lives next
    to it inside the same run dir (``<run dir>/afc_media``) so that run-level
    cleanup (prune_protective_backups, failure rmtree) reclaims both together.
    """
    return os.path.join(os.path.dirname(os.path.abspath(backup_root)),
                        AFC_MEDIA_DIRNAME)


def _is_afc_link(stat: dict) -> bool:
    return bool(stat) and stat.get("st_ifmt") == "S_IFLNK"


# ---- media store verification -------------------------------------------
#
# A media store is only trustworthy when a pull ran to completion. That fact is
# recorded in a marker file next to the tree; anything that would exclude the
# media trees from the backup (and therefore delete the only copy of the user's
# photos) has to require this marker.

def media_store_state(media_root: str) -> dict | None:
    """Parsed completion marker for ``media_root``, or ``None`` if there is none."""
    if not media_root:
        return None
    try:
        with open(os.path.join(media_root, MEDIA_STATE_FILE),
                  encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


def _media_store_actual(media_root: str) -> tuple[int, int]:
    """(files, bytes) actually present in the store.

    A local directory walk only — no file is read — so it stays cheap even for a
    60 GB store, while still catching a store that lost files after it was
    marked (manual deletion, a cleanup tool, a failed disk).
    """
    files = 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(media_root):
        for name in filenames:
            if name == MEDIA_STATE_FILE or name.endswith(".part"):
                continue
            files += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return files, total


def media_store_verified(media_root: str) -> bool:
    """True when the store still holds everything the last pull put in it.

    Two conditions have to hold: the last pull finished without a single
    failure (``complete`` in the marker), and the tree on disk is still at least
    as large as that pull recorded. The second check means a store that was
    emptied or trimmed *after* a good pull is rejected too. Extra local files
    are fine — files deleted on the device are never removed locally, so the
    store is allowed to be larger than the device.

    This is the gate that decides whether the media trees may be left out of the
    backup. An unverified store (first run, interrupted pull, cancelled parallel
    task, missing marker) must keep the media rows in the manifest.
    """
    state = media_store_state(media_root)
    if not state or not state.get("complete"):
        return False
    if not os.path.isdir(media_root):
        return False
    marked_files = int(state.get("files") or 0)
    marked_bytes = int(state.get("bytes") or 0)
    # a store that verified zero files is indistinguishable from one that was
    # never populated, so it must not pass as a media carrier
    if marked_files <= 0:
        return False
    actual_files, actual_bytes = _media_store_actual(media_root)
    if actual_files < marked_files or actual_bytes < marked_bytes * 0.999:
        log_warn(f"AFC media: {media_root} holds {actual_files} files / "
                 f"{actual_bytes / (1024 * 1024):.1f} MB but the last verified "
                 f"pull recorded {marked_files} files / "
                 f"{marked_bytes / (1024 * 1024):.1f} MB — treating it as "
                 f"UNVERIFIED so the backup keeps its own copy of the media")
        return False
    return True


def describe_media_store(media_root: str) -> str:
    """One-line summary of a media store, for logs and error messages."""
    state = media_store_state(media_root) or {}
    files = int(state.get("files") or 0)
    mib = int(state.get("bytes") or 0) / (1024 * 1024)
    return (f"{media_root}: {files} files / {mib:.1f} MB "
            f"({'verified' if media_store_verified(media_root) else 'NOT verified'})")


def _write_media_state(media_root: str, files: int, bytes_: int,
                       skipped: int) -> None:
    """Record a completed pull so later applies may treat the store as intact."""
    state = {
        "complete": True,
        "files": int(files),
        "bytes": int(bytes_),
        "skipped": int(skipped),
        "ts": time.time(),
    }
    tmp = os.path.join(media_root, MEDIA_STATE_FILE + ".tmp")
    try:
        os.makedirs(media_root, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, os.path.join(media_root, MEDIA_STATE_FILE))
    except OSError as e:
        log_warn(f"AFC media: could not write the media store marker "
                 f"({e}) — the store stays unverified")


def _invalidate_media_state(media_root: str, reason: str) -> None:
    """Drop the completion marker after a failed/cancelled pull.

    A partially written media tree must never be presented as a complete copy of
    the user's photos, or the next apply would delete the backup's copy of the
    media trees and push only the fragment that is left.
    """
    if not media_root:
        return
    had_state = media_store_state(media_root) is not None
    try:
        os.remove(os.path.join(media_root, MEDIA_STATE_FILE))
    except OSError:
        pass
    if had_state:
        log_warn(f"AFC media: media store marker dropped ({reason}) — "
                 f"{media_root} is now UNVERIFIED and must not be used as the "
                 f"only copy of the photos")


def _progress_str(action: str, done_files: int, total_files: int,
                  done_bytes: int, total_bytes: int) -> str:
    if total_bytes > 0:
        pct = 100.0 * done_bytes / total_bytes
        mb = done_bytes / (1024 * 1024)
        return (f"{action}... {pct:.0f}% ({done_files}/{total_files} files, "
                f"{mb:.1f} MB)")
    return f"{action}... {done_files}/{total_files} files"


async def _pull_one(afc, src: str, dst: str, stat) -> int:
    """Stream one regular file from the device to ``dst``, returning bytes.

    The write is verified against the size the device reported and lands through
    a temp file, so a short read can never leave a truncated file behind that a
    later size-based ``diff`` would accept as already pulled. That failure mode
    is not cosmetic: a truncated MP4/MOV still *is* recognised by Photos but
    will not play (its ``moov`` atom is at the tail), and this is the branch
    every file over ``MAXIMUM_READ_SIZE`` — i.e. essentially every video —
    takes, while the small-file branch below reads exactly ``st_size``.
    """
    size = int(stat.get("st_size", 0))
    if size <= MAXIMUM_READ_SIZE:
        data = await afc.get_file_contents(src)
        # ``size`` is 0 when the device did not report one; only a real
        # advertised size can be violated
        if size and len(data) != size:
            raise NuggetException(
                f"AFC media: short read on {src} — device reported {size} bytes, "
                f"got {len(data)}")
        _atomic_write(dst, data)
        return len(data)

    tmp = dst + ".part"
    handle = await afc.fopen(src)
    try:
        written = 0
        with open(tmp, "wb") as f:
            while written < size:
                to_read = min(MAXIMUM_READ_SIZE, size - written)
                chunk = await afc.fread(handle, to_read)
                if not chunk:
                    # premature EOF: the file is incomplete, not finished
                    raise NuggetException(
                        f"AFC media: connection ended mid-file on {src} — "
                        f"got {written} of {size} bytes")
                f.write(chunk)
                written += len(chunk)
    except BaseException:
        # never leave a partial file the diff would treat as complete
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    finally:
        await afc.fclose(handle)
    os.replace(tmp, dst)
    return written


def _atomic_write(dst: str, data: bytes) -> None:
    """Write ``data`` to ``dst`` through a temp file + rename."""
    tmp = dst + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


async def _list_afc_tree(afc, dirpath: str, entries: list,
                         on_error: str) -> None:
    """Recursively collect the regular files under ``dirpath`` into ``entries``.

    Mirrors the on-device layout: each item is (src, rel, stat) where ``rel``
    is the path relative to the AFC root (``DCIM/100APPLE/IMG_0001.JPG``).
    Directory entries that cannot be listed are skipped with a warning (their
    contents are out of scope for AFC — e.g. protected PhotoData subdirs),
    never fatal.
    """
    try:
        children = await afc.listdir(dirpath)
    except Exception as e:
        msg = f"AFC media: cannot list {dirpath or '/'}: {e}"
        if on_error == "warn":
            log_warn(msg + " — skipping this directory")
            return
        raise NuggetException(msg) from e
    for name in sorted(children):
        if name in (".", ".."):
            continue
        src = posixpath.join(dirpath, name)
        rel = src.lstrip("/")
        try:
            st = await afc.stat(src)
            if _is_afc_link(st):
                log_info(f"AFC media: skipping symlink {src}")
                continue
            if st.get("st_ifmt") == "S_IFDIR":
                await _list_afc_tree(afc, src, entries, on_error)
            else:
                entries.append((src, rel, st))
        except Exception as e:
            msg = f"AFC media: could not stat {src}: {e}"
            if on_error != "warn":
                raise NuggetException(msg) from e
            log_warn(msg + " — skipping this entry")


async def backup_media_via_afc(lockdown_client, media_root: str,
                               progress_callback=None,
                               on_error: str = "raise",
                               diff: bool = False) -> dict:
    """Pull the bulk photo trees over AFC into ``media_root``.

    Walks only the top-level Media trees named by ``AFC_MEDIA_TREES`` (DCIM,
    PhotoStreamsData) under the AFC root and mirrors every regular file into
    ``media_root`` preserving the on-device layout. Returns a tally dict
    ``{"files": int, "bytes": int, "skipped": int}``.

    With ``diff=True`` a local file that already exists at the same size is
    left untouched, so only new/changed objects are pulled — that is the
    cache refresh path, where ``media_root`` is the persistent per-device
    media store from a previous run (the first pull is still a full one).
    Extra local files (deleted on the device) are never removed: the media
    dir is the ONLY copy of the user's photos after a wipe, so deleting
    anything here would be data loss.
    """
    root = os.path.abspath(media_root)
    os.makedirs(root, exist_ok=True)
    tally = {"files": 0, "bytes": 0, "skipped": 0}

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    if os.path.isdir(root) and os.listdir(root):
        log_info(f"AFC media pull: {root} already populated — "
                 f"{'diff refresh (pull only new/changed)' if diff else 'full refresh'}")
    # Remember the previous claim so an unreadable enumeration can be told apart
    # from an emptied library (see the restore below).
    prev_state = media_store_state(root) or {}
    prev_files = int(prev_state.get("files") or 0)
    # Drop the old claim BEFORE touching anything: this pull is about to rewrite
    # files in the store, so the previous run's "verified" is already stale. It
    # also covers the case the except-branch cannot — a hard process kill in the
    # middle of the pull — which would otherwise leave the marker claiming a
    # complete copy of a half-rewritten store.
    _invalidate_media_state(root, "a new pull is starting")
    try:
        result = await _backup_media_tree(afc_lockdown_client=lockdown_client, root=root,
                                          diff=diff, on_error=on_error,
                                          progress_callback=_log)
        # A pull that enumerated nothing while the store previously held files
        # did not empty the library — the trees were simply unreadable (a locked
        # device lists only ``.MISC/Incoming`` under DCIM). Nothing was rewritten,
        # so the store still is the copy the last good pull verified and that
        # claim must survive: clobbering it with files=0 would discard a complete
        # media store and abort the apply in ``_require_media_copy`` for nothing.
        if (result.get("files", 0) == 0 and prev_files > 0
                and not result.get("failed")):
            _write_media_state(root, prev_files,
                               int(prev_state.get("bytes") or 0),
                               int(prev_state.get("skipped") or 0))
            log_warn(f"AFC media: {root} enumerated 0 files while the store holds "
                     f"{prev_files} — the media trees were unreadable (locked "
                     f"device?), previous verification kept: "
                     f"{describe_media_store(root)}")
        return result
    except BaseException as e:
        # Covers per-file failures AND cancellation (the parallel task is
        # cancelled when the mobilebackup2 backup fails). Either way the store is
        # now a fragment: make sure no later apply can mistake it for a
        # complete copy of the user's photos.
        _invalidate_media_state(root, f"pull did not finish ({type(e).__name__})")
        raise


async def _backup_media_tree(afc_lockdown_client, root: str, diff: bool,
                             on_error: str, progress_callback) -> dict:
    tally = {"files": 0, "bytes": 0, "skipped": 0}
    async with AfcService(afc_lockdown_client) as afc:
        entries: list = []
        root_children = await afc.listdir("/")
        for name in sorted(root_children):
            if name in (".", ".."):
                continue
            if name not in AFC_MEDIA_TREES:
                log_info(f"AFC media: leaving {name} to the mobilebackup2 "
                         "backup (out of AFC scope)")
                continue
            await _list_afc_tree(afc, f"/{name}", entries, on_error)

        total_files = len(entries)
        total_bytes = sum(int(st.get("st_size", 0)) for _src, _rel, st in entries)

        done_files = 0
        done_bytes = 0
        failed: list[str] = []
        skipped = 0
        for src, rel, st in entries:
            dst = os.path.join(root, *rel.split("/"))
            if diff:
                try:
                    if (os.path.getsize(dst) == int(st.get("st_size", 0))):
                        # Same size on both ends — already local, skip the pull.
                        skipped += 1
                        done_files += 1
                        continue
                except OSError:
                    pass  # file missing locally -> pull it
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            n = 0
            try:
                n = await _pull_one(afc, src, dst, st)
            except Exception as e:
                msg = f"AFC media: failed to pull {src}: {e}"
                if on_error == "warn":
                    log_warn(msg)
                    failed.append(src)
                else:
                    raise NuggetException(msg) from e
            done_files += 1
            done_bytes += n
            if done_files % 25 == 0 or done_files == total_files:
                progress_callback(_progress_str(
                    "Backing up photos/videos over AFC", done_files,
                    total_files, done_bytes, total_bytes))

        log_info(f"AFC media pull complete: {total_files} files, "
                 f"{total_bytes / (1024 * 1024):.1f} MB"
                 + (f" ({skipped} already present, skipped)" if skipped else ""))
        tally["files"] = total_files
        tally["bytes"] = total_bytes
        tally["skipped"] = skipped
        if failed:
            # a store with holes in it is not a copy of the photos: leave it
            # unmarked so the apply refuses to treat it as the media carrier
            log_warn(f"AFC media pull: {len(failed)} files skipped on error "
                     f"(e.g. {failed[:3]}) — media store left UNVERIFIED")
            tally["failed"] = failed
        else:
            _write_media_state(root, total_files, total_bytes, skipped)
    return tally


async def _push_one(afc, src: str, remote_rel: str) -> int:
    """Push one local file onto the device, returning bytes written."""
    size = os.path.getsize(src)
    if size <= MAXIMUM_READ_SIZE:
        with open(src, "rb") as f:
            await afc.set_file_contents(remote_rel, f.read())
        return size
    handle = await afc.fopen(remote_rel, "w")
    try:
        with open(src, "rb") as f:
            while True:
                chunk = f.read(MAXIMUM_READ_SIZE)
                if not chunk:
                    break
                await afc.fwrite(handle, chunk)
        # a streaming write is the one that can end up half-written on the
        # device, so confirm what actually landed before reporting success
        st = await afc.stat(remote_rel)
        got = st.get("st_size") if st else None
        if got != size:
            raise NuggetException(
                f"AFC media: {remote_rel} was written short on the device "
                f"({got} of {size} bytes)")
        return size
    finally:
        await afc.fclose(handle)


# Phase 5 runs right after a reboot, and lockdownd answers StartService with
# PasswordProtected until the device is unlocked. A *paired* lockdown session
# is established happily while the device still sits at the lock screen, so
# _wait_for_device() returning is NOT evidence that services will start -- the
# first AFC open routinely fails on a device that is not actually broken. The
# media store is the only copy of the user's photos at that point, so give them
# a real window to unlock instead of failing the apply on a locked screen.
_AFC_OPEN_TIMEOUT = 5 * 60
_AFC_OPEN_INITIAL_DELAY = 2.0
_AFC_OPEN_MAX_DELAY = 15.0
# Pure safety net so the wait loop is finite by construction, no matter what
# the clock does. The real budget is the timeout above (~30 attempts at the
# capped delay), so this never fires in practice -- it only stops a runaway
# loop on a hostile/broken timing condition.
_AFC_OPEN_MAX_ATTEMPTS = 400


@asynccontextmanager
async def open_afc_for_media(lockdown_client, progress_callback=None,
                             prompt_choice=None, unlock_prompt=None,
                             timeout: float = _AFC_OPEN_TIMEOUT):
    """Open the AFC service, waiting out a locked device.

    Only the *connect* is retried. Once the service is up the caller's body
    runs exactly once, so a failure halfway through a push is never silently
    re-run (that would risk re-writing files the device already has).

    ``prompt_choice``/``unlock_prompt`` are the Abort/Resume escape hatch used
    once the wait budget is spent, mirroring ``_wait_for_device``. They are
    passed in (title, text) rather than built here so this module stays
    importable without Qt -- the offline AFC tests run on a bare interpreter.
    """
    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    while True:
        start = time.monotonic()
        deadline = start + timeout
        delay = _AFC_OPEN_INITIAL_DELAY
        last_error = None
        announced = False
        attempt = 0
        while True:
            attempt += 1
            afc = AfcService(lockdown_client)
            try:
                # __aenter__ is connect() and nothing else, and a failed
                # connect leaves the service object with no open channel
                # (upstream resets its in-flight state so the next attempt
                # starts clean). The lockdown session itself stays valid, which
                # is why no reconnect is needed here.
                service = await afc.__aenter__()
            except Exception as e:
                locked = is_device_lock_required_error(e)
                if not (locked or is_connection_error(e)):
                    # a real rejection (bad service name, protocol error) --
                    # retrying would just burn the wait
                    raise
                last_error = e
                if locked and not announced:
                    announced = True
                    log_warn("AFC media restore: the device is locked - waiting "
                             "for it to be unlocked")
                    _log("Waiting for the device to be unlocked to restore your photos...")
                elif not locked:
                    log_warn(f"AFC media restore: {type(e).__name__}: {e} - retrying")
                if (time.monotonic() + delay > deadline
                        or attempt >= _AFC_OPEN_MAX_ATTEMPTS):
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, _AFC_OPEN_MAX_DELAY)
                continue
            try:
                yield service
            finally:
                await afc.__aexit__(None, None, None)
            return

        # wait budget spent: offer Abort/Resume instead of killing the restore
        err = NuggetException(
            f"Could not open the AFC service for the photo restore within "
            f"{int(timeout // 60)} min - the device stayed locked or "
            f"unreachable. Last error: {last_error}"
        )
        if prompt_choice is None or unlock_prompt is None:
            raise err from last_error
        title, text = unlock_prompt
        log_info("AFC media wait timed out; asking the user whether to resume or abort")
        try:
            decision = prompt_choice(title, text)
        except Exception as e:
            log_warn(f"AFC media prompt failed ({e}) - aborting")
            raise err from last_error
        if decision != "resume":
            raise err from last_error
        log_info("User chose to resume - restarting the AFC media wait cycle")


async def restore_media_via_afc(lockdown_client, media_root: str,
                                progress_callback=None,
                                on_error: str = "raise",
                                prompt_choice=None,
                                unlock_prompt=None) -> dict:
    """Push a previously pulled Media tree back to the device over AFC.

    Mirrors ``media_root`` (which holds the AFC root layout: DCIM/, PhotoData/,
    ...) back onto the device after the iOS 27 security-recovery wipe. Returns
    a tally dict ``{"files": int, "bytes": int}``.

    The device has just rebooted, so the AFC open waits out a locked screen
    first (see ``open_afc_for_media``) -- pass ``prompt_choice`` to get the
    Abort/Resume prompt if that wait runs out.
    """
    root = os.path.abspath(media_root)
    if not os.path.isdir(root):
        log_info(f"AFC media restore: nothing to restore (no {root})")
        return {"files": 0, "bytes": 0}

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    entries = []
    total_bytes = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            # never push our own bookkeeping: the marker and any leftover
            # .part are host-side files, not photos
            if name == MEDIA_STATE_FILE or name.endswith(".part"):
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, root).replace(os.sep, "/")
            entries.append((src, rel))
            total_bytes += os.path.getsize(src)

    async with open_afc_for_media(lockdown_client, progress_callback=_log,
                                  prompt_choice=prompt_choice,
                                  unlock_prompt=unlock_prompt) as afc:
        done_files = 0
        done_bytes = 0
        failed: list[str] = []
        made_dirs: set = set()
        for src, rel in entries:
            remote = f"/{rel}"
            rdir = posixpath.dirname(remote)
            n = 0
            try:
                # only MAKE_DIR once per directory: a redundant MAKE_DIR can come
                # back non-SUCCESS on an existing directory and would abort the
                # restore on the second file of every folder
                if rdir and rdir != "/" and rdir not in made_dirs:
                    made_dirs.add(rdir)
                    if not await afc.exists(rdir):
                        await afc.makedirs(rdir)
                n = await _push_one(afc, src, remote)
            except Exception as e:
                msg = f"AFC media: failed to restore {remote}: {e}"
                if on_error == "warn":
                    log_warn(msg)
                    failed.append(remote)
                else:
                    raise NuggetException(msg) from e
            done_files += 1
            done_bytes += n
            if done_files % 25 == 0 or done_files == len(entries):
                _log(_progress_str("Restoring photos/videos over AFC",
                                   done_files, len(entries), done_bytes, total_bytes))

        log_info(f"AFC media restore complete: {done_files} files, "
                 f"{done_bytes / (1024 * 1024):.1f} MB")
        if failed:
            log_warn(f"AFC media restore: {len(failed)} files failed "
                     f"(e.g. {failed[:3]})")
            tally = {"files": done_files, "bytes": done_bytes, "failed": failed}
            return tally
    return {"files": done_files, "bytes": done_bytes}