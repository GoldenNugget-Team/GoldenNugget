#!/usr/bin/env python3
"""Offline test for the tweak reset flow (no device needed).

Guards the removal of the pre-reset original-plist capture (``psysbackup``):
reset must write stock values straight to the device on every iOS version,
without opening a lockdown session or pulling a single plist off the device.

The one thing that must NOT become uniform across versions is the byte
content: iOS 26.2+ (so iOS 27 too) needs a *parseable* empty plist, because a
zero-byte com.apple.springboard.plist crashes SpringBoard at boot.

Run: python tools/test_reset_no_capture.py
"""
import asyncio
import os
import plistlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.devicemanagement.device_manager as dm_mod
from src.devicemanagement import device_manager as _dm
from src.tweaks.basic_plist_locations import FileLocation
from src.utils.pages import Page

PASS = 0
UDID = "00008101-TESTUDID"


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


class FakeDeviceManager:
    """Stand-in for DeviceManager holding only what _reset_tweaks touches."""

    def __init__(self, version):
        self.version = version
        self.written: dict = {}
        self.owners: dict = {}
        self.restored = None
        self.skip_setup_args = None
        self.session_opened = False
        self.labels: list = []

    # --- device queries -------------------------------------------------
    def _raise_if_unsupported(self):
        pass

    def get_current_device_udid(self):
        return UDID

    def get_current_device_version(self):
        return self.version

    # --- what _reset_tweaks builds into ----------------------------------
    def concat_file(self, contents, path, files_to_restore, owner=None, group=None):
        self.written[path] = contents
        self.owners[path] = (owner, group)
        files_to_restore.append(path)

    async def add_skip_setup(self, files_to_restore, restoring_domains):
        self.skip_setup_args = restoring_domains

    async def start_restore(self, files_to_restore, update_label, prompt_choice=None):
        self.restored = list(files_to_restore)
        return "OK"

    def _record_label(self, text):
        self.labels.append(text)


class _NoSession:
    """A lockdown_session stand-in that screams if the reset opens one."""

    def __init__(self, owner):
        self.owner = owner

    def __call__(self, *a, **kw):
        self.owner.session_opened = True
        raise AssertionError("reset opened a lockdown session")


def run_reset(version, pages):
    """Run _reset_tweaks against a fake device; return (written, errors, dm)."""
    fake = FakeDeviceManager(version)
    alerts: list = []
    errors: list = []

    def show_apply_error(e, update_label, files_list=None):
        errors.append(e)
        return "ERROR"

    real_session = _dm.lockdown_session
    real_apply_error = _dm.show_apply_error
    real_clear = None
    try:
        import src.restore.lastapply as lastapply
        real_clear = lastapply.clear_lastapply
        lastapply.clear_lastapply = lambda udid: None
    except Exception:
        pass
    _dm.lockdown_session = _NoSession(fake)
    _dm.show_apply_error = show_apply_error
    try:
        asyncio.run(_dm.DeviceManager._reset_tweaks(
            fake, pages, None, fake._record_label, alerts.append))
    finally:
        _dm.lockdown_session = real_session
        _dm.show_apply_error = real_apply_error
        if real_clear is not None:
            import src.restore.lastapply as lastapply
            lastapply.clear_lastapply = real_clear
    return fake, errors, alerts


# =============================================================================
def test_capture_is_gone():
    print("\nThe psysbackup capture is gone")
    for name in ("_capture_original_plists", "_get_original_plist_paths",
                 "_get_lockdown_values"):
        check(f"DeviceManager.{name} is gone", not hasattr(dm_mod.DeviceManager, name))
    try:
        import src.restore.original_plist  # noqa: F401
        gone = False
    except ImportError:
        gone = True
    check("src/restore/original_plist.py no longer exists", gone)


