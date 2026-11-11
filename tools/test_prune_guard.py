#!/usr/bin/env python3
"""Offline test for the prune guard (no device needed).

prune_protective_backups must never delete a run whose restore never
completed: after a failed apply the device is wiped and that run may be the
only surviving copy of the user's photos. Run:
python tools/test_prune_guard.py
"""
import os
import plistlib
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["GOLDENNUGGET_BACKUP_DIR"] = tempfile.mkdtemp(prefix="gn_prune_test_")

from src.restore.protective import (  # noqa: E402
    list_protective_backups,
    mark_restore_ok,
    prune_protective_backups,
)

UDID = "00008101-PRUNETEST"
PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def make_run(udid: str, name: str) -> Path:
    """A minimal valid backup run (list_protective_backups only needs a
    readable Manifest.db inside device_backup/<udid>/)."""
    device_dir = (Path(os.environ["GOLDENNUGGET_BACKUP_DIR"]) / "protective"
                  / udid / name / "device_backup" / udid)
    device_dir.mkdir(parents=True)
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    conn.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
                 "relativePath TEXT, flags INTEGER, file BLOB)")
    conn.execute("INSERT INTO Files VALUES ('a', 'HomeDomain', 'x', 1, NULL)")
    conn.commit()
    conn.close()
    (device_dir.parent / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    return device_dir.parent.parent  # run dir


def mtime_of(run: Path) -> float:
    return run.stat().st_mtime


def main():
    udid = UDID
    old = make_run(udid, "run_old")   # photos from the previous apply
    time.sleep(0.02)
    new = make_run(udid, "run_new")   # fresh backup taken on the next apply
    assert mtime_of(new) > mtime_of(old)

    # No restore ever completed: nothing may be pruned.
    removed = prune_protective_backups(udid)
    check("never prunes without a completed restore", removed == 0)
    check("old run survives the guard", old.is_dir())

    # A restore completes AFTER the new run was taken (marker > run mtimes):
    # now the older run is fair game again.
    mark_restore_ok(udid)
    removed = prune_protective_backups(udid)
    check("prunes consumed runs after a completed restore", removed == 1)
    check("newest run kept", new.is_dir())

    # Two failed applies AFTER the completed restore: each takes a fresh run
    # whose restore never finishes (no new marker). The next prune may only
    # delete the run the completed restore consumed.
    time.sleep(0.02)
    failed2 = make_run(udid, "run_failed2")
    time.sleep(0.02)
    failed3 = make_run(udid, "run_failed3")
    removed = prune_protective_backups(udid)
    check("only the consumed run is pruned", removed == 1)
    check("unconsumed failed-apply runs kept",
          failed2.is_dir() and failed3.is_dir())
    check("consumed run gone", not new.is_dir())

    check("list excludes nothing here", len(list_protective_backups(udid)) == 2)

    print(f"\n{PASS} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
