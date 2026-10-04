"""Regression tests for the PosterBoard snapshot check.

Background: iOS 26 uploads the PosterBoard database WITHOUT its ``-wal``
sibling, so what ``extract_posterboard_db`` copies out of the backup is a plain
copy of a database PosterBoard is still writing. A copy that races a checkpoint
comes out torn, and the user used to be told their "backup was interrupted" and
sent off to re-create a backup that was never the problem. The pull now retries
instead.

Run: .venv/bin/python tools/test_posterboard_snapshot.py
"""

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.exceptions.nugget_exception import NuggetException
from src.tweaks.posterboard.db_validate import (
    IncompletePosterBoardSnapshot, POSTERBOARD_TABLES, is_encrypted_database,
    posterboard_db_is_snapshot_ok, snapshot_problem)

TMP = tempfile.mkdtemp(prefix="nugget_pb_snapshot_test_")
FAILURES = []
CHECKS = 0


def check(label, condition):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(label)
        print(f"FAIL  {label}")
    else:
        print(f"ok    {label}")


def _make_schema(conn):
    conn.execute("CREATE TABLE poster (posterId INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "UUID TEXT, providerId TEXT)")
    conn.execute("CREATE TABLE posterAttributes (identifier INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "posterUUID TEXT, roleId TEXT, attributeIdentifier TEXT, attributePayload BLOB)")
    conn.execute("CREATE TABLE posterRoleMembership (posterUUID TEXT, roleId TEXT, roleSortKey INTEGER)")
    # db5+ extras seen on iOS 26/27
    conn.execute("CREATE TABLE posterRoles (roleId TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE posterMetadata (posterUUID TEXT, key TEXT, value TEXT)")


