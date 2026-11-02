"""Community tweaks: switchable tweaks declared in a .batter template.

A template with ``"format_version": "3"`` may carry a ``tweaks`` list in its
config.json. Each entry shows up as a switch (optionally with a slider, text
box or choice) and, when on, writes plist keys or whole files to absolute
device paths, the same places GoldenNugget's own tweaks write to:

    {
      "id": "hide-dock",
      "label": "Hide Dock",
      "description": "Removes the Dock background.",
      "default": false,
      "min_version": "26.0",
      "control": {"type": "slider", "min": 0, "max": 1, "step": 0.1, "default": 0.5},
      "writes": [
        {"type": "plist", "path": "/var/Managed Preferences/mobile/com.apple.springboard.plist",
         "values": {"SBDockAlpha": "$value"}}
      ],
      "writes_off": []
    }

Write types: ``plist`` merges ``values`` into the plist at ``path`` together
with GoldenNugget's own keys for that file (built-in tweaks win a clash),
``file`` writes ``source`` (a file in the archive, relative to config.json)
and ``empty`` writes an empty file (an empty plist for ``.plist`` paths: a
zero-byte plist can send iOS 26.2+ into a boot loop). A string value of exactly ``"$value"`` is
replaced with the control's value. ``writes_off`` is applied while the switch
is off, so a tweak can put a key back.

Paths must map to a backup domain the restore pipeline knows
(src/restore/path_mapping.py); nothing else can be written.
"""
import json
import os
import plistlib
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from src.utils.i18n import QCoreApplication, QT_TRANSLATE_NOOP

from src.restore.path_mapping import split_path_into_domain

MAX_TWEAKS = 64
MAX_WRITES = 32
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 16 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
VALUE_TOKEN = "$value"
WRITE_TYPES = ("plist", "file", "empty")
CONTROL_TYPES = ("slider", "text", "choice")

MANAGED_PREFIX = "/var/Managed Preferences/"
SYSTEM_PREFIXES = ("/var/db/", "/var/root/", "/var/preferences/", "/var/MobileDevice/", "/var/containers/")
RISK_LOW, RISK_MEDIUM, RISK_HIGH = 1, 2, 3

# Files GoldenNugget itself must own, or that would break pairing or setup.
BLOCKED_PREFIXES = (
    "/var/root/Library/Lockdown/",
    "/var/mobile/Library/Preferences/com.apple.purplebuddy.plist",
    "/var/Managed Preferences/mobile/com.apple.purplebuddy.plist",
    "/var/mobile/Library/Backup/",
)


class CommunityTweakError(ValueError):
    pass


def _fail(text: str):
    raise CommunityTweakError(QCoreApplication.translate("CommunityTweaks", text))


def check_path(path) -> str:
    """Return ``path`` if a community tweak may write it."""
    if not isinstance(path, str) or not path.startswith("/var/"):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Paths must be absolute and start with /var/."))
    if posixpath.normpath(path) != path or "\0" in path or path.endswith("/"):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Paths may not contain '..', '//' or a trailing slash."))
    domain, relative = split_path_into_domain(path)
    if domain is None or not relative:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "GoldenNugget cannot write to this location."))
    if path.startswith(BLOCKED_PREFIXES):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "This file is protected and cannot be changed by a template."))
    return path


def _check_plist_value(value, depth=0):
    if depth > 16:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Plist values are nested too deeply."))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Plist keys must be text."))
        for item in value.values():
            _check_plist_value(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_plist_value(item, depth + 1)
    elif value is None or not isinstance(value, (str, int, float, bool)):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Plist values cannot be null."))


def _substitute(value, replacement):
    if isinstance(value, dict):
        return {key: _substitute(item, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, replacement) for item in value]
    if value == VALUE_TOKEN:
        return replacement
    return value


@dataclass
class Write:
    type: str
    path: str
    values: dict = field(default_factory=dict)
    source: str = ""
    data: bytes = b""
    owner: int = 501


@dataclass
class Control:
    type: str
    default: Any = None
    min: float = 0
    max: float = 1
    step: float = 1
    max_length: int = 200
    choices: list = field(default_factory=list)   # (label, value)

    def clamp(self, value):
        """A stored or typed value made safe for this control."""
        if self.type == "slider":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return self.default
            value = min(max(value, self.min), self.max)
            return int(value) if all(isinstance(item, int) and not isinstance(item, bool)
                                     for item in (self.min, self.max, self.step)) else float(value)
        if self.type == "text":
            return value[:self.max_length] if isinstance(value, str) else self.default
        if self.type == "choice":
            values = [choice[1] for choice in self.choices]
            return value if value in values else self.default
        return value


@dataclass
class CommunityTweak:
    id: str
    label: str
    description: str = ""
    default: bool = False
    min_version: str = ""
    max_version: str = ""
    control: Optional[Control] = None
    writes: list = field(default_factory=list)
    writes_off: list = field(default_factory=list)
    enabled: bool = False
    value: Any = None

    def supports(self, version) -> bool:
        if not version:
            return True
        from src.devicemanagement.constants import Version
        if self.min_version and Version(version) < Version(self.min_version):
            return False
        if self.max_version and Version(version) > Version(self.max_version):
            return False
        return True

    def active_writes(self) -> list:
        """Writes for the current switch state, with ``$value`` filled in."""
        writes = self.writes if self.enabled else self.writes_off
        if self.control is None:
            return writes
        value = self.control.clamp(self.value)
        return [Write(write.type, write.path, _substitute(write.values, value), write.source,
                      write.data, write.owner) for write in writes]

    def paths(self) -> list:
        return sorted({write.path for write in self.writes + self.writes_off})

    def state(self) -> dict:
        data = {"enabled": self.enabled}
        if self.control is not None:
            data["value"] = self.value
        return data

    def restore_state(self, data):
        if not isinstance(data, dict):
            return
        if isinstance(data.get("enabled"), bool):
            self.enabled = data["enabled"]
        if self.control is not None and "value" in data:
            self.value = self.control.clamp(data["value"])


def _text(raw, key, limit, required=False):
    value = raw.get(key, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Every tweak needs a label, and text fields must be short text."))
    return value.strip()


def _version(raw, key):
    value = raw.get(key, "")
    if not isinstance(value, str) or (value and not re.match(r"^\d{1,2}(\.\d{1,2}){0,2}$", value)):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "iOS versions look like 18 or 18.4."))
    return value


