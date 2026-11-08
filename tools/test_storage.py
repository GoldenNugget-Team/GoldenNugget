#!/usr/bin/env python3
"""Offline test for the backup/cache location resolver (no device needed).

``src/restore/storage.py`` decides where the heavy backup trees live:
  1. ``GOLDENNUGGET_BACKUP_DIR`` env override (headless/manual tools)
  2. the ``backup_storage_dir`` settings key (GUI: Settings -> Backup
     -> "Backup/Cache Location")
  3. the app's own data folder (``src.utils.paths``).

The test pins all three branches plus the relative-subfolder layout for a
custom root, using throwaway XDG dirs so the host profile is never touched.
Run: python tools/test_storage.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

cfg_tmp = tempfile.mkdtemp(prefix="gn_storage_cfg_")
data_tmp = tempfile.mkdtemp(prefix="gn_storage_data_")
os.environ["XDG_CONFIG_HOME"] = cfg_tmp
os.environ["XDG_DATA_HOME"] = data_tmp
os.environ.pop("GOLDENNUGGET_BACKUP_DIR", None)

from PySide6.QtCore import QCoreApplication, QStandardPaths

app = QCoreApplication(sys.argv)
app.setApplicationName("GoldenNugget")
app.setOrganizationDomain("com.leemin")

from src.controllers.settings import Settings
from src.restore import storage
from src.utils.paths import (
    APP_NAME,
    app_data_dir,
    app_data_root,
    legacy_app_data_dirs,
)

# The app's own folder (``<data root>/gnugget``). The old builds used Qt's
# ``QStandardPaths`` with the app name, which is exactly the legacy folder the
# migration moves out of.
AD = app_data_dir()
QAD = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def reset():
    os.environ.pop("GOLDENNUGGET_BACKUP_DIR", None)
    Settings("settings").remove("backup_storage_dir")
    Settings("settings").sync()


reset()
check("the brand folder is the lower-case name", APP_NAME == "gnugget")
check("app data lives under <data root>/gnugget",
      AD == app_data_root() / "gnugget")
check("Qt still answers the OLD folder (that is what we migrate from)",
      QAD != AD and QAD.parent == AD.parent)
check("the legacy folder is a sibling of the new one",
      legacy_app_data_dirs()[0] == AD.parent / "GoldenNugget")

# 1. Defaults: nothing configured -> the app's own folder, no extra nesting.
check("default cache_base", storage.cache_base() == AD / "backup_cache")
check("default protective_base", storage.protective_base() == AD / "protective")
check("default posterboard_dir", storage.posterboard_dir() == AD / "PosterBoard")
check("default legacy_backups_dir", storage.legacy_backups_dir() == AD / "Backups")
check("default is_custom_backup_dir()", storage.is_custom_backup_dir() is False)

# 2. Settings key set -> relative subfolders mirror the default layout.
custom = Path(tempfile.mkdtemp(prefix="gn_storage_custom_"))
Settings("settings").setValue("backup_storage_dir", str(custom))
Settings("settings").sync()
check("setting: is_custom_backup_dir()", storage.is_custom_backup_dir() is True)
check("setting: cache_base under custom root", storage.cache_base() == custom / "backup_cache")
check("setting: protective_base under custom root", storage.protective_base() == custom / "protective")
check("setting: posterboard under custom root", storage.posterboard_dir() == custom / "PosterBoard")
check("setting: legacy under custom root", storage.legacy_backups_dir() == custom / "Backups")

# 3. Env override beats the QSettings key.
env_custom = Path(tempfile.mkdtemp(prefix="gn_storage_env_"))
os.environ["GOLDENNUGGET_BACKUP_DIR"] = str(env_custom)
check("env: overrides the setting entirely", storage.is_custom_backup_dir() is True)
check("env: cache_base under env root", storage.cache_base() == env_custom / "backup_cache")
check("env: protective_base under env root", storage.protective_base() == env_custom / "protective")

# 4. Clearing the env var falls back to the QSettings key again.
os.environ.pop("GOLDENNUGGET_BACKUP_DIR", None)
check("env cleared: setting applies again", storage.cache_base() == custom / "backup_cache")

# 5. Env override accepts a tilde-expanded relative home path.
os.environ["GOLDENNUGGET_BACKUP_DIR"] = "~/gn_backup_store"
check("env: ~ expands to home", storage.cache_base() == Path.home() / "gn_backup_store" / "backup_cache")

# 6. Reset: no env, no key -> AppData defaults back.
os.environ.pop("GOLDENNUGGET_BACKUP_DIR", None)
Settings("settings").remove("backup_storage_dir")
Settings("settings").sync()
check("reset: cache_base back to default", storage.cache_base() == AD / "backup_cache")
check("reset: is_custom_backup_dir() False again", storage.is_custom_backup_dir() is False)

print(f"ALL STORAGE CHECKS PASSED ({PASS} checks)", flush=True)