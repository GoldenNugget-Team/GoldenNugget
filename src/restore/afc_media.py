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

# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "pymobiledevice3.services.afc",
)

import asyncio
import os
import posixpath
import sys
import tempfile
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from pymobiledevice3.exceptions import AfcException, AfcFileNotFoundError
from pymobiledevice3.services.afc import MAXIMUM_READ_SIZE, AfcError, AfcService

from src.controllers.archive_safety import safe_member
from src.devicemanagement.progress_status import OperationStatus
from src.devicemanagement.session import lockdown_session
from src.exceptions.device_errors import (
    is_connection_error,
    is_device_lock_required_error,
)
from src.exceptions.nugget_exception import NuggetException
from src.utils.async_disk import disk_call as _disk_io
from src.utils.log_util import log_info, log_warn

from .afc_transport import BackupTransferResult, MediaEntry, service_concurrency
from .media_store import (
    AFC_MEDIA_DIRNAME,
    AFC_MEDIA_TREES,
    MEDIA_STATE_FILE,
    _invalidate_media_state,
    _local_media_path,
    _media_inventory,
    _write_media_state,
    afc_media_dir_for,
    describe_media_store,
    media_store_state,
    media_store_verified,
    recovery_media_dir,
    verified_media_state,
)


def afc_media_enabled(pref_enabled: bool = True) -> bool:
    """Whether the AFC media channel is active for a given apply.

    The environment ``GOLDENNUGGET_NO_AFC_MEDIA=1`` kill switch always wins —
    it force-disables the channel the way ``GOLDENNUGGET_NO_BACKUP_CACHE``
    force-disables the backup cache.
    """
    return pref_enabled and os.environ.get("GOLDENNUGGET_NO_AFC_MEDIA") != "1"


def _is_afc_link(stat: dict) -> bool:
    return bool(stat) and stat.get("st_ifmt") == "S_IFLNK"


# ---- media store verification -------------------------------------------
#
# A media store is only trustworthy when a pull ran to completion. That fact is
# recorded in a marker file next to the tree; anything that would exclude the
# media trees from the backup (and therefore delete the only copy of the user's
# photos) has to require this marker.


def _progress_str(action: str, done_files: int, total_files: int,
                  done_bytes: int, total_bytes: int) -> str:
    if total_bytes > 0:
        pct = 100.0 * done_bytes / total_bytes
        mb = done_bytes / (1024 * 1024)
        return (f"{action}... {pct:.0f}% ({done_files}/{total_files} files, "
                f"{mb:.1f} MB)")
    return f"{action}... {done_files}/{total_files} files"


@asynccontextmanager
async def _afc_file_handle(afc, path: str, mode: str = "r"):
    """Close handles on cancellation without replacing a transfer failure."""
    handle = await afc.fopen(path, mode)
    try:
        yield handle
    except BaseException:
        try:
            await afc.fclose(handle)
        except Exception as error:
            log_warn(f"AFC media: could not close {path}: {error}")
        raise
    else:
        # A failed close after a successful write is itself a transfer failure.
        await afc.fclose(handle)


@asynccontextmanager
async def _media_service(client):
    """Clean up even a partially opened AFC service; preserve body failures."""
    afc = AfcService(client)
    try:
        service = await afc.__aenter__()
        yield service
    finally:
        try:
            await afc.__aexit__(*sys.exc_info())
        except Exception as error:
            log_warn(f"AFC media: could not close service: {error}")


def _afc_mtime(stat: dict) -> str | None:
    value = stat.get("st_mtime")
    return str(value) if value is not None else None


@asynccontextmanager
async def _local_file(factory, *args, temporary=False, **kwargs):
    opening = asyncio.create_task(asyncio.to_thread(factory, *args, **kwargs))
    try:
        stream = await asyncio.shield(opening)
    except BaseException:
        await asyncio.gather(opening, return_exceptions=True)
        if not opening.cancelled() and opening.exception() is None:
            stream = opening.result()
            try:
                await _disk_io(stream.close)
            except Exception as error:
                log_warn(f"AFC media: could not close cancelled local open: {error}")
            if temporary:
                try:
                    await _disk_io(os.remove, stream.name)
                except OSError as error:
                    log_warn(f"AFC media: could not remove cancelled local open: {error}")
        raise
    failed = False
    try:
        yield stream
    except BaseException:
        failed = True
        raise
    finally:
        try:
            await _disk_io(stream.close)
        except Exception as error:
            if not failed:
                raise
            log_warn(f"AFC media: could not close local file: {error}")


