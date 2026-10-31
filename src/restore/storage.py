"""Single source of truth for where GoldenNugget's backup data lives on disk.

All the heavy trees (protective backup cache master + AFC media store, live
protective backup runs, PosterBoard database pulls and legacy full backups)
have to sit somewhere on this computer. By default that somewhere is Qt's
per-user AppData directory — on a small system drive that can fill up fast.

Settings -> Backup -> "Backup/Cache Location" (key ``backup_storage_dir``)
lets the user point the whole backup data root at another volume/folder. When
set, every component keeps its usual relative subfolder underneath, mirroring
the AppData layout; when unset the historical AppData locations are used
verbatim, so existing installs never move on their own.

Resolution priority (highest first):
  1. ``GOLDENNUGGET_BACKUP_DIR`` environment override (headless/manual tools)
  2. the ``backup_storage_dir`` QSettings key (GUI + CLI)
  3. the default AppData location
"""

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

_SETTING_KEY = "backup_storage_dir"
_ENV_OVERRIDE = "GOLDENNUGGET_BACKUP_DIR"


def _configured_root() -> Path:
    """The configured backup root (env override > QSettings > AppData default).

    The QSettings read is cheap and only happens when the env override is
    absent; headless/manual tools may force a location via the env var.
    """
    raw = os.environ.get(_ENV_OVERRIDE, "").strip()
    if not raw:
        try:
            from src.controllers.settings import Settings
            raw = str(Settings("settings").value(_SETTING_KEY, "", type=str)).strip()
        except Exception:
            raw = ""
    return Path(raw).expanduser() if raw else Path(
        QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))


def is_custom_backup_dir() -> bool:
    """True when a non-default backup location is configured."""
    raw = os.environ.get(_ENV_OVERRIDE, "").strip()
    if raw:
        return True
    try:
        from src.controllers.settings import Settings
        raw = str(Settings("settings").value(_SETTING_KEY, "", type=str)).strip()
    except Exception:
        raw = ""
    return bool(raw)


def cache_base() -> Path:
    """Root of the protective backup cache (master, media store, restore views)."""
    root = _configured_root()
    if is_custom_backup_dir():
        return root / "backup_cache"
    return root / "GoldenNugget" / "backup_cache"


def protective_base() -> Path:
    """Per-user folder holding live protective backups that survive reboots."""
    root = _configured_root()
    if is_custom_backup_dir():
        return root / "protective"
    return root / "GoldenNugget" / "protective"


def posterboard_dir() -> Path:
    """Folder holding extracted PosterBoard database pulls (per UDID)."""
    return _configured_root() / "PosterBoard"


def statusbar_dir() -> Path:
    """Folder holding StatusBarOverrides.archive dumps (per UDID, research)."""
    return _configured_root() / "StatusBar"


def legacy_backups_dir() -> Path:
    """Folder holding legacy full-device backups (PosterBoard fallback)."""
    return _configured_root() / "Backups"