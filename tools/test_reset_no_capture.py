#!/usr/bin/env python3
"""Offline reset checks for empty-plist preference resets and status-bar reset.

Preference sections reset by writing a valid empty plist (never zero bytes):
the device falls back to its defaults and no backup baseline is needed.
FeatureFlags/Global.plist and the launchd disabled.plist stay keyed removals —
wiping those files whole would undo flags and disabled services GoldenNugget
does not own; Daemons stay recorded-only. Status-bar reset retains its
version-specific binary/archive format.
"""

import asyncio
import os
import plistlib
import sys
from unittest.mock import patch

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

    async def start_restore(
        self, files_to_restore, update_label, prompt_choice=None, **kwargs
    ):
        self.prepared_root = kwargs.get("prepared_backup_root")
        self.restored = list(files_to_restore)
        return "OK"

    async def _prepare_protective_backup(self, update_label):
        # The real Phase 0 establishes the encryption state on the manager
        # (see _build_protective_backup); the fallback lockdown check below
        # must never run when it did.
        self._known_backup_encryption = False
        return "verified-test-backup", False

    def _record_label(self, text):
        self.labels.append(text)


class _NoSession:
    """A lockdown_session stand-in that screams if the reset opens one."""

    def __init__(self, owner):
        self.owner = owner

    def __call__(self, *a, **kw):
        self.owner.session_opened = True
        raise AssertionError("reset opened a lockdown session")


def run_reset(version, pages, recorded=None):
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
        with (
            patch("src.controllers.apply_preview.load_preview", return_value=recorded),
            patch("src.controllers.apply_preview.write_preview"),
        ):
            asyncio.run(
                _dm.DeviceManager._reset_tweaks(
                    fake, pages, None, fake._record_label, alerts.append
                )
            )
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
    for name in (
        "_capture_original_plists",
        "_get_original_plist_paths",
        "_get_lockdown_values",
    ):
        check(f"DeviceManager.{name} is gone", not hasattr(dm_mod.DeviceManager, name))
    try:
        import src.restore.original_plist  # noqa: F401

        gone = False
    except ImportError:
        gone = True
    check("src/restore/original_plist.py no longer exists", gone)


def test_ios27_status_bar_resets_the_archive():
    print("\niOS 27 Status Bar reset: empty archive, no FeatureFlags write")
    from src.tweaks.status_bar.statusbar_archive import carrier_names, is_reset_archive

    fake, errors, _ = run_reset("27.0", [Page.StatusBar])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    data = fake.written.get(FileLocation.statusBarOverridesArchive.value)
    check("writes StatusBarOverrides.archive", data is not None)
    check(
        "the payload is a valid reset archive",
        data is not None and is_reset_archive(data),
        repr(data[:16]),
    )
    check(
        "the reset archive carries no carrier name",
        data is not None and carrier_names(data) == (None, None),
    )
    check(
        "no SpeakeasyNewStatusBar FeatureFlags write",
        FileLocation.featureflags.value not in fake.written,
    )
    check(
        "the reset is not a null/zero-byte file",
        data not in (b"", None),
        f"{len(data) if data else 0} bytes",
    )


def test_ios26_status_bar_still_resets_the_classic_file():
    print("\niOS 26 Status Bar reset: classic binary file unchanged")
    fake, errors, _ = run_reset("26.2", [Page.StatusBar])
    check("no exception escaped the reset", not errors, repr(errors[:1]))
    restored = [getattr(f, "restore_path", f) for f in fake.restored]
    check(
        "writes the classic statusBarOverrides, not the archive",
        "/Library/SpringBoard/statusBarOverrides" in restored,
        repr(restored),
    )
    check(
        "the classic file still goes to HomeDomain",
        any(getattr(f, "domain", None) == "HomeDomain" for f in fake.restored),
    )
    check(
        "no archive on iOS 26",
        FileLocation.statusBarOverridesArchive.value not in fake.written,
    )


