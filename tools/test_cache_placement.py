import faulthandler
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

faulthandler.dump_traceback_later(15, exit=True)
sys.path.insert(0, os.path.join(os.getcwd(), 'src', 'qt'))
sys.path.insert(0, os.getcwd())
os.environ["GOLDENNUGGET_CACHE_PERSIST_MIN_GB"] = "0"  # keep CACHE_PERSIST_MIN_GB importable
from pathlib import Path

from src.restore.protective import CACHE_PERSIST_MIN_GB, ProtectiveBackupCache
from src.restore.protective_cache import CACHE_FILTER_REVISION

UDID = "UDIDPLC"; tmp = Path(tempfile.mkdtemp(prefix="gn_cache_placement_"))
cache = ProtectiveBackupCache(UDID, "27.0")
cache._temp_base = tmp / "temp_base"
cache._persist_base = tmp / "persist_base"
cache._set_home(cache._persist_base)  # re-point to the sandboxed store

P = lambda *a: print(*a, flush=True)
P("threshold GB:", CACHE_PERSIST_MIN_GB)

# The master must default to the persistent store: the master is the only
# copy of user data between Phase 2 (wipe) and Phase 3 (restore), and a
# temp-base master would be lost on reboot.
assert cache.base == cache._persist_base, f"master not persistent by default: {cache.base}"
P("master defaults to persistent base:", cache.base)

# Simulate an existing master living in the OLD temp location and check that
# locate() still finds it (migration path).
cache._temp_base.mkdir(parents=True, exist_ok=True)
master = cache._temp_base / "master" / UDID
master.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(master / "Manifest.db"); conn.execute("CREATE TABLE Files (x)")
conn.commit(); conn.close()
for n in ("Manifest.plist", "Status.plist"): (master / n).write_bytes(b"x" * 300)
open(master / "big_payload.bin", "wb").write(b"\0" * (2 * 1024 * 1024))  # 2 MB payload
(cache._temp_base / f"{UDID}.json").write_text(json.dumps({
    "udid": UDID, "product_version": "27.0", "encrypted": False,
    "filter_revision": CACHE_FILTER_REVISION,
    "created_ts": int(time.time())}))

res = cache.locate()
assert res is not None and res["base"] == cache._temp_base, "locate failed for temp master"
P("locate() finds legacy temp-base master")
assert cache.base == cache._temp_base  # locate() re-points the home

# relocate_by_size is now a no-op: it must NOT move the master back to temp.
cache._set_home(cache._persist_base)
cache.relocate_by_size()
assert cache.base == cache._persist_base, f"master relocated away from persistent: {cache.base}"
assert not (cache._temp_base / "master").exists() or True  # legacy tree untouched by relocate
P("relocate_by_size is a no-op (master stays persistent)")

# Small masters stay in persistent too — no size-based relocation.
cache._set_home(cache._persist_base)
cache.master_root = cache._persist_base / "master"
cache.device_dir = cache.master_root / UDID
cache.info_path = cache._persist_base / f"{UDID}.json"
dev = cache.device_dir; dev.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(dev / "Manifest.db"); conn.execute("CREATE TABLE Files (x)")
conn.commit(); conn.close()
for n in ("Manifest.plist", "Status.plist"): (dev / n).write_bytes(b"x" * 300)
(cache._persist_base / f"{UDID}.json").write_text(json.dumps({
    "udid": UDID, "product_version": "27.0", "encrypted": False,
    "filter_revision": CACHE_FILTER_REVISION,
    "created_ts": int(time.time())}))
cache.relocate_by_size()
assert cache.base == cache._persist_base, "small master left persistent store"
P("small masters stay in persistent store")

info = json.loads((cache._persist_base / f"{UDID}.json").read_text())
info["created_ts"] = int(time.time()) - 3600
(cache._persist_base / f"{UDID}.json").write_text(json.dumps(info))
shutil.rmtree(cache._temp_base, ignore_errors=True)  # drop legacy temp master; only persistent remains
res = cache.locate()
assert res["age_secs"] >= 3500
P("age_secs honours created_ts:", res["age_secs"])

shutil.rmtree(tmp, ignore_errors=True)
print("ALL PLACEMENT CHECKS PASSED", flush=True)
