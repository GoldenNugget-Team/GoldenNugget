#!/usr/bin/env python3
"""Offline reset checks for recorded key removal and status-bar restoration.

Missing apply history must never trigger whole-file preference clearing. A
recorded reset uses explicit key-removal requests and a prepared backup;
status-bar reset retains its version-specific binary/archive format.
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
    for version in ("26.2", "27.0", "27.2"):
        for page in (
            Page.Springboard,
            Page.InternalOptions,
            Page.LiquidGlass,
            Page.Daemons,
        ):
            fake, errors, _ = run_reset(version, [page])
            check(f"{version}/{page.name}: missing evidence is reported", bool(errors))
            check("no restore is started", fake.restored is None)
            check("no preference file is cleared", fake.written == {})
            check("no capture connection is opened", not fake.session_opened)


def test_recorded_reset_targets_only_applied_keys():
    from src.controllers.default_reset import PAGE_SECTIONS
    from src.tweaks.registry import HOME_PREFIX, SPECS_BY_ID, managed_pref_target
    from src.tweaks.tweak_names import TweakID
    from src.utils.preference_reset import PreferenceKeyReset

    spec = SPECS_BY_ID[TweakID.NoLiquidDock]
    page = next(
        page for page, section in PAGE_SECTIONS.items() if section == spec.section
    )
    recorded = {spec.id.name: {"value": True}}
    for version in ("26.2", "27.0"):
        fake, errors, _ = run_reset(version, [page], recorded)
        check("recorded keyed reset succeeds", not errors, repr(errors))
        check(
            "verified backup is passed to restore",
            fake.prepared_root == "verified-test-backup",
        )
        request = fake.written[spec.location.value]
        check(
            "reset uses a key-removal request", isinstance(request, PreferenceKeyReset)
        )
        check("only the applied preference is removed", request.paths == ((spec.key,),))
        mirror = HOME_PREFIX + managed_pref_target(spec.location.value)
        check(
            "managed mirror follows the iOS 27 route",
            (mirror in fake.written) == version.startswith("27"),
        )
        check(
            "no whole-file clearing payload is generated",
            all(
                isinstance(value, PreferenceKeyReset) for value in fake.written.values()
            ),
        )


test_capture_is_gone()
test_missing_reset_evidence_never_clears_preferences()
test_recorded_reset_targets_only_applied_keys()
test_ios27_status_bar_resets_the_archive()
test_ios26_status_bar_still_resets_the_classic_file()
test_status_bar_is_always_resettable()

print(f"\nALL {PASS} CHECKS PASSED")
