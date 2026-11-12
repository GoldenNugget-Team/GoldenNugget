#!/usr/bin/env python3
"""Offline test for the protective backup cache (no device needed).

Exercises: cache validity, hardlink working copies, prune interplay,
PosterBoard DB extraction. Run: python tools/test_protective_cache.py
"""
import os
import plistlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.protective import (
    ProtectiveBackupCache,
    clean_backup_for_restore,
    discard_restore_view,
    make_protective_working_copy,
    make_restore_view,
)
from src.restore.protective_cache import CACHE_FILTER_REVISION

UDID = "00008101-TESTUDID"
PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def make_manifest(device_dir: Path, rows):
    """rows: list of (domain, relative_path, payload_bytes or None, flags)."""
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    import hashlib
    for domain, rel, payload, *rest in rows:
        flags = rest[0] if rest else 1
        file_id = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        if payload is not None:
            pdir = device_dir / file_id[:2]
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / file_id).write_bytes(payload)
        conn.execute("INSERT OR REPLACE INTO Files VALUES (?, ?, ?, ?, NULL)", (file_id, domain, rel, flags))
    conn.commit()
    conn.close()


def main():
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="gn_cache_test_"))
    base = tmp / "cache"

    # --- build a fake master via the real cache paths ---
    cache = ProtectiveBackupCache(UDID, product_version="27.0")
    # redirect both bases into our temp dir (locate() scans them)
    cache._temp_base = tmp / "cache"
    cache._persist_base = tmp / "persist"
    cache.base = cache._temp_base
    cache.master_root = cache._temp_base / "master"
    cache.device_dir = cache.master_root / UDID
    cache.info_path = cache._temp_base / f"{UDID}.json"
    cache.device_dir.mkdir(parents=True, exist_ok=True)

    pb_payload = b"PBDB" * 100
    photo_payload = b"JPGDATA" * 500
    make_manifest(cache.device_dir, [
        ("HomeDomain", "Library/SpringBoard/IconState.plist", b"<plist>"),
        ("HomeDomain", "Library/SpringBoard", None, 2),          # directory row — no payload by design
        ("HomeDomain", "Library/Accounts", None, 2),             # directory row (regression: renameatx ENOENT)
        ("HomeDomain", "Library/Accounts/Accounts3.sqlite", b"acc"),
        ("CameraRollDomain", "DCIM/100APPLE/IMG.JPG", photo_payload),
        ("AppDomain-com.apple.PosterBoard",
         "Library/Application Support/PRBPosterExtensionDataStore/61/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3",
         pb_payload),
        ("HomeDomain", "Library/SMS/sms.db", None),  # drained mid-stream: row without payload
    ])
    for name, content in (("Status.plist", b"s"), ("Manifest.plist", plistlib.dumps({"IsEncrypted": False})), ("Info.plist", b"i")):
        (cache.device_dir / name).write_bytes(content)

    check("no master before first refresh marker", not cache.has_valid_master())
    import json
    base.mkdir(parents=True, exist_ok=True)
    with open(cache.info_path, "w") as f:
        json.dump({"udid": UDID, "product_version": "27.0",
                   "filter_revision": CACHE_FILTER_REVISION,
                   "encrypted": False}, f)
    check("master valid after marker", cache.has_valid_master())

    other = ProtectiveBackupCache(UDID, product_version="26.2")
    other._temp_base = cache._temp_base
    other._persist_base = cache._persist_base
    other.base, other.master_root = cache.base, cache.master_root
    other.device_dir = cache.device_dir
    other.info_path = cache.info_path
    check("version change invalidates master", not other.has_valid_master())

    # --- working copy is hardlinked and isolated ---
    wc = make_protective_working_copy(str(cache.master_root), UDID)
    wc_device = Path(wc) / UDID
    check("working copy exists", wc_device.is_dir())

    # --- prune drops drained rows + non-protective payloads in the COPY only ---
    removed_rows, _ = clean_backup_for_restore(wc, UDID)
    check("prune removed rows", removed_rows >= 1)
    conn = sqlite3.connect(str(wc_device / "Manifest.db"))
    rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("sms.db pruned from working copy", "Library/SMS/sms.db" not in rels)
    check("icon state kept", "Library/SpringBoard/IconState.plist" in rels)
    # directory rows MUST survive: without them the restore agent fails with
    # renameatx ENOENT when staging files into those directories
    check("directory row Library/SpringBoard kept", "Library/SpringBoard" in rels)
    check("directory row Library/Accounts kept", "Library/Accounts" in rels)
    check("Accounts3.sqlite kept", "Library/Accounts/Accounts3.sqlite" in rels)
    # the raw PB DB must NOT be restored in Phase 3 (it would clobber the
    # tweaked DB from Phase 2) — it is renewed separately on every apply
    check("posterboard db pruned from working copy",
          "Library/Application Support/PRBPosterExtensionDataStore/61/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"
          not in rels)

    # --- MessagesDomain is preserved across the wipe (issue #25) ---
    make_manifest(cache.device_dir, [
        ("MessagesDomain", "5B/00", None, 2),  # directory row
        ("MessagesDomain", "5B/00/Avatar", None, 2),
        ("MessagesDomain", "5B/00/2/0-09-48-02.sqlitedb", b"msgs"),
        ("KeychainDomain", "keychain-backup.plist", b"keychain" * 10),
    ])
    wc2 = make_protective_working_copy(str(cache.master_root), UDID)
    wc2_device = Path(wc2) / UDID
    # default (unencrypted) prune: keychain NOT kept, MessagesDomain kept
    removed_rows, _ = clean_backup_for_restore(wc2, UDID, include_photos=True)
    conn = sqlite3.connect(str(wc2_device / "Manifest.db"))
    rels2 = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("MessagesDomain db kept", any("0-09-48-02.sqlitedb" in r for r in rels2))
    check("keychain pruned when unencrypted", "keychain-backup.plist" not in rels2)
    # encrypted prune: keychain kept too
    wc3 = make_protective_working_copy(str(cache.master_root), UDID)
    wc3_device = Path(wc3) / UDID
    removed_rows, _ = clean_backup_for_restore(wc3, UDID, include_photos=True, include_keychain=True)
    conn = sqlite3.connect(str(wc3_device / "Manifest.db"))
    rels3 = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("keychain kept when encrypted", "keychain-backup.plist" in rels3)
    check("messages kept when encrypted", any("0-09-48-02.sqlitedb" in r for r in rels3))

    # --- master untouched by pruning of the copy; PB row survives there ---
    conn = sqlite3.connect(str(cache.device_dir / "Manifest.db"))
    master_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("master manifest still has sms.db row", "Library/SMS/sms.db" in master_rels)

    # --- restore view (apply flow): the master is IMMUTABLE ---
    # The apply prunes + tweak-injects a disposable view of the master, never
    # the master itself, so the master stays a pristine full-manifest mirror
    # (which is what the next incremental refresh diffs against).
    view_base = make_restore_view(str(cache.master_root), UDID, str(tmp / "view"))
    view_device = Path(view_base) / UDID
    check("restore view created", view_device.is_dir())
    check("restore view has its own manifest",
          (view_device / "Manifest.db").is_file())
    check("restore view manifest is a separate file (not a hardlink)",
          not _same_file(view_device / "Manifest.db", cache.device_dir / "Manifest.db"))
    accounts_id = _file_id_for("HomeDomain", "Library/Accounts/Accounts3.sqlite")
    accounts_payload = Path(accounts_id[:2]) / accounts_id
    check("restore view payloads are hardlinked to the master",
          _same_file(view_device / accounts_payload,
                     cache.device_dir / accounts_payload))

    # prune + inject the VIEW, never the master
    clean_backup_for_restore(view_base, UDID)
    conn = sqlite3.connect(str(view_device / "Manifest.db"))
    view_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("view pruned by the apply", "Library/SMS/sms.db" not in view_rels)
    check("view kept the protective rows",
          "Library/Accounts/Accounts3.sqlite" in view_rels)

    # the master is untouched: full manifest AND every payload still there
    conn = sqlite3.connect(str(cache.device_dir / "Manifest.db"))
    master_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("master manifest untouched by the apply",
          "Library/SMS/sms.db" in master_rels)
    check("master payload untouched by the apply",
          (cache.device_dir / accounts_payload).is_file())

    # dropping the view must not touch the master's data
    discard_restore_view(view_base, UDID)
    check("view removed", not view_device.exists())
    check("master payloads survive the view being dropped",
          (cache.device_dir / accounts_payload).is_file())
    conn = sqlite3.connect(str(cache.device_dir / "Manifest.db"))
    master_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("master manifest survives the view being dropped",
          "Library/SMS/sms.db" in master_rels)

    # --- an ENCRYPTED master is a usable master -------------------------
    # Regression: locate() required the master's Manifest.db to read as
    # SQLite, but an encrypted backup's Manifest.db is AES-encrypted. With
    # "Encrypted Backups" on, the cache therefore NEVER matched, every apply
    # silently ran a full backup (255k+ files re-uploaded) and the fast cache
    # did nothing at all.
    enc_base = tmp / "encrypted_cache"
    enc_udid = "00008101-ENCRYPTED"
    enc_device = enc_base / "master" / enc_udid
    enc_device.mkdir(parents=True)
    (enc_device / "Manifest.db").write_bytes(bytes(range(256)) * 16)  # AES blocks, not sqlite
    (enc_device / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))
    (enc_device / "Status.plist").write_bytes(plistlib.dumps({"BackupState": "finished"}))
    import json
    (enc_base / f"{enc_udid}.json").write_text(json.dumps({
        "udid": enc_udid, "product_version": "27.0", "filter_revision": CACHE_FILTER_REVISION,
        "encrypted": True, "created_ts": 1}), encoding="utf-8")

    enc_cache = _cache_in(enc_base, enc_udid, encrypted=True)
    check("encrypted master is usable", enc_cache.has_valid_master())
    check("encrypted master keeps its encryption flag",
          bool(enc_cache.locate()["info"].get("encrypted")))
    check("a flipped encryption state invalidates the master",
          not _cache_in(enc_base, enc_udid, encrypted=False).has_valid_master())

    # a damaged Manifest.plist cannot prove the manifest is healthy: locate()
    # must report "no usable master" instead of raising out of the apply
    (enc_device / "Manifest.plist").write_bytes(b"not a plist")
    check("an unreadable manifest is not a usable master",
          not enc_cache.has_valid_master())
    (enc_device / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))

    # a full run leaves Manifest.plist as a 0-byte placeholder before the
    # device re-sends it: an interrupted rebuild must not be reused
    (enc_device / "Manifest.plist").write_bytes(b"")
    check("interrupted rebuild is not a usable master",
          not enc_cache.has_valid_master())
    (enc_device / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": True}))

    # --- a failed refresh restores the retained previous master -----------
    # The refresh writes into the master. Before it starts, the valid master
    # is copied aside. A dead transfer rolls that copy's metadata back and
    # keeps the marker, instead of leaving a truncated mirror marked usable
    # or throwing the last good copy away.
    import asyncio

    from src.restore import protective as _protective

    original_backup = _protective.perform_protective_backup

    async def _failing_backup(*_args, **_kwargs):
        raise RuntimeError("simulated stall")

    _protective.perform_protective_backup = _failing_backup
    try:
        try:
            asyncio.run(enc_cache.refresh(None))
        except RuntimeError:
            pass
        check("failed refresh restores the retained previous master marker",
              (enc_base / f"{enc_udid}.json").is_file())
        check("failed refresh keeps the payload files",
              (enc_device / "Manifest.db").is_file())
        check("failed refresh keeps the previous copy until a restore finishes",
              (enc_base / "previous" / enc_udid / "Manifest.db").is_file())
    finally:
        _protective.perform_protective_backup = original_backup

    print(f"\nALL {PASS} CHECKS PASSED")


def _same_file(a, b) -> bool:
    """True when both paths exist and are the same inode (a hardlink)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _file_id_for(domain, rel_path) -> str:
    """The manifest's fileID for a row (sha1 of domain-relativePath)."""
    import hashlib
    return hashlib.sha1(f"{domain}-{rel_path}".encode()).hexdigest()


def _cache_in(base: Path, udid: str, encrypted: bool, version: str = "27.0") -> ProtectiveBackupCache:
    """Point a cache at exactly one store so ``locate()`` cannot see another."""
    cache = ProtectiveBackupCache(udid, product_version=version, encrypted=encrypted)
    cache._temp_base = base / "absent-temp"
    cache._persist_base = base
    cache._set_home(base)
    return cache


if __name__ == "__main__":
    main()