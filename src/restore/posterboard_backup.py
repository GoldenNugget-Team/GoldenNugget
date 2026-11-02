"""Standalone PosterBoard database backup.

Kept GUI-independent so the backend apply path
(``device_manager._backup_posterboard_database``) needs no GUI imports:

* ``targeted_posterboard_database_backup`` — modern channel: backs up ONLY the
  PosterBoard container (everything else the device uploads is drained
  mid-stream, never written to disk) and hands back a WAL-merged copy of the
  sqlite. This is what iOS 26 applies use instead of the full Phase 0 backup,
  and what the "Fetch Database File" wizard calls.
"""

import errno
import logging
import os
import sqlite3
import tempfile
from contextlib import contextmanager

from src.utils.i18n import QCoreApplication
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError

from src.devicemanagement.session import lockdown_session
from src.restore.protective import (
    ProtectiveBackupService, backup_disk_space_message, check_disk_space,
)
from src.restore.storage import posterboard_dir as _posterboard_dir
from src.exceptions.nugget_exception import BackupDiskSpaceError, NuggetException, PosterBoardBackupEncryptionError
from src.devicemanagement.constants import is_supported_by_fork
from src.utils.async_retry import async_retry

_log = logging.getLogger("GoldenNugget.posterboard_backup")


async def _require_readable_backup(backup_client):
    if await backup_client.get_will_encrypt():
        raise PosterBoardBackupEncryptionError(
            'PosterBoard extraction cannot read encrypted backup manifests and payloads in this build. '
            'No separate backup was started. Repeating the backup will not fix this. '
            'Keep backup encryption enabled if you rely on it for protected data; '
            'leave PosterBoard changes out of this apply until encrypted extraction is supported.')


@contextmanager
def _posterboard_workspace(prefix):
    """Keep scratch backup bytes on the chosen backup volume, not system temp."""
    work_root = _posterboard_dir() / ".work"
    try:
        work_root.mkdir(parents=True, exist_ok=True)
        check_disk_space(path=str(work_root))
        with tempfile.TemporaryDirectory(prefix=prefix, dir=work_root) as backup_dir:
            yield backup_dir
    except NotEnoughDiskSpaceError as e:
        raise BackupDiskSpaceError(str(e).strip() or backup_disk_space_message(work_root)) from e
    except OSError as e:
        if e.errno != errno.ENOSPC:
            raise
        # An exhausted local disk must not be retried as a lost USB connection.
        raise BackupDiskSpaceError(backup_disk_space_message(work_root)) from e


async def targeted_posterboard_database_backup(udid: str, update_label=lambda x: None,
                                               update_progress=lambda x: None) -> tuple[str, int]:
    """Back up ONLY the PosterBoard container and return the merged sqlite path.

    The PosterBoard delivery channel for iOS 26 applies: there is no Phase 0
    protective backup there (the restore is a plain sparse pass, nothing gets
    restored), so this pulls just the ``AppDomain-com.apple.PosterBoard``
    database off the device. The factory info lists only that container and the
    mid-stream filter drops every other file the device uploads, so the run
    stays small on disk and fast — no photos, contacts or settings are ever
    written here. Returns ``(extracted_db_path, structure_version)`` — the
    structure version parsed from the database's manifest path so the restored
    copy lands in the same store directory it was fetched from.

    iOS 26 uploads the database WITHOUT its ``-wal`` sibling, so what comes out
    is a plain copy of a file PosterBoard is still writing. When that copy
    races a checkpoint it comes out torn, which is a transient condition and not
    a broken device — so an incomplete snapshot is retried exactly like a lost
    connection instead of failing the wizard on the first try.
    """
    from src.exceptions.device_errors import is_connection_error as _is_connection_error
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.restore.protective import (
        POSTERBOARD_DB_DOMAIN, _domain_match,
        _posterboard_db_match, extract_posterboard_db)
    from src.tweaks.posterboard.db_validate import IncompletePosterBoardSnapshot

    pb_dir = str(_posterboard_dir())
    if not os.path.exists(pb_dir):
        os.makedirs(pb_dir)
    dest_path = os.path.join(pb_dir, f"{udid}.sqlite3")

    max_retries = 3

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        _log.warning('PosterBoard database attempt %s/%s failed: %s: %s',
                     attempt, total, type(e).__name__, e, exc_info=(type(e), e, e.__traceback__))
        if attempt < total:
            if isinstance(e, IncompletePosterBoardSnapshot):
                update_label(QCoreApplication.tr(
                    "PosterBoard database copy was incomplete, retrying in {0}s... "
                    "(attempt {1}/{2})").format(delay, attempt, total))
            else:
                update_label(QCoreApplication.tr(
                    "Connection lost, retrying in {0}s... (attempt {1}/{2})").format(
                        delay, attempt, total))

    async def _attempt():
        with _posterboard_workspace("nugget_pb_only_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                    raise NuggetException(
                        "This version of iOS is not supported by this fork.\n\n"
                        "GoldenNugget only supports iOS 26.2 and newer. "
                        "Please use the original Nugget for iOS 26.1 and earlier.")
                async with ProtectiveBackupService(service_provider, include_posterboard=True) as backup_client:
                    await _require_readable_backup(backup_client)
                    def _pb_only(backup_file):
                        device_name = backup_file.device_name or ""
                        return (_domain_match(device_name, POSTERBOARD_DB_DOMAIN)
                                or _posterboard_db_match(device_name))
                    try:
                        await backup_client.backup(
                            full=True, backup_directory=backup_dir,
                            progress_callback=update_progress, filter_callback=_pb_only)
                    except Exception as e:
                        if _is_device_locked_error(e):
                            raise NuggetException(
                                "Device locked during backup. Please unlock your device, "
                                "keep it awake (tap screen periodically), and try again.")
                        raise
            update_label("Getting the file...")
            db_path_and_version = extract_posterboard_db(backup_dir, udid, dest_path)
            if db_path_and_version is None:
                raise NuggetException(
                    "Could not find the PosterBoard database in the backup!")
            return db_path_and_version

    return await async_retry(
        _attempt, max_retries,
        retry_if=lambda e: _is_connection_error(e) or isinstance(e, IncompletePosterBoardSnapshot),
        exp_cap=15, on_retry=_on_retry)


