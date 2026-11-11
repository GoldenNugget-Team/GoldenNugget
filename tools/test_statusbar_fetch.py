#!/usr/bin/env python3
"""Offline tests for the StatusBarOverrides.archive fetch channel (no device).

The fetch is what unblocks migrating the remaining status bar tweaks to the
iOS 27 archive: it is the only way to read back the schema SpringBoard itself
wrote. Its manifest resolution therefore has to be trustworthy, because a
silent "nothing found" sends us off guessing key names again.

Run: python tools/test_statusbar_fetch.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore import statusbar_fetch as sf  # noqa: E402

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}")


def make_backup(root, udid, rows, write_payload=True):
    """Synthesize a backup dir: ``rows`` is [(fileID, relativePath)]."""
    device_dir = Path(root) / udid
    device_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    conn.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INTEGER)")
    for file_id, rel in rows:
        conn.execute("INSERT INTO Files VALUES (?,?,?,?)", (file_id, "HomeDomain", rel, 1))
        if write_payload:
            payload = device_dir / file_id[:2] / file_id
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_bytes(b"ARCHIVE:" + rel.encode())
    conn.commit()
    conn.close()
    return device_dir


def test_filter_matches_every_layout():
    keep = sf._archive_only
    target = "Library/SpringBoard/StatusBarOverrides.archive"
    # bare physical path (iOS 26)
    check("bare path kept", keep(type("F", (), {"device_name": target})()))
    # domain-qualified (iOS 26 legacy)
    check("HomeDomain-qualified kept",
          keep(type("F", (), {"device_name": f"HomeDomain/{target}"})()))
    # iOS 27 raw filesystem tree
    check("iOS 27 tree kept",
          keep(type("F", (), {"device_name": f"/.b/3/{target}"})()))
    # a sibling file in the same folder must NOT be kept, or the run stops
    # being a one-file dump
    check("sibling file rejected",
          not keep(type("F", (), {"device_name": "Library/SpringBoard/StatusBar.plist"})()))
    check("app container rejected",
          not keep(type("F", (), {"device_name":
                                  "Containers/Data/Application/X/Library/SpringBoard/StatusBarOverrides.archive"})()))
    check("empty name rejected", not keep(type("F", (), {"device_name": None})()))


def test_extract_finds_payload():
    rel = "Library/SpringBoard/StatusBarOverrides.archive"
    with tempfile.TemporaryDirectory() as root:
        make_backup(root, "UDID1", [("abcdef0123", rel)])
        out = Path(root) / "out.archive"
        got = sf.extract_statusbar_archive(root, "UDID1", str(out))
        check("payload extracted", got == str(out) and out.is_file())
        check("payload bytes intact", out.read_bytes() == b"ARCHIVE:" + rel.encode())


def test_extract_prefers_shortest_path():
    short = "Library/SpringBoard/StatusBarOverrides.archive"
    long = "Library/SpringBoard/Nested/Copy/StatusBarOverrides.archive"
    with tempfile.TemporaryDirectory() as root:
        make_backup(root, "UDID2", [("aaaa111111", long), ("bbbb222222", short)])
        out = Path(root) / "out.archive"
        sf.extract_statusbar_archive(root, "UDID2", str(out))
        check("shortest (HomeDomain) path wins", out.read_bytes() == b"ARCHIVE:" + short.encode())


def test_extract_missing_is_none_not_error():
    rel = "Library/Preferences/com.apple.springboard.plist"
    with tempfile.TemporaryDirectory() as root:
        # manifest present, archive absent -> the normal "device has no
        # override applied yet" answer, must be None and not an exception
        make_backup(root, "UDID3", [("cccc333333", rel)])
        check("no archive -> None",
              sf.extract_statusbar_archive(root, "UDID3", str(Path(root) / "o")) is None)

    with tempfile.TemporaryDirectory() as root:
        # no device dir and no manifest at all
        check("no manifest -> None",
              sf.extract_statusbar_archive(root, "UDID4", str(Path(root) / "o")) is None)

    with tempfile.TemporaryDirectory() as root:
        # manifest row exists but its payload was drained -> None, not a crash
        make_backup(root, "UDID5",
                    [("dddd444444", "Library/SpringBoard/StatusBarOverrides.archive")],
                    write_payload=False)
        check("missing payload -> None",
              sf.extract_statusbar_archive(root, "UDID5", str(Path(root) / "o")) is None)

    with tempfile.TemporaryDirectory() as root:
        # corrupt manifest -> None
        (Path(root) / "UDID6").mkdir()
        (Path(root) / "UDID6" / "Manifest.db").write_bytes(b"not a database")
        check("corrupt manifest -> None",
              sf.extract_statusbar_archive(root, "UDID6", str(Path(root) / "o")) is None)


def test_falls_back_to_flat_backup_dir():
    # some flows keep Manifest.db at the root instead of under <udid>/
    with tempfile.TemporaryDirectory() as root:
        rel = "Library/SpringBoard/StatusBarOverrides.archive"
        make_backup(root, "", [("eeee555555", rel)])
        out = Path(root) / "o.archive"
        got = sf.extract_statusbar_archive(root, "UDID7", str(out))
        check("flat layout handled", got == str(out) and out.is_file())


def test_describe_reports_the_schema():
    from src.tweaks.status_bar.statusbar_archive import (
        build_archive,
        build_reset_archive,
    )

    report = sf.describe(build_archive("MegaFone", "BeeLine"))
    for needed in ("_SBSystemStatusStatusBarOverridesArchiveRecord",
                   "STStatusBarData", "STStatusBarDataCellularEntry",
                   "cellularEntry", "secondaryCellularEntry",
                   "MegaFone", "BeeLine"):
        check(f"describe reports {needed}", needed in report)

    reset = sf.describe(build_reset_archive())
    check("describe marks a reset record", "STStatusBarData keys:" in reset)
    check("reset has no cellular entry", "cellularEntry" not in reset)


def test_paths():
    check("relative path is HomeDomain-style",
          sf.ARCHIVE_REL_PATH == "Library/SpringBoard/StatusBarOverrides.archive")
    check("dump_path is per-udid", "UDIDX" in sf.dump_path("UDIDX"))


def main():
    print("StatusBarOverrides.archive fetch channel (offline)")
    test_filter_matches_every_layout()
    test_extract_finds_payload()
    test_extract_prefers_shortest_path()
    test_extract_missing_is_none_not_error()
    test_falls_back_to_flat_backup_dir()
    test_describe_reports_the_schema()
    test_paths()
    print(f"\nALL {PASS} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
