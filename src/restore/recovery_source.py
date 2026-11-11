"""Read-only recovery lookup across the original and Liquid UI data stores."""
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from .inject import _is_encrypted_backup
from .protective import _validate_sqlite_db
from .storage import cache_base, protective_base


def locate_restore_source(udid):
    if not udid or Path(udid).name != udid or udid in (".", ".."):
        return None, None
    app_data = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    generic = Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation))
    legacy_roots = [app_data / "GoldenNugget",
                    generic / "GoldenNugget" / "GoldenNugget",
                    generic / "GoldenNugget Liquid UI" / "GoldenNugget"]

    def usable(root):
        device = root / udid
        manifest = device / "Manifest.db"
        return manifest.is_file() and (_validate_sqlite_db(manifest) or _is_encrypted_backup(device))

    caches = [cache_base(), *(root / "backup_cache" for root in legacy_roots),
              Path(tempfile.gettempdir()) / "goldennugget_protective_cache"]
    for base in dict.fromkeys(caches):
        if usable(base / "master"):
            return str(base / "master"), base
    runs = []
    for base in dict.fromkeys([protective_base(), *(root / "protective" for root in legacy_roots)]):
        device_root = base / udid
        if device_root.is_dir():
            for run in device_root.iterdir():
                root = run / "device_backup"
                if run.is_dir() and usable(root):
                    runs.append((run.stat().st_mtime, root))
    if runs:
        return str(max(runs, key=lambda item: item[0])[1]), None
    return None, None
