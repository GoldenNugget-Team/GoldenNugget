"""Standalone PosterBoard database backup.

Two mechanisms, both kept GUI-independent so the backend apply path
(``device_manager._backup_posterboard_database``) needs no GUI imports:

* ``backup_posterboard_database`` — LEGACY: backs up the whole device and
  extracts the PosterBoard SQLite file. Only safe as a fallback now.
* ``targeted_posterboard_database_backup`` — modern channel: backs up ONLY the
  PosterBoard container (everything else the device uploads is drained
  mid-stream, never written to disk) and hands back a WAL-merged copy of the
  sqlite. This is what iOS 26 applies use instead of the full Phase 0 backup,
  and what the "Fetch Database File" wizard calls.
"""

import os
import sqlite3
import tempfile

from PySide6.QtCore import QCoreApplication
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from src.devicemanagement.session import lockdown_session
from src.restore.protective import check_disk_space_for_backup, _validate_sqlite_db
from src.restore.storage import legacy_backups_dir, posterboard_dir as _posterboard_dir
from src.exceptions.nugget_exception import NuggetException
from src.devicemanagement.constants import is_supported_by_fork
from src.utils.async_retry import async_retry


async def backup_posterboard_database(udid: str, update_label=lambda x: None, update_progress=lambda x: None) -> str:
    """Back up the device and return the extracted PosterBoard sqlite db path."""
    from src.exceptions.device_errors import is_device_locked_error as _is_device_locked_error
    from src.exceptions.device_errors import is_connection_error as _is_connection_error

    app_data_path = str(legacy_backups_dir())
    if not os.path.exists(app_data_path):
        os.makedirs(app_data_path)
    backup_folder = os.path.join(app_data_path, udid)
    # check if a full backup is needed (makes it faster)
    needs_full = False
    if os.path.exists(backup_folder):
        files_to_verify = ["Info.plist", "Manifest.db", "Manifest.plist", "Status.plist"]
        for file in files_to_verify:
            if not os.path.exists(os.path.join(backup_folder, file)):
                needs_full = True
                break

    max_retries = 3

    async def _attempt():
        async with lockdown_session(udid) as service_provider:
            # hard-block fetching the database from an unsupported (old) iOS version
            if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                raise NuggetException(
                    "This version of iOS is not supported by this fork.\n\n"
                    "GoldenNugget only supports iOS 26.2 and newer. "
                    "Please use the original Nugget for iOS 26.1 and earlier.")
            async with Mobilebackup2Service(service_provider) as backup_client:
                try:
                    await backup_client.backup(full=needs_full, backup_directory=app_data_path, progress_callback=update_progress)
                except Exception as e:
                    if _is_device_locked_error(e):
                        raise NuggetException("Device locked during backup. Please unlock your device, keep it awake (tap screen periodically), and try again.")
                    raise

    async with lockdown_session(udid) as service_provider:
        await check_disk_space_for_backup(service_provider, path=app_data_path)

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        if attempt < total:
            update_label(f"Connection lost, retrying in {delay}s... (attempt {attempt}/{max_retries})")

    await async_retry(
        _attempt,
        max_retries,
        retry_if=_is_connection_error,
        exp_cap=15,
        on_retry=_on_retry,
    )

    # get the file, reading the sqlite db first to get the file id
    update_label("Getting the file...")
    db_path = os.path.join(backup_folder, "Manifest.db")
    if not _validate_sqlite_db(db_path):
        raise NuggetException("Backup manifest (Manifest.db) is not a valid SQLite database. The backup may have failed or been interrupted.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # resolve by file name: the store dir's structure version varies by iOS
    # (and iOS 27 stores it under the physical tree, not the AppDomain-* domain)
    cursor.execute(
        "SELECT fileID FROM Files WHERE relativePath LIKE ? ORDER BY relativePath DESC",
        ("%PRBPosterExtensionDataStore%PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3%",))
    fileID = cursor.fetchone()
    conn.close()
    if fileID is None or len(fileID) == 0:
        raise NuggetException("Could not find sqlite database in the backup!")
    fileID = fileID[0]
    db_file_path = os.path.join(backup_folder, fileID[:2], fileID)
    if not os.path.exists(db_file_path):
        raise NuggetException("The database file doesn't exist!")
    return db_file_path


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
        with tempfile.TemporaryDirectory(prefix="nugget_pb_only_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                    raise NuggetException(
                        "This version of iOS is not supported by this fork.\n\n"
                        "GoldenNugget only supports iOS 26.2 and newer. "
                        "Please use the original Nugget for iOS 26.1 and earlier.")
                async with Mobilebackup2Service(service_provider) as backup_client:
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
    conn = sqlite3.connect(f"file:{manifest}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT relativePath, fileID, flags FROM Files").fetchall()
    finally:
        conn.close()
    count = 0
    for rel_path, file_id, flags in rows:
        if flags != 1 or not file_id:
            continue
        src = os.path.join(device_dir, file_id[:2], file_id)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(out_dir, rel_path.lstrip("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as source, open(dst, "wb") as target:
            target.write(source.read())
        count += 1
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
        os.makedirs(out_dir, exist_ok=True)

    max_retries = 3

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        if attempt < total and isinstance(e, IncompletePosterBoardSnapshot):
            update_label(QCoreApplication.tr(
                "PosterBoard database copy was incomplete, retrying in {0}s... "
                "(attempt {1}/{2})").format(delay, attempt, total))
        elif attempt < total:
            update_label(QCoreApplication.tr(
                "Connection lost, retrying in {0}s... (attempt {1}/{2})").format(
                    delay, attempt, total))

    async def _attempt():
        with tempfile.TemporaryDirectory(prefix="nugget_pb_pull_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                if not is_supported_by_fork(service_provider.all_values.get("ProductVersion", "0.0")):
                    raise NuggetException(
                        "This version of iOS is not supported by this fork.\n\n"
                        "GoldenNugget only supports iOS 26.2 and newer. "
                        "Please use the original Nugget for iOS 26.1 and earlier.")
                async with Mobilebackup2Service(service_provider) as backup_client:
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
            with tempfile.TemporaryDirectory(prefix="nugget_pb_db_") as db_dir:
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