def test_status_bar_is_always_resettable():
    print("\nResettable pages: Status Bar is offered on every version")
    from src.utils.pages import get_resettable_pages

    for version in ("26.2", "27.0", "27.1"):
        pages = get_resettable_pages(FakeDeviceManager(version))
        check(
            f"{version} reset offers Status Bar",
            Page.StatusBar in pages,
            repr([p.getPageName() for p in pages]),
        )
        check(
            f"{version} reset keeps the other sections",
            {Page.Springboard, Page.LiquidGlass, Page.InternalOptions, Page.Daemons}
            <= set(pages),
            repr([p.getPageName() for p in pages]),
        )


# =============================================================================


def test_missing_reset_evidence_never_clears_preferences():
    """Registry sections reset by writing valid empty plists; Daemons stay recorded-only."""
    from src.utils.preference_reset import PreferenceNullify

    def is_empty_plist(value):
        # A valid, non-empty-byte empty plist: the device parses it and
        # falls back to its defaults.
        return (isinstance(value, PreferenceNullify)
                and len(value) > 0 and plistlib.loads(value) == {})

    for version in ("26.2", "27.0", "27.2"):
        for page in (
            Page.Springboard,
            Page.InternalOptions,
            Page.LiquidGlass,
        ):
            fake, errors, _ = run_reset(version, [page])
            check(f"{version}/{page.name}: unrecorded section still resets", not errors, repr(errors[:1]))
            check("a restore is started", fake.restored is not None)
            check("every preference payload is a valid empty plist",
                  fake.written and all(is_empty_plist(value) for value in fake.written.values()))
            check("no capture connection is opened", not fake.session_opened)
        # A dynamic launchd set has no registry truth: no record, no reset.
        fake, errors, _ = run_reset(version, [Page.Daemons])
        check(f"{version}/Daemons: missing evidence is reported", bool(errors))
        check("no restore is started", fake.restored is None)
        check("no preference file is cleared", fake.written == {})
        check("no capture connection is opened", not fake.session_opened)


def test_unrecorded_liquid_glass_covers_legacy_keys():
    """Files applied before records existed are reset without any record."""
    from src.utils.preference_reset import PreferenceNullify

    fake, errors, _ = run_reset("27.2", [Page.LiquidGlass])
    check("reset succeeds with no record", not errors, repr(errors))
    managed_sb = fake.written.get("/var/Managed Preferences/mobile/com.apple.springboard.plist")
    check("SBDisallowGlassLockScreen's file is reset without a record",
          managed_sb is not None and plistlib.loads(managed_sb) == {},
          repr(managed_sb[:24]) if managed_sb else None)
    swiftui = fake.written.get("/var/mobile/Library/Preferences/com.apple.SwiftUI.plist")
    check("the SwiftUI plist is reset without a record (no baseline needed)",
          swiftui is not None and plistlib.loads(swiftui) == {},
          repr(swiftui[:24]) if swiftui else None)
    # iOS 27 writes the cfprefs mirror of every managed file too.
    mirror = fake.written.get("/var/mobile/Library/Preferences/com.apple.springboard.plist")
    check("the springboard mirror follows the managed file",
          mirror is not None and plistlib.loads(mirror) == {})
    check("every payload is a nullify, never zero bytes",
          all(isinstance(v, PreferenceNullify) and len(v) > 0
              for v in fake.written.values()))


def test_recorded_reset_targets_only_applied_keys():
    from src.controllers.default_reset import PAGE_SECTIONS
    from src.tweaks.registry import HOME_PREFIX, SPECS_BY_ID, managed_pref_target
    from src.tweaks.tweak_names import TweakID
    from src.utils.preference_reset import PreferenceNullify

    spec = SPECS_BY_ID[TweakID.NoLiquidDock]
    page = next(
        page for page, section in PAGE_SECTIONS.items() if section == spec.section
    )
    recorded = {spec.id.name: {"value": True}}
    for version in ("26.2", "27.0"):
        fake, errors, _ = run_reset(version, [page], recorded)
        check("recorded reset succeeds", not errors, repr(errors))
        check(
            "verified backup is passed to restore",
            fake.prepared_root == "verified-test-backup",
        )
        request = fake.written[spec.location.value]
        check(
            "reset writes a valid empty plist",
            isinstance(request, PreferenceNullify) and plistlib.loads(request) == {},
            repr(request[:24]),
        )
        mirror = HOME_PREFIX + managed_pref_target(spec.location.value)
        check(
            "managed mirror follows the iOS 27 route",
            (mirror in fake.written) == version.startswith("27"),
        )
        check(
            "the mirror is reset the same way",
            mirror not in fake.written or plistlib.loads(fake.written[mirror]) == {},
        )


