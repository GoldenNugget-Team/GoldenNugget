"""Qt-free persistent settings store (``QSettings`` replacement).

Everything the app persists as user preferences (toggles, paths, accent
colours, per-device PosterBoard ids, ...) goes through :class:`Settings`.
Historically this was ``QSettings``; the backend may no longer import Qt, so
this module implements the small part of the API the app uses on top of a
JSON file, and **migrates the existing QSettings data on first use**:

* macOS: ``~/Library/Preferences/<org>.<app>.plist`` (``CFPreferences``)
* Windows: ``HKEY_CURRENT_USER\\Software\\<org>\\<app>``
* Linux/BSD: ``<XDG_CONFIG_HOME>/<org>/<app>.conf`` (INI)

A JSON store written by an earlier build (in the pre-rename ``GoldenNugget``
folder, see ``src.utils.paths.legacy_app_data_dirs``) is read as well, and wins
over the native data because it is newer. Without that, a user who dismisses
the one-time "move your data" window would start from defaults and the old
values would be skipped later as already-present.

The legacy data is only ever **read**; it is not deleted or rewritten, so a
downgrade still sees the old values. New values are written to::

    <app data dir>/preferences/<org>/<app>.json

which keeps the per-user data location historical (``src.utils.paths``).

QSettings semantics that callers rely on and that are preserved here:

* ``/`` in a key is a group separator; macOS stored it as ``.`` and Linux as
  an INI section.
* a wrapper keeps the old "read through to the legacy org" rule (see
  ``src/controllers/settings.py``).
* all ``Settings`` instances in a process share one in-memory store, so a
  value written by one page is visible to the next immediately (what
  ``QSettings`` does).
* ``value(key, default, type=...)`` coerces to ``bool``/``str``/``int``/
  ``float`` with QSettings' string rules.
"""

from __future__ import annotations

import configparser
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.utils.paths import app_data_dir, legacy_app_data_dirs

_LOCK = threading.RLock()
_STORES: dict[tuple[str, str], "_Store"] = {}


# --------------------------------------------------------------------------- #
# Native (legacy QSettings) readers
# --------------------------------------------------------------------------- #

