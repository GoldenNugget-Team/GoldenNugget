#!/usr/bin/env python3
"""Offline test for the full-PosterBoard-reset empty database (no device needed).

Regression cover for a hard failure of the reset path:

    sqlite3.OperationalError: object name reserved for internal use: sqlite_sequence

``create_empty_posterboard_db`` used to finish with an explicit
``CREATE TABLE IF NOT EXISTS sqlite_sequence (name TEXT, seq INTEGER)``, which
SQLite **always** rejects: the reserved-name check in the table-creation path
runs before the ``IF NOT EXISTS`` lookup, so it fails even when the table is
already there (and it is — the ``AUTOINCREMENT`` column on ``poster`` creates
``sqlite_sequence`` as part of the very first statement). The statement came in
with the full-reset feature itself, so that path could never have run.

Exercises: the shell the reset injects into the on-device store, the strict
table check it has to satisfy (:data:`POSTERBOARD_TABLES`), and the reason the
explicit create must never come back.

Run: python tools/test_posterboard_reset_db.py
"""
import ast
import inspect
import os
import plistlib
import re
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.exceptions.nugget_exception import NuggetException
from src.tweaks.posterboard import pb_config_manager as pb_mod
from src.tweaks.posterboard import posterboard_tweak as posterboard_tweak_mod
from src.tweaks.posterboard.pb_config_manager import (
    DB_FILE_NAME,
    POSTERBOARD_TABLES,
    _list_tables,
    _validate_posterboard_db,
    create_empty_posterboard_db,
)

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_pb_reset_")


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def empty_shell(name="empty_posterboard.sqlite3"):
    return create_empty_posterboard_db(os.path.join(TMP, name))


def test_shell_is_created():
    print("\nthe reset shell is actually created")
    dest = os.path.join(TMP, "shell.sqlite3")
    ret = create_empty_posterboard_db(dest)

    check("creating it does not raise (the pinned regression)", os.path.isfile(dest))
    check("...and it returns the path it wrote", ret == dest, ret)
    check("...with real content, not a 0-byte file",
          os.path.getsize(dest) > 4096, f"{os.path.getsize(dest)} bytes")
    check("a second call over the same path is idempotent",
          create_empty_posterboard_db(dest) == dest)


def test_shell_satisfies_the_strict_check():
    print("\nthe shell satisfies the table check the reset depends on")
    dest = empty_shell("strict.sqlite3")
    tables = _list_tables(dest)

    check("the strict validator accepts it (it goes straight to the device)",
          _validate_posterboard_db(dest) is True, tables)
    check("...so does the loose one", _validate_posterboard_db(dest, strict=False) is True)
    check("all four POSTERBOARD_TABLES are present, by name",
          set(POSTERBOARD_TABLES) <= set(tables), tables)
    with sqlite3.connect(dest) as conn:
        missing = [t for t in POSTERBOARD_TABLES
                   if conn.execute(f"PRAGMA table_info({t})").fetchone() is None]
        check("...each of them resolvable through PRAGMA table_info", not missing, missing)
        check("integrity_check says ok",
              conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
        check("it is empty: no poster rows come back with it",
              conn.execute("SELECT COUNT(*) FROM poster").fetchone()[0] == 0)


def test_sequence_table_is_the_internal_one():
    print("\nsqlite_sequence is SQLite's own table, not a hand-made one")
    dest = empty_shell("seq.sqlite3")
    with sqlite3.connect(dest) as conn:
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone()
        poster_ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'poster'").fetchone()[0]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sqlite_sequence)")]

        check("it exists", ddl is not None)
        check("...created implicitly (the DDL is SQLite's, not ours)",
              ddl is not None and ddl[0] == "CREATE TABLE sqlite_sequence(name,seq)", ddl)
        check("...with exactly (name, seq)", cols == ["name", "seq"], cols)
        check("the AUTOINCREMENT column that creates it is still on poster",
              "AUTOINCREMENT" in poster_ddl.upper(), poster_ddl[:48])

        conn.execute("INSERT INTO poster (UUID, providerId) VALUES ('u', 'p')")
        seq = conn.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
        check("...and it behaves: an insert allocates posterId 1", seq == [("poster", 1)], seq)


