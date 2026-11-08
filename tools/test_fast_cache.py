#!/usr/bin/env python3
"""Offline test for the redesigned fast backup cache (no device needed).

Covers the behaviour that makes the cache actually speed an apply up:

1. The **master is immutable** — an apply prunes + tweak-injects a disposable
   restore *view* of it, so the master keeps its full manifest (which is what
   the next incremental refresh diffs against) and a crashed apply cannot
   leave it half-pruned.
2. **Freshness is tracked per part** — the protective master and the AFC photo
   store have independent clocks, so a wallpaper apply no longer forces a
   full master refresh (the PosterBoard database comes from the targeted
   PosterBoard-only channel instead).
3. **Phase 5 pushes only what the device lacks** — the media store is diffed
   against the device's own media tree.

Run: python tools/test_fast_cache.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.protective import (
    CACHE_MEDIA_REFRESH_SECS,
    CACHE_REFRESH_SECS,
    ProtectiveBackupCache,
    clean_backup_for_restore,
    discard_restore_view,
    make_restore_view,
)

UDID = "00008101-FASTCACHE"
PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def write_manifest(device_dir: Path, rows):
    """rows: list of (domain, relative_path, payload_bytes or None, flags)."""
    import hashlib
    conn = sqlite3.connect(str(device_dir / "Manifest.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS Files (fileID TEXT PRIMARY KEY, "
                 "domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    for domain, rel, payload, *rest in rows:
        flags = rest[0] if rest else 1
        file_id = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        if payload is not None:
            pdir = device_dir / file_id[:2]
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / file_id).write_bytes(payload)
        conn.execute("INSERT OR REPLACE INTO Files VALUES (?,?,?,?,NULL)",
                     (file_id, domain, rel, flags))
    conn.commit()
    conn.close()


def file_id_for(domain, rel_path) -> str:
    import hashlib
    return hashlib.sha1(f"{domain}-{rel_path}".encode()).hexdigest()


def make_cache(tmp: Path, **info_extra):
    cache = ProtectiveBackupCache(UDID, product_version="27.0")
    cache._temp_base = tmp / "temp"
    cache._persist_base = tmp / "persist"
    cache._set_home(cache._persist_base)
    cache.master_root = cache.base / "master"
    cache.device_dir = cache.master_root / UDID
    cache.info_path = cache.base / f"{UDID}.json"
    cache.device_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(cache.device_dir, [
        ("HomeDomain", "Library/Preferences/x.plist", b"<plist>"),
        ("HomeDomain", "Library/SMS/sms.db", b"sms"),
    ])
    for name in ("Manifest.plist", "Status.plist", "Info.plist"):
        (cache.device_dir / name).write_bytes(b"x" * 300)
    info = {"udid": UDID, "product_version": "27.0", "encrypted": False,
            "media_afc": True, "created_ts": int(time.time()),
            "media_ts": int(time.time())}
    info.update(info_extra)
    cache.base.mkdir(parents=True, exist_ok=True)
    with open(cache.info_path, "w", encoding="utf-8") as f:
        json.dump(info, f)
    return cache


# =============================================================================
def test_master_immutable():
    print("\nthe cache master is never modified by an apply")
    tmp = Path(tempfile.mkdtemp(prefix="gn_fast_cache_"))
    cache = make_cache(tmp)

    before = (cache.device_dir / "Manifest.db").read_bytes()
    check("master manifest present before the apply", len(before) > 0)

    view = make_restore_view(str(cache.master_root), UDID, str(cache.base / "view"))
    view_device = Path(view) / UDID
    check("restore view built", view_device.is_dir())

    # the apply prunes the VIEW (this is what removes the non-protective rows)
    clean_backup_for_restore(view, UDID)
    conn = sqlite3.connect(str(view_device / "Manifest.db"))
    view_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("the view was pruned", "Library/SMS/sms.db" not in view_rels)

    # the master keeps EVERY row — the next incremental refresh needs them
    conn = sqlite3.connect(str(cache.device_dir / "Manifest.db"))
    master_rels = {r[0] for r in conn.execute("SELECT relativePath FROM Files")}
    conn.close()
    check("the master kept every manifest row",
          "Library/SMS/sms.db" in master_rels, sorted(master_rels))
    check("the master manifest is byte-identical",
          (cache.device_dir / "Manifest.db").read_bytes() == before)

    # and every payload is still there
    payload = cache.device_dir / file_id_for("HomeDomain", "Library/SMS/sms.db")[:2] \
        / file_id_for("HomeDomain", "Library/SMS/sms.db")
    check("the master payload survived the apply", payload.is_file())

    # dropping the view is free of side effects
    discard_restore_view(view, UDID)
    check("the view was removed", not view_device.exists())
    check("the master payload survived the view being dropped", payload.is_file())


# =============================================================================
def test_per_part_freshness():
    print("\nthe master and the photo store are tracked separately")
    tmp = Path(tempfile.mkdtemp(prefix="gn_fast_cache_"))
    cache = make_cache(tmp)

    found = cache.locate()
    check("locate() reports the master age", "age_secs" in found)
    check("locate() reports the media age", "media_age_secs" in found)

    # A cache whose photos are old but whose master is new must report both.
    cache = make_cache(tmp / "b",
                       created_ts=int(time.time()),
                       media_ts=int(time.time()) - (CACHE_MEDIA_REFRESH_SECS + 600))
    found = cache.locate()
    check("a fresh master with old photos is still located", found is not None)
    check("the master reads as fresh", found["age_secs"] < CACHE_REFRESH_SECS)
    check("the photos read as stale",
          found["media_age_secs"] > CACHE_MEDIA_REFRESH_SECS,
          f"{found['media_age_secs']}s")
    check("the media TTL is longer than the master TTL by default",
          CACHE_MEDIA_REFRESH_SECS > CACHE_REFRESH_SECS,
          f"media={CACHE_MEDIA_REFRESH_SECS}s master={CACHE_REFRESH_SECS}s")

    # A legacy cache with no media_ts must not be trusted forever: the media
    # falls back to the master's age.
    cache = make_cache(tmp / "c", created_ts=int(time.time()) - 99999)
    with open(cache.info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    info.pop("media_ts", None)
    with open(cache.info_path, "w", encoding="utf-8") as f:
        json.dump(info, f)
    found = cache.locate()
    check("a legacy cache without media_ts falls back to the master age",
          found["media_age_secs"] == found["age_secs"],
          f"{found['media_age_secs']} vs {found['age_secs']}")


# =============================================================================
def test_media_refresh_keeps_metadata():
    print("\nrefreshing the photos preserves the rest of the cache record")
    tmp = Path(tempfile.mkdtemp(prefix="gn_fast_cache_"))
    cache = make_cache(tmp)

    # Simulate a media-only refresh (the AFC pull is stubbed out — only the
    # bookkeeping is under test here).
    import src.restore.afc_media as afc_media

    async def _fake_pull(lockdown_client, media_root, progress_callback=None,
                         on_error="raise", diff=False):
        return {"files": 0, "bytes": 0, "skipped": 0}

    real = afc_media.backup_media_via_afc
    afc_media.backup_media_via_afc = _fake_pull
    try:
        import asyncio
        asyncio.run(cache.refresh_media(None))
    finally:
        afc_media.backup_media_via_afc = real

    with open(cache.info_path, "r", encoding="utf-8") as f:
        info = json.load(f)
    check("the udid survived the media refresh", info.get("udid") == UDID)
    check("the product version survived", info.get("product_version") == "27.0")
    check("the encryption flag survived", info.get("encrypted") is False)
    check("the media_afc flag survived", info.get("media_afc") is True)
    check("the media timestamp was updated", info.get("media_ts", 0) >= info.get("created_ts", 0))
    # the master must still be locatable afterwards
    check("the cache is still locatable after a media refresh",
          cache.locate() is not None)


# =============================================================================
def test_media_push_is_a_diff():
    print("\nPhase 5 pushes only what the device lacks")
    import asyncio

    import src.restore.afc_media as afc_media
    from src.restore.afc_media import MEDIA_STATE_FILE, _write_media_state

    tmp = Path(tempfile.mkdtemp(prefix="gn_fast_cache_"))
    store = tmp / "media"
    (store / "DCIM" / "100APPLE").mkdir(parents=True)
    (store / "DCIM" / "100APPLE" / "SAME.JPG").write_bytes(b"s" * 500)
    (store / "DCIM" / "100APPLE" / "NEW.JPG").write_bytes(b"n" * 400)
    _write_media_state(str(store), files=2, bytes_=900, skipped=0)

    class FakeAfc:
        def __init__(self, files):
            self.files = dict(files)
            self.written = {}

        async def listdir(self, path):
            if path == "/":
                trees = {p.split("/")[1] for p in self.files}
                return ["." , ".."] + sorted(trees)
            prefix = path.rstrip("/") + "/"
            kids = {p[len(prefix):].split("/")[0]
                    for p in self.files if p.startswith(prefix)}
            return ["." , ".."] + sorted(kids)

        async def stat(self, path):
            if path in self.written:
                return {"st_size": len(self.written[path]), "st_ifmt": "S_IFREG"}
            if path in self.files:
                return {"st_size": len(self.files[path]), "st_ifmt": "S_IFREG"}
            return {"st_size": 0, "st_ifmt": "S_IFDIR"}

        async def isdir(self, path):
            return (await self.stat(path))["st_ifmt"] == "S_IFDIR"

        async def makedirs(self, path):
            pass

        async def get_file_contents(self, path):
            return self.files[path]

        async def fopen(self, path, mode="r"):
            return path

        async def fread(self, handle, size):
            return b""

        async def fclose(self, handle):
            pass

        async def fwrite(self, handle, chunk):
            self.written[handle] = self.written.get(handle, b"") + chunk

        async def set_file_contents(self, path, data):
            self.written[path] = data

    class _Ctx:
        def __init__(self, afc):
            self.afc = afc

        async def __aenter__(self):
            return self.afc

        async def __aexit__(self, *a):
            return False

    fake = FakeAfc({"/DCIM/100APPLE/SAME.JPG": b"s" * 500})
    real = afc_media.AfcService
    afc_media.AfcService = lambda lc: _Ctx(fake)
    try:
        tally = asyncio.run(afc_media.restore_media_via_afc(None, str(store)))
    finally:
        afc_media.AfcService = real

    check("the file the device already has is not re-sent",
          "/DCIM/100APPLE/SAME.JPG" not in fake.written, list(fake.written))
    check("the file the device lacks is sent",
          fake.written.get("/DCIM/100APPLE/NEW.JPG") == b"n" * 400)
    check("only the missing file was transferred", tally["files"] == 1, tally)
    check("the skipped file is counted", tally.get("skipped") == 1, tally)
    check("the marker is never pushed to the device",
          not any(MEDIA_STATE_FILE in k for k in fake.written), list(fake.written))


# =============================================================================
def main():
    test_master_immutable()
    test_per_part_freshness()
    test_media_refresh_keeps_metadata()
    test_media_push_is_a_diff()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