def _afc_concurrency(service):
    return service_concurrency(service)


async def _run_workers(items, callback, count):
    iterator = iter(items)
    async def worker():
        for item in iterator:
            await callback(item)
    tasks = [asyncio.create_task(worker()) for _ in range(min(count, len(items)))]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _pull_one(afc, src: str, dst: str, stat) -> int:
    """Stream an exact, stable file through a unique temporary file + rename."""
    size = int(stat["st_size"])
    if size < 0:
        raise NuggetException(f"AFC media: invalid size for {src}: {size}")
    tmp = None
    try:
        async with _local_file(tempfile.NamedTemporaryFile, temporary=True,
                dir=os.path.dirname(dst), prefix=".afc-", suffix=".part",
                delete=False) as output:
            tmp = output.name
            async with _afc_file_handle(afc, src) as handle:
                written = 0
                while written < size:
                    to_read = min(MAXIMUM_READ_SIZE, size - written)
                    chunk = await afc.fread(handle, to_read)
                    if not chunk or len(chunk) > to_read:
                        raise NuggetException(
                            f"AFC media: incomplete read on {src} — "
                            f"got {written} of {size} bytes")
                    await _disk_io(output.write, chunk)
                    written += len(chunk)
        current = await afc.stat(src)
        if (current.get("st_ifmt") != "S_IFREG" or int(current["st_size"]) != size
                or _afc_mtime(current) != _afc_mtime(stat)):
            raise NuggetException(f"AFC media: {src} changed during backup; retry the backup")
        await _disk_io(os.replace, tmp, dst)
        return written
    finally:
        if tmp is not None:
            try:
                await _disk_io(os.remove, tmp)
            except FileNotFoundError:
                pass
            except OSError as error:
                log_warn(f"AFC media: could not remove temporary file {tmp}: {error}")


async def _list_afc_tree(afc, dirpath: str, entries: list,
                         on_error: str, failed: list[str]) -> None:
    """Recursively collect the regular files under ``dirpath`` into ``entries``.

    Mirrors the on-device layout: each item is (src, rel, stat) where ``rel``
    is the path relative to the AFC root (``DCIM/100APPLE/IMG_0001.JPG``).
    A warned enumeration failure still makes the store incomplete: unknown
    directory contents cannot be excluded safely from the native backup.
    """
    try:
        children = await afc.listdir(dirpath)
    except Exception as e:
        msg = f"AFC media: cannot list {dirpath or '/'}: {e}"
        if on_error == "warn":
            log_warn(msg + " — skipping this directory")
            failed.append(dirpath)
            return
        raise NuggetException(msg) from e
    names = [name for name in sorted(children) if name not in (".", "..")]
    stats = {}
    async def inspect(name):
        if not safe_member(name) or '/' in name:
            raise NuggetException(f"AFC media: unsafe directory entry {name!r}")
        try:
            stats[name] = await afc.stat(posixpath.join(dirpath, name))
        except Exception as error:
            stats[name] = error
    await _run_workers(names, inspect, _afc_concurrency(afc))
    for name in names:
        src = posixpath.join(dirpath, name)
        rel = src.lstrip("/")
        try:
            st = stats[name]
            if isinstance(st, Exception):
                raise st
            if _is_afc_link(st):
                log_info(f"AFC media: skipping symlink {src}")
                continue
            if st.get("st_ifmt") == "S_IFDIR":
                await _list_afc_tree(afc, src, entries, on_error, failed)
            elif st.get("st_ifmt") == "S_IFREG":
                if int(st["st_size"]) < 0:
                    raise ValueError("negative file size")
                entries.append(MediaEntry(rel, int(st["st_size"]), _afc_mtime(st)))
            else:
                raise ValueError(f"unsupported file type: {st.get('st_ifmt')}")
        except Exception as e:
            msg = f"AFC media: could not stat {src}: {e}"
            if on_error != "warn":
                raise NuggetException(msg) from e
            log_warn(msg + " — skipping this entry")
            failed.append(src)


