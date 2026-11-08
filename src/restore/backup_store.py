"""Local protective-backup generations and payload inventory (no device sessions)."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock

from src.exceptions.nugget_exception import NuggetException
from src.utils.filecopy import clone_or_copy
from src.utils.log_util import log_info, log_warn

WORKING_COPY_PREFIX = "nugget_working_"
_BACKUP_METADATA_FILES = frozenset({
    "Manifest.db", "Manifest.plist", "Status.plist", "Info.plist", "backup_manifest.db",
})
_retirement_pool = None
_retirement_lock = Lock()

def _copy_backup_tree(src_root: Path, dst_root: Path) -> None:
    """Faithfully copy one backup device dir into ``dst_root``.

    Metadata (incl. sqlite sidecars) is real-copied — pruning rewrites
    Manifest.db, and a hardlink would corrupt the cache master through the
    shared inode/-wal. Everything else is hardlinked (near-instant, size-free),
    with a copy fallback for cross-device destinations.
    """
    dst_root.mkdir(parents=True, exist_ok=True)
    always_copy = set(_BACKUP_METADATA_FILES) | {"Manifest.db-wal", "Manifest.db-shm"}
    for dirpath, _dirnames, filenames in os.walk(src_root):
        rel = Path(dirpath).relative_to(src_root)
        (dst_root / rel).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            src_file = Path(dirpath) / name
            dst_file = dst_root / rel / name
            if name in always_copy:
                clone_or_copy(src_file, dst_file)
            else:
                try:
                    os.link(src_file, dst_file)
                except OSError:
                    clone_or_copy(src_file, dst_file)


def make_protective_working_copy(backup_root: str, udid: str) -> str:
    """Build a throwaway hardlink copy of a protective backup for prune + injection.

    Hardlinks keep it near-instant and size-free; pruning unlinks orphans
    without touching the source's own files (the cache master stays intact).

    The disposable copy lives beside its source on the same volume so a
    configured external backup drive never spills payloads into system temp.
    ``WORKING_COPY_PREFIX`` distinguishes its scratch directory from masters.
    """
    src_root = Path(backup_root) / udid
    if not src_root.is_dir():
        # Tolerate a root pointing directly at the device directory.
        if (Path(backup_root) / "Manifest.db").is_file():
            src_root = Path(backup_root)
        else:
            raise NuggetException("Protective backup is missing its payload.")

    working_root = Path(tempfile.mkdtemp(prefix=WORKING_COPY_PREFIX, dir=src_root.parent)) / "device_backup"
    try:
        _copy_backup_tree(src_root, working_root / udid)
    except BaseException:
        shutil.rmtree(working_root.parent, ignore_errors=True)
        raise
    return str(working_root)


def make_cache_snapshot(backup_root: str, udid: str, inject_files: list = None) -> str:
    """Record the pristine state of a cache master before an apply modifies it.

    The cache master is both the Phase 3 restore source AND the next apply's
    incremental-refresh store. So before pruning + tweak-injection touch the
    master in place, this snapshots it under ``<base>/snapshot/<udid>`` (the
    same hardlink-copy semantics as ``make_protective_working_copy``, but in
    the persistent store next to the master — never the temp dir, since the
    snapshot is the pristine full-manifest record that must survive a crash
    between Phase 2's wipe and Phase 3's restore).

    The files the upcoming injection will change are recorded as
    ``inject_plan.json`` beside the snapshot for diagnostics. Returns the
    snapshot base dir (``<base>/snapshot``).
    """
    snap_base = Path(backup_root).parent / "snapshot"
    # Drop a stale snapshot left by a crashed run before recording a new one.
    shutil.rmtree(snap_base, ignore_errors=True)
    src_root = Path(backup_root) / udid
    if not src_root.is_dir():
        # Tolerate a root pointing directly at the device directory.
        if (Path(backup_root) / "Manifest.db").is_file():
            src_root = Path(backup_root)
        else:
            raise NuggetException("Cache master is missing its payload.")

    _copy_backup_tree(src_root, snap_base / udid)
    plan = [{"domain": f.domain, "path": f.restore_path.lstrip("/")}
            for f in (inject_files or [])]
    (snap_base / "inject_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return str(snap_base)


def _retire_backup_tree(directory):
    global _retirement_pool
    from concurrent.futures.thread import ThreadPoolExecutor
    with _retirement_lock:
        if _retirement_pool is None:
            _retirement_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backup-cleanup")
    def remove():
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log_warn(f"Could not remove retired backup {directory}: {exc}")
    _retirement_pool.submit(remove)


def discard_protective_working_copy(working_root):
    """Retire only a successful recovery's own disposable copy, never a master."""
    root = Path(working_root)
    if root.name != 'device_backup' or not root.parent.name.startswith(WORKING_COPY_PREFIX):
        raise ValueError("Not a disposable protective working copy")
    _retire_backup_tree(root.parent)


