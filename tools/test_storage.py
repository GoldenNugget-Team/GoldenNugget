#!/usr/bin/env python3
"""Offline test for the backup/cache location resolver (no device needed).

``src/restore/storage.py`` decides where the heavy backup trees live:
  1. ``GOLDENNUGGET_BACKUP_DIR`` env override (headless/manual tools)
  2. the ``backup_storage_dir`` QSettings key (GUI: Settings -> Backup
     -> "Backup/Cache Location")
  3. the historical AppData defaults, byte-for-byte.

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
app.setOrganizationName("GoldenNugget")
app.setOrganizationDomain("com.leemin")

from src.controllers.settings import Settings
from src.restore import storage

AD = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))

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
check("custom root resolves under AppData when app name set", AD.name == "GoldenNugget")

# 1. Defaults: nothing configured -> historical layout, byte-for-byte.
check("default cache_base", storage.cache_base() == AD / "GoldenNugget" / "backup_cache")
check("default protective_base", storage.protective_base() == AD / "GoldenNugget" / "protective")
check("default posterboard_dir", storage.posterboard_dir() == AD / "PosterBoard")
check("default legacy_backups_dir", storage.legacy_backups_dir() == AD / "Backups")
check("default is_custom_backup_dir()", storage.is_custom_backup_dir() is False)

# 2. QSettings key set -> relative subfolders mirror the AppData layout.
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
check("reset: cache_base back to default", storage.cache_base() == AD / "GoldenNugget" / "backup_cache")
check("reset: is_custom_backup_dir() False again", storage.is_custom_backup_dir() is False)

print(f"ALL STORAGE CHECKS PASSED ({PASS} checks)", flush=True)