def _number(raw, key, default):
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Slider limits must be numbers."))
    return value


def parse_control(raw) -> Optional[Control]:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("type") not in CONTROL_TYPES:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Controls are slider, text or choice."))
    kind = raw["type"]
    if kind == "slider":
        control = Control(kind, min=_number(raw, "min", 0), max=_number(raw, "max", 1),
                          step=_number(raw, "step", 1))
        if control.min >= control.max or control.step <= 0:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A slider needs min below max and a positive step."))
        control.default = control.min
        control.default = control.clamp(_number(raw, "default", control.min))
        return control
    if kind == "text":
        limit = raw.get("max_length", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "max_length must be between 1 and 1000."))
        default = raw.get("default", "")
        if not isinstance(default, str):
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A text default must be text."))
        return Control(kind, default=default[:limit], max_length=limit)
    choices = raw.get("choices")
    if not isinstance(choices, list) or not 0 < len(choices) <= 50:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A choice needs between 1 and 50 choices."))
    parsed = []
    for choice in choices:
        if not isinstance(choice, dict) or "value" not in choice:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Each choice needs a label and a value."))
        _check_plist_value(choice["value"])
        parsed.append((_text(choice, "label", 80, True), choice["value"]))
    index = raw.get("default", 0)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(parsed):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A choice default is the index of a choice."))
    return Control(kind, default=parsed[index][1], choices=parsed)


def parse_write(raw, read_source) -> Write:
    if not isinstance(raw, dict) or raw.get("type") not in WRITE_TYPES:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Writes are plist, file or empty."))
    owner = raw.get("owner", 501)
    if owner not in (0, 501) or isinstance(owner, bool):
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "The owner is 501 (mobile) or 0 (root)."))
    write = Write(raw["type"], check_path(raw.get("path")), owner=owner)
    if write.type == "plist":
        values = raw.get("values")
        if not isinstance(values, dict) or not values:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A plist write needs a values object."))
        _check_plist_value(values)
        write.values = values
    elif write.type == "empty" and write.path.endswith(".plist"):
        write.data = plistlib.dumps({})
    elif write.type == "file":
        source = raw.get("source")
        if not isinstance(source, str) or not source or posixpath.normpath(source) != source \
                or source.startswith(("/", "../")) or source == "..":
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A file write needs a source inside the template."))
        write.source = source
        write.data = read_source(source)
    return write


def parse_tweaks(raw_list, read_source) -> list:
    """Validate a config.json ``tweaks`` list.

    ``read_source(relative_path) -> bytes`` reads a file from the template."""
    if not isinstance(raw_list, list) or len(raw_list) > MAX_TWEAKS:
        _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "tweaks must be a list of at most 64 tweaks."))
    result, seen = [], set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Each tweak must be an object."))
        tweak_id = raw.get("id")
        if not isinstance(tweak_id, str) or not ID_PATTERN.match(tweak_id) or tweak_id in seen:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "Each tweak needs a unique id of letters, digits, '.', '_' or '-'."))
        seen.add(tweak_id)
        default = raw.get("default", False)
        if not isinstance(default, bool):
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "default must be true or false."))
        writes, writes_off = raw.get("writes"), raw.get("writes_off", [])
        if not isinstance(writes, list) or not writes or not isinstance(writes_off, list) \
                or len(writes) + len(writes_off) > MAX_WRITES:
            _fail(QT_TRANSLATE_NOOP("CommunityTweaks", "A tweak needs between 1 and 32 writes."))
        tweak = CommunityTweak(
            id=tweak_id, label=_text(raw, "label", 80, True),
            description=_text(raw, "description", 500), default=default,
            min_version=_version(raw, "min_version"), max_version=_version(raw, "max_version"),
            control=parse_control(raw.get("control")),
            writes=[parse_write(item, read_source) for item in writes],
            writes_off=[parse_write(item, read_source) for item in writes_off])
        tweak.enabled = default
        tweak.value = tweak.control.default if tweak.control else None
        result.append(tweak)
    return result