async def backup_media_via_afc(lockdown_client, media_root: str,
                               progress_callback=None,
                               on_error: str = "raise",
                               diff: bool = False) -> dict:
    """Pull the bulk photo trees over AFC into ``media_root``.

    Walks only the top-level Media trees named by ``AFC_MEDIA_TREES`` (DCIM,
    PhotoStreamsData) under the AFC root and mirrors every regular file into
    ``media_root`` preserving the on-device layout. Returns a tally dict
    ``{"files": int, "bytes": int, "skipped": int}``.

    With ``diff=True`` a previously verified local file with the same size
    and device modification time is left untouched — that is the
    cache refresh path, where ``media_root`` is the persistent per-device
    media store from a previous run (the first pull is still a full one).
    Extra local files (deleted on the device) are never removed: the media
    dir is the ONLY copy of the user's photos after a wipe, so deleting
    anything here would be data loss.
    """
    root = os.path.abspath(media_root)
    os.makedirs(root, exist_ok=True)

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    if os.path.isdir(root) and os.listdir(root):
        log_info(f"AFC media pull: {root} already populated — "
                 f"{'diff refresh (pull only new/changed)' if diff else 'full refresh'}")
    # Drop the old claim BEFORE touching anything: this pull is about to rewrite
    # files in the store, so the previous run's "verified" is already stale. It
    # also covers the case the except-branch cannot — a hard process kill in the
    # middle of the pull — which would otherwise leave the marker claiming a
    # complete copy of a half-rewritten store.
    previous = await _disk_io(verified_media_state, root) if diff else None
    _invalidate_media_state(root, "a new pull is starting")
    try:
        result = await _backup_media_tree(afc_lockdown_client=lockdown_client, root=root,
                                          diff=diff, on_error=on_error,
                                          progress_callback=_log, previous=previous)
        return result
    except BaseException as e:
        # Covers per-file failures AND cancellation (the parallel task is
        # cancelled when the mobilebackup2 backup fails). Either way the store is
        # now a fragment: make sure no later apply can mistake it for a
        # complete copy of the user's photos.
        try:
            _invalidate_media_state(root, f"pull did not finish ({type(e).__name__})")
        except OSError as cleanup_error:
            log_warn(f"AFC media: could not remove media marker: {cleanup_error}")
        raise


async def _backup_media_tree(afc_lockdown_client, root: str, diff: bool,
                             on_error: str, progress_callback, previous=None) -> BackupTransferResult:
    tally = {"files": 0, "bytes": 0, "skipped": 0}
    async with _media_service(afc_lockdown_client) as afc:
        entries: list = []
        failed: list[str] = []
        root_children = await afc.listdir("/")
        for name in sorted(root_children):
            if name in (".", ".."):
                continue
            if name not in AFC_MEDIA_TREES:
                log_info(f"AFC media: leaving {name} to the mobilebackup2 "
                         "backup (out of AFC scope)")
                continue
            st = await afc.stat(f"/{name}")
            if _is_afc_link(st):
                log_info(f"AFC media: skipping symlink /{name}")
                continue
            if st.get("st_ifmt") != "S_IFDIR":
                raise NuggetException(f"AFC media: /{name} is not a directory")
            await _list_afc_tree(afc, f"/{name}", entries, on_error, failed)

        total_files = len(entries)
        total_bytes = sum(entry.size for entry in entries)

        done_files = 0
        done_bytes = 0
        skipped = 0
        previous_entries = (previous or {}).get("entries", {})
        previous_mtimes = (previous or {}).get("mtimes", {})
        if not isinstance(previous_mtimes, dict):
            previous_mtimes = {}
        async def pull(entry):
            nonlocal skipped, done_files, done_bytes
            rel, src = entry.relative, entry.source
            st = {"st_size": entry.size, "st_mtime": entry.mtime}
            dst = str(await _disk_io(_local_media_path, root, rel))
            mtime = _afc_mtime(st)
            if (diff and mtime is not None
                    and previous_entries.get(rel) == int(st["st_size"])
                    and previous_mtimes.get(rel) == mtime):
                try:
                    if (os.path.getsize(dst) == int(st.get("st_size", 0))):
                        skipped += 1
                        done_files += 1
                        done_bytes += int(st["st_size"])
                        if done_files % 25 == 0 or done_files == total_files:
                            progress_callback(_progress_str(
                                "Backing up photos/videos over AFC", done_files,
                                total_files, done_bytes, total_bytes))
                        return
                except OSError:
                    pass  # file missing locally -> pull it
            await _disk_io(os.makedirs, os.path.dirname(dst), exist_ok=True)
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

        await _run_workers(entries, pull, _afc_concurrency(afc))

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
            await _disk_io(_write_media_state, root, total_files, total_bytes, skipped,
                               {entry.relative: entry.size for entry in entries},
                               {entry.relative: entry.mtime for entry in entries
                                if entry.mtime is not None})
    return tally


