#!/usr/bin/env python3
"""Offline test for the iOS 27 StatusBarOverrides.archive (no device needed).

Guards the two things that are easy to break silently:

* the archive we build is a real ``NSKeyedArchiver`` binary plist with the
  class graph SpringBoard unarchives -- ``_SBSystemStatusStatusBarOverrides
  ArchiveRecord`` -> ``STStatusBarData`` -> ``STStatusBarDataCellularEntry``;
* the apply/reset paths stage it in **HomeDomain**, the same domain the iOS 26
  classic statusBarOverrides uses, and the reset writes a *valid empty* record
  (SpringBoard unlinks that itself) instead of poking FeatureFlags.

Also pins the deliberate scope limit: the carrier name, its service badge and
its bar count are settable; the classic time/date/battery/wifi overrides and
the per-item show/hide toggles are not, because the archive has no documented
counterpart for them.

Run: python tools/test_statusbar_archive.py
"""
import os
import plistlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.status_bar.statusbar_archive import (
    ARCHIVE_DOMAIN,
    ARCHIVE_PATH,
    MAX_BADGE_LENGTH,
    MAX_BARS,
    MAX_CARRIER_LENGTH,
    build_archive,
    build_reset_archive,
    carrier_names,
    carrier_overrides,
    is_reset_archive,
    status_bar_data,
)

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def classname(objects, uid):
    return objects[uid.data].get("$classname")


def cell_entries(payload):
    """Return the cellular entry instances held by an archive."""
    data, objects = status_bar_data(payload)
    entries = []
    for key in ("cellularEntry", "secondaryCellularEntry"):
        uid = data.get(key)
        if isinstance(uid, plistlib.UID):
            entries.append(objects[uid.data])
    return entries


# =============================================================================
def test_is_a_keyed_archive():
    print("\nNSKeyedArchiver container")
    payload = build_archive("Testname", None)
    archive = plistlib.loads(payload)
    check("binary plist", payload.startswith(b"bplist"), payload[:8].decode("latin-1"))
    check("$archiver is NSKeyedArchiver", archive["$archiver"] == "NSKeyedArchiver")
    check("$version is 100000", archive["$version"] == 100000)
    check("$top points at root", isinstance(archive["$top"]["root"], plistlib.UID))
    check("objects start with $null", archive["$objects"][0] == "$null")

    objects = archive["$objects"]
    root = objects[archive["$top"]["root"].data]
    check(
        "root class is the override record",
        classname(objects, root["$class"]) == "_SBSystemStatusStatusBarOverridesArchiveRecord",
    )
    data = objects[root["statusBarData"].data]
    check("only cellular entries are targeted", set(data) <= {"$class", "cellularEntry", "secondaryCellularEntry"})
    check("statusBarData class", classname(objects, data["$class"]) == "STStatusBarData")
    suppressed = objects[root["suppressedBackgroundActivityIdentifiers"].data]
    check("suppressed set class", classname(objects, suppressed["$class"]) == "NSSet")
    check("suppressed set is empty", suppressed["NS.objects"] == [])


def test_cellular_entry_shape():
    print("\ncellular entry shape")
    payload = build_archive("Testname", "Second")
    entry, secondary = cell_entries(payload)
    objects = plistlib.loads(payload)["$objects"]

    for label, item in (("primary", entry), ("secondary", secondary)):
        check(f"{label} class", classname(objects, item["$class"]) == "STStatusBarDataCellularEntry")
        check(f"{label} omits unset bars", "displayValue" not in item)
        check(f"{label} enabled", item["enabled"] is True)
        check(f"{label} status is connected", item["status"] == 5)
        check(f"{label} string and crossfadeString share an object",
              item["string"].data == item["crossfadeString"].data)
        check(f"{label} no badge", objects[item["badgeString"].data] == "$null")
        check(f"{label} no suffix", objects[item["suffixString"].data] == "$null")
        # The merge replaces the whole live entry, so a name-only override
        # must not fabricate a network type or a bar count (regression:
        # type 10 pinned a "5G" indicator and displayValue 4 pinned full
        # signal onto every carrier-name change).
        check(f"{label} no network type pinned", item["type"] == 0, item["type"])

    check("both entries share one class definition",
          entry["$class"].data == secondary["$class"].data)
    check("names round-trip", carrier_names(payload) == ("Testname", "Second"))


