"""iOS 27+ ``StatusBarOverrides.archive`` writer.

Starting with iOS 27 SpringBoard no longer reads the classic binary
``statusBarOverrides`` struct (and the ``SpeakeasyNewStatusBar`` feature flag
in ``FeatureFlags/Settings.plist`` cannot be written by a restore at all).
Instead it unarchives an ``NSKeyedArchiver`` binary property list from
``/var/mobile/Library/SpringBoard/StatusBarOverrides.archive``:

    _SBSystemStatusStatusBarOverridesArchiveRecord
      +-- statusBarData : STStatusBarData
      |     +-- cellularEntry          : STStatusBarDataCellularEntry
      |     +-- secondaryCellularEntry : STStatusBarDataCellularEntry
      +-- suppressedBackgroundActivityIdentifiers : NSSet (empty)

The file lives in **HomeDomain**, the same domain the iOS 26 classic path
writes, so it is delivered by the normal backup restore -- no exploit and no
out-of-band channel is involved.

Scope: the carrier name, service badge, signal-bar count and fixed network
badge are user-settable. Network type is a visual override only; it cannot
change the radio connection or track live LTE/5G transitions.

Signal bars are optional: omit ``displayValue`` unless the user explicitly
selects a count, including an explicit zero. Network type defaults to
0 (no generation badge) unless explicitly selected; there is no supported dynamic network-type sentinel.
The archive targets cellular entries only: it must never include ``vpnEntry``
or suppress background activity identifiers.

There is deliberately **no** support for the classic time/date/battery/wifi
overrides or for the 46 per-item show/hide toggles: no counterpart for them
has ever been documented for this archive, and the classic
``statusBarOverrides`` struct no longer drives the iOS 27 status bar.

Failure mode is safe by design: when the record decodes empty SpringBoard
removes the file itself and the stock carrier names come back, so a rejected
archive degrades to "no override" instead of a broken status bar.

Pure stdlib on purpose -- ``src.tweaks`` is imported by the tweak loader and
must not drag in the pymobiledevice3-backed ``src.restore`` package.
"""

import plistlib

# HomeDomain path of the archive, relative to /var/mobile.
ARCHIVE_PATH = "/Library/SpringBoard/StatusBarOverrides.archive"
ARCHIVE_DOMAIN = "HomeDomain"

# The record refuses to render anything longer, so cut here rather than let
# SpringBoard silently drop the whole override.
MAX_CARRIER_LENGTH = 64

# The badge is a small SIM slot glyph ("P", "1", "2"), not free text.
MAX_BADGE_LENGTH = 8

# Signal-bar count accepted for ``displayValue``. The classic tweak allowed
# 0-5 through the UI; iOS itself only draws 0-4, so 5 is clamped.
MAX_BARS = 5

_RECORD_CLASS = "_SBSystemStatusStatusBarOverridesArchiveRecord"
_CELLULAR_CLASS = "STStatusBarDataCellularEntry"
_CELLULAR_CLASS_CHAIN = [
    "STStatusBarDataCellularEntry",
    "STStatusBarDataNetworkEntry",
    "STStatusBarDataIntegerEntry",
    "STStatusBarDataEntry",
    "NSObject",
]

# Cellular-entry rendering defaults. Signal-bar displayValue is deliberately
# absent; add it only for an explicit user override. Network type 0 suppresses
# the generation label rather than requesting live network-type passthrough.
# An explicit network-type selection replaces that default.
_ENTRY_DEFAULTS = {
    "badgeString": None,
    "callForwardingEnabled": False,
    "displayRawValue": 0,
    "enabled": True,
    "isBootstrapCellular": False,
    "lowDataModeActive": False,
    "numberSharingState": 0,
    "rawValue": 0,
    "showsSOSWhenDisabled": False,
    "sosAvailable": False,
    "status": 5,
    "suffixString": None,
    "type": 0,
    "wifiCallingEnabled": False,
}


def _class_def(classname, chain):
    return {"$classes": list(chain), "$classname": classname}


def _truncate(name):
    # An explicit "" is a blank override (hide the label entirely, issue #83):
    # keep it as "" so build_archive writes a hiding entry instead of
    # collapsing the override into the reset record. Only None means unset.
    if name is None:
        return None
    return str(name)[:MAX_CARRIER_LENGTH]


def _truncate_badge(text):
    """Trim a service badge to the glyph length iOS will draw."""
    if text is None:
        return None
    text = str(text).strip()[:MAX_BADGE_LENGTH]
    return text or None


def _bars(value):
    """Clamp an explicit bar count; absent or invalid input stays omitted."""
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(MAX_BARS, value))


