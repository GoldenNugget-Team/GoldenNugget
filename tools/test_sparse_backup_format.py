#!/usr/bin/env python3
"""Offline test for the sparse-restore backup format (no device needed).

The backup writer emits two formats, gated per device version:
  * iOS 26.x -> legacy MBDB (Status.plist 2.4 / Manifest.mbdb / Manifest.plist
    Version 9.1 / SystemDomainsVersion 20.0 / empty Lockdown) with payloads
    flat in the backup root — what the iOS 26 restore daemon reads.
  * iOS 27+  -> modern sqlite (Manifest.db format 3.3 / Manifest.plist
    Version 10.0 / SystemDomainsVersion 24.0 / Lockdown=device_manifest) with
    payloads under <xx>/<fileID>.

Run: python tools/test_sparse_backup_format.py
"""
import os
import plistlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.backup import Backup, ConcreteFile

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


DEVICE_MANIFEST = {
    "ProductType": "iPhone17,1",
    "DeviceClass": "iPhone",
    "UniqueDeviceID": "deadbeef",
    "SerialNumber": "F123",
    "DeviceName": "iPhone",
}

FILE = ConcreteFile("Library/Preferences/Test.plist", "HomeDomain", contents=b"x")
DIR = __import__("src.restore.backup", fromlist=["Directory"]).Directory(
    "Library/Preferences", "HomeDomain")


def write_and_load(back):
    tmp = tempfile.mkdtemp()
    d = Path(tmp)
    back.write_to_directory(d)
    return d


# --- iOS 26: legacy MBDB format (manifest_ios27=False) ---
d = write_and_load(Backup(files=[FILE, DIR], apps=[], device_manifest=None,
                          manifest_ios27=False))
status = plistlib.loads((d / "Status.plist").read_bytes())
manifest = plistlib.loads((d / "Manifest.plist").read_bytes())
check("iOS26: Status.plist Version is 2.4 (MBDB)", status["Version"] == "2.4")
check("iOS26: Manifest.mbdb exists, no sqlite Manifest.db",
      (d / "Manifest.mbdb").exists() and not (d / "Manifest.db").exists())
check("iOS26: Manifest.plist Version is 9.1", manifest["Version"] == "9.1")
check("iOS26: SystemDomainsVersion is 20.0", manifest["SystemDomainsVersion"] == "20.0")
check("iOS26: Lockdown is empty (no IsEncrypted key)",
      manifest.get("Lockdown") == {} and "IsEncrypted" not in manifest)
check("iOS26: Manifest.mbdb starts with the mbdb magic + version",
      (d / "Manifest.mbdb").read_bytes().startswith(b"mbdb\x05\x00"))
mbdb_raw = (d / "Manifest.mbdb").read_bytes()
check("iOS26: Manifest.mbdb mentions the HomeDomain file path",
      b"Library/Preferences/Test.plist" in mbdb_raw and b"HomeDomain" in mbdb_raw)
check("iOS26: payload staged flat in the backup root (not <xx>/<fileID>)",
      any(p.is_file() and p.name not in ("Manifest.plist", "Manifest.mbdb",
                                         "Status.plist", "Info.plist")
          for p in d.iterdir()))

# --- iOS 27+: modern sqlite format (manifest_ios27 default True) ---
d = write_and_load(Backup(files=[FILE, DIR], apps=[], device_manifest=DEVICE_MANIFEST))
status = plistlib.loads((d / "Status.plist").read_bytes())
manifest = plistlib.loads((d / "Manifest.plist").read_bytes())
check("iOS27: Status.plist Version is 3.3 (sqlite)", status["Version"] == "3.3")
check("iOS27: Manifest.db exists, no legacy Manifest.mbdb",
      (d / "Manifest.db").exists() and not (d / "Manifest.mbdb").exists())
check("iOS27: Manifest.plist Version is 10.0", manifest["Version"] == "10.0")
check("iOS27: SystemDomainsVersion is 24.0", manifest["SystemDomainsVersion"] == "24.0")
check("iOS27: Lockdown carries the device_manifest",
      manifest["Lockdown"] == DEVICE_MANIFEST)
check("iOS27: IsEncrypted is present and False",
      manifest["IsEncrypted"] is False)

con = sqlite3.connect(d / "Manifest.db")
tables = {r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
cols = {r[1] for r in con.execute("PRAGMA table_info(Files)").fetchall()}
rows = con.execute("SELECT domain, relativePath, flags FROM Files").fetchall()
con.close()
check("iOS27: Manifest.db has the Files/Properties tables",
      {"Files", "Properties"} <= tables)
check("iOS27: Manifest.db Files has the fileID/domain/path/flags/file columns",
      {"fileID", "domain", "relativePath", "flags", "file"} <= cols)
check("iOS27: Manifest.db holds the HomeDomain row",
      ("HomeDomain", "Library/Preferences/Test.plist", 1) in rows)
payloads = [p.name for p in d.rglob("*") if p.is_file()
            and p.name not in ("Manifest.plist", "Manifest.db",
                               "Status.plist", "Info.plist")]
check("iOS27: payload file staged under the hash layout",
      len(payloads) == 1 and Path(d / payloads[0][:2] / payloads[0]).is_file())

# --- AppBundle registration in both formats ---
from src.restore.backup import AppBundle

app = AppBundle(identifier="com.apple.PosterBoard",
                path="/Applications/PosterBoard.app",
                container_content_class="Data/Application", version="1.0")
d = write_and_load(Backup(files=[], apps=[app], device_manifest=DEVICE_MANIFEST))
manifest = plistlib.loads((d / "Manifest.plist").read_bytes())
apps = manifest.get("Applications", {})
check("iOS27: AppBundle registered in Applications",
      "com.apple.PosterBoard" in apps
      and apps["com.apple.PosterBoard"]["Path"] == "/Applications/PosterBoard.app")
d = write_and_load(Backup(files=[], apps=[app], device_manifest=None,
                          manifest_ios27=False))
manifest = plistlib.loads((d / "Manifest.plist").read_bytes())
apps = manifest.get("Applications", {})
check("iOS26: AppBundle registered in Applications",
      "com.apple.PosterBoard" in apps
      and apps["com.apple.PosterBoard"]["Path"] == "/Applications/PosterBoard.app")

print(f"\nALL PASSED ({PASS} checks)")