def test_ios27_writes_valid_empty_plists():
    print("\niOS 27 reset: parseable empty plists, no capture")
    fake, errors, alerts = run_reset("27.0", [Page.Springboard, Page.InternalOptions])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    check("restore actually ran", fake.restored is not None and fake.restored)
    check("no lockdown session was opened for a capture", not fake.session_opened)
    check("no 'capturing original plists' label", not any(
        "apturing" in str(x) for x in fake.labels))
    for path in (FileLocation.springboard.value, FileLocation.uikit.value,
                 FileLocation.globalPreferences.value, FileLocation.notes.value):
        data = fake.written.get(path)
        ok = data is not None and len(data) > 0
        parsed = None
        if ok:
            try:
                parsed = plistlib.loads(data)
            except Exception as e:
                parsed = f"unparseable: {e}"
        check(f"{path} is a valid empty plist", parsed == {}, repr(parsed))
        check(f"{path} is not a zero-byte file", ok,
              f"{len(data) if data else 0} bytes")


def test_ios26_writes_valid_empty_plists():
    print("\niOS 26 reset: parseable empty plists")
    fake, errors, _ = run_reset("26.2", [Page.Springboard])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    check("no lockdown session was opened", not fake.session_opened)
    for path in (FileLocation.springboard.value, FileLocation.uikit.value):
        check(f"{path} parses as an empty dictionary",
              plistlib.loads(fake.written[path]) == {})


SPRINGBOARD_MIRROR = "/var/mobile/Library/Preferences/com.apple.springboard.plist"
UIKIT_MIRROR = "/var/mobile/Library/Preferences/com.apple.UIKit.plist"


def test_ios27_clears_managed_pref_mirrors():
    print("\niOS 27 reset: clears the app-domain managed-pref mirrors too")
    # mcxd merges each managed preference into the target app's own cfprefs
    # domain, so the stale value survives in Library/Preferences/<domain>.plist
    # after the managed entry is emptied -- and Phase 3 used to restore that
    # mirror, which is what kept the Dynamic Island hidden after a reset.
    fake, errors, _ = run_reset("27.0", [Page.Springboard, Page.InternalOptions])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    for path in (SPRINGBOARD_MIRROR, UIKIT_MIRROR):
        data = fake.written.get(path)
        check(f"{path} is written", data is not None)
        parsed = None
        if data is not None:
            try:
                parsed = plistlib.loads(data)
            except Exception as e:
                parsed = f"unparseable: {e}"
        check(f"{path} is a valid empty plist", parsed == {}, repr(parsed))
        check(f"{path} is not a zero-byte app plist", data not in (b"", None),
              f"{len(data) if data else 0} bytes")


def test_ios26_clears_app_mirrors():
    print("\niOS 26 reset: clears app-domain mirrors")
    fake, errors, _ = run_reset("26.2", [Page.Springboard])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    for path in (SPRINGBOARD_MIRROR, UIKIT_MIRROR):
        check(f"{path} parses as an empty dictionary",
              plistlib.loads(fake.written[path]) == {})
        check(f"{path} belongs to mobile", fake.owners[path] == (501, 501))


def test_registry_reset_coverage():
    print("\nReset covers registry preference files, including previously omitted domains")
    from src.tweaks.registry import HOME_PREFIX, SPECS, Section, managed_pref_target
    sections = {
        Page.Springboard: Section.SPRINGBOARD,
        Page.InternalOptions: Section.INTERNAL,
        Page.LiquidGlass: Section.LIQUID_GLASS,
    }
    for version in ("26.2", "26.7", "27.0"):
        for page, section in sections.items():
            fake, errors, _ = run_reset(version, [page])
            check(f"{version} {page.name} reset succeeds", not errors, repr(errors))
            for path in {s.location.value for s in SPECS
                         if s.section == section and s.location.value.endswith(".plist")}:
                check(f"{version} {page.name} resets {path}",
                      plistlib.loads(fake.written[path]) == {})
                mirror = managed_pref_target(path)
                if mirror:
                    check(f"{version} resets the mirror for {path}",
                          plistlib.loads(fake.written[HOME_PREFIX + mirror]) == {})
            check("opaque Siri AI archive never replaced by an empty plist",
                  FileLocation.siriAIOverrides.value not in fake.written)
    fake, errors, _ = run_reset("27.0", list(sections))
    check("overlapping sections produce one write per path",
          not errors and len(fake.restored) == len(set(fake.restored)))
    fake, errors, _ = run_reset("27.0", [Page.Springboard])
    check("Springboard reset leaves Internal-only domains alone",
          not errors and FileLocation.notes.value not in fake.written)