def _flatten_dotted(data: dict, prefix: str = "") -> dict:
    """Turn CFPreferences' ``group.key`` form into ``group/key``."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        name = str(key)
        if isinstance(value, dict):
            flat.update(_flatten_dotted(value, prefix + name.replace(".", "/") + "/"))
            continue
        flat[prefix + name.replace(".", "/")] = value
    return flat


def _read_plist(org: str, app: str) -> dict:
    """Read a macOS QSettings plist (``~/.config`` on other systems is N/A)."""
    preferences = Path(os.path.expanduser("~")) / "Library" / "Preferences"
    # Qt's macOS backend maps a plain organisation name to the reverse-domain
    # CFPreferences identifier ``com.<org>``; app names keep their case
    # (``com.goldennugget.PB Configs.plist``).
    candidates = [
        preferences / f"com.{org.lower()}.{app}.plist",
        preferences / f"{org.lower()}.{app}.plist",
        preferences / f"{org}.{app}.plist",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            import plistlib

            with open(path, "rb") as stream:
                data = plistlib.load(stream)
        except Exception:
            continue
        if isinstance(data, dict):
            return _flatten_dotted(data)
    return {}


def _read_ini(org: str, app: str) -> dict:
    """Read a Qt INI settings file (Linux/BSD)."""
    roots = []
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        roots.append(Path(os.path.expanduser(xdg)))
    roots.append(Path(os.path.expanduser("~")) / ".config")
    flat: dict[str, Any] = {}
    for root in roots:
        path = root / org / f"{app}.conf"
        if not path.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(path, encoding="utf-8")
        except Exception:
            continue
        for section in parser.sections():
            for key, value in parser.items(section):
                flat[f"{section}/{key}"] = value
        # Keys in the implicit [General] section arrive via DEFAULT.
        for key, value in parser.defaults().items():
            flat.setdefault(key, value)
        if flat:
            return flat
    return {}


def _read_registry(org: str, app: str) -> dict:
    """Read a Windows QSettings registry tree."""
    if os.name != "nt":
        return {}
    try:
        import winreg
    except Exception:
        return {}
    flat: dict[str, Any] = {}

    def walk(path: str, prefix: str):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                index = 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    flat[prefix + name] = value
                index = 0
                while True:
                    try:
                        child = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    walk(f"{path}\\{child}", prefix + child + "/")

        except OSError:
            return

    walk(f"Software\\{org}\\{app}", "")
    return flat


def _legacy_native(org: str, app: str) -> dict:
    if sys.platform == "darwin":
        return _read_plist(org, app)
    if os.name == "nt":
        return _read_registry(org, app)
    return _read_ini(org, app)


def _legacy_json(org: str, app: str) -> dict:
    """Values from a JSON store written before the folder rename.

    Builds shipped since the Qt-free settings store keep their JSON under
    ``<app data>/preferences/<org>/<app>.json``. That folder was called
    ``GoldenNugget``; it is ``gnugget`` now, and the old copy is only moved over
    by the migration window. A user who dismisses that window (or launches the
    new build with ``GOLDENNUGGET_NO_DATA_MIGRATION=1``) must still see their
    preferences instead of writing fresh defaults over a store that is skipped
    later as "already exists in the new folder".

    The oldest copy lives in the pre-rename folder; the newest file wins. The
    legacy file is only ever read.
    """
    if os.environ.get("GOLDENNUGGET_PREFERENCES_DIR", "").strip():
        # An explicit store location is a sandbox (tests, tools): no history.
        return {}
    candidates = [root / "preferences" / org / f"{app}.json"
                  for root in legacy_app_data_dirs()]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    return {}


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

def _preferences_root() -> Path:
    """Directory holding the JSON stores.

    ``GOLDENNUGGET_PREFERENCES_DIR`` relocates it (the offline test runner uses
    this so a suite can never touch the real user preferences).
    """
    override = os.environ.get("GOLDENNUGGET_PREFERENCES_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return app_data_dir() / "preferences"


def _json_path(org: str, app: str) -> Path:
    return _preferences_root() / org / f"{app}.json"


class _Store:
    """One organisation/application settings store, shared per process."""

    def __init__(self, org: str, app: str):
        self.org = org
        self.app = app
        self.path = _json_path(org, app)
        self._data: dict[str, Any] | None = None
        self._dirty = False
        # Exact JSON payload last written to disk, so a write that changes
        # nothing (a theme re-applied, a switch toggled back) costs no I/O.
        self._written: str | None = None

    # -- loading ----------------------------------------------------------- #

    def _ensure_loaded(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        data: dict[str, Any] = {}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
        if not self.path.is_file():
            # Values written by an older build: the native store first (the
            # oldest), then the JSON store of the pre-rename folder (newest).
            data = dict(_legacy_native(self.org, self.app))
            data.update(_legacy_json(self.org, self.app))
            # Reading never writes: an app that only reads settings (the CLI,
            # the theme manager built before the one-time data move) must not
            # create files. `_dirty` only means "persist the merged view with
            # the first write" — which would otherwise make the migration skip
            # the very JSON file this store just shadowed.
            if data:
                self._dirty = True
        self._data = data
        return data

    # -- persistence ------------------------------------------------------- #

    def _flush_if_dirty(self) -> None:
        if not self._dirty or self._data is None:
            return
        try:
            payload = json.dumps(self._data, ensure_ascii=False, indent=2,
                                 default=_json_default)
        except Exception:
            # Settings must never crash an operation; losing a preference is
            # better than aborting an apply.
            return
        if payload == self._written:
            # Nothing actually changed. This is the common case for a theme
            # manager that re-applies the same accent on every page switch.
            self._dirty = False
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".settings-", delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                # No fsync: the atomic os.replace below is what keeps the store
                # from being torn, and fsync cost 1-10 ms per call on APFS —
                # paid on the GUI thread for every single setValue. Losing the
                # last preference on a power cut is acceptable; corrupting the
                # file is not, and replace() already prevents that.
            os.replace(temporary, self.path)
            temporary = None
            self._dirty = False
            self._written = payload
        except Exception:
            # Settings must never crash an operation; losing a preference is
            # better than aborting an apply.
            pass
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    # -- API --------------------------------------------------------------- #

    def contains(self, key: str) -> bool:
        return key in self._ensure_loaded()

    def raw(self, key: str) -> Any:
        return self._ensure_loaded().get(key)

    def set(self, key: str, value: Any) -> None:
        self._ensure_loaded()[key] = value
        self._dirty = True
        self._flush_if_dirty()

    def set_many(self, values: dict[str, Any]) -> None:
        """Write several keys with a single serialization + flush.

        Pages that persist a handful of related values (a theme choice, a
        preset's options) used to pay one full JSON rewrite per key.
        """
        if not values:
            return
        self._ensure_loaded().update(values)
        self._dirty = True
        self._flush_if_dirty()

    def remove(self, key: str) -> None:
        if key in self._ensure_loaded():
            del self._data[key]
            self._dirty = True
            self._flush_if_dirty()

    def keys(self) -> list[str]:
        return list(self._ensure_loaded().keys())

    def sync(self) -> None:
        self._flush_if_dirty()

    def fileName(self) -> str:  # noqa: N802 - QSettings-compatible name
        return str(self.path)


def _json_default(value: Any):
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _store(org: str, app: str) -> _Store:
    key = (org, app)
    with _LOCK:
        store = _STORES.get(key)
        if store is None:
            store = _Store(org, app)
            _STORES[key] = store
        return store


def _coerce(value: Any, wanted: type | None) -> Any:
    if wanted is None:
        return value
    if wanted is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off", ""):
                return False
            try:
                return bool(float(lowered))
            except ValueError:
                return False
        return bool(value)
    if wanted is str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value)
    if wanted is int:
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0
    if wanted is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    try:
        return wanted(value)
    except Exception:
        return value


# --------------------------------------------------------------------------- #
# Public wrapper
# --------------------------------------------------------------------------- #

NEW_ORG = "GoldenNugget"
LEGACY_ORG = "Nugget"


class Settings:
    """Stores under ``GoldenNugget`` and reads through to ``Nugget``.

    Drop-in replacement for the old QSettings-backed wrapper; the public
    methods (``contains``/``value``/``setValue``/``remove``/``sync``) are
    unchanged.
    """

    def __init__(self, app: str = "settings"):
        self.app = app
        self._primary = _store(NEW_ORG, app)
        self._legacy = _store(LEGACY_ORG, app)

    def contains(self, key: str) -> bool:
        return self._primary.contains(key) or self._legacy.contains(key)

    def value(self, key: str, defaultValue=None, type=None):  # noqa: A002 - QSettings API
        if self._primary.contains(key):
            return _coerce(self._primary.raw(key), type)
        if self._legacy.contains(key):
            return _coerce(self._legacy.raw(key), type)
        return defaultValue

    def setValue(self, key: str, value):  # noqa: N802 - QSettings API
        self._primary.set(key, value)

    def set_many(self, values: dict):
        """Batch form of :meth:`setValue` — one flush for all keys."""
        self._primary.set_many(values)

    def remove(self, key: str):
        self._primary.remove(key)
        self._legacy.remove(key)

    def sync(self):
        self._primary.sync()
        self._legacy.sync()

    def allKeys(self) -> list[str]:  # noqa: N802 - QSettings API
        keys = set(self._primary.keys()) | set(self._legacy.keys())
        return sorted(keys)

    def fileName(self) -> str:  # noqa: N802 - QSettings API
        return self._primary.fileName()


def reset_for_tests() -> None:
    """Drop every in-process store (tests only)."""
    with _LOCK:
        _STORES.clear()