def test_reset_record():
    print("\nreset record")
    payload = build_reset_archive()
    check("is a reset record", is_reset_archive(payload))
    check("carries no names", carrier_names(payload) == (None, None))
    check("has no cellular entries", cell_entries(payload) == [])
    # SpringBoard drops the file itself when the record decodes empty, so the
    # reset must stay structurally valid rather than become a null file.
    root = plistlib.loads(payload)["$objects"][1]
    check("root still a valid record",
          root["$class"] is not None and root["statusBarData"] is not None)


def test_variants():
    print("\nvariants")
    check("primary only", carrier_names(build_archive("A", None)) == ("A", None))
    check("secondary only", carrier_names(build_archive(None, "B")) == (None, "B"))
    check("blank names build hiding entries, not a reset",
          not is_reset_archive(build_archive("", ""))
          and carrier_names(build_archive("", "")) == ("", ""))
    check("blank primary only", carrier_names(build_archive("", None)) == ("", None))
    check("blank secondary only", carrier_names(build_archive(None, "")) == (None, ""))
    hiding = cell_entries(build_archive("", None))
    check("a hiding entry still replaces the whole live entry",
          len(hiding) == 1 and hiding[0]["enabled"] is True
          and hiding[0]["status"] == 5)
    check("no args is a reset", is_reset_archive(build_archive()))
    check("build_reset_archive matches build_archive()",
          build_reset_archive() == build_archive(None, None))

    long_name = "X" * 200
    primary, _ = carrier_names(build_archive(long_name))
    check("long names are truncated", len(primary) == MAX_CARRIER_LENGTH,
          f"{len(primary)} chars")

    unicode_name = "Билайн"
    check("utf-8 names survive", carrier_names(build_archive(unicode_name))[0] == unicode_name)


def test_rejects_foreign_payloads():
    print("\nrejects non-archive payloads")
    for label, payload in (
        ("random bytes", b"\x00\x01\x02not a plist"),
        ("empty", b""),
        ("plain plist", plistlib.dumps({"hello": "world"})),
    ):
        check(f"{label} is not a reset", is_reset_archive(payload) is False)
        try:
            status_bar_data(payload)
            check(f"{label} raises", False)
        except (ValueError, KeyError, IndexError, TypeError):
            check(f"{label} raises", True)


# =============================================================================
def test_delivery_path():
    print("\ndelivery path")
    from src.restore.path_mapping import split_path_into_domain

    check("enum path matches the writer constant",
          FileLocation.statusBarOverridesArchive.value == "/var/mobile" + ARCHIVE_PATH,
          FileLocation.statusBarOverridesArchive.value)
    domain, rel = split_path_into_domain("/var/mobile" + ARCHIVE_PATH)
    check("resolves to HomeDomain", domain == ARCHIVE_DOMAIN, domain)
    check("relative path is inside Library/SpringBoard",
          rel == "Library/SpringBoard/StatusBarOverrides.archive", rel)

    # The iOS 26 classic file has to land in the same domain, otherwise the
    # restore would need a second mechanism on 27.
    classic_domain, classic_rel = split_path_into_domain("/var/mobile/Library/SpringBoard/statusBarOverrides")
    check("same domain as the iOS 26 classic file", classic_domain == domain)
    check("classic file is not the archive", classic_rel != rel)