def collect(tweak_lists, version=None) -> tuple:
    """Merge every active write into (plists, files).

    ``plists`` maps a path to the merged keys; ``files`` maps a path to
    (bytes, owner). Two templates writing different whole contents to one
    file, or a plist and a whole file on one path, is an error."""
    plists, files, owners, origins = {}, {}, {}, {}
    for name, tweak_list in tweak_lists:
        for tweak in tweak_list:
            if not tweak.supports(version):
                continue
            for write in tweak.active_writes():
                if write.type == "plist":
                    if write.path in files:
                        _conflict(write.path, origins[write.path], name)
                    plists.setdefault(write.path, {}).update(write.values)
                    owners[write.path] = write.owner
                else:
                    data = write.data
                    if write.path in plists or (write.path in files and files[write.path][0] != data):
                        _conflict(write.path, origins[write.path], name)
                    files[write.path] = (data, write.owner)
                origins.setdefault(write.path, name)
    return {path: (values, owners[path]) for path, values in plists.items()}, files


def _conflict(path, first, second):
    raise CommunityTweakError(QCoreApplication.translate(
        "CommunityTweaks", "{0} and {1} both replace {2}.").format(first, second, path))



def active(tweak_lists, version=None) -> list:
    """[(template name, tweak, writes)] for every tweak that writes something
    on this apply: switched on, or switched off with ``writes_off``."""
    result = []
    for name, tweak_list in tweak_lists:
        for tweak in tweak_list:
            if tweak.supports(version):
                writes = tweak.active_writes()
                if writes:
                    result.append((name, tweak, writes))
    return result


def write_risk(write) -> int:
    """How much a single write can hurt.

    Managed Preferences are an overlay GoldenNugget rewrites on every apply,
    so keys there are the same kind of change as a built-in tweak. Anywhere
    else the whole file is replaced, losing whatever the iPhone kept in it,
    and the system folders hold files iOS needs to boot and pair."""
    if write.path.startswith(SYSTEM_PREFIXES):
        return RISK_HIGH
    if write.type != "plist" or not write.path.startswith(MANAGED_PREFIX):
        return RISK_MEDIUM
    return RISK_LOW


# --- what the last apply wrote, for reset --------------------------------

def _record_path(udid) -> str:
    from src.restore.lastapply import lastapply_path
    return lastapply_path(udid) + ".community"


def write_record(udid, plists: dict, files: dict):
    """Remember the paths (and plist keys) community tweaks just wrote."""
    if not udid:
        return
    record = {"schema": 1, "plists": {path: sorted(values) for path, (values, _owner) in plists.items()},
              "files": sorted(files)}
    try:
        old = load_record(udid)
        for path, keys in old.get("plists", {}).items():
            record["plists"][path] = sorted(set(record["plists"].get(path, [])) | set(keys))
        record["files"] = sorted(set(record["files"]) | set(old.get("files", [])))
        if not record["plists"] and not record["files"]:
            return
        path = _record_path(udid)
        with open(path + ".part", "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
        os.replace(path + ".part", path)
    except (OSError, ValueError, TypeError):
        pass


def load_record(udid) -> dict:
    if not udid:
        return {}
    try:
        with open(_record_path(udid), encoding="utf-8") as stream:
            record = json.load(stream)
    except (OSError, ValueError):
        return {}
    if not isinstance(record, dict) or record.get("schema") != 1 \
            or not isinstance(record.get("plists"), dict) or not isinstance(record.get("files"), list):
        return {}
    plists = {path: keys for path, keys in record["plists"].items()
              if isinstance(path, str) and isinstance(keys, list)}
    files = [path for path in record["files"] if isinstance(path, str)]
    return {"plists": plists, "files": files}


def clear_record(udid):
    try:
        os.unlink(_record_path(udid))
    except OSError:
        pass


def reset_plan(record: dict) -> tuple:
    """(paths to empty, paths that cannot be reset) for a stored record.

    Managed Preferences files are emptied, as the built-in resets do. Any
    other file was replaced whole, and GoldenNugget kept no copy of what was
    there before, so it is only reported."""
    to_empty, leftover = [], []
    for path in sorted(record.get("plists", {})):
        (to_empty if path.startswith(MANAGED_PREFIX) else leftover).append(path)
    leftover += [path for path in record.get("files", []) if path not in leftover]
    return to_empty, sorted(leftover)
