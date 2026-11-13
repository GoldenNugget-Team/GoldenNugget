#!/usr/bin/env python3
"""Offline regression test for preference tweaks whose baseline is unusable.

The 9.7.x regression: all tweak delivery moved into Phase 1's Manifest.db
injection, which merges each preference tweak into the device's existing
baseline file. When the baseline plist does not exist in the backup (the
device simply does not have it — e.g. ManagedPreferencesDomain/mobile/
com.apple.backboardd.plist or com.apple.mobilenotes.plist on a stock phone,
or the daemons disabled.plist on a first-ever apply) the injector aborted
the WHOLE apply with:

    ValueError: (4 current preference baseline(s) are unavailable: ...
    no file row in the backup ...)

The protective capture keeps EVERY preference file in these domains
(``is_preference_upload`` mid-stream + the prune keep-set), so a missing
manifest row means the device does not have the file — the tweak payload is
then the whole file, exactly what the old sparse restore laid down. This
locks in that behaviour instead of a hard apply abort.

Run: python tools/test_missing_preference_baseline.py
"""
import hashlib
import os
import plistlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.inject import (  # noqa: E402
    FeatureFlagBaselineUnavailable,
    created_baseline_payloads,
    inject_files_into_backup,
    preference_baseline_creates,
    preference_baseline_skips,
)
from src.utils.file_to_restore import _FileMode  # noqa: E402
from src.utils.preference_reset import PreferenceKeyReset, PreferenceNullify  # noqa: E402

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def _blob_for(path: str) -> bytes:
    """A minimal regular-file MBFile blob the donor patcher can clone."""
    return plistlib.dumps({
        "$version": 100000, "$archiver": "NSKeyedArchiver",
        "$top": {"root": plistlib.UID(1)},
        "$objects": [
            "$null",
            {"Birth": 0, "LastModified": 0, "LastStatusChange": 0, "Flags": 0,
             "GroupID": 501, "UserID": 501, "Mode": 0o100644,
             "ProtectionClass": 4, "Size": 0, "InodeNumber": 17,
             "RelativePath": plistlib.UID(2), "Digest": plistlib.UID(3),
             "$class": plistlib.UID(4)},
            path,
            plistlib.dumps({}, fmt=plistlib.FMT_BINARY),
            {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
        ],
    }, fmt=plistlib.FMT_BINARY)


def make_core_backup(root: Path, udid: str) -> Path:
    """A protective backup whose Manifest.db is empty (nothing captured)."""
    dev = root / udid
    dev.mkdir(parents=True)
    (dev / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    conn = sqlite3.connect(str(dev / "Manifest.db"))
    conn.executescript(
        "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
        "relativePath TEXT, flags INTEGER, file BLOB);"
        "CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB);")
    conn.commit()
    conn.close()
    return dev


def make_row(dev: Path, domain: str, path: str, contents: bytes):
    file_id = hashlib.sha1(f"{domain}-{path}".encode()).hexdigest()
    payload = dev / file_id[:2] / file_id
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(contents)
    conn = sqlite3.connect(str(dev / "Manifest.db"))
    conn.execute("INSERT INTO Files VALUES (?, ?, ?, 1, ?)",
                 (file_id, domain, path, _blob_for(path)))
    conn.commit()
    conn.close()
    return file_id


def read_payload(dev: Path, domain: str, path: str):
    file_id = hashlib.sha1(f"{domain}-{path}".encode()).hexdigest()
    f = dev / file_id[:2] / file_id
    return f.read_bytes() if f.is_file() else None


def read_blob(dev: Path, domain: str, path: str):
    conn = sqlite3.connect(str(dev / "Manifest.db"))
    file_id = hashlib.sha1(f"{domain}-{path}".encode()).hexdigest()
    row = conn.execute(
        "SELECT file FROM Files WHERE fileID=? AND flags=1", (file_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def inject(dev_root: Path, udid: str, items, created_history=None):
    created, skipped = [], []
    create_token = preference_baseline_creates.set(created)
    skip_token = preference_baseline_skips.set(skipped)
    try:
        injected, unchanged, failed = inject_files_into_backup(
            str(dev_root), udid, items, created_history=created_history)
    finally:
        preference_baseline_creates.reset(create_token)
        preference_baseline_skips.reset(skip_token)
    return injected, unchanged, failed, created


def main():
    mode = _FileMode.S_IFREG | 0o644
    # ---- The EXACT field scenario: Accessibility, AppStore, backboardd,
    # mobilenotes managed plists absent from the backup ------------------------
    missing = ["mobile/com.apple.Accessibility.plist",
               "mobile/com.apple.AppStore.plist",
               "mobile/com.apple.backboardd.plist",
               "mobile/com.apple.mobilenotes.plist"]
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        items = [("ManagedPreferencesDomain", p,
                  plistlib.dumps({f"Key{i}": True}), mode, 501, 501)
                 for i, p in enumerate(missing)]
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", items)
        check("missing managed baselines no longer abort the apply",
              failed == 0, f"{injected}/{unchanged}/{failed}")
        check("every new file landed", injected == 4, f"count={injected}")
        check("all four were recorded as created-new",
              sorted(created) == sorted(f"ManagedPreferencesDomain/{p}"
                                        for p in missing),
              f"created={sorted(created)}")
        blob = read_blob(dev, "ManagedPreferencesDomain", missing[2])
        check("each file is in the manifest", blob is not None)
        info = plistlib.loads(blob)["$objects"][1]
        check("new file carries a unique inode and mobile ownership",
              isinstance(info.get("InodeNumber"), int) and info["InodeNumber"] > 0
              and (info["UserID"], info["GroupID"]) == (501, 501),
              f"ino={info.get('InodeNumber')} uid={info['UserID']}")
        contents = plistlib.loads(read_payload(dev, "ManagedPreferencesDomain",
                                               missing[2]))
        check("payload keeps the tweak keys", contents == {"Key2": True},
              f"contents={contents}")

    # ---- Daemons disabled.plist + a HomeDomain preference on a first apply --
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", [
            ("DatabaseDomain", "com.apple.xpc.launchd/disabled.plist",
             plistlib.dumps({"com.apple.daemon": True}), mode, 0, 0),
            ("HomeDomain", "Library/Preferences/com.apple.novel.plist",
             plistlib.dumps({"K": 1}), mode, 501, 501)])
        check("first-ever apply with no baselines succeeds",
              (failed, injected) == (0, 2), f"{injected}/{unchanged}/{failed}")
        check("both were recorded as created-new", len(created) == 2,
              f"created={sorted(created)}")
        blob = read_blob(dev, "DatabaseDomain",
                         "com.apple.xpc.launchd/disabled.plist")
        info = plistlib.loads(blob)["$objects"][1]
        check("root ownership survives a created-new daemons plist",
              (info["UserID"], info["GroupID"]) == (0, 0),
              f"uid={info['UserID']} gid={info['GroupID']}")

    # ---- A reset against a missing baseline is a no-op, not an abort --------
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", [
            ("HomeDomain", "Library/Preferences/com.apple.springboard.plist",
             PreferenceKeyReset([("SBDontLockAfterCrash",)]), mode, 501, 501)])
        check("reset on a nonexistent file does not abort",
              (injected, failed) == (0, 0), f"{injected}/{unchanged}/{failed}")
        check("nothing recorded as created", created == [])
        check("no row was written for the skipped reset",
              read_blob(dev, "HomeDomain",
                        "Library/Preferences/com.apple.springboard.plist") is None)

    # ---- A keyed reset of a file WE delivered as a new file resolves against
    #      the recorded payload: no backup session ever uploads such a file
    #      (the restore marks it as known to the host), so the backup row the
    #      reset normally merges against never appears -------------------------
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        history = {"HomeDomain/Library/Preferences/com.apple.SwiftUI.plist":
                   plistlib.dumps({"SolariumEnableDockExteriorEffects": True})}
        recorded = {}
        record_token = created_baseline_payloads.set(recorded)
        try:
            injected, unchanged, failed, created = inject(
                Path(tmp), "UDID",
                [("HomeDomain", "Library/Preferences/com.apple.SwiftUI.plist",
                  PreferenceKeyReset([("SolariumEnableDockExteriorEffects",)]),
                  mode, 501, 501)],
                created_history=history)
        finally:
            created_baseline_payloads.reset(record_token)
        check("reset of a self-created file is delivered, not skipped",
              (injected, failed) == (1, 0), f"{injected}/{unchanged}/{failed}")
        check("the delivered file is recorded as created-new",
              created == ["HomeDomain/Library/Preferences/com.apple.SwiftUI.plist"],
              f"created={created}")
        contents = plistlib.loads(read_payload(
            dev, "HomeDomain", "Library/Preferences/com.apple.SwiftUI.plist"))
        check("the tweak key was removed from the recorded payload",
              contents == {}, f"contents={contents}")
        check("the post-reset payload is recorded for the next reset",
              plistlib.loads(recorded.get(
                  "HomeDomain/Library/Preferences/com.apple.SwiftUI.plist", b""))
              == {}, f"recorded={recorded}")

    # ---- A partial reset keeps the file's other keys ------------------------
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        history = {"HomeDomain/Library/Preferences/com.apple.SwiftUI.plist":
                   plistlib.dumps({"SolariumEnableDockExteriorEffects": True,
                                   "SolariumEnableHomeScreenExteriorEffects": True})}
        injected, unchanged, failed, created = inject(
            Path(tmp), "UDID",
            [("HomeDomain", "Library/Preferences/com.apple.SwiftUI.plist",
              PreferenceKeyReset([("SolariumEnableDockExteriorEffects",)]),
              mode, 501, 501)],
            created_history=history)
        check("partial reset of a self-created file lands",
              (injected, failed) == (1, 0), f"{injected}/{unchanged}/{failed}")
        contents = plistlib.loads(read_payload(
            dev, "HomeDomain", "Library/Preferences/com.apple.SwiftUI.plist"))
        check("only the reset key is removed",
              contents == {"SolariumEnableHomeScreenExteriorEffects": True},
              f"contents={contents}")

    # ---- An existing baseline still merges (the original safe path) ---------
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        baseline = plistlib.dumps({"SBDontLockAfterCrash": True,
                                   "SBKeepExisting": 7})
        make_row(dev, "ManagedPreferencesDomain",
                 "mobile/com.apple.springboard.plist", baseline)
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", [
            ("ManagedPreferencesDomain", "mobile/com.apple.springboard.plist",
             plistlib.dumps({"SBDontLockAfterCrash": False}), mode, 501, 501)])
        check("existing baseline merged, not re-created",
              (failed, created) == (0, []), f"{injected}/{unchanged}/{failed} {created}")
        contents = plistlib.loads(read_payload(
            dev, "ManagedPreferencesDomain", "mobile/com.apple.springboard.plist"))
        check("tweak key merged onto the baseline",
              (contents.get("SBDontLockAfterCrash"), contents.get("SBKeepExisting"))
              == (False, 7), f"contents={contents}")

    # ---- Feature-flag RESET without Global.plist still refuses explicitly ---
    with tempfile.TemporaryDirectory() as tmp:
        make_core_backup(Path(tmp), "UDID")
        try:
            inject(Path(tmp), "UDID", [
                ("SystemPreferencesDomain", "FeatureFlags/Global.plist",
                 PreferenceKeyReset([("someDomain",)]), mode, 0, 0)])
        except FeatureFlagBaselineUnavailable:
            check("feature-flag reset without a baseline still raises explicitly",
                  True)
        else:
            check("feature-flag reset without a baseline still raises explicitly",
                  False, "no exception raised")

    # ---- Issue #85: an unreadable MANAGED baseline degrades to whole-file
    # delivery (device upgraded from an iOS 26 apply to iOS 27 keeps managed
    # files the merge can no longer read; re-capturing yields the same
    # payload, so aborting makes the apply unrecoverable) ---------------------
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        items = [("ManagedPreferencesDomain", "mobile/com.apple.Accessibility.plist",
                  plistlib.dumps({"AccessibilityKey": 1}), mode, 501, 501),
                 ("ManagedPreferencesDomain", "mobile/com.apple.springboard.plist",
                  plistlib.dumps({"SBSomeTweakKey": True}), mode, 501, 501)]
        make_row(dev, items[0][0], items[0][1], b"\x00not-a-plist")
        make_row(dev, items[1][0], items[1][1], b"")            # zero-byte capture
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", items)
        check("unreadable managed baselines do not abort the apply",
              failed == 0 and injected == 2, f"{injected}/{unchanged}/{failed}")
        check("both degraded files recorded as created-new",
              sorted(created) == sorted(f"ManagedPreferencesDomain/{p}"
                                        for p in ("mobile/com.apple.Accessibility.plist",
                                                  "mobile/com.apple.springboard.plist")),
              f"created={sorted(created)}")
        first = plistlib.loads(read_payload(dev, items[0][0], items[0][1]))
        check("the tweak payload replaced the unreadable baseline",
              first == {"AccessibilityKey": 1}, f"contents={first}")

    # ---- A managed row whose payload file is missing degrades the same way --
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        path = "mobile/com.apple.springboard.plist"
        file_id = hashlib.sha1(f"ManagedPreferencesDomain-{path}".encode()).hexdigest()
        conn = sqlite3.connect(str(dev / "Manifest.db"))
        conn.execute("INSERT INTO Files VALUES (?, ?, ?, 1, ?)",
                     (file_id, "ManagedPreferencesDomain", path, _blob_for(path)))
        conn.commit()
        conn.close()
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", [
            ("ManagedPreferencesDomain", path,
             plistlib.dumps({"Key": True}), mode, 501, 501)])
        check("a managed row with a missing payload file is delivered wholesale",
              failed == 0 and injected == 1, f"{injected}/{unchanged}/{failed}")
        check("recorded as created-new", created == [f"ManagedPreferencesDomain/{path}"],
              f"created={created}")

    # ---- An unreadable NATIVE baseline still aborts (user data may be lost) -
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        make_row(dev, "HomeDomain", "Library/Preferences/com.apple.Preferences.plist",
                 b"\x00not-a-plist")
        try:
            inject(Path(tmp), "UDID", [
                ("HomeDomain", "Library/Preferences/com.apple.Preferences.plist",
                 plistlib.dumps({"K": 1}), mode, 501, 501)])
        except ValueError as error:
            check("corrupt native baseline payload still aborts loudly",
                  "could not be merged" in str(error), str(error)[:80])
            check("the abort reports the payload size for triage",
                  "InvalidFileException" in str(error), str(error)[:120])
        else:
            check("corrupt native baseline payload still aborts loudly", False,
                  "no exception raised")

    # ---- A nullify payload (Clear ScreenTimeAgent.plist) is delivered whole:
    #      wiping the file is the tweak's purpose, so even a corrupt baseline
    #      in the backup must not abort the apply (and no merge is attempted).
    with tempfile.TemporaryDirectory() as tmp:
        dev = make_core_backup(Path(tmp), "UDID")
        path = "Library/Preferences/com.apple.ScreenTimeAgent.plist"
        make_row(dev, "HomeDomain", path, b"\x00torn binary plist")
        nullify = PreferenceNullify(plistlib.dumps({}))
        injected, unchanged, failed, created = inject(Path(tmp), "UDID", [
            ("HomeDomain", path, nullify, mode, 501, 501)])
        check("a nullify payload ignores an unreadable baseline entirely",
              failed == 0 and injected == 1, f"{injected}/{unchanged}/{failed}")
        check("a nullify payload is not recorded as created-new",
              created == [], f"created={created}")
        payload = read_payload(dev, "HomeDomain", path)
        check("the nullified file landed as an empty plist",
              payload == plistlib.dumps({}), f"contents={payload!r}")

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
