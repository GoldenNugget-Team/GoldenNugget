"""Persistent AFC media store, paths and completeness markers (no device I/O)."""
import json
import os
import stat as stat_module
import tempfile
import time
from pathlib import Path

from src.controllers.archive_safety import safe_member
from src.utils.log_util import log_warn

AFC_MEDIA_DIRNAME = "afc_media"
MEDIA_STATE_FILE = ".media_state.json"
AFC_MEDIA_TREES = frozenset({"DCIM", "PhotoStreamsData"})

def afc_media_dir_for(backup_root: str) -> str:
    """Media directory paired with a protective backup run.

    ``backup_root`` is ``<run dir>/device_backup``; the media tree lives next
    to it inside the same run dir (``<run dir>/afc_media``) so that run-level
    cleanup (prune_protective_backups, failure rmtree) reclaims both together.
    """
    return os.path.join(os.path.dirname(os.path.abspath(backup_root)),
                        AFC_MEDIA_DIRNAME)


def _local_media_path(root: str, relative: str) -> Path:
    """Reject ambiguous paths and links, including links in parent directories."""
    if not isinstance(relative, str) or not safe_member(relative):
        raise ValueError(f"Unsafe AFC media path: {relative!r}")
    target = Path(root)
    for part in relative.split('/'):
        target = target / part
        if target.is_symlink():
            raise ValueError(f"Linked AFC media path: {relative!r}")
    return target


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


def _media_inventory(media_root: str) -> dict[str, int]:
    """One metadata read per entry; never follow links, including directories."""
    inventory = {}
    pending = [(os.path.abspath(media_root), "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as children:
            for entry in children:
                relative = prefix + entry.name
                if not safe_member(relative):
                    raise ValueError(f"Unsafe media store entry: {relative}")
                st = entry.stat(follow_symlinks=False)
                if stat_module.S_ISLNK(st.st_mode):
                    raise ValueError(f"Media store contains a linked entry: {relative}")
                if stat_module.S_ISDIR(st.st_mode):
                    pending.append((entry.path, relative + '/'))
                elif entry.name in (MEDIA_STATE_FILE, MEDIA_STATE_FILE + '.tmp') or entry.name.endswith('.part'):
                    continue
                elif stat_module.S_ISREG(st.st_mode):
                    inventory[relative] = st.st_size
                else:
                    raise ValueError(f"Media store contains a non-regular file: {relative}")
    return inventory


def verified_media_state(media_root: str) -> dict | None:
    """Validate every recorded file, with one check per shared parent directory.

    This is deliberately a fresh pass, never a persistent completeness cache.
    Directory metadata is reused only within this invocation.
    """
    state = media_store_state(media_root)
    if not state or state.get('complete') is not True or state.get('version') != 2:
        return None
    entries = state.get('entries')
    if not isinstance(entries, dict) or not entries:
        return None
    try:
        root = Path(media_root).resolve(strict=True)
        if not root.is_dir():
            return None
        directories = {root}
        total = 0
        for relative, size in entries.items():
            if (not isinstance(relative, str) or not safe_member(relative)
                    or type(size) is not int or size < 0
                    or relative.rsplit('/', 1)[-1] in (MEDIA_STATE_FILE, MEDIA_STATE_FILE + '.tmp')
                    or relative.endswith('.part')):
                return None
            parts = relative.split('/')
            parent = root
            for part in parts[:-1]:
                parent = parent / part
                if parent not in directories:
                    if not stat_module.S_ISDIR(os.stat(parent, follow_symlinks=False).st_mode):
                        return None
                    directories.add(parent)
            st = os.stat(parent / parts[-1], follow_symlinks=False)
            if not stat_module.S_ISREG(st.st_mode) or st.st_size != size:
                return None
            total += size
        if (type(state.get('files')) is int and state['files'] == len(entries)
                and type(state.get('bytes')) is int and state['bytes'] == total):
            return state
    except (OSError, ValueError):
        pass
    return None


def media_store_verified(media_root: str) -> bool:
    return verified_media_state(media_root) is not None


def recovery_media_dir(backup_root: str, udid: str, cache_base=None) -> str:
    """Resolve media from the selected backup's metadata, never another cache."""
    if cache_base is not None:
        base = Path(cache_base)
        media = base / 'media' / udid
        try:
            info = json.loads((base / f'{udid}.json').read_text(encoding='utf-8'))
            if isinstance(info, dict) and 'media_afc' in info:
                return str(media) if info['media_afc'] else ''
        except (OSError, ValueError):
            pass
        return str(media) if media.is_dir() else ''
    media = afc_media_dir_for(backup_root)
    required = Path(backup_root).parent / '.afc_media_required'
    return media if os.path.isdir(media) or required.exists() else ''


def describe_media_store(media_root: str, *, verified=None, verify=True) -> str:
    """One-line summary of a media store, for logs and error messages."""
    state = media_store_state(media_root) or {}
    files = int(state.get("files") or 0)
    mib = int(state.get("bytes") or 0) / (1024 * 1024)
    if verified is None and verify:
        verified = media_store_verified(media_root)
    status = ("verified" if verified else "NOT verified") if verified is not None else "not rechecked"
    return f"{media_root}: {files} files / {mib:.1f} MB ({status})"


def _write_media_state(media_root: str, files: int, bytes_: int,
                       skipped: int, entries: dict[str, int] | None = None,
                       mtimes: dict[str, str] | None = None) -> None:
    """Record a completed pull so later applies may treat the store as intact."""
    if entries is None:
        try:
            entries = _media_inventory(media_root)
        except (OSError, ValueError):
            _invalidate_media_state(media_root, "could not inventory payloads")
            return
    state = {
        "version": 2,
        "entries": entries,
        "mtimes": mtimes or {},
        "complete": True,
        "files": int(files),
        "bytes": int(bytes_),
        "skipped": int(skipped),
        "ts": time.time(),
    }
    tmp = None
    try:
        os.makedirs(media_root, exist_ok=True)
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=media_root,
                prefix=".afc-state-", suffix=".part", delete=False) as f:
            tmp = f.name
            json.dump(state, f, indent=2)
        os.replace(tmp, os.path.join(media_root, MEDIA_STATE_FILE))
    except OSError as e:
        log_warn(f"AFC media: could not write the media store marker "
                 f"({e}) — the store stays unverified")
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass
            except OSError as error:
                log_warn(f"AFC media: could not remove marker temp file: {error}")


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
    except FileNotFoundError:
        pass
    if had_state:
        log_warn(f"AFC media: media store marker dropped ({reason}) — "
                 f"{media_root} is now UNVERIFIED and must not be used as the "
                 f"only copy of the photos")
