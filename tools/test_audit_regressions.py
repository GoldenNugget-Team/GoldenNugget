#!/usr/bin/env python3
"""Offline regressions for fixes found in the 2026-11 repo audit (no device).

Covers, each with the concrete case that used to fail:

1. ``FileLock`` stale reclaim must not delete a lock another process freshly
   took between the staleness check and the unlink (two holders).
2. ``clean_backup_for_restore`` fails loudly on a missing backup instead of
   returning "pruned nothing" and letting the restore continue.
3. Status-bar string setters truncate by BYTES, not characters, so a CJK
   carrier name cannot overflow the fixed-size override field.
4. ``IncrementalBuilder`` notifies the page when a build step raises, so the
   Tweaks/Daemons pages do not stay stuck in "building" with a dead search.
5. ``_prepare_protective_backup`` (the wrapper) re-runs the backup with
   standard media when the AFC store fails verification, and aborts when the
   second attempt fails too — the data-loss gate no return path may bypass.

Run: python tools/test_audit_regressions.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_audit_regressions_")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def store(name):
    return os.path.join(TMP, name)


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# =============================================================================
def test_file_lock_reclaim():
    print("\nFileLock: stale reclaim vs a fresh holder")
    from src.utils.file_lock import FileLock

    path = os.path.join(TMP, "fresh.lock")

    # A lock left by a dead process (pid that does not exist) is reclaimable.
    dead = os.path.join(TMP, "dead.lock")
    with open(dead, "w") as f:
        f.write("999999999\n")
    os.utime(dead, (time.time() - 3600, time.time() - 3600))
    lock = FileLock(dead)
    check("dead-pid lock is reclaimable", lock._reclaimable())

    # A lock whose pid is alive (this process) must NOT be reclaimed even
    # when it looks old — deleting it would leave two holders.
    mine = os.path.join(TMP, "mine.lock")
    with open(mine, "w") as f:
        f.write(f"{os.getpid()}\n")
    os.utime(mine, (time.time() - 3600, time.time() - 3600))
    lock = FileLock(mine)
    check("a live holder is never reclaimable", not lock._reclaimable())
    check("tryLock fails politely while the holder is alive",
          lock.tryLock(timeout_ms=60) is False)
    check("the live holder's lock file still exists", os.path.exists(mine))

    # Reclaim of a genuinely stale lock works and the winner can lock.
    stale = os.path.join(TMP, "stale.lock")
    with open(stale, "w") as f:
        f.write("999999999\n")
    os.utime(stale, (time.time() - 3600, time.time() - 3600))
    lock = FileLock(stale)
    check("stale lock reclaimed", lock.tryLock(timeout_ms=0))
    check("reclaimed lock file now names this process",
          open(stale).read().strip() == str(os.getpid()))
    lock.unlock()
    check("unlock removes the lock file", not os.path.exists(stale))

    _ = path  # (unused placeholder for readability)


# =============================================================================
def test_clean_backup_missing():
    print("\nclean_backup_for_restore: missing backup fails loudly")
    from src.exceptions.nugget_exception import NuggetException
    from src.restore.protective import clean_backup_for_restore

    def run(path):
        try:
            clean_backup_for_restore(path, "UDID")
            return "ok"
        except NuggetException as e:
            return str(e)

    check("a missing device dir aborts", run(store("nope")) != "ok")
    d = store("manifestless")
    os.makedirs(d)
    check("a backup without Manifest.db aborts", run(d) != "ok")


# =============================================================================
def test_status_bar_bytes_fit():
    print("\nStatusBarTweak._bytes_fit: byte-safe truncation")
    from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak

    fit = StatusBarTweak._bytes_fit
    check("short ascii passes through",
          fit("Carrier", 100) == b"Carrier")
    check("exactly at the limit passes", len(fit("a" * 100, 100)) == 100)
    check("over-limit ascii truncates to the byte limit",
          len(fit("a" * 250, 100)) == 100)
    cjk = "移" * 100                     # 3 bytes each = 300 bytes
    out = fit(cjk, 100)
    check("CJK truncates to the byte limit", len(out) <= 100, len(out))
    check("CJK truncation stays valid UTF-8",
          out.decode("utf-8") == "移" * (len(out) // 3))
    check("emoji truncation keeps whole characters",
          fit("🚀" * 100, 100).decode("utf-8").endswith("🚀"))


# =============================================================================
def test_incremental_builder_error_hook():
    print("\nIncrementalBuilder: a failed build step tells the page")
    from PySide6.QtWidgets import QApplication

    from src.gui.ios.incremental_builder import IncrementalBuilder

    app = QApplication.instance() or QApplication([])

    class Page:
        def __init__(self):
            self.building = False
            self.label_hidden = False

        def on_build_failed(self):
            self.building = False
            self.label_hidden = True

    page = Page()
    page.building = True
    builder = IncrementalBuilder(None, on_error=page.on_build_failed)

    def steps():
        yield None
        raise RuntimeError("boom")

    builder._steps = iter(steps())
    try:
        builder._advance()
        raised = False
    except RuntimeError as e:
        raised = "boom" in str(e)
    check("the failing step re-raises to the caller", raised)
    check("the page left the building state", page.building is False)
    check("the page hid its loading label", page.label_hidden is True)

    # finish() reports through the same hook
    page2 = Page()
    page2.building = True
    builder2 = IncrementalBuilder(None, on_error=page2.on_build_failed)

    def boom2_steps():
        yield None
        raise ValueError("boom2")

    builder2._steps = iter(boom2_steps())
    try:
        builder2.finish()
        raised2 = False
    except ValueError:
        raised2 = True
    check("finish re-raises the generator error", raised2)
    check("finish also cleared the page state", page2.building is False)
    _ = app


# =============================================================================
def test_prepare_backup_wrapper_gate():
    print("\n_prepare_protective_backup: unverified media store retries, then aborts")
    from src.devicemanagement.device_manager import DeviceManager
    from src.exceptions.nugget_exception import NuggetException
    from src.restore.afc_media import _write_media_state

    verified = store("wrap_verified")
    write_file(os.path.join(verified, "DCIM", "a.MOV"), b"x" * 100)
    _write_media_state(verified, files=1, bytes_=100, skipped=0)
    broken = store("wrap_broken")
    write_file(os.path.join(broken, "DCIM", "a.MOV"), b"x" * 10)

    class Prepared:
        def __init__(self, media_src):
            self.media_src = media_src
            self.root = "r"

    calls = []

    class Manager:
        # the real data-loss gate (a staticmethod on DeviceManager)
        _require_media_copy = staticmethod(DeviceManager._require_media_copy)

        def _report_operation_stage(self, stage, sub):
            pass

        async def _build_protective_backup(self, update_label, needs_posterboard,
                                           prompt_password, force_standard_media=False):
            calls.append(force_standard_media)
            if len(calls) == 1:
                return Prepared(broken), False
            return Prepared(""), True     # standard backup: media rides it

    async def go():
        return await DeviceManager._prepare_protective_backup(Manager(), lambda s: None)

    prepared, pb_ok = asyncio.run(go())
    check("first attempt used the AFC store", calls[0] is False)
    check("the wrapper retried with standard media", calls == [False, True], calls)
    check("the retry's backup is handed back", prepared.media_src == "" and pb_ok)

    # Both attempts unverified -> the gate aborts before anything is wiped.
    calls2 = []

    class Manager2(Manager):
        async def _build_protective_backup(self, update_label, needs_posterboard,
                                           prompt_password, force_standard_media=False):
            calls2.append(force_standard_media)
            return Prepared(broken), False

    def go2():
        try:
            asyncio.run(DeviceManager._prepare_protective_backup(
                Manager2(), lambda s: None))
            return "ok"
        except NuggetException as e:
            return "no complete copy" in str(e)

    check("double failure aborts with the media message", go2() is True, calls2)
    check("both attempts were made before aborting", calls2 == [False, True])


# =============================================================================
def test_reset_encrypted_password():
    print("\n_reset_tweaks: encrypted device gets a password for the Phase 3 restore")
    from unittest.mock import patch

    import src.devicemanagement.device_manager as dm_mod
    from src.devicemanagement.device_manager import DeviceManager
    from src.tweaks.basic_plist_locations import FileLocation
    from src.utils.pages import Page

    class Fake:
        _known_backup_encryption = True

        def _raise_if_unsupported(self):
            pass

        def get_current_device_udid(self):
            return "UDID"

        def get_current_device_version(self):
            return "27.0"

        def _get_backup_password(self):
            return "secret123"

        def concat_file(self, contents, path, files_to_restore, owner=None, group=None):
            files_to_restore.append(SimpleNamespace(domain="HomeDomain"))

        async def add_skip_setup(self, files, uses_domains):
            pass

        async def _prepare_protective_backup(self, update_label):
            return "prepared-root", False

        async def start_restore(self, files, update_label, **kwargs):
            self.restore_kwargs = kwargs
            return None

    fake = Fake()
    errors = []
    real_show_apply_error = dm_mod.show_apply_error

    def fake_show_apply_error(e, update_label=lambda x: None, files_list=None):
        errors.append(e)
        return None

    # A truthy reset plan is what routes the reset through Phase 0 and the
    # password branch. Patched, so the test does not need a real recorded
    # baseline; the plan shape only has to survive the concat loop.
    plan = {FileLocation.springboard: {}}
    dm_mod.show_apply_error = fake_show_apply_error
    try:
        with (
            patch("src.controllers.apply_preview.load_preview", return_value={}),
            patch("src.controllers.apply_preview.write_preview"),
            patch("src.controllers.default_reset.preference_reset_plan", return_value=plan),
            patch("src.restore.lastapply.clear_lastapply"),
        ):
            ok = asyncio.run(dm_mod.DeviceManager._reset_tweaks(
                fake, [Page.StatusBar], None, lambda s: None))
    finally:
        dm_mod.show_apply_error = real_show_apply_error

    check("the reset completed", ok is True and not errors, repr(errors[:1]))
    kw = fake.restore_kwargs
    check("the password reaches start_restore",
          kw.get("backup_password") == "secret123", kw.get("backup_password"))
    check("keychain rides the encrypted restore", kw.get("include_keychain") is True)
    check("the prepared root reaches start_restore",
          kw.get("prepared_backup_root") == "prepared-root")


def main():
    test_file_lock_reclaim()
    test_clean_backup_missing()
    test_status_bar_bytes_fit()
    test_incremental_builder_error_hook()
    test_prepare_backup_wrapper_gate()
    test_reset_encrypted_password()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
