"""Shared local preparation before any normal or manual protective restore."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.exceptions.nugget_exception import NuggetException
from src.utils.async_disk import disk_call
from src.utils.file_to_restore import _FileMode

from .verification import PruneResult


@dataclass(frozen=True)
class RecoverySource:
    root: str
    udid: str
    password: str = ""
    include_keychain: bool = False
    media_dir: str = ""
    require_media_complete: bool = False  # manual rescue may use an incomplete store


@dataclass(frozen=True)
class RecoveryBackend:
    prune: Callable
    verify: Callable
    media_verified: Callable
    inject: Callable | None = None


async def prepare_recovery(source: RecoverySource, backend: RecoveryBackend,
                           inject_files=()) -> PruneResult:
    """Prune, optionally inject, and require complete verification in that order.

    Normal apply and GUI/CLI rescue share this gate. Historical media policy and
    device reconnect/setup remain the caller's explicit operation policy.
    """
    media_ready = await disk_call(backend.media_verified, source.media_dir)
    if source.media_dir and source.require_media_complete and not media_ready:
        raise NuggetException(
            f"The AFC media store could not be verified ({source.media_dir}). "
            "Restore stopped before modifying the device.")
    if inject_files and backend.inject is None:
        raise TypeError("An injection backend is required for tweak payloads")
    options = dict(include_keychain=source.include_keychain,
                   manifest_password=source.password,
                   exclude_afc_media_trees=media_ready)
    if inject_files:
        options["collect_inode"] = True
    result = await disk_call(backend.prune, source.root, source.udid, **options)
    result = result if isinstance(result, PruneResult) else PruneResult(*result)
    if inject_files:
        batch = []
        for item in inject_files:
            data = item.contents
            if data is None and item.contents_path:
                data = Path(item.contents_path)
            if isinstance(data, str):
                data = data.encode("utf-8")
            batch.append((item.domain, item.restore_path.lstrip("/"), data,
                          _FileMode.S_IFREG | 0o644, item.owner, item.group))
        _, _, failed = await disk_call(
            backend.inject, source.root, source.udid, batch, source.password,
            max_inode_hint=result.max_inode)
        if failed:
            raise NuggetException(f"Could not prepare {failed} tweak file(s) for restore. "
                                  "The device has not been modified.")
    missing = await disk_call(backend.verify, source.root, source.udid, source.password)
    if missing:
        raise NuggetException(
            f"{len(missing)} manifest rows lack payloads (e.g. {missing[:5]}). "
            "The backup is incomplete. Restore stopped before modifying the device.")
    return result
