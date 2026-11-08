"""Fetch the on-device ``StatusBarOverrides.archive`` for format research.

Why this exists
---------------
``statusbar_archive.py`` deliberately ships only the two carrier-name entries,
because the rest of the ``_SBSystemStatusStatusBarOverridesArchiveRecord``
schema is not known from source and guessing an ``NSKeyedArchiver`` key ships
a status bar that fails to draw. The missing half of the schema can only come
from a device: SpringBoard *writes* that archive itself whenever it applies an
override, so a carrier-only archive that went through one apply/reboot comes
back rewritten in SpringBoard's own canonical form -- with the real class
names and key names in it.

That round trip is this module's whole job. It is a research/diagnostic
channel, not part of the apply flow: nothing in the app calls it.

The file is read over the same channel the PosterBoard database already uses
-- a targeted ``mobilebackup2`` run whose factory info lists no app containers
and whose mid-stream filter keeps exactly one path. No jailbreak, no Developer
Mode, nothing but a paired device that the user trusts.

Runs against ``Library/SpringBoard/StatusBarOverrides.archive`` in
**HomeDomain**, i.e. the same place ``apply_ios27_tweak`` writes it, so what
comes out is byte-comparable with what we produce.
"""

# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "pymobiledevice3.services.mobilebackup2",
)

import plistlib
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service

from src.devicemanagement.session import lockdown_session
from src.exceptions.nugget_exception import NuggetException
from src.utils.async_retry import async_retry

# HomeDomain path of the archive, relative to /var/mobile. Same value the tweak
# writes (ARCHIVE_PATH), re-derived here as a *relative* prefix because that is
# what the manifest rows and the upload names use.
ARCHIVE_FILE_NAME = "StatusBarOverrides.archive"
ARCHIVE_REL_PATH = f"Library/SpringBoard/{ARCHIVE_FILE_NAME}"


def _archive_only(backup_file) -> bool:
    """Mid-stream filter: keep the status bar archive, drain everything else.

    Imports ``_path_match`` lazily -- ``protective`` installs a runtime shim on
    import and we do not want to drag that in just to build a one-file filter.
    """
    from src.restore.protective import _path_match

    return _path_match(backup_file.device_name or "", ARCHIVE_REL_PATH)


def extract_statusbar_archive(backup_root: str, udid: str, dest_path: str) -> Optional[str]:
    """Copy the status bar archive out of a backup directory.

    Resolves the payload by FILE NAME (the manifest path layout moves between
    iOS releases) and returns the destination path, or None when the backup
    carries no such file -- which is the normal answer on a device that has
    never had a status bar override applied.
    """
    device_dir = Path(backup_root) / udid
    if not device_dir.is_dir():
        if (Path(backup_root) / "Manifest.db").is_file():
            device_dir = Path(backup_root)
        else:
            return None

    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.is_file():
        return None

    conn = sqlite3.connect(str(manifest_db))
    try:
        rows = conn.execute(
            "SELECT fileID, relativePath FROM Files WHERE relativePath LIKE ?",
            (f"%{ARCHIVE_FILE_NAME}",),
        ).fetchall()
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()

    if not rows:
        return None

    # Prefer the shortest path: the HomeDomain copy is the real file, while
    # longer matches could be a backup-of-a-backup or a container copy.
    file_id, rel_path = sorted(rows, key=lambda r: len(r[1]))[0]
    payload = device_dir / file_id[:2] / file_id
    if not payload.is_file():
        return None

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload.read_bytes())
    return str(dest)


def dump_path(udid: str) -> str:
    """Default location for this device's archive dump."""
    from src.restore.storage import statusbar_dir

    return str(statusbar_dir() / f"{udid}.{ARCHIVE_FILE_NAME}")


async def targeted_statusbar_archive_fetch(udid: str,
                                           update_label=lambda x: None,
                                           update_progress=lambda x: None,
                                           dest_path: Optional[str] = None) -> Optional[str]:
    """Back up ONLY the status bar archive and return its path, or None.

    None is the expected answer when the device has no archive yet (no override
    has ever been applied, or SpringBoard unlinked a reset record). That is not
    an error -- it just means there is nothing to research.
    """
    dest = dest_path or dump_path(udid)
    max_retries = 3

    from src.exceptions.device_errors import is_connection_error as _is_connection_error
    from src.exceptions.device_errors import (
        is_device_locked_error as _is_device_locked_error,
    )

    def _on_retry(attempt: int, total: int, e: Exception, delay: float) -> None:
        if attempt < total:
            update_label(f"Connection lost, retrying in {delay}s... "
                         f"(attempt {attempt}/{max_retries})")

    async def _attempt():
        with tempfile.TemporaryDirectory(prefix="nugget_sb_only_") as backup_dir:
            async with lockdown_session(udid) as service_provider:
                async with Mobilebackup2Service(service_provider) as backup_client:
                    try:
                        await backup_client.backup(
                            full=True, backup_directory=backup_dir,
                            progress_callback=update_progress,
                            filter_callback=_archive_only)
                    except Exception as e:
                        if _is_device_locked_error(e):
                            raise NuggetException(
                                "Device locked during backup. Please unlock your device, "
                                "keep it awake (tap the screen periodically), and try again.")
                        raise
            update_label("Getting the file...")
            return extract_statusbar_archive(backup_dir, udid, dest)

    return await async_retry(
        _attempt, max_retries, retry_if=_is_connection_error, exp_cap=15,
        on_retry=_on_retry)


def describe(payload: bytes) -> str:
    """Human-readable dump of an archive's schema.

    Prints every class name, every key on ``STStatusBarData`` and every key on
    each entry, which is exactly the information the writer needs and cannot
    get from source. Reuses the real unarchiver from ``statusbar_archive`` so
    the report reflects what SpringBoard's reader would see.
    """
    from src.tweaks.status_bar import statusbar_archive as sba

    data, objects = sba.status_bar_data(payload)
    lines = [f"payload: {len(payload)} bytes", ""]

    lines.append("class names:")
    for i, obj in enumerate(objects):
        if isinstance(obj, dict) and "$classname" in obj:
            lines.append(f"  [{i}] {obj['$classname']}")
            for cls in obj.get("$classes", []):
                lines.append(f"        {cls}")

    lines.append("")
    lines.append("STStatusBarData keys:")
    for key, value in sorted(data.items()):
        if key == "$class":
            continue
        if isinstance(value, plistlib.UID):
            entry = objects[value.data] if value.data < len(objects) else None
            if isinstance(entry, dict):
                cname = None
                c = entry.get("$class")
                if isinstance(c, plistlib.UID) and c.data < len(objects):
                    cname = objects[c.data].get("$classname")
                lines.append(f"  {key}: -> [{value.data}] ({cname})")
                for k, v in sorted(entry.items()):
                    if k == "$class":
                        continue
                    lines.append(f"      {k}: {_render(v, objects)}")
            else:
                lines.append(f"  {key}: -> [{value.data}]")
        else:
            lines.append(f"  {key}: {_render(value, objects)}")

    return "\n".join(lines)


def _render(value, objects) -> str:
    """Render a leaf value, following one UID hop into the object table."""
    if isinstance(value, plistlib.UID):
        if value.data < len(objects):
            return f"-> [{value.data}] {objects[value.data]!r}"
        return f"-> [{value.data}] (out of range)"
    return repr(value)