def test_reserved_name_cannot_be_created():
    print("\nwhy the explicit create had to go")
    dest = empty_shell("reserved.sqlite3")
    with sqlite3.connect(dest) as conn:
        raised = None
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS sqlite_sequence ("
                         "name TEXT, seq INTEGER)")
        except sqlite3.OperationalError as e:
            raised = str(e)
        check("CREATE TABLE IF NOT EXISTS sqlite_sequence still raises",
              raised is not None and "reserved for internal use" in raised, raised)
        # ...even though the table is demonstrably present
        check("...despite the table already existing",
              conn.execute("SELECT 1 FROM sqlite_master WHERE name = "
                           "'sqlite_sequence'").fetchone() is not None)

    src = inspect.getsource(pb_mod)
    check("no source create names sqlite_sequence any more",
          "CREATE TABLE IF NOT EXISTS sqlite_sequence" not in src)
    # Check the statements that actually run: every string literal handed to a
    # call (so docstrings, which mention the reserved name on purpose, are not
    # mistaken for SQL). The other sqlite_sequence statements (INSERT/UPDATE on
    # the real table) are legitimate and must stay; only a CREATE is impossible.
    for path, expect_writes in (("src/tweaks/posterboard/pb_config_manager.py", True),
                                ("src/tweaks/posterboard/posterboard_tweak.py", False)):
        text = open(os.path.join(os.path.dirname(__file__), "..", path),
                    encoding="utf-8").read()
        stmts = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                stmts += [a.value for a in node.args
                          if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        offenders = [s for s in stmts
                     if re.search(r"CREATE\s+TABLE", s, re.IGNORECASE)
                     and "sqlite_sequence" in s]
        check(f"no SQL run by {os.path.basename(path)} creates it",
              not offenders, offenders)
        if expect_writes:
            # Sanity check on the extraction itself: this module really does
            # write sqlite_sequence (INSERT/UPDATE), so an empty `stmts` would
            # make the check above pass vacuously.
            check("...while the legitimate sqlite_sequence writes remain",
                  any("sqlite_sequence" in s for s in stmts),
                  f"{len(stmts)} string statements")


def test_incomplete_shell_is_refused():
    print("\nan incomplete shell is refused instead of shipped")
    dest = empty_shell("guard.sqlite3")

    # the premise: the strict check really does reject a shell missing a table
    thin = os.path.join(TMP, "thin.sqlite3")
    with sqlite3.connect(thin) as conn:
        conn.execute("CREATE TABLE poster (posterId INTEGER PRIMARY KEY AUTOINCREMENT)")
    check("a DB missing the other three tables fails the strict check",
          _validate_posterboard_db(thin) is False, _list_tables(thin))

    real_validate = pb_mod._validate_posterboard_db
    pb_mod._validate_posterboard_db = lambda *a, **kw: False
    try:
        raised = None
        try:
            create_empty_posterboard_db(dest)
        except NuggetException as e:
            raised = str(e)
    finally:
        pb_mod._validate_posterboard_db = real_validate
    check("a shell that fails validation raises instead of returning",
          raised is not None and "could not be created correctly" in raised,
          (raised or "")[:72])
    check("...and says the reset was stopped before wiping",
          raised is not None and "before wiping" in raised)


def test_reset_path_still_ships_the_shell():
    print("\nthe reset path still hands the shell to the device")
    src = inspect.getsource(posterboard_tweak_mod)

    check("the full reset still builds the empty DB",
          "empty_db = create_empty_posterboard_db(" in src)
    check("...in the run's output dir",
          '"empty_posterboard.sqlite3"' in src)
    check("...and injects it at the structure-versioned store path",
          "{self.structure_version}/{DB_FILE_NAME}" in src, DB_FILE_NAME)
    check("...with the 0-byte -wal/-shm companions (WAL dead-zone)",
          'for wal_suffix in ("-wal", "-shm")' in src
          and "restore_path=db_path + wal_suffix" in src)
    check("the whole container is still wiped for a full reset",
          "Extensions" in src and "GalleryCache" in src and "Backups" in src)


def run_full_reset(version="27.0", structure_version=65):
    """Run the real full-reset branch and return (tweak, files_to_restore)."""
    tweak = posterboard_tweak_mod.PosterboardTweak()
    tweak.full_reset = True
    tweak.config_manager.structure_version = structure_version
    out = os.path.join(TMP, f"reset_{version}_{structure_version}")
    os.makedirs(out, exist_ok=True)
    files = []
    tweak.apply_tweak(files, output_dir=out, templates=[], version=version,
                      force_pb_refresh=False)
    return tweak, files


def test_full_reset_end_to_end():
    print("\nthe full reset branch runs for real (it could never get this far)")
    tweak, files = run_full_reset("27.0", 65)
    store = "/Library/Application Support/PRBPosterExtensionDataStore"
    db_path = f"{store}/65/{DB_FILE_NAME}"
    by_path = {f.restore_path: f for f in files}

    check("the structure version is learned from the config manager, not 61",
          tweak.structure_version == 65, tweak.structure_version)
    check("the emptied container and the fresh DB are all it emits",
          len(files) == 7, [f.restore_path.replace(store, "…") for f in files])
    check("every entry targets the PosterBoard app domain",
          all(f.domain == "AppDomain-com.apple.PosterBoard" for f in files),
          sorted({f.domain for f in files}))
    check("Extensions / GalleryCache / Backups are zeroed out",
          all(by_path[f"{store}/65/{d}"].contents == b""
              for d in ("Extensions", "GalleryCache", "Backups")))
    check("the fresh DB lands on the versioned store path", db_path in by_path)
    check("...with 0-byte -wal/-shm companions (WAL dead-zone)",
          by_path[db_path + "-wal"].contents == b""
          and by_path[db_path + "-shm"].contents == b"")
    check("the reset plist is written",
          any("unprotectedUserDefaults.plist" in p for p in by_path),
          [p for p in by_path if "Preferences" in p])

    # the file that actually gets injected onto the device
    shell = by_path[db_path].contents_path
    check("the injected DB exists where the entry points",
          shell is not None and os.path.isfile(shell), shell)
    check("...and passes the strict validator", _validate_posterboard_db(shell) is True,
          _list_tables(shell))
    check("...so PosterBoard gets all four tables after the wipe",
          set(POSTERBOARD_TABLES) <= set(_list_tables(shell)))

    plist_path = next(p for p in by_path if "unprotectedUserDefaults.plist" in p)
    plist = plistlib.loads(by_path[plist_path].contents)
    check("the plist asks PosterBoard to reset its file protections",
          plist.get("PBF_RESET_FILE_PROTECTIONS") is True, plist)
    check("it carries the 26.4+ bundle-identifier migrations on iOS 27",
          "PersistedPosterContainerBundleIdentifiers" in plist
          and "CompletedPosterBundleIdentifierMigrations" in plist)

    _old_tweak, old_files = run_full_reset("26.0", 61)
    old_plist = plistlib.loads(next(
        f.contents for f in old_files if "unprotectedUserDefaults.plist" in f.restore_path))
    check("...and omits them below 26.4 (the version gate still bites)",
          "PersistedPosterContainerBundleIdentifiers" not in old_plist
          and "CompletedPosterBundleIdentifierMigrations" not in old_plist, old_plist)
    check("the older device's store uses its own structure version",
          any("/PRBPosterExtensionDataStore/61/" in f.restore_path for f in old_files),
          [f.restore_path.split("DataStore")[-1] for f in old_files][:3])


def main():
    test_shell_is_created()
    test_shell_satisfies_the_strict_check()
    test_sequence_table_is_the_internal_one()
    test_reserved_name_cannot_be_created()
    test_incomplete_shell_is_refused()
    test_reset_path_still_ships_the_shell()
    test_full_reset_end_to_end()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