def build_archive(
    primary_carrier=None,
    secondary_carrier=None,
    primary_badge=None,
    secondary_badge=None,
    primary_bars=None,
    secondary_bars=None,
    primary_network_type=None,
    secondary_network_type=None,
) -> bytes:
    """Build the ``StatusBarOverrides.archive`` payload.

    With no carrier names this returns the *reset* record: a structurally
    valid archive whose status-bar data carries no cellular entries, which
    SpringBoard decodes as "no overrides" and then unlinks.

    ``primary_badge``/``secondary_badge`` become the entry ``badgeString`` and
    ``primary_bars``/``secondary_bars`` its ``displayValue``; ``None`` keeps
    badge unset and omits the signal-bar key.
    """
    primary = _truncate(primary_carrier)
    secondary = _truncate(secondary_carrier)

    objects = ["$null"]

    def add(value):
        objects.append(value)
        return plistlib.UID(len(objects) - 1)

    # Laid out the way the stock archiver writes it: root and status-bar data
    # first, then the payload objects, then every class definition, and the
    # NSSet instance last. Object order carries no meaning to the unarchiver,
    # but matching it keeps our bytes diffable against a real device dump.
    data_obj = {"$class": None}
    root_obj = {
        "$class": None,
        "statusBarData": None,
        "suppressedBackgroundActivityIdentifiers": None,
    }
    root = add(root_obj)
    data_uid = add(data_obj)
    root_obj["statusBarData"] = data_uid

    def add_cellular(carrier, badge=None, bars=None, network_type=None):
        # `string` and `crossfadeString` reference one shared string object,
        # the same way the stock archiver deduplicates them.
        text = add(carrier)
        entry = {"$class": None}
        for key, value in _ENTRY_DEFAULTS.items():
            entry[key] = plistlib.UID(0) if value is None else value
        entry["string"] = text
        entry["crossfadeString"] = text
        # The badge is its own string object, referenced only by badgeString.
        if badge:
            entry["badgeString"] = add(badge)
        if network_type is not None:
            entry["type"] = max(0, min(30, int(network_type)))
        count = _bars(bars)
        if count is not None:
            entry["displayValue"] = count
        return add(entry)

    entries = []
    if primary is not None:
        entry_uid = add_cellular(
            primary, _truncate_badge(primary_badge), primary_bars, primary_network_type
        )
        data_obj["cellularEntry"] = entry_uid
        entries.append(entry_uid)
    if secondary is not None:
        entry_uid = add_cellular(
            secondary, _truncate_badge(secondary_badge), secondary_bars, secondary_network_type
        )
        data_obj["secondaryCellularEntry"] = entry_uid
        entries.append(entry_uid)

    if entries:
        # one shared class definition for both cellular entries
        cell_class = add(_class_def(_CELLULAR_CLASS, _CELLULAR_CLASS_CHAIN))
        for entry_uid in entries:
            objects[entry_uid.data]["$class"] = cell_class
    data_obj["$class"] = add(_class_def("STStatusBarData", ["STStatusBarData", "NSObject"]))
    set_class = add(_class_def("NSSet", ["NSSet", "NSObject"]))
    root_obj["$class"] = add(_class_def(_RECORD_CLASS, [_RECORD_CLASS, "NSObject"]))
    root_obj["suppressedBackgroundActivityIdentifiers"] = add({"$class": set_class, "NS.objects": []})

    return plistlib.dumps({
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": plistlib.UID(root.data)},
        "$objects": objects,
    }, fmt=plistlib.FMT_BINARY)


def build_reset_archive() -> bytes:
    """Archive with no cellular entries -- clears any applied carrier name."""
    return build_archive(None, None)


def status_bar_data(payload: bytes):
    """Return the decoded ``STStatusBarData`` instance of an archive.

    Follows ``$top.root`` -> ``statusBarData`` the same way SpringBoard's
    unarchiver does. Raises ``ValueError`` if the payload is not a usable
    status-bar override archive.
    """
    archive = plistlib.loads(payload)
    if archive.get("$archiver") != "NSKeyedArchiver":
        raise ValueError("not an NSKeyedArchiver payload")
    objects = archive["$objects"]
    root = objects[archive["$top"]["root"].data]
    if objects[root["$class"].data]["$classname"] != _RECORD_CLASS:
        raise ValueError("unexpected root class")
    data = objects[root["statusBarData"].data]
    if objects[data["$class"].data]["$classname"] != "STStatusBarData":
        raise ValueError("unexpected statusBarData class")
    return data, objects


def carrier_names(payload: bytes):
    """Return ``(primary, secondary)`` carrier names held by an archive."""
    data, objects = status_bar_data(payload)

    def read(key):
        uid = data.get(key)
        if not isinstance(uid, plistlib.UID):
            return None
        entry = objects[uid.data]
        if not isinstance(entry, dict):
            return None
        string = entry.get("string")
        if not isinstance(string, plistlib.UID):
            return None
        value = objects[string.data]
        return value if isinstance(value, str) else None

    return read("cellularEntry"), read("secondaryCellularEntry")


def carrier_overrides(payload: bytes):
    """Return ``{primary: (name, badge, bars), secondary: (...)}`` for tests.

    Every value is taken back out of the encoded plist, so this doubles as a
    round-trip check that the fields really landed where SpringBoard will
    look for them.
    """
    data, objects = status_bar_data(payload)
    found = {}

    def read(key):
        uid = data.get(key)
        if not isinstance(uid, plistlib.UID):
            return None
        entry = objects[uid.data]
        if not isinstance(entry, dict):
            return None

        def string(field):
            ref = entry.get(field)
            if not isinstance(ref, plistlib.UID):
                return None
            value = objects[ref.data]
            # UID 0 is the archiver's "$null" sentinel, i.e. an unset string.
            return value if isinstance(value, str) and value != "$null" else None

        bars = entry.get("displayValue")
        return string("string"), string("badgeString"), (
            bars if isinstance(bars, int) else None
        )

    found["primary"] = read("cellularEntry")
    found["secondary"] = read("secondaryCellularEntry")
    return found


def is_reset_archive(payload: bytes) -> bool:
    """True when the payload carries no cellular entries."""
    try:
        data, _ = status_bar_data(payload)
    except (ValueError, KeyError, IndexError, TypeError):
        return False
    return not any(key in data for key in ("cellularEntry", "secondaryCellularEntry"))