def make_good_db(path, rows=3, wal=True):
    """A healthy WAL-mode PosterBoard-like database (like the device ships)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL" if wal else "PRAGMA journal_mode=DELETE")
    _make_schema(conn)
    conn.executemany("INSERT INTO poster (UUID, providerId) VALUES (?, ?)",
                     [(f"uuid-{i}", "com.apple.wallpaper") for i in range(rows)])
    conn.commit()
    if wal:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


def tear_header(path):
    """A copy that raced a checkpoint: header claims more pages than the file holds."""
    with open(path, "r+b") as f:
        header = bytearray(f.read(100))
        pages = int.from_bytes(header[28:32], "big")
        header[28:32] = (pages + 4).to_bytes(4, "big")
        f.seek(0)
        f.write(header)
        f.truncate(os.path.getsize(path) - 4096)  # and drop the last page
    return path


def tear_page(path):
    """Same story, different damage: an interior page zeroes out."""
    shutil.copyfile(good_for_torn, path)
    with open(path, "r+b") as f:
        f.seek(4096 * 2)
        f.write(b"\x00" * 4096)
    return path


print("== snapshot_problem ==")
good = make_good_db(os.path.join(TMP, "good.sqlite3"))
check("healthy WAL database is accepted", posterboard_db_is_snapshot_ok(good))
check("healthy database reports no problem", snapshot_problem(good) is None)
check("healthy database is not flagged as encrypted", not is_encrypted_database(good))

good_for_torn = good
torn = tear_header(make_good_db(os.path.join(TMP, "torn.sqlite3")))
problem = snapshot_problem(torn)
check("torn (bad page count) is rejected", problem is not None)
check(f"torn page-count reason is specific ({problem!r})",
      "malformed" in (problem or "").lower() or "integrity" in (problem or "").lower())

zeroed = tear_page(os.path.join(TMP, "zeroed.sqlite3"))
problem = snapshot_problem(zeroed)
check("torn (blanked page) is rejected", problem is not None)
check(f"blanked-page reason is specific ({problem!r})",
      "integrity" in (problem or "").lower() or "malformed" in (problem or "").lower())

check("missing file is rejected", snapshot_problem(os.path.join(TMP, "nope.sqlite3")))
tiny = os.path.join(TMP, "tiny.sqlite3")
open(tiny, "wb").write(b"SQLite format 3\x00")
check("truncated stub is rejected", snapshot_problem(tiny) is not None)

not_db = os.path.join(TMP, "notdb.sqlite3")
with open(not_db, "wb") as f:
    f.write(b"\x00" * 4096)
check("non-sqlite blob is rejected", snapshot_problem(not_db) is not None)
# A file SQLite cannot open at all is exactly what SQLCipher looks like, so the
# existing heuristic (unchanged) reports it as encrypted rather than corrupt.
check("an unopenable blob is treated as encrypted, not as a broken schema",
      is_encrypted_database(not_db))

other = sqlite3.connect(os.path.join(TMP, "other.sqlite3"))
other.execute("CREATE TABLE something (a INTEGER)")
other.commit()
other.close()
check("unrelated database fails strict", not posterboard_db_is_snapshot_ok(
    os.path.join(TMP, "other.sqlite3"), strict=True))
check("unrelated database fails loose too", not posterboard_db_is_snapshot_ok(
    os.path.join(TMP, "other.sqlite3"), strict=False))

only_poster = sqlite3.connect(os.path.join(TMP, "partial.sqlite3"))
only_poster.execute("CREATE TABLE poster (a INTEGER)")
only_poster.commit()
only_poster.close()
check("database missing tables fails strict", not posterboard_db_is_snapshot_ok(
    os.path.join(TMP, "partial.sqlite3"), strict=True))
check("database with poster-ish table passes loose", posterboard_db_is_snapshot_ok(
    os.path.join(TMP, "partial.sqlite3"), strict=False))
check("missing required table is named in the reason",
      any(t in (snapshot_problem(os.path.join(TMP, "partial.sqlite3")) or "")
          for t in POSTERBOARD_TABLES))

print("\n== require_usable_snapshot ==")
from src.tweaks.posterboard.db_validate import require_usable_snapshot
try:
    require_usable_snapshot(good)
    check("usable snapshot does not raise", True)
except NuggetException as e:
    check("usable snapshot does not raise", False)
try:
    require_usable_snapshot(torn)
    check("torn snapshot raises", False)
except IncompletePosterBoardSnapshot as e:
    check("torn snapshot raises IncompletePosterBoardSnapshot", True)
    check("exception carries a detailed explanation", bool(e.detailed_text))
    check("exception is a NuggetException", isinstance(e, NuggetException))

print("\n== targeted_posterboard_database_backup retries a torn copy ==")
import src.restore.posterboard_backup as pbb

good_bytes = open(good, "rb").read()
torn_bytes = open(torn, "rb").read()
attempts = {"n": 0, "served": []}


class FakeExtraction:
    """Stands in for extract_posterboard_db: serves torn first, then good."""

    def __init__(self):
        self.calls = 0

    def __call__(self, backup_dir, udid, dest):
        self.calls += 1
        attempts["n"] += 1
        payload = torn_bytes if self.calls == 1 else good_bytes
        attempts["served"].append("torn" if payload is torn_bytes else "good")
        with open(dest, "wb") as f:
            f.write(payload)
        require_usable_snapshot(dest)  # same gate the real extractor uses
        return dest, 61


labels = []
fake = FakeExtraction()

import src.restore.protective as protective
real_extractor = protective.extract_posterboard_db
protective.extract_posterboard_db = fake

# every device-facing dependency is faked: only the retry logic is under test
class FakeServiceProvider:
    all_values = {"ProductVersion": "26.5.2"}


class FakeLockdown:
    async def __aenter__(self):
        return FakeServiceProvider()

    async def __aexit__(self, *a):
        return False


class FakeBackupClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def backup(self, *a, **kw):
        return None


class FakeBackup2:
    def __init__(self, sp):
        pass

    async def __aenter__(self):
        return FakeBackupClient()

    async def __aexit__(self, *a):
        return False


import src.devicemanagement.session as session_mod
pbb.lockdown_session = lambda udid: FakeLockdown()
pbb.Mobilebackup2Service = FakeBackup2
pbb.is_supported_by_fork = lambda v: True
protective.extract_posterboard_db = fake
delays = []


async def _instant_sleep(seconds):
    """Record the backoff the retry loop asked for, without waiting it out."""
    delays.append(seconds)


# the retry backoff is not what is under test — keep the run quick
pbb.async_retry.__globals__["asyncio"].sleep = _instant_sleep


async def run_fetch():
    return await pbb.targeted_posterboard_database_backup(
        "TESTUDID", labels.append, lambda v: None)


try:
    result = asyncio.run(run_fetch())
    check("fetch succeeds after a torn first pull", result is not None)
    check(f"it re-pulled exactly once (served={attempts['served']})", fake.calls == 2)
    check("a retry was announced to the user",
          any("incomplete" in str(x).lower() for x in labels), )
    check(f"the retry waited the usual backoff ({delays})", delays == [2])
finally:
    protective.extract_posterboard_db = real_extractor

print("\n== a torn pull every time fails loudly (no silent success) ==")


class AlwaysTorn(FakeExtraction):
    def __call__(self, backup_dir, udid, dest):
        self.calls += 1
        attempts["n"] += 1
        with open(dest, "wb") as f:
            f.write(torn_bytes)
        require_usable_snapshot(dest)
        return dest, 61


always = AlwaysTorn()
protective.extract_posterboard_db = always
try:
    asyncio.run(pbb.targeted_posterboard_database_backup(
        "TESTUDID", labels.append, lambda v: None))
    check("persistent failure raises", False)
except IncompletePosterBoardSnapshot:
    check("persistent failure raises IncompletePosterBoardSnapshot", True)
    check(f"it tried all 3 attempts (calls={always.calls})", always.calls == 3)
except Exception as e:
    check(f"persistent failure raises IncompletePosterBoardSnapshot (got {type(e).__name__})", False)
finally:
    protective.extract_posterboard_db = real_extractor

print("\n== the real extractor's gate ==")
# Build a fake backup tree: Manifest.db + the database payload, no -wal sibling.
backup_root = os.path.join(TMP, "backup")
udid = "FAKEUDID"
device_dir = os.path.join(backup_root, udid)
os.makedirs(device_dir, exist_ok=True)
rel = ("Library/Application Support/PRBPosterExtensionDataStore/61/"
       "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3")
file_id = "ab" + "0" * 58
os.makedirs(os.path.join(device_dir, "ab"), exist_ok=True)
shutil.copyfile(good, os.path.join(device_dir, "ab", file_id))

manifest = sqlite3.connect(os.path.join(device_dir, "Manifest.db"))
manifest.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, "
                 "flags INTEGER, file BLOB)")
manifest.execute("INSERT INTO Files VALUES (?,?,?,?,NULL)",
                 (file_id, "AppDomain-com.apple.PosterBoard", rel, 1))
manifest.commit()
manifest.close()

extracted = protective.extract_posterboard_db(
    backup_root, udid, os.path.join(TMP, "extracted.sqlite3"))
check("a good payload extracts", extracted is not None)
check("the extracted copy is usable", posterboard_db_is_snapshot_ok(extracted[0]))
check("structure version is parsed from the path", extracted and extracted[1] == 61)

# now the payload in the backup is torn
shutil.copyfile(torn, os.path.join(device_dir, "ab", file_id))
try:
    protective.extract_posterboard_db(
        backup_root, udid, os.path.join(TMP, "extracted_torn.sqlite3"))
    check("a torn payload raises instead of being handed out", False)
except IncompletePosterBoardSnapshot as e:
    check("a torn payload raises instead of being handed out", True)
    check("the raise explains the torn copy", "incomplete" in str(e).lower())

# a manifest without the PosterBoard container still returns None (unchanged)
manifest = sqlite3.connect(os.path.join(device_dir, "Manifest.db"))
manifest.execute("DELETE FROM Files")
manifest.commit()
manifest.close()
check("a missing container still returns None",
      protective.extract_posterboard_db(
          backup_root, udid, os.path.join(TMP, "none.sqlite3")) is None)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL ' + str(CHECKS) + ' CHECKS PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURES'}")
sys.exit(1 if FAILURES else 0)