async def _device_media_inventory(afc) -> dict:
    """Map the media trees currently on the DEVICE to their sizes.

    The mirror image of :func:`_media_inventory`, but read back from the
    device over AFC. Used to decide which files still have to be pushed:
    a file the device already holds at the same size needs no transfer.

    Symlinks are skipped (they are never pushed), and a directory that
    cannot be listed is skipped as well — the caller then pushes the files
    it could not confirm, which is the safe direction (never skip a file
    that might be missing).
    """
    inventory = {}
    entries: list = []
    failed: list = []
    for name in sorted(AFC_MEDIA_TREES):
        try:
            await _list_afc_tree(afc, f"/{name}", entries, "warn", failed)
        except Exception as e:  # noqa: BLE001 - a tree we cannot read is not fatal
            log_warn(f"AFC media: could not list /{name} on the device: {e} "
                     f"— files below it will be re-pushed")
    for entry in entries:
        inventory[entry.relative] = entry.size
    return inventory


async def _push_one(afc, src: str, remote_rel: str) -> int:
    """Stream and verify every write, including small and empty files."""
    async with _local_file(open, src, "rb") as source:
        size = os.fstat(source.fileno()).st_size
        written = 0
        async with _afc_file_handle(afc, remote_rel, "w") as handle:
            while True:
                chunk = await _disk_io(source.read, MAXIMUM_READ_SIZE)
                if not chunk:
                    break
                await afc.fwrite(handle, chunk)
                written += len(chunk)
        if written != size or os.fstat(source.fileno()).st_size != size:
            raise NuggetException(f"AFC media: {src} changed during restoration")
    # Verify after FILE_CLOSE: the final size may only become visible then.
    st = await afc.stat(remote_rel)
    got = st.get("st_size") if st else None
    if not st or st.get("st_ifmt") != "S_IFREG" or got != size:
        raise NuggetException(
            f"AFC media: {remote_rel} was written short on the device "
            f"({got} of {size} bytes)")
    return size


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
                             timeout: float = _AFC_OPEN_TIMEOUT,
                             refresh_client: bool = False):
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

    reconnect = refresh_client
    while True:
        start = time.monotonic()
        deadline = start + timeout
        delay = _AFC_OPEN_INITIAL_DELAY
        last_error = None
        announced = False
        attempt = 0
        while True:
            attempt += 1
            stack = AsyncExitStack()
            try:
                client = lockdown_client
                if reconnect:
                    client = await stack.enter_async_context(lockdown_session(
                        serial=lockdown_client.identifier, connection_type="USB",
                        autopair=False,
                        usbmux_address=getattr(lockdown_client, "usbmux_address", None)))
                service = await stack.enter_async_context(_media_service(client))
            except BaseException as e:
                await stack.aclose()
                if not isinstance(e, Exception):
                    raise
                locked = is_device_lock_required_error(e)
                if not (locked or is_connection_error(e)):
                    # a real rejection (bad service name, protocol error) --
                    # retrying would just burn the wait
                    raise
                last_error = e
                reconnect = reconnect or is_connection_error(e)
                if locked and not announced:
                    announced = True
                    log_warn("AFC media restore: the device is locked - waiting "
                             "for it to be unlocked")
                    _log(OperationStatus("Your iPhone is locked. Unlock it and enter its passcode to continue restoring your photos and videos.", "authentication"))
                elif not locked:
                    log_warn(f"AFC media restore: {type(e).__name__}: {e} - retrying")
                if (time.monotonic() + delay > deadline
                        or attempt >= _AFC_OPEN_MAX_ATTEMPTS):
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, _AFC_OPEN_MAX_DELAY)
                continue
            async with stack:
                if announced:
                    _log(OperationStatus("Connected. Continuing the photo and video transfer…", "transfer_ready"))
                yield service
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