# =============================================================================
def test_tweak_stages_the_archive():
    print("\nStatusBarTweak.apply_ios27_tweak")
    try:
        from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
    except Exception as e:
        # needs the cffi-backed statusBarOverrideData struct; skip when the
        # interpreter has no cffi so this file still runs bare.
        print(f"  skipped: {type(e).__name__}: {e}")
        return

    tweak = StatusBarTweak()
    check("disabled by default", not tweak.enabled)

    files: list = []
    tweak.apply_ios27_tweak(files)
    check("a disabled tweak stages nothing", files == [])

    tweak.set_enabled(True)
    tweak.apply_ios27_tweak(files)
    check("enabled with no names stages a reset record",
          len(files) == 1 and is_reset_archive(files[0].contents))

    tweak.set_carrier_override("MyCarrier")
    tweak.set_secondary_carrier_override("Second")
    files = []
    tweak.apply_ios27_tweak(files)
    check("one file staged", len(files) == 1)
    staged = files[0]
    check("lands in HomeDomain", staged.domain == "HomeDomain", staged.domain)
    check("lands on the archive path",
          staged.restore_path == ARCHIVE_PATH, staged.restore_path)
    check("owned by mobile:mobile",
          (staged.owner, staged.group) == (501, 501),
          f"{staged.owner}:{staged.group}")
    check("carries both carrier names",
          carrier_names(staged.contents) == ("MyCarrier", "Second"))

    # The dead iOS 27 no-op is gone; the iOS 26 classic writer is untouched.
    check("the iOS 27 no-op apply_tweak override is gone",
          "apply_tweak" not in StatusBarTweak.__dict__)
    check("the classic iOS 26 writer still exists",
          callable(getattr(tweak, "apply_classic_tweak", None)))
    classic: list = []
    tweak.apply_classic_tweak(classic)
    check("classic writer still targets the classic file",
          len(classic) == 1
          and classic[0].restore_path == "/Library/SpringBoard/statusBarOverrides"
          and classic[0].domain == "HomeDomain",
          getattr(classic[0], "restore_path", None))


def test_badge_and_bars_round_trip():
    """The badge and bar count must land in the entry SpringBoard reads."""
    payload = build_archive("Mango", "Telkomsel", "P", "S", 3, 1)
    got = carrier_overrides(payload)
    check("primary name/badge/bars", got["primary"] == ("Mango", "P", 3), got["primary"])
    check("secondary name/badge/bars", got["secondary"] == ("Telkomsel", "S", 1),
          got["secondary"])

    # Defaults omit signal bars instead of serializing an unwanted zero.
    got = carrier_overrides(build_archive("Mango"))
    check("default badge is unset", got["primary"][1] is None, got["primary"])
    check("default bars are omitted", got["primary"][2] is None, got["primary"])

    # The badge is a separate string object referenced only by badgeString.
    data, objects = status_bar_data(build_archive("Mango", None, "P"))
    entry = objects[data["cellularEntry"].data]
    badge = objects[entry["badgeString"].data]
    check("badgeString is its own object", badge == "P", badge)
    check("badge is not the carrier string",
          entry["badgeString"] != entry["string"])

    # A primary-only archive still leaves the secondary entry absent.
    check("no secondary entry is invented",
          carrier_overrides(build_archive("Mango", None, "P"))["secondary"] is None)


def test_badge_and_bars_are_sanitised():
    """Bad input is clamped rather than written through verbatim."""
    long_badge = "ABCDEFGHIJK"
    got = carrier_overrides(build_archive("Mango", None, long_badge))
    check("badge is truncated", got["primary"][1] == long_badge[:MAX_BADGE_LENGTH],
          got["primary"][1])

    # Whitespace-only and empty badges are treated as "no badge".
    for blank in ("", "   "):
        got = carrier_overrides(build_archive("Mango", None, blank))
        check("blank badge is dropped", got["primary"][1] is None, blank)

    check("bars clamp high", carrier_overrides(
        build_archive("Mango", None, None, None, 99))["primary"][2] == MAX_BARS)
    check("bars clamp low", carrier_overrides(
        build_archive("Mango", None, None, None, -5))["primary"][2] == 0)

    # Invalid inputs are omitted as well.
    check("explicit zero bars are retained", carrier_overrides(
        build_archive("Mango", primary_bars=0))["primary"][2] == 0)
    for junk in ("x", None, object()):
        got = carrier_overrides(build_archive("Mango", None, None, None, junk))
        check("junk bars are omitted", got["primary"][2] is None, repr(junk))