def test_featureflags_reset_never_clears_the_whole_file():
    """FeatureFlags/Global.plist stays keyed: other flags live in it too."""
    import src.controllers.default_reset as dr
    from src.tweaks.registry import Section
    from src.tweaks.tweak_classes import BasicPlistTweak
    from src.utils.preference_reset import PreferenceKeyReset, PreferenceNullify

    class _FlagTweak(BasicPlistTweak):
        def __init__(self):
            super().__init__(FileLocation.featureflags, "SpringBoard")

        def apply_tweak(self, other_tweaks: dict) -> dict:
            return {FileLocation.featureflags:
                    {"SpringBoard": {"ClockAnim": {"Enabled": True}}}}

    class _FakeSpec:
        class id:
            name = "FakeFlagTweak"
        section = Section.INTERNAL

    fake_paths = {FileLocation.featureflags: {("SpringBoard", "ClockAnim", "Enabled")}}
    with (
        patch.object(dr, "SPECS", (_FakeSpec(),)),
        patch.object(dr, "_build_spec", return_value=_FlagTweak()),
        patch.object(dr, "_spec_reset_paths", return_value=fake_paths),
    ):
        plan = dr.preference_reset_plan({}, [Page.InternalOptions])
    payload = plan.get(FileLocation.featureflags)
    check("feature flags stay a keyed removal", isinstance(payload, PreferenceKeyReset),
          type(payload).__name__)
    check("it removes only the tweak's keys",
          payload is not None and ("SpringBoard", "ClockAnim", "Enabled") in payload.paths)
    check("the keyed branch is not a nullify",
          payload is not None and not isinstance(payload, PreferenceNullify))


def test_duplicate_nullify_files_stay_nullify():
    """A managed location and its native twin name the same file: the
    duplicate merge must keep the Nullify marker (a plain empty dict is
    rejected by the injector as an unverified reset)."""
    from src.restore.restore import merge_duplicates
    from src.utils.file_to_restore import FileToRestore
    from src.utils.preference_reset import PreferenceNullify

    empty = PreferenceNullify(plistlib.dumps({}))
    files = [
        FileToRestore(contents=empty, restore_path='/var/mobile/Library/Preferences/.GlobalPreferences.plist',
                      domain='HomeDomain'),
        FileToRestore(contents=empty, restore_path='/var/mobile/Library/Preferences/.GlobalPreferences.plist',
                      domain='HomeDomain'),
    ]
    merged = merge_duplicates(files)
    check('the duplicate collapses to one file', len(merged) == 1, len(merged))
    check('the merged payload is still a nullify',
          isinstance(merged[0].contents, PreferenceNullify), type(merged[0].contents).__name__)
    check('and still a valid empty plist',
          len(merged[0].contents) > 0 and plistlib.loads(merged[0].contents) == {})


test_capture_is_gone()
test_missing_reset_evidence_never_clears_preferences()
test_unrecorded_liquid_glass_covers_legacy_keys()
test_recorded_reset_targets_only_applied_keys()
test_featureflags_reset_never_clears_the_whole_file()
test_duplicate_nullify_files_stay_nullify()
test_ios27_status_bar_resets_the_archive()
test_ios26_status_bar_still_resets_the_classic_file()
test_status_bar_is_always_resettable()

print(f"\nALL {PASS} CHECKS PASSED")