def test_ios26_daemons_page_still_written():
    print("\niOS 26/27 Daemons page: real values, not nulled")
    for version in ("26.2", "27.0"):
        fake, errors, _ = run_reset(version, [Page.Daemons])
        data = fake.written.get(FileLocation.disabledDaemons.value)
        check(f"{version} daemons plist parses",
              errors == [] and data is not None and plistlib.loads(data) != {},
              repr(errors[:1]))
    fake, errors, _ = run_reset("27.0", [Page.Daemons])
    check("27 daemon defaults are the stock ones",
          plistlib.loads(fake.written[FileLocation.disabledDaemons.value])
          .get("com.apple.magicswitchd.companion") is True)


def test_ios27_status_bar_resets_the_archive():
    print("\niOS 27 Status Bar reset: empty archive, no FeatureFlags write")
    from src.tweaks.status_bar.statusbar_archive import carrier_names, is_reset_archive

    fake, errors, _ = run_reset("27.0", [Page.StatusBar])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    data = fake.written.get(FileLocation.statusBarOverridesArchive.value)
    check("writes StatusBarOverrides.archive", data is not None)
    check("the payload is a valid reset archive",
          data is not None and is_reset_archive(data), repr(data[:16]))
    check("the reset archive carries no carrier name",
          data is not None and carrier_names(data) == (None, None))
    check("no SpeakeasyNewStatusBar FeatureFlags write",
          FileLocation.featureflags.value not in fake.written)
    check("the reset is not a null/zero-byte file", data not in (b"", None),
          f"{len(data) if data else 0} bytes")


def test_ios26_status_bar_still_resets_the_classic_file():
    print("\niOS 26 Status Bar reset: classic binary file unchanged")
    fake, errors, _ = run_reset("26.2", [Page.StatusBar])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    restored = [getattr(f, "restore_path", f) for f in fake.restored]
    check("writes the classic statusBarOverrides, not the archive",
          "/Library/SpringBoard/statusBarOverrides" in restored, repr(restored))
    check("the classic file still goes to HomeDomain",
          any(getattr(f, "domain", None) == "HomeDomain" for f in fake.restored))
    check("no archive on iOS 26",
          FileLocation.statusBarOverridesArchive.value not in fake.written)


def test_status_bar_is_always_resettable():
    print("\nResettable pages: Status Bar is offered on every version")
    from src.utils.pages import get_resettable_pages
    for version in ("26.2", "27.0", "27.1"):
        pages = get_resettable_pages(FakeDeviceManager(version))
        check(f"{version} reset offers Status Bar",
              Page.StatusBar in pages, repr([p.getPageName() for p in pages]))
        check(f"{version} reset keeps the other sections",
              {Page.Springboard, Page.LiquidGlass, Page.InternalOptions, Page.Daemons} <= set(pages),
              repr([p.getPageName() for p in pages]))


# =============================================================================
test_capture_is_gone()
test_ios27_writes_valid_empty_plists()
test_ios26_writes_valid_empty_plists()
test_ios27_clears_managed_pref_mirrors()
test_ios26_clears_app_mirrors()
test_registry_reset_coverage()
test_ios26_daemons_page_still_written()
test_ios27_status_bar_resets_the_archive()
test_ios26_status_bar_still_resets_the_classic_file()
test_status_bar_is_always_resettable()

print(f"\nALL {PASS} CHECKS PASSED")
