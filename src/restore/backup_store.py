"""Local protective-backup generations and payload inventory (no device sessions)."""
import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock

from src.exceptions.nugget_exception import NuggetException
from src.utils.filecopy import clone_or_copy
from src.utils.log_util import log_warn

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
                    # accept both the standard <aa>/<fileID> layout and the
                    # flat <fileID> layout inject.py tolerates, so a legacy
                    # backup is not misreported as missing payloads
                    if (entry.is_file(follow_symlinks=False)
                            and directory in (device_dir / entry.name[:2], device_dir)):
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
