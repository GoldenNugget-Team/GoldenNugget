"""PosterBoard snapshot validation.

Qt-free on purpose: the restore path (``src/restore/protective.py``) has to run
this check on the file it just pulled, and it must not drag PySide6 in.

Why this check exists
--------------------
The database PosterBoard runs on-device is a **live WAL-mode** SQLite file.
mobilebackup2 streams it while PosterBoard keeps writing, and iOS 26 does NOT
upload the ``-wal``/``-shm`` siblings, so what lands on disk is a plain copy of
the main file. When that copy races a checkpoint the file is **torn**: the
header page count and the b-tree pages disagree and ``PRAGMA integrity_check``
reports it. A torn file is unusable — without this gate the config manager only
saw it much later and blamed "an interrupted backup", which sends the user off to
re-create a backup that was never the problem.

``snapshot_problem`` returns None when the file is a usable snapshot and
otherwise a short reason, so the caller can re-pull the device AND tell the
user what was actually wrong.
"""

import sqlite3
from os import path
from typing import Optional, Union

from src.exceptions.nugget_exception import NuggetException

DB_FILE_NAME = "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"

#: Tables every usable PosterBoard database carries (the pre-db5 schema; db5+
#: adds posterRoles/posterMetadata on top, which is why the check is a subset).
POSTERBOARD_TABLES = ("poster", "posterAttributes", "posterRoleMembership", "sqlite_sequence")

PathLike = Union[str, "os.PathLike[str]"]  # noqa: F821


class IncompletePosterBoardSnapshot(NuggetException):
    """The pulled PosterBoard file is not a usable snapshot — re-pull the device.

    Raised by the extraction path so callers can distinguish "the device shipped
    a torn copy" (retryable: pull again) from "this file simply isn't a
    PosterBoard database" (the user picked the wrong file).
    """


def list_tables(db_path) -> list[str]:
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            return [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return []


def is_encrypted_database(db_path) -> bool:
    """Check if a database file appears to be encrypted (SQLCipher) or unreadable."""
    if not path.exists(db_path) or path.getsize(db_path) < 100:
        return False
    try:
        # Try to open as regular SQLite first
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        conn.close()
        return False
    except sqlite3.DatabaseError as e:
        # Check if it's an encryption-related error
        err_msg = str(e).lower()
        if "encrypted" in err_msg or "not a database" in err_msg or "file is not a database" in err_msg:
            return True
        return False
    except Exception:
        return False


def snapshot_problem(db_path, strict: bool = True) -> Optional[str]:
    """Describe why ``db_path`` is not a usable PosterBoard snapshot, else None.

    strict=True requires the classic table set (pre-db5 schema).
    strict=False accepts any healthy database that carries poster-ish
    tables — the schema may change between iOS releases (db5+).
    """
    if not path.exists(db_path) or path.getsize(db_path) < 100:
        return f"missing or too small ({0 if not path.exists(db_path) else path.getsize(db_path)} bytes)"
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.DatabaseError as e:
        return f"cannot be opened as SQLite ({e})"
    try:
        # First check it's a valid SQLite database
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except sqlite3.DatabaseError as e:
            return f"not a readable SQLite database ({e})"
        cursor = conn.cursor()
        if strict:
            for tab in POSTERBOARD_TABLES:
                cursor.execute(f"PRAGMA table_info({tab})")
                if cursor.fetchone() is None:
                    return f"missing table '{tab}' (tables present: {list_tables(db_path)})"
        else:
            tables = [t.lower() for t in list_tables(db_path)]
            if not any("poster" in t for t in tables):
                return f"no poster-ish tables (present: {tables})"
        # Check database integrity — this is what catches a copy that raced a
        # checkpoint, and the per-page report is the only useful diagnostic.
        try:
            rows = cursor.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as e:
            return f"integrity check failed to run ({e})"
        if not rows or rows[0][0] != "ok":
            report = "; ".join(str(r[0]).replace("\n", " ").strip() for r in rows[:3])
            return f"integrity check: {report}"
        return None
    except Exception as e:  # noqa: BLE001 — any failure means "not usable"
        return f"unusable ({type(e).__name__}: {e})"
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def posterboard_db_is_snapshot_ok(db_path, strict: bool = True) -> bool:
    return snapshot_problem(db_path, strict=strict) is None


def require_usable_snapshot(db_path, strict: bool = True) -> None:
    """Raise :class:`IncompletePosterBoardSnapshot` unless the file is usable."""
    problem = snapshot_problem(db_path, strict=strict)
    if problem is not None:
        raise IncompletePosterBoardSnapshot(
            "The PosterBoard database copied off the device is incomplete "
            f"({problem}).",
            detailed_text=(
                "PosterBoard keeps its database open while writing, and iOS does "
                "not include its write-ahead log in the backup, so a copy taken "
                "at the wrong moment comes out inconsistent. Fetching the "
                "database again usually lands between two writes."))