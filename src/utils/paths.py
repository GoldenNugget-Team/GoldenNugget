"""Qt-free per-user data locations.

Every file GoldenNugget owns lives under one brand folder per platform:

=================  =========================================
macOS              ``~/Library/Application Support/gnugget``
Linux / BSD        ``$XDG_DATA_HOME/gnugget`` (``~/.local/share/gnugget``)
Windows            ``%APPDATA%/gnugget``
=================  =========================================

The cache follows the platform convention the same way
(``~/Library/Caches/gnugget``, ``$XDG_CACHE_HOME/gnugget``,
``%LOCALAPPDATA%/gnugget``).

The folder used to be called ``GoldenNugget`` (and, for the Liquid UI build,
``GoldenNugget Liquid UI``). :func:`legacy_app_data_dirs` and
:func:`legacy_cache_dirs` return those historical locations so
``src.utils.user_data_migration`` can move an existing install into the new
folder, and so the recovery tools can still read a cache that was never
migrated. Nothing here deletes anything: the move is driven by the GUI
migration window.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "gnugget"

#: Historical brand folder names, newest first. Everything the app wrote before
#: the rename lives in one of these.
LEGACY_APP_NAMES = ("GoldenNugget", "GoldenNugget Liquid UI")

#: Folders that used to be created next to the brand folder (generic data
#: location) instead of inside it, before ``posterboard_dir`` moved.
LEGACY_GENERIC_NAMES = ("PosterBoard", "Backups", "StatusBar")

#: Names accepted as "this already IS the app's own folder", so a root that the
#: user picked before the rename is not nested a second time.
_BRAND_NAMES = (APP_NAME, *(name.lower() for name in LEGACY_APP_NAMES))


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(os.path.expanduser(raw)) if raw else None


def _mac_app_support() -> Path:
    return _home() / "Library" / "Application Support"


def _mac_caches() -> Path:
    return _home() / "Library" / "Caches"


def _windows_roaming() -> Path:
    return _env_path("APPDATA") or (_home() / "AppData" / "Roaming")


def _windows_local() -> Path:
    return _env_path("LOCALAPPDATA") or (_home() / "AppData" / "Local")


def _xdg_data() -> Path:
    return _env_path("XDG_DATA_HOME") or (_home() / ".local" / "share")


def _xdg_cache() -> Path:
    return _env_path("XDG_CACHE_HOME") or (_home() / ".cache")


# --------------------------------------------------------------------------- #
# Platform roots (without our own folder name)
# --------------------------------------------------------------------------- #

def app_data_root() -> Path:
    """The per-user data root that contains the brand folder."""
    if sys.platform == "darwin":
        return _mac_app_support()
    if os.name == "nt":
        return _windows_roaming()
    return _xdg_data()


def cache_root() -> Path:
    """The per-user cache root that contains the brand folder."""
    if sys.platform == "darwin":
        return _mac_caches()
    if os.name == "nt":
        return _windows_local()
    return _xdg_cache()


# --------------------------------------------------------------------------- #
# App folders
# --------------------------------------------------------------------------- #

def app_data_dir() -> Path:
    """Per-application data directory (``<data root>/gnugget``)."""
    return app_data_root() / APP_NAME


def cache_dir() -> Path:
    """Per-application cache directory (``<cache root>/gnugget``)."""
    return cache_root() / APP_NAME


def generic_data_dir() -> Path:
    """Shared data directory (``QStandardPaths.GenericDataLocation``)."""
    if sys.platform == "darwin":
        return _mac_app_support()
    if os.name == "nt":
        return _windows_local()
    return _xdg_data()


def generic_cache_dir() -> Path:
    """Shared cache directory (``QStandardPaths.GenericCacheLocation``)."""
    if sys.platform == "darwin":
        return _mac_caches()
    if os.name == "nt":
        return _windows_local() / "cache"
    return _xdg_cache()


def brand_dir(root) -> Path:
    """The app's own folder inside *root*.

    *root* is either a platform root (``app_data_dir()``, a user-chosen backup
    volume, ...). Returns *root* unchanged when it already names the app's
    folder — including the pre-rename ``GoldenNugget`` names, so a backup
    volume that was configured before the rename keeps its existing tree
    instead of growing a second ``gnugget`` level.
    """
    root = Path(root)
    return root if root.name.lower() in _BRAND_NAMES else root / APP_NAME


# --------------------------------------------------------------------------- #
# Historical locations (migration + recovery)
# --------------------------------------------------------------------------- #

def legacy_app_data_dirs() -> list[Path]:
    """Data folders written by older builds, newest first."""
    return [app_data_root() / name for name in LEGACY_APP_NAMES]


def legacy_cache_dirs() -> list[Path]:
    """Cache folders written by older builds, newest first."""
    return [cache_root() / name for name in LEGACY_APP_NAMES]


def legacy_generic_dirs() -> list[Path]:
    """Old loose folders that sat next to the brand folder."""
    return [generic_data_dir() / name for name in LEGACY_GENERIC_NAMES]


def ensure_dir(path: str | os.PathLike) -> Path:
    """Create *path* (including parents) and return it as a :class:`Path`."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target