def test_tweak_passes_badge_and_bars_to_the_archive():
    """apply_ios27_tweak must forward the four classic overrides."""
    from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak

    tweak = StatusBarTweak()
    tweak.enabled = True

    # Drive the values the same way the GUI does: through the setter-backed
    # methods, then assert what actually got staged.
    tweak.set_carrier_override("Mango")
    tweak.set_secondary_carrier_override("Telkomsel")
    tweak.set_primary_service_badge("P")
    tweak.set_secondary_service_badge("S")
    tweak.set_gsm_signal_strength_bars(2)
    tweak.set_secondary_gsm_signal_strength_bars(4)

    staged: list = []
    tweak.apply_ios27_tweak(staged)
    check("one file staged", len(staged) == 1, len(staged))
    got = carrier_overrides(staged[0].contents)
    check("primary override forwarded",
          got["primary"] == ("Mango", "P", 2), got["primary"])
    check("secondary override forwarded",
          got["secondary"] == ("Telkomsel", "S", 4), got["secondary"])

    # Unsetting every override must collapse to the reset record, which is
    # what clears an applied carrier name.
    tweak.unset_carrier_override()
    tweak.unset_secondary_carrier_override()
    tweak.unset_primary_service_badge()
    tweak.unset_secondary_service_badge()
    tweak.unset_gsm_signal_strength_bars()
    tweak.unset_secondary_gsm_signal_strength_bars()
    staged = []
    tweak.apply_ios27_tweak(staged)
    check("all overrides unset -> reset record",
          is_reset_archive(staged[0].contents))


def test_tweak_blank_carrier_overrides_the_label():
    """Enabled with a blank name, the tweak must stage a hiding entry.

    OG Nugget hid the label entirely when "change carrier text" was enabled
    with no input (issue #83); a blank override must not collapse into the
    reset record, which is what brings the stock carrier name back.
    """
    try:
        from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
    except Exception as e:  # needs the cffi-backed struct; skip bare
        print(f"  skipped: {type(e).__name__}: {e}")
        return

    tweak = StatusBarTweak()
    tweak.enabled = True
    tweak.set_carrier_override("")
    staged: list = []
    tweak.apply_ios27_tweak(staged)
    check("one file staged for a blank name", len(staged) == 1, len(staged))
    check("a blank name is not the reset record",
          staged and not is_reset_archive(staged[0].contents))
    check("a blank name stages a hiding entry",
          staged and carrier_names(staged[0].contents) == ("", None))


def test_network_types():
    from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak

    tweak = StatusBarTweak()
    tweak.enabled = True
    tweak.set_carrier_override("Primary")
    tweak.set_secondary_carrier_override("Secondary")
    for primary, secondary in ((4, 8), (10, 11), (12, 13), (0, 9)):
        tweak.set_data_network_type(primary)
        tweak.set_secondary_data_network_type(secondary)
        staged = []
        tweak.apply_ios27_tweak(staged)
        entries = cell_entries(staged[0].contents)
        check("network types forwarded independently", [e["type"] for e in entries] == [primary, secondary])
        check("network type leaves live bars unset", all("displayValue" not in e for e in entries))
    tweak.unset_data_network_type()
    tweak.unset_secondary_data_network_type()
    staged = []
    tweak.apply_ios27_tweak(staged)
    check("unset network types return to hidden badge", all(e["type"] == 0 for e in cell_entries(staged[0].contents)))
    check("network type alone does not invent a carrier", is_reset_archive(build_archive(primary_network_type=10)))


test_network_types()
# =============================================================================
test_is_a_keyed_archive()
test_cellular_entry_shape()
test_reset_record()
test_variants()
test_badge_and_bars_round_trip()
test_badge_and_bars_are_sanitised()
test_rejects_foreign_payloads()
test_delivery_path()
test_tweak_stages_the_archive()
test_tweak_blank_carrier_overrides_the_label()
test_tweak_passes_badge_and_bars_to_the_archive()

print(f"\nALL {PASS} CHECKS PASSED")
