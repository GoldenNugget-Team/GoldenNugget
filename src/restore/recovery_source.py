"""Read-only recovery lookup across the original and Liquid UI data stores."""
import stat as _stat
import tempfile
from pathlib import Path

from src.utils.paths import generic_data_dir, legacy_app_data_dirs

from .inject import _is_encrypted_backup
from .protective import _validate_sqlite_db
from .storage import cache_base, protective_base


def locate_restore_source(udid):
    if not udid or Path(udid).name != udid or udid in (".", ".."):
        return None, None
    generic = Path(str(generic_data_dir()))
    # Folders written before the rename (``GoldenNugget``, Liquid UI) and the
    # nested layout those builds produced (``GoldenNugget/GoldenNugget``).
    # They only still exist if the user has not run the migration yet.
    legacy_roots = []
    for legacy in legacy_app_data_dirs():
        legacy_roots += [legacy, legacy / "GoldenNugget"]
    legacy_roots.append(generic / "GoldenNugget Liquid UI" / "GoldenNugget")
    legacy_roots = list(dict.fromkeys(legacy_roots))

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
                try:
                    # One stat for both the type test and the mtime; the old
                    # loop called is_dir() and then stat() again.
                    run_stat = run.stat()
                except OSError:
                    continue
                if not _stat.S_ISDIR(run_stat.st_mode):
                    continue
                root = run / "device_backup"
                if usable(root):
                    runs.append((run_stat.st_mtime, root))
    if runs:
        return str(max(runs, key=lambda item: item[0])[1]), None
    return None, None