async def _ensure_media_directory(afc, directory, confirmed, progress_callback):
    if directory in ("", "/") or directory in confirmed:
        return
    await _ensure_media_directory(afc, posixpath.dirname(directory), confirmed, progress_callback)
    for attempt in range(6):
        try:
            try:
                present = await afc.isdir(directory)
            except AfcFileNotFoundError:
                present = False
            else:
                if not present:
                    raise NuggetException(f"AFC media: {directory} exists but is not a directory")
            if not present:
                try:
                    await afc.makedirs(directory)
                except AfcException as creation_error:
                    # Photos may create the folder between the stat and MAKE_DIR.
                    try:
                        present = await afc.isdir(directory)
                    except AfcException:
                        present = False
                    if not present:
                        raise creation_error
                if not await afc.isdir(directory):
                    raise NuggetException(f"AFC media: could not confirm directory {directory}")
            confirmed.add(directory)
            return
        except AfcException as error:
            if error.status != AfcError.PERM_DENIED:
                raise
            if attempt == 5:
                raise NuggetException(
                    f"AFC media: the device denied access to {directory}. "
                    "Photo restoration is incomplete. Keep the local media backup; "
                    "unlock the device and check the application log before resuming."
                ) from error
            progress_callback("The device denied access to the photo folder. Retrying photo restoration…")
            await asyncio.sleep(min(2 ** attempt, 5))


@asynccontextmanager
async def _pausable_media_connection(lockdown_client, progress_callback, prompt_choice, unlock_prompt):
    from src.restore.pause_control import current_pause_control
    control = current_pause_control.get()
    async with AsyncExitStack() as stack:
        async def connect(refresh=False):
            return await stack.enter_async_context(open_afc_for_media(
                lockdown_client, progress_callback=progress_callback,
                prompt_choice=prompt_choice, unlock_prompt=unlock_prompt,
                refresh_client=refresh))
        async def checkpoint(refresh=False):
            nonlocal service
            if refresh:
                await stack.aclose()
                service = await connect(refresh=True)
            if control and control.requested.is_set():
                await stack.aclose()
                progress_callback("Photo and video restoration paused. Keep your device connected. Select Resume to continue.")
                await control.wait_for_resume()
                service = await connect(refresh=True)
                control.state = "available"
                progress_callback("Resuming photo and video restoration…")
            return service
        try:
            service = await connect()
            if control:
                control.state = "available"
            yield checkpoint
        finally:
            if control:
                control.finish_media()


async def _wait_for_media_directory(checkpoint, directory, confirmed,
                                    progress_callback, prompt_choice):
    deadline = time.monotonic() + _AFC_OPEN_TIMEOUT
    while True:
        afc = await checkpoint()
        try:
            await _ensure_media_directory(afc, directory, confirmed, progress_callback)
            return afc
        except (AfcException, NuggetException) as error:
            cause = error.__cause__ if isinstance(error, NuggetException) else error
            if not isinstance(cause, AfcException) or cause.status != AfcError.PERM_DENIED:
                raise
            log_warn(f"AFC media: access denied to {directory}; waiting on a fresh session")
            progress_callback(OperationStatus(
                "iOS is denying access to the photo folder. Unlock your device and keep it connected. Waiting to retry…",
                "authentication"))
            if time.monotonic() >= deadline:
                message = (
                    f"iOS is still denying access to {directory}. Photo restoration is incomplete. "
                    "The local media backup has been kept. Unlock your device before resuming. "
                    "If this continues while unlocked, a service or permission problem may need to be resolved. "
                    "Resume retries photo-folder access; it does not repeat the device wipe.")
                if prompt_choice is None or prompt_choice(
                        "Photo folder access denied", message) != "resume":
                    raise NuggetException(message) from error
                deadline = time.monotonic() + _AFC_OPEN_TIMEOUT
            await asyncio.sleep(_AFC_OPEN_MAX_DELAY)
            await checkpoint(refresh=True)