def _find_manifest(backup_dir: str) -> "str | None":
    for dirpath, _dirs, files in os.walk(backup_dir):
        if "Manifest.db" in files:
            return os.path.join(dirpath, "Manifest.db")
    return None


def _materialise_backup(device_dir: str, manifest: str, out_dir: str) -> int:
    """Copy every regular payload to ``out_dir`` mirroring its relativePath.

    Only ``flags == 1`` manifest rows have a payload (``flags == 2`` are
    directories); missing payloads are simply skipped, exactly like the
    reference pull tool. Returns the number of files materialised.
    """
    from shutil import copyfile
    count = 0
    conn = sqlite3.connect(f"file:{manifest}?mode=ro", uri=True)
    try:
        for rel_path, file_id in conn.execute(
                "SELECT relativePath, fileID FROM Files WHERE flags = 1"):
            if not file_id:
                continue
            src = os.path.join(device_dir, file_id[:2], file_id)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(out_dir, rel_path.lstrip("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            copyfile(src, dst)
            count += 1
    finally:
        conn.close()
    return count


async def pull_posterboard_container(udid: str, out_dir: str,
                                     update_label=lambda x: None,
                                     update_progress=lambda x: None
                                     ) -> tuple[str, int]:
    """Pull the whole PosterBoard container and materialise it under ``out_dir``.

    Same targeted mobilebackup2 channel as
    ``targeted_posterboard_database_backup`` (only the PosterBoard domain is
    uploaded, everything else is drained mid-stream), but instead of keeping
    just the sqlite every payload is written next to its device relativePath
    (``out_dir/Library/Application Support/PRBPosterExtensionDataStore/...``).
    Used by the "Rebuild Database" flow so the on-device wallpaper packages can
    be repacked and pushed back. Returns ``(out_dir, structure_version)``.
    """
    from src.exceptions.device_errors import is_connection_error as _is_connection_error
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.restore.protective import (
        POSTERBOARD_DB_DOMAIN, _domain_match, _posterboard_db_match,
        extract_posterboard_db)
    from src.tweaks.posterboard.db_validate import IncompletePosterBoardSnapshot

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    max_retries = 3

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        _log.warning('PosterBoard container attempt %s/%s failed: %s: %s',
                     attempt, total, type(e).__name__, e, exc_info=(type(e), e, e.__traceback__))
        if attempt < total and isinstance(e, IncompletePosterBoardSnapshot):
            update_label(QCoreApplication.tr(
                "PosterBoard database copy was incomplete, retrying in {0}s... "
                "(attempt {1}/{2})").format(delay, attempt, total))
        elif attempt < total:
            update_label(QCoreApplication.tr(
                "Connection lost, retrying in {0}s... (attempt {1}/{2})").format(
                    delay, attempt, total))

    async def _attempt():
        with _posterboard_workspace("nugget_pb_pull_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                    raise NuggetException(
                        "This version of iOS is not supported by this fork.\n\n"
                        "GoldenNugget only supports iOS 26.2 and newer. "
                        "Please use the original Nugget for iOS 26.1 and earlier.")
                async with ProtectiveBackupService(service_provider, include_posterboard=True) as backup_client:
                    await _require_readable_backup(backup_client)
                    def _pb_only(backup_file):
                        device_name = backup_file.device_name or ""
                        # iOS 26 uploads the container as AppDomain-*; iOS 27
                        # uploads the raw physical tree (/.b/<n>/Containers/...)
                        # so the domain match misses it and the store-path
                        # substring is what selects the wallpaper packages.
                        return (_domain_match(device_name, POSTERBOARD_DB_DOMAIN)
                                or _posterboard_db_match(device_name)
                                or "PRBPosterExtensionDataStore" in device_name
                                or "PosterBoard" in device_name)
                    try:
                        await backup_client.backup(
                            full=True, backup_directory=backup_dir,
                            progress_callback=update_progress, filter_callback=_pb_only)
                    except Exception as e:
                        if _is_device_locked_error(e):
                            raise NuggetException(
                                "Device locked during backup. Please unlock your device, "
                                "keep it awake (tap screen periodically), and try again.")
                        raise

            manifest = _find_manifest(backup_dir)
            if manifest is None:
                raise NuggetException(
                    "Could not find the backup manifest — the backup may have failed "
                    "or the device backup is encrypted.")
            device_dir = os.path.dirname(manifest)

            update_label("Reading PosterBoard database...")
            with tempfile.TemporaryDirectory(prefix="nugget_pb_db_", dir=backup_dir) as db_dir:
                extracted = extract_posterboard_db(
                    device_dir, udid, os.path.join(db_dir, "posterboard.sqlite3"))
            if extracted is None:
                raise NuggetException(
                    "Could not find the PosterBoard database in the backup!")
            _db_path, structure_version = extracted

            update_label("Copying wallpaper files...")
            count = _materialise_backup(device_dir, manifest, out_dir)
            if count == 0:
                raise NuggetException(
                    "No PosterBoard files were found in the backup.")
            return out_dir, structure_version

    return await async_retry(
        _attempt, max_retries,
        retry_if=lambda e: _is_connection_error(e) or isinstance(e, IncompletePosterBoardSnapshot),
        exp_cap=15, on_retry=_on_retry)