def regenerate_cache_from_snapshot(snapshot_dir: str, backup_root: str, udid: str) -> str:
    """Regenerate the cache master from the snapshot taken before the apply.

    The master (pruned + tweak-injected in place for this apply) is replaced by
    the pristine snapshot via generation renames on the same filesystem.
    The retired generation is unlinked in a background cleanup worker. A missing
    master after an interrupted rename is recovered from the snapshot too.
    The snapshot's recorded inject plan is then removed. Returns the regenerated master
    root (``backup_root``).
    """
    snap_root = Path(snapshot_dir) / udid
    if not snap_root.is_dir():
        # Tolerate a snapshot dir pointing directly at the device directory.
        if (Path(snapshot_dir) / "Manifest.db").is_file():
            snap_root = Path(snapshot_dir)
        else:
            log_warn("Cache snapshot missing — cannot regenerate")
            return backup_root
    master_dev = Path(backup_root) / udid
    if not master_dev.is_dir():
        if (Path(backup_root) / "Manifest.db").is_file():
            master_dev = Path(backup_root)
    import uuid
    master_dev.parent.mkdir(parents=True, exist_ok=True)
    retired = None
    if master_dev.exists():
        retired = master_dev.with_name(f".retired-{master_dev.name}-{uuid.uuid4().hex}")
        master_dev.rename(retired)
    try:
        # Both generations live on the cache volume. Never delete the old
        # master until the pristine generation has successfully taken its place.
        snap_root.rename(master_dev)
    except BaseException:
        if retired is not None:
            retired.rename(master_dev)
        raise
    shutil.rmtree(Path(snapshot_dir), ignore_errors=True)
    if retired is not None:
        _retire_backup_tree(retired)
    # Reclaim only our own abandoned generations after a previous crash.
    for leftover in master_dev.parent.glob(f".retired-{master_dev.name}-*"):
        if leftover != retired and leftover.is_dir() and not leftover.is_symlink():
            _retire_backup_tree(leftover)
    log_info(f"Cache master regenerated from snapshot: {master_dev}")
    return str(backup_root)


def _payload_inventory(device_dir):
    files, directories, counts, regular_ids = [], [], {}, set()
    pending = [device_dir]
    while pending:
        directory = pending.pop()
        directories.append(directory)
        count = 0
        with os.scandir(directory) as children:
            for entry in children:
                count += 1
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.name not in _BACKUP_METADATA_FILES:
                    payload = Path(entry.path)
                    files.append(payload)
                    if (entry.is_file(follow_symlinks=False)
                            and directory == device_dir / entry.name[:2]):
                        regular_ids.add(entry.name)
        counts[directory] = count
    return files, directories, counts, regular_ids


def _remove_orphan_payloads(inventory, keep_ids):
    files, directories, counts, _ = inventory
    removed = 0
    for payload in files:
        if payload.name not in keep_ids:
            payload.unlink(missing_ok=True)
            counts[payload.parent] -= 1
            removed += 1
    for directory in reversed(directories[1:]):
        if counts[directory] == 0:
            directory.rmdir()
            counts[directory.parent] -= 1
    return removed