async def restore_media_via_afc(lockdown_client, media_root: str,
                                progress_callback=None,
                                on_error: str = "raise",
                                prompt_choice=None,
                                unlock_prompt=None,
                                diff: bool = True,
                                include_historical: bool = True) -> dict:
    """Push a previously pulled Media tree back to the device over AFC.

    Mirrors ``media_root`` (which holds the AFC root layout: DCIM/, PhotoData/,
    ...) back onto the device after the iOS 27 security-recovery wipe. Returns
    a tally dict ``{"files": int, "bytes": int, "skipped": int}``.

    The device has just rebooted, so the AFC open waits out a locked screen
    first (see ``open_afc_for_media``) -- pass ``prompt_choice`` to get the
    Abort/Resume prompt if that wait runs out.

    With ``diff=True`` (the default) only the files the device is actually
    missing (or holds at a different size) are transferred. The device's
    current media tree is inventoried over AFC and compared against the store
    with the same size rule the pull side uses, so a store that is already
    in sync costs one directory listing and no transfer at all. This is what
    makes a repeat apply cheap: the photos are already on the device and do
    not need to go up the cable again.

    A file the device holds at the same size is skipped -- the identical rule
    the pull-side diff uses. A file the device holds at a *different* size is
    still pushed, so the store stays authoritative for anything that differs.
    """
    root = os.path.abspath(media_root)
    if not os.path.isdir(root):
        raise NuggetException(f"AFC media store is missing ({root})")

    def _log(value):
        if progress_callback is not None and not isinstance(value, (int, float)):
            progress_callback(value)

    try:
        current = None if include_historical else await _disk_io(verified_media_state, root)
        inventory = current['entries'] if current else await _disk_io(_media_inventory, root)
    except (OSError, ValueError) as e:
        raise NuggetException(f"Cannot read AFC media store ({root}): {e}") from e

    total_files = len(inventory)
    if not total_files:
        raise NuggetException(f"AFC media store has no photo/video payloads ({root})")

    entries = sorted(inventory.items())

    async with _pausable_media_connection(lockdown_client, _log, prompt_choice, unlock_prompt) as checkpoint:
        done_files = 0
        done_bytes = 0
        skipped = 0
        failed: list[str] = []
        made_dirs: set = set()

        device_sizes: dict = {}
        if diff:
            try:
                device_sizes = await _device_media_inventory(await checkpoint())
            except Exception as e:  # noqa: BLE001 - fall back to pushing everything
                log_warn(f"AFC media: could not inventory the device media tree "
                         f"({e}) — pushing every file")
                device_sizes = {}

        pending = []
        for rel, size in entries:
            if rel in device_sizes and device_sizes.get(rel) == size:
                skipped += 1
                continue
            pending.append((rel, size))

        if skipped:
            log_info(f"AFC media: {skipped} of {len(entries)} files are already "
                     f"on the device at the same size — not re-transferring them")
        pending_bytes = sum(size for _rel, size in pending)

        for rel, size in pending:
            src = str(await _disk_io(_local_media_path, root, rel))
            remote = f"/{rel}"
            try:
                afc = await _wait_for_media_directory(
                    checkpoint, posixpath.dirname(remote), made_dirs, _log, prompt_choice)
                n = await _push_one(afc, src, remote)
            except Exception as e:
                msg = f"AFC media: failed to restore {remote}: {e}"
                if on_error == "warn":
                    log_warn(msg)
                    failed.append(rel)
                else:
                    raise NuggetException(msg) from e
            done_files += 1
            done_bytes += n
            if done_files % 25 == 0 or done_files == len(pending):
                _log(_progress_str("Restoring photos/videos over AFC",
                                   done_files, len(pending), done_bytes, pending_bytes))

        log_info(f"AFC media restore complete: {done_files} files pushed, "
                 f"{skipped} already on the device, "
                 f"{done_bytes / (1024 * 1024):.1f} MB transferred")

    if failed:
        log_warn(f"AFC media restore: {len(failed)} files failed (e.g. {failed[:3]})")
        return {"files": done_files, "bytes": done_bytes, "skipped": skipped,
                "failed": failed}

    if not include_historical and current is None and not failed:
        raise NuggetException(
            "The media store could not be verified. Available files were restored, "
            "but photo restoration is incomplete. Keep the local media backup.")

    return {"files": done_files, "bytes": done_bytes, "skipped": skipped}
