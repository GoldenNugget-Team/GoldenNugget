"""
Protective backup module for iOS 27+.

On iOS 27, the sparse restore triggers a "safe state recovery" that purges
device data not present in the backup (photos, Apple ID credentials, user
settings). To keep user data alive, the three-phase flow in restore.py does:

  Phase 1 (this module): selective device backup. App containers are skipped
      device-side (empty Applications dict in the factory info), and every
      non-protective file the device uploads is discarded mid-stream instead
      of being written to disk. Peak disk usage drops from a full backup
      (10-100+ GB) to just the protective payload. If the selective upload
      fails for any reason, we automatically fall back to a full backup.
  Phase 3 (this module): the same backup directory — with Manifest.db pruned
      to the protective rows and orphan payload files removed — is restored
      back to the device after the security recovery.

Protective scope: HomeDomain/{Accounts, ConfigurationProfiles, Preferences,
Library/SpringBoard} (Apple ID + user settings + home screen layout),
Library/ControlCenter (Control Center module layout), Library/Shortcuts
(iOS Shortcuts automations and commands), Library/WebClips (Safari
"Add to Home Screen" web clips, incl. each <.webclip>/Storage PWA payload),
Library/WebApp + Library/WebKit/WebsiteData (installed-PWA data on iOS
releases that keep it outside the web clip), MessagesDomain
(iMessage/SMS/MMS), and, optionally, CameraRollDomain + MediaDomain (photos).
KeychainDomain (captured keychain material) is
included only when backup encryption is enabled — keychain payloads are
encrypted at rest and iOS rejects them in an unencrypted backup.
"""

from src.utils.filecopy import clone_or_copy

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid as _uuid
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymobiledevice3.exceptions as _pm3_exc
import pymobiledevice3.service_connection as _sc
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
from pymobiledevice3.services.lockdown_service import LockdownService
from src.devicemanagement.progress_status import BackupStatus

from pymobiledevice3.services.mobilebackup2 import (
    Mobilebackup2Service, NP_LOCAL_AUTH_PRESENTED, NP_LOCAL_AUTH_DISMISSED,
)

from PySide6.QtCore import QCoreApplication

from src.exceptions.nugget_exception import NuggetException, BackupStorageError, BackupDiskSpaceError
from src.restore.preference_scope import is_preference_file, is_preference_parent, is_preference_upload
from src.restore.afc_media import (  # noqa: F401  (re-exported public API)
    AFC_MEDIA_TREES,
    afc_media_dir_for,
    backup_media_via_afc,
    restore_media_via_afc,
)
from src.restore.inject import (  # noqa: F401  (re-exported public API)
    _is_encrypted_backup,
    _validate_sqlite_db,
    inject_files_into_backup,
)
from src.restore.protective_cache import (  # noqa: F401  (re-exported public API)
    CACHE_MEDIA_REFRESH_SECS,
    CACHE_PERSIST_MIN_GB,
    CACHE_REFRESH_SECS,
    ProtectiveBackupCache,
)


@dataclass
class PreparedBackup:
    """A protective backup prepared ahead of the three-phase restore."""
    root: str
    manifest_password: str = ""  # required to prune/inject encrypted manifests
    # True when ``root`` is the CACHE MASTER — a pristine, incrementally
    # refreshed mirror of the device that the master must never modify.
    # The apply therefore builds a disposable *view* of it (a pruned copy of
    # the manifest plus hardlinks to the payloads) and restores from that; the
    # master itself stays untouched, so the next refresh still diffs against a
    # full manifest and a crashed apply cannot leave it half-pruned.
    # False for a fresh live backup, which the restore prunes in place (it is
    # disposable by nature, so no copy is needed).
    master: bool = False
    # Where the per-apply restore view is built. It must sit on the same
    # filesystem as the master so the view's payload hardlinks stay links
    # instead of degrading into full copies. Empty for live backups.
    view_root: str = ""
    # Directory holding the photos/videos pulled over AFC in parallel with this
    # backup ('' when the media stayed in the mobilebackup2 backup — those
    # manifest rows ride Phase 3's protective restore). Phase 5 pushes this
    # tree back to the device via AFC, after the Phase 4 reboot and reconnect.
    media_src: str = ""


# Minimum free disk space required before any device backup is started.
# Backups can easily reach several GB (photos, app data), so filling the disk
# mid-backup is a real hazard. Overridable via GOLDENNUGGET_MIN_FREE_GB.
#
# PosterBoard workspaces and live protective backups use the configured
# backup storage volume. Callers that
# pass a path must pass the one they actually write to — on a multi-volume Mac
# the check has to measure the right disk.
MIN_FREE_DISK_GB = 5.0


def _min_free_disk_bytes() -> int:
    try:
        return int(float(os.environ.get("GOLDENNUGGET_MIN_FREE_GB", str(MIN_FREE_DISK_GB))) * (1024 ** 3))
    except ValueError:
        return int(MIN_FREE_DISK_GB * (1024 ** 3))


def check_disk_space(path: str = None, min_free_bytes: int = None) -> None:
    """Raise ``NuggetException`` if free disk space is below the backup threshold.

    Device backups are written to disk (temp directory by default); a full
    backup can be tens of GB. Fail early with a clear error instead of filling
    the disk mid-backup, which would corrupt the backup and the apply flow.
    """
    import tempfile
    if path is None:
        path = tempfile.gettempdir()
    os.makedirs(path, exist_ok=True)  # disk_usage requires an existing path
    if min_free_bytes is None:
        min_free_bytes = _min_free_disk_bytes()
    usage = shutil.disk_usage(path)
    if usage.free < min_free_bytes:
        free_gb = usage.free / (1024 ** 3)
        required_gb = min_free_bytes / (1024 ** 3)
        raise BackupStorageError(
            QCoreApplication.translate(
                "Nugget",
                "Not enough free disk space: only {0} GB available, at least {1} GB is required for the backup. "
                "Free up space on your computer (backups are written to {2}) and try again.",
            ).format(f"{free_gb:.1f}", f"{required_gb:.1f}", path), location="computer"
        )


async def _get_device_used_storage(lockdown_client) -> Optional[int]:
    """Return the device's used data storage in bytes, or ``None`` if unreadable.

    Queries the diagnostics relay's ``All`` report. ``TotalDataCapacity`` is the
    total size of the data partition and ``TotalDataSpace`` is its free space, so
    the difference is how much data a full device backup would carry. A full
    backup mirrors roughly the used capacity, so this is the disk space a backup
    needs to be written to the computer without exhausting it.
    """
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown_client) as diag:
            report = await diag.info("All")
        if not isinstance(report, dict):
            return None
        capacity = report.get("TotalDataCapacity")
        free = report.get("TotalDataSpace")
        if capacity is None or free is None:
            nested = report.get("DiskUsage")
            if isinstance(nested, dict):
                capacity = nested.get("TotalDataCapacity", capacity)
                free = nested.get("TotalDataSpace", free)
        if capacity is None or free is None:
            return None
        used = int(capacity) - int(free)
        return used if used > 0 else None
    except Exception:
        return None


async def check_disk_space_for_backup(lockdown_client=None, path: str = None,
                                      min_free_bytes: int = None) -> int:
    """Check free disk space before a device backup, sized to the device's data.

    The required free space is derived from the amount of data actually stored
    on the device (a full backup mirrors used capacity), never below the
    ``MIN_FREE_DISK_GB`` floor. If the device cannot be queried, the floor is
    used. Returns the required free space in bytes that was enforced.
    """
    if min_free_bytes is None:
        min_free_bytes = _min_free_disk_bytes()
        if lockdown_client is not None:
            used = await _get_device_used_storage(lockdown_client)
            if used is not None:
                min_free_bytes = max(min_free_bytes, used)
    check_disk_space(path=path, min_free_bytes=min_free_bytes)
    return min_free_bytes

# Bump SSL handshake timeout — the default 10 seconds is too short for
# mobilebackup2 service startup on busy or post-reboot devices (iOS 27+).
# Importing this module applies it process-wide.
_sc.DEFAULT_SSL_HANDSHAKE_TIMEOUT = 60

# Resolve the executor through its defining module, including Python 3.15.
from src.utils.async_disk import ensure_thread_executor
ensure_thread_executor()

from src.utils.log_util import log_info, log_warn, log_error, log_debug
from .device_link_adapter import recv_timeout_secs

# --- DeviceLink protocol constants (from pymobiledevice3.services.device_link) ---

# Backup metadata files that must always be preserved (never filtered out)
from .backup_store import (
    _BACKUP_METADATA_FILES, WORKING_COPY_PREFIX, _copy_backup_tree,
    make_protective_working_copy, make_cache_snapshot, _retire_backup_tree,
    discard_protective_working_copy, regenerate_cache_from_snapshot,
    _payload_inventory, _remove_orphan_payloads,
)

# Domains whose files should be kept in the protective backup.
PROTECTIVE_DOMAINS = frozenset({
    "CameraRollDomain",  # Actual photos and videos (DCIM/)
    "MediaDomain",       # Photo metadata (PhotoData/), PhotoStream, other media
    "MessagesDomain",    # iMessage / SMS / MMS (preserved across safe-state recovery)
})

# KeychainDomain is only included when the user has backup encryption
# enabled — keychain payloads are encrypted at rest and iOS rejects
# unencrypted keychain entries in a backup. Keeping these entries is not proof
# that Apple Watch pairing can be reconstructed after a restore.
KEYCHAIN_DOMAIN = "KeychainDomain"

# Path prefixes within HomeDomain that contain Apple ID account data and
# user settings.
APPLE_ID_PATH_PREFIXES = (
    "Library/Accounts",              # Account database (Accounts3.sqlite)
    "Library/ConfigurationProfiles",  # Configuration profiles
    "Library/Preferences",           # User settings (dark mode, wallpaper, etc.)
)

# NOTE: ConfigurationProfiles (MDM/VPN/WebClip) backup was added in commit
# 25006f5 (Aug 12) and later removed again in the 8.3 hotfix (875d4e1) — the
# widened Phase 3 restore scope rolled back applied tweaks on repeat apply and
# corrupted the PosterBoard database. It was then re-added on top of the
# iOS 27 five-phase restore, which no longer shares scope with the tweak
# pass, so profiles now ride the protective backup without those regressions.
# Restoring profiles is still best-effort: iOS may re-install MDM profiles
# independently of the backup.

# Path prefixes within HomeDomain that hold SpringBoard's home screen layout
# and icon state. Restoring these keeps the home screen (icon layout, folders,
# dock) intact after the iOS 27 "safe state recovery" wipe.
SPRINGBOARD_PATH_PREFIXES = (
    "Library/SpringBoard",
)

WATCH_STATE_PATH_PREFIXES = (
    "Library/DeviceRegistry",
    "Library/DeviceRegistry.state",
)

KEYBOARD_PATH_PREFIXES = ('Library/Keyboard',)

# Path prefixes within HomeDomain holding the Control Center module layout
# (Library/ControlCenter/ModuleConfiguration.plist). Not part of the
# "user settings" prefix above, so it must be listed explicitly — otherwise
# the iOS 27 wipe resets Control Center to its default modules.
CONTROL_CENTER_PATH_PREFIXES = (
    "Library/ControlCenter",
)

# Path prefixes within HomeDomain holding iOS Shortcuts (the Shortcuts app:
# Library/Shortcuts/Shortcuts.sqlite, ShortcutIcons/, VoiceShortcuts/...).
# Automations and custom shortcuts are pure user data and would be lost to
# the iOS 27 "safe state recovery" wipe without an explicit entry.
SHORTCUTS_PATH_PREFIXES = (
    "Library/Shortcuts",
)

# Path prefixes within HomeDomain holding Safari "Add to Home Screen" web
# clips (Library/WebClips/<UUID>.webclip/Info.plist + icon.png). Pure user
# data that the iOS 27 "safe state recovery" wipe would discard; the icon
# layout (IconState.plist) references them by bundle id. The whole tree is
# kept, so a web app's own WKWebsiteDataStore under <.webclip>/Storage/
# (___IndexedDB, Default/<profile>/local storage, cookies, HSTS) rides along —
# that is where iOS 26/27 keeps installed-PWA data.
WEB_CLIPS_PATH_PREFIXES = (
    "Library/WebClips",
)

# Older/alternative HomeDomain homes for installed web-app data. iOS has kept
# per-web-app state under Library/WebApp (WebAppCache, WebAppLocalStorage) on
# some releases, and the modern shared WKWebsiteDataStore (ServiceWorkers,
# IndexedDB, LocalStorage per profile) under Library/WebKit/WebsiteData when
# a web app runs against the Safari store. Covering both makes PWA data
# survive the wipe regardless of which layout the release uses — the browser's
# own store lives in AppDomain-com.apple.mobilesafari and is out of scope.
WEB_APP_PATH_PREFIXES = (
    "Library/WebApp",
)
WEBKIT_WEBSITE_DATA_PATH_PREFIXES = (
    "Library/WebKit/WebsiteData",
)

# Path prefixes within HomeDomain holding the contacts database
# (Library/AddressBook/AddressBook.sqlitedb + -wal/-shm and
# AddressBookImages.sqlitedb). The iOS 27 "safe state recovery" wipe would
# otherwise discard every contact.
ADDRESS_BOOK_PATH_PREFIXES = (
    "Library/AddressBook",
)

# Files/dirs inside the protective HomeDomain scope that tweaks write
# themselves — restoring the stale copies would undo the applied tweaks.
# NOTE the archive keeps a capital "S" (StatusBarOverrides.archive): the
# lowercase classic prefix does NOT match it (Python compares case-sensitively
# and the device filesystem does too), so it needs its own entry. Without it the
# applied carrier override was captured by Phase 1 and handed straight back by
# Phase 3, i.e. a status bar reset looked like it did nothing on iOS 27.
_SKIP_PATH_PREFIXES = (
    "Library/SpringBoard/statusBarOverrides",          # iOS ≤26 classic binary struct
    "Library/SpringBoard/StatusBarOverrides.archive",  # iOS 27+ NSKeyedArchiver record
)

# Files iOS manages internally and rejects if included in a sparse backup
# with incorrect metadata (e.g. wrong protection class). With copy=True the
# existing on-device data is preserved anyway, so skipping them is safe.
_SKIP_FILES = frozenset({
    "keychain-backup.plist",    # iOS validates protection class, rejects flags=4
})

# PosterBoard sqlite database carried by the protective backup so wallpaper
# applies need no second device backup. Scope note: the database lives in the
# cache MASTER only — clean_backup_for_restore prunes it from the restore copy
# so Phase 3 never clobbers the tweaked database Phase 2 lays down. Because
# the master is incrementally refreshed BEFORE extraction, the extracted DB
# always mirrors the live on-device state.
# The store directory carries a structure version (61, 62, ...) that varies
# between iOS releases, so matching is done by FILE NAME, not full path.
POSTERBOARD_DB_DOMAIN = "AppDomain-com.apple.PosterBoard"
POSTERBOARD_DB_NAME = "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"
POSTERBOARD_DB_STORE_DIR = "PRBPosterExtensionDataStore"


def _is_protective_file(domain: str, relative_path: str, include_photos: bool = True, include_keychain: bool = False,
                        exclude_afc_media_trees: bool = False) -> bool:
    """Check if a file belongs in the protective backup."""
    filename = relative_path.rsplit("/", 1)[-1]
    # keychain-backup.plist carries the KeychainDomain payload. It is rejected
    # when restored unencrypted (iOS validates protection class, flags=4), but
    # with an encrypted backup — exactly the case where include_keychain is set —
    # the device decrypts it on restore, so it must be kept.
    if filename in _SKIP_FILES and not (include_keychain and filename == "keychain-backup.plist"):
        return False
    if is_preference_file(domain, relative_path):
        return True
    if domain == 'KeyboardDomain':
        return True
    if domain == "HomeDomain":
        if relative_path.startswith(_SKIP_PATH_PREFIXES):
            return False
        return (relative_path.startswith(APPLE_ID_PATH_PREFIXES)
                or relative_path.startswith(SPRINGBOARD_PATH_PREFIXES)
                or any(relative_path == root or relative_path.startswith(root + '/')
                       for root in WATCH_STATE_PATH_PREFIXES)
                or any(relative_path == root or relative_path.startswith(root + '/')
                       for root in KEYBOARD_PATH_PREFIXES)
                or relative_path.startswith(CONTROL_CENTER_PATH_PREFIXES)
                or relative_path.startswith(SHORTCUTS_PATH_PREFIXES)
                or relative_path.startswith(WEB_CLIPS_PATH_PREFIXES)
                or relative_path.startswith(WEB_APP_PATH_PREFIXES)
                or relative_path.startswith(WEBKIT_WEBSITE_DATA_PATH_PREFIXES)
                or relative_path.startswith(ADDRESS_BOOK_PATH_PREFIXES))
    if include_photos and domain in PROTECTIVE_DOMAINS:
        # Media trees moved to the AFC channel (DCIM, PhotoStreamsData) are not
        # uploaded by mobilebackup2 at all — the manifest rows the device still
        # records for them must be pruned too, or Phase 3 tries to restore
        # payloads that were never written (MBErrorDomain/205).
        if exclude_afc_media_trees and _media_tree_scope(relative_path) in AFC_MEDIA_TREES:
            return False
        return True
    if include_keychain and domain == KEYCHAIN_DOMAIN:
        return True
    return False


def _norm_device_name(device_name: str) -> str:
    return device_name.replace("\\", "/").lstrip("/")


def _domain_match(device_name: str, domain: str) -> bool:
    name = _norm_device_name(device_name)
    return name == domain or name.startswith(f"{domain}/")


def _path_match(device_name: str, path: str) -> bool:
    """Match a HomeDomain-scoped path prefix against a device-side upload name.

    Accepts the three layouts seen in the wild:
    - bare physical path: ``Library/Preferences/...``
    - legacy domain-qualified: ``HomeDomain/Library/Preferences/...``
    - iOS 27 physical tree: ``/.b/<n>/Library/Preferences/...`` (via ``_tree_match``)

    App-container names (``AppDomain-.../`` or ``Containers/.../Library/...``)
    never match: they sit under a different root and are out of protective
    scope. (An earlier substring form ``f"/{path}/" in name`` did match them,
    which is how app plists/WebKit data leaked into the backup.)
    """
    name = _norm_device_name(device_name)
    if name == path or name.startswith(f"{path}/"):
        return True
    if name == f"HomeDomain/{path}" or name.startswith(f"HomeDomain/{path}/"):
        return True
    return _tree_match(device_name, path)


def _device_tree_name(device_name: str) -> str:
    """Normalised device name with the iOS 27+ backup-session root stripped.

    On iOS 27 the device uploads the raw filesystem tree: names arrive as
    ``/.b/<n>/Media/DCIM/IMG_0001.PNG`` with the logical domain (``CameraRollDomain``)
    absent from the name entirely. Stripping the ``.b/<n>/`` root yields the
    physical relative path (``Media/DCIM/IMG_0001.PNG``); legacy domain-qualified
    names (``HomeDomain/Library/...``) pass through unchanged so the domain-style
    matchers keep working on older iOS.
    """
    name = _norm_device_name(device_name)
    for prefix in (".b", "b"):
        if name.startswith(f"{prefix}/"):
            name = name[len(prefix) + 1:]
            if name.split("/", 1)[0].isdigit():
                return name.split("/", 1)[1]
            break
    return name


def _tree_match(device_name: str, *trees: str) -> bool:
    """Match a device name against physical tree roots (iOS 27+ layout).

    ``CameraRollDomain``/``MediaDomain`` files live under the top-level ``Media``
    node (DCIM/, PhotoData/, PhotoStream/...), iMessage data under
    ``Library/Messages`` etc., and the keychain export under ``Keychains/``.
    App-container media sits deeper under ``Containers/...`` (and app containers
    are skipped device-side anyway), so a bare first-segment comparison is
    unambiguous.
    """
    name = _device_tree_name(device_name)
    for tree in trees:
        if name == tree or name.startswith(f"{tree}/"):
            return True
    return False


def _media_tree_scope(device_name: str) -> str:
    """Top-level ``Media`` child an upload lives under, or ``""`` if none.

    Handles every layout the filters see:
    - iOS 26 domain-qualified: ``CameraRollDomain/Media/DCIM/IMG_1.JPG``
    - iOS 27 physical tree: ``/.b/<n>/Media/DCIM/IMG_1.JPG`` (also bare ``Media/...``)

    ``PhotoData`` files return ``"PhotoData"`` etc. Files elsewhere in the
    backup (HomeDomain, MessagesDomain, ...) return ``""``.
    """
    name = _device_tree_name(device_name)
    for prefix in ("CameraRollDomain/Media/", "MediaDomain/Media/", "Media/"):
        if name.startswith(prefix):
            rest = name[len(prefix):]
            seg = rest.split("/", 1)[0]
            return seg
    return ""


def _posterboard_db_match(device_name: str) -> bool:
    """Match the PosterBoard sqlite database by its physical file name.

    The store directory carries a structure version (61, 62, ...) that varies
    between iOS releases and lives inside an app container either as
    ``AppDomain-com.apple.PosterBoard/...`` (iOS 26) or under the raw file tree
    ``/.b/<n>/Containers/...`` (iOS 27), so matching is done by file name, not
    path or domain. Matching is pinned to the (unique) database file name only —
    the ``PRBPosterExtensionDataStore`` store-dir name also varies across iOS
    releases and is missing entirely from some iOS 27.x upload paths.
    """
    name = _norm_device_name(device_name)
    return POSTERBOARD_DB_NAME in name


def backup_category_for(device_name: str) -> BackupStatus:
    """Progress label for the kind of data a device upload belongs to.

    Only ever a label — it says what a long, quiet backup is working on. The
    name shapes differ per iOS release: iOS 26 sends domain-qualified names
    (``CameraRollDomain/Media/...``) while iOS 27+ sends the raw filesystem
    tree (``/.b/<n>/Media/...``). ``_device_tree_name`` normalises both, so a
    physical ``Media/`` or ``Keychains/`` root lands in the same category as
    its domain form; without that every iOS 27 upload fell through to the
    generic "Device data", which is the label a stalled apply appeared to sit
    on forever.
    """
    low = _device_tree_name(device_name or "").lower()

    def under(*roots: str) -> bool:
        return any(low == root or low.startswith(f"{root}/") for root in roots)

    if "keychaindomain" in low or under("keychains"):
        return BackupStatus(QCoreApplication.translate("Nugget", "Keychain"), "keychain")
    if "messagesdomain" in low or under("library/messages"):
        return BackupStatus(QCoreApplication.translate("Nugget", "Messages"), "messages")
    if "camerarolldomain" in low or "mediadomain" in low or under("media"):
        return BackupStatus(QCoreApplication.translate("Nugget", "Photos and videos"), "photos")
    if "accounts" in low or "appleaccount" in low:
        return BackupStatus(QCoreApplication.translate("Nugget", "Apple account"), "account")
    if "springboard" in low or "home screen" in low:
        return BackupStatus(QCoreApplication.translate("Nugget", "Home screen"), "home")
    if "shortcuts" in low:
        return BackupStatus(QCoreApplication.translate("Nugget", "Shortcuts"), "shortcuts")
    if "poster" in low:
        return BackupStatus(QCoreApplication.translate("Nugget", "Wallpaper data"), "wallpaper")
    if "preferences" in low or "configurationprofiles" in low:
        return BackupStatus(QCoreApplication.translate("Nugget", "Settings"), "settings")
    return BackupStatus(QCoreApplication.translate("Nugget", "Device data"), "backup")


def backup_disk_space_message(path, available_bytes=None) -> str:
    """Describe a host-side backup space refusal using the actual destination."""
    if available_bytes is None:
        try:
            available_bytes = shutil.disk_usage(path).free
        except OSError:
            pass
    available = (QCoreApplication.translate("Nugget", "Available on that drive: {0} GiB.")
                 .format(f"{available_bytes / (1024 ** 3):.1f}")
                 if available_bytes is not None else "")
    return QCoreApplication.translate(
        "Nugget",
        "The device refused the backup because the backup drive does not have enough free disk space.\n\n"
        "Backup location: {0}\n{1}\n\n"
        "Free space on that drive, or choose a drive with more room in Settings → Backup → "
        "Backup/Cache Location, then retry. A filtered backup can still require space for "
        "the device's full backup estimate.").format(path, available)


def _install_device_link_verbose():
    from .device_link_adapter import install_verbose
    install_verbose(backup_disk_space_message)


def _install_device_link_contents_shim():
    from .device_link_adapter import install_contents
    install_contents()


def _install_device_link_recv_timeout():
    from .device_link_adapter import install_recv_timeout
    install_recv_timeout()


_install_device_link_verbose()
_install_device_link_contents_shim()
_install_device_link_recv_timeout()


def is_protective_device_file(device_name: str, include_photos: bool = True,
                              include_posterboard: bool = False,
                              include_keychain: bool = False,
                              exclude_afc_media_trees: bool = False) -> bool:
    """Mid-stream backup filter: match an upload's device-side name against the keep-set.

    On iOS 26 upload names carry the domain and path (``HomeDomain/Library/...``),
    mirroring pymobiledevice3's own BackupSelectionRule matching. On iOS 27 the
    device uploads the raw filesystem tree (``/.b/<n>/Media/DCIM/...``) with no
    domain in the name, so the keep-set is matched against the physical tree
    roots instead (see ``_tree_match``). Rejected payloads are drained by the
    DeviceLink; their Manifest.db rows survive so subsequent incremental backups
    do not re-upload them.
    """
    if is_preference_upload(_device_tree_name(device_name)):
        return True
    for domain in (("CameraRollDomain", "MediaDomain") if include_photos else ()) + \
            ("SystemPreferencesDomain", "MessagesDomain", "AddressBookDomain", "KeyboardDomain"):
        if _domain_match(device_name, domain):
            # Media trees moved to the AFC channel are handed to AFC, not this
            # backup — drop their uploads mid-stream so their payloads never
            # hit disk (the same exclusion prunes their manifest rows later).
            if exclude_afc_media_trees and _media_tree_scope(device_name) in AFC_MEDIA_TREES:
                continue
            return True
    if _tree_match(device_name, 'preferences'):
        return True
    if include_photos and not (exclude_afc_media_trees
                               and _media_tree_scope(device_name) in AFC_MEDIA_TREES) \
            and _tree_match(device_name, "Media"):
        return True
    if _tree_match(device_name, "Library/Messages", "Library/SMS", "Library/MessagesMetaData"):
        return True
    if include_keychain and (_domain_match(device_name, KEYCHAIN_DOMAIN)
                             or _tree_match(device_name, "Keychains")):
        return True
    for prefix in (APPLE_ID_PATH_PREFIXES + SPRINGBOARD_PATH_PREFIXES
               + WATCH_STATE_PATH_PREFIXES
               + KEYBOARD_PATH_PREFIXES
               + CONTROL_CENTER_PATH_PREFIXES + SHORTCUTS_PATH_PREFIXES
               + WEB_CLIPS_PATH_PREFIXES + WEB_APP_PATH_PREFIXES
               + WEBKIT_WEBSITE_DATA_PATH_PREFIXES
               + ADDRESS_BOOK_PATH_PREFIXES):
        if _path_match(device_name, prefix):
            return True
    if include_posterboard and _posterboard_db_match(device_name):
        return True
    return False


class ProtectiveBackupService(Mobilebackup2Service):
    """Mobilebackup2Service tuned for fast protective backups.

    - ``init_mobile_backup_factory_info`` returns an empty ``Applications``
      dict, so the device skips all app containers (AppDomain-*) entirely —
      they are never uploaded at all. With ``include_posterboard`` it lists
      only the PosterBoard container so its sqlite database rides the same
      backup.
    - Mid-stream payload filtering is done via pymobiledevice3's native
      ``filter_callback`` on ``backup()``.
    - ``connect`` retries transient failures with exponential backoff —
      iOS 27+ devices can take a while to spin up mobilebackup2.
    """

    def __init__(self, lockdown, include_posterboard: bool = False, authentication_callback=None):
        pair_record = getattr(lockdown, "pair_record", None)
        if pair_record is not None and "EscrowBag" not in pair_record:
            LockdownService.__init__(self, lockdown, self.SERVICE_NAME,
                                     include_escrow_bag=False)
        else:
            super().__init__(lockdown)
        self.include_posterboard = include_posterboard
        self.authentication_callback = authentication_callback

    def _log_backup_notification(self, event):
        super()._log_backup_notification(event)
        name = event.get("Name")
        if self.authentication_callback is not None:
            if name == NP_LOCAL_AUTH_PRESENTED:
                self.authentication_callback(True)
            elif name == NP_LOCAL_AUTH_DISMISSED:
                self.authentication_callback(False)

    async def connect(self, max_retries: int = 5):
        from src.utils.async_retry import async_retry

        retryable = (_pm3_exc.ConnectionTerminatedError, ConnectionError,
                     OSError, asyncio.TimeoutError)
        base_connect = super().connect
        return await async_retry(
            base_connect,
            max_retries,
            retry_if=lambda e: isinstance(e, retryable),
            exp_cap=15,
            on_retry=lambda attempt, total, e, delay: print(
                f"[ProtectiveBackup] mobilebackup2 connect failed "
                f"(attempt {attempt}/{total}), retrying in {delay}s: {e}"
            ),
        )

    @asynccontextmanager
    async def device_link(self, backup_directory, filter_callback=None, password=""):
        retryable = (_pm3_exc.ConnectionTerminatedError, ConnectionError, asyncio.TimeoutError)
        stack = AsyncExitStack()
        try:
            for attempt in range(3):
                try:
                    link = await stack.enter_async_context(super().device_link(
                        backup_directory, filter_callback=filter_callback, password=password))
                    break
                except retryable as error:
                    log_warn(f"Backup service closed during DeviceLink handshake (attempt {attempt + 1}/3): {type(error).__name__}. This does not establish a USB disconnect.")
                    try:
                        await self.close()
                    except Exception:
                        pass
                    if attempt == 2:
                        raise
                    await asyncio.sleep(3 * (attempt + 1))
            yield link
        finally:
            await stack.aclose()

    async def init_mobile_backup_factory_info(self, afc):
        root_node = self.lockdown.all_values
        info = {
            "iTunes Version": "10.0.1",
            "iTunes Files": {},
            "Unique Identifier": self.lockdown.udid.upper(),
            "Target Type": "Device",
            "Target Identifier": root_node["UniqueDeviceID"],
            "Serial Number": root_node["SerialNumber"],
            "Product Version": root_node["ProductVersion"],
            "Product Type": root_node["ProductType"],
            "Installed Applications": [],
            "GUID": _uuid.uuid4().bytes,
            "Display Name": root_node.get("DeviceName", ""),
            "Device Name": root_node.get("DeviceName", ""),
            "Build Version": root_node["BuildVersion"],
            "Applications": {},  # skip all app containers — big speedup
        }
        if self.include_posterboard:
            await self._add_posterboard_container(info)
        return info

    async def _add_posterboard_container(self, info: dict):
        """List only the PosterBoard container so its sqlite DB rides this backup.

        The entry mirrors what the stock factory info carries for an app
        (ApplicationSINF / iTunesMetadata / PlaceholderIcon / Container) —
        that format provably yields the PosterBoard DB in full backups.
        """
        try:
            from pymobiledevice3.services.installation_proxy import InstallationProxyService
            from pymobiledevice3.services.springboard import SpringBoardServicesService
            bundle_id = POSTERBOARD_DB_DOMAIN.removeprefix("AppDomain-")
            async with InstallationProxyService(lockdown=self.lockdown) as ip:
                apps = await ip.get_apps(application_type="Any", calculate_sizes=False)
            app_info = apps.get(bundle_id)
            if app_info is None:
                log_warn("PosterBoard app not found via installation proxy; skipping container inclusion")
                return
            entry = {
                "Container": app_info["Container"],
                "CFBundleIdentifier": bundle_id,
                "CFBundleVersion": app_info.get("CFBundleVersion", "1.0"),
                "ApplicationSINF": app_info.get("ApplicationSINF", b""),
                "iTunesMetadata": app_info.get("iTunesMetadata", {}),
            }
            try:
                async with SpringBoardServicesService(self.lockdown) as sbs:
                    entry["PlaceholderIcon"] = await sbs.get_icon_pngdata(bundle_id)
            except Exception:
                entry["PlaceholderIcon"] = b""
            info["Installed Applications"] = [bundle_id]
            info["Applications"] = {bundle_id: entry}
            log_debug(f"PosterBoard container added to factory info: "
                      f"bundle={bundle_id} Container={app_info.get('Container')} "
                      f"keys={sorted(entry.keys())}")
        except Exception as e:
            log_warn(f"PosterBoard container inclusion failed: {e}")


async def perform_protective_backup(
    lockdown_client: LockdownClient,
    backup_root: str,
    progress_callback=None,
    include_photos: bool = True,
    include_posterboard: bool = False,
    include_keychain: Optional[bool] = None,
    incremental_ok: bool = False,
    include_afc_media: bool = False,
    media_root: str = None,
    afc_media_diff: bool = False,
) -> bool:
    report_progress = progress_callback
    authentication_presented = False

    def progress_callback(progress):
        if report_progress is not None and not authentication_presented:
            report_progress(progress)

    def authentication_changed(presented):
        nonlocal authentication_presented
        authentication_presented = presented
        if report_progress is not None:
            report_progress(BackupStatus(QCoreApplication.translate(
                "Nugget",
                "iOS authentication prompt detected. Check your iPhone and enter its passcode if requested to continue the protective backup."
                if presented else
                "iOS authentication prompt closed. Waiting for protective backup progress…"),
                "authentication" if presented else "backup"))

    await check_disk_space_for_backup(lockdown_client, path=backup_root)
    if not incremental_ok:
        Path(backup_root).mkdir(parents=True, exist_ok=True)

    # When the media channel is active, the bulk photo trees (DCIM,
    # PhotoStreamsData) go out over AFC in parallel with this mobilebackup2
    # backup. PhotoData — the photo library database plus its protected
    # metadata — is NOT listable over the media AFC service (PhotoData/UBF
    # returns AFC error 10 / PERM_DENIED), so it stays inside this backup:
    # ``include_photos`` keeps it, and the filter's ``exclude_afc_media_trees``
    # drops only the AFC-handled trees (whose payloads are not uploaded here).
    # The manifest prune applies the same exclusion, so no restore-time row
    # points at a payload that was never written.
    #
    # ``media_root`` overrides where the media tree is stored. The LIVE path
    # uses ``afc_media_dir_for(backup_root)`` (a sibling of the run's
    # device_backup); the CACHE path hands over its persistent per-device
    # media store, and with ``afc_media_diff=True`` the refresh only pulls
    # objects that are new/changed on the device (size and device modification
    # time compared against the previous verified pull).
    afc_media_task = None
    if include_afc_media:
        media_dir = media_root or afc_media_dir_for(backup_root)
        if media_root is None:
            # Keep channel metadata outside the payload tree so recovery still
            # knows the media was required if that tree is later lost.
            (Path(backup_root).parent / '.afc_media_required').touch()
        afc_media_task = asyncio.create_task(backup_media_via_afc(
            lockdown_client,
            media_dir,
            progress_callback=progress_callback,
            diff=afc_media_diff,
        ))
        log_info("Photos/videos over AFC in parallel: pulling "
                 f"{sorted(AFC_MEDIA_TREES)} via AFC; mobilebackup2 keeps "
                 "PhotoData and the rest of the protective scope")

    _pb_names_to_db: list = []
    _totals = {"seen": 0, "kept": 0, "containers": 0}
    _last_category = [None]
    _last_heartbeat = [time.monotonic()]

    def _filter_callback(backup_file):
        name = backup_file.device_name or ""
        category = backup_category_for(name)
        if category != _last_category[0]:
            _last_category[0] = category
            if progress_callback:
                progress_callback(BackupStatus(category + "…", category.category))
        keep = is_protective_device_file(
            name,
            include_photos=include_photos,
            include_posterboard=include_posterboard,
            include_keychain=include_keychain,
            exclude_afc_media_trees=include_afc_media)
        _totals["seen"] += 1
        _totals["kept"] += int(keep)
        low = name.lower()
        if "containers/" in low or "/.b/" in low:
            _totals["containers"] += 1
        if include_posterboard and ("poster" in low or POSTERBOARD_DB_NAME.lower() in low):
            _pb_names_to_db.append((name, keep))
            log_debug(f"PB filter {'KEEP' if keep else 'drop'}: {name}")
        # A heartbeat keeps the session log informative during a long silent
        # stretch: without it a wedged transfer and a slow one look identical
        # (the log stops either way until the DeviceLink read timeout fires).
        now = time.monotonic()
        if now - _last_heartbeat[0] >= 60:
            _last_heartbeat[0] = now
            log_info(f"Backup upload heartbeat: seen={_totals['seen']} "
                     f"kept={_totals['kept']} "
                     f"container_paths={_totals['containers']}")
        return keep

    is_encrypted = False
    try:
        async with ProtectiveBackupService(
                lockdown_client, include_posterboard=include_posterboard,
                authentication_callback=authentication_changed) as mb:
            try:
                is_encrypted = await mb.get_will_encrypt()
            except Exception:
                pass
            # Keychain inclusion follows the device's real encryption state unless
            # the caller pinned it explicitly — saves a redundant round-trip before
            # this call. The filter callback above reads ``include_keychain`` by
            # reference, so it picks up the resolved value.
            if include_keychain is None:
                include_keychain = is_encrypted
            if is_encrypted:
                log_info("Backup encryption already enabled on device.")
                progress_callback("Using existing backup encryption...")
            else:
                progress_callback("Creating protective backup (unencrypted)...")
            # Name the mode explicitly: "the cache did nothing" reports all
            # traced back to an encrypted master that was silently rejected by
            # locate(), so every apply ran a full backup instead of a diff.
            log_info(f"Protective backup mode: {'incremental' if incremental_ok else 'full'} "
                     f"| root={backup_root} | encrypted={is_encrypted} "
                     f"| silence budget={recv_timeout_secs():g}s")
            try:
                await mb.backup(full=not incremental_ok, backup_directory=backup_root,
                                progress_callback=progress_callback,
                                filter_callback=_filter_callback)
            except NotEnoughDiskSpaceError as e:
                message = str(e).strip() or backup_disk_space_message(backup_root)
                log_warn(message)
                if progress_callback:
                    progress_callback(message)
                raise BackupDiskSpaceError(message) from e
    except BaseException:
        if afc_media_task is not None:
            # The backup failed — the media pull (still uploading user data) is
            # pointless without a backup to restore it next to. Cancel it and
            # let its cancellation resolve here so it can't mask the real error.
            afc_media_task.cancel()
            try:
                await afc_media_task
            except (asyncio.CancelledError, Exception):
                pass
        raise
    else:
        if afc_media_task is not None:
            # The media pull either completed alongside the backup or raised on
            # a per-file/connection failure (photos are user data — fail loudly).
            try:
                await afc_media_task
            except NuggetException:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                raise NuggetException(
                    QCoreApplication.translate(
                        "Nugget",
                        "Could not back up photos/videos over AFC: {0}")
                    .format(e)) from e

    kept = sum(1 for _, keep in _pb_names_to_db if keep)
    log_info(f"Backup upload tally: seen={_totals['seen']} kept={_totals['kept']} "
             f"container_paths={_totals['containers']} | PosterBoard names seen="
             f"{len(_pb_names_to_db)} (kept {kept}, dropped {len(_pb_names_to_db) - kept})")

    return is_encrypted


async def is_backup_encrypted(lockdown_client: LockdownClient) -> bool:
    """Check whether the device currently encrypts its backups."""
    try:
        async with Mobilebackup2Service(lockdown_client) as mb:
            return await mb.get_will_encrypt()
    except Exception as e:
        log_warn(f"Could not read backup encryption state: {e}")
        return False


# --- Live protective backups (the only copy after Phase 2 wipes the device) --
#
# Between Phase 2 (sparse restore, which triggers the iOS 27 wipe) and Phase 3
# (protective restore) the backup directory on this computer is the SOLE copy
# of the user's photos, Apple ID and settings. It therefore must not live in
# the system temp directory — a reboot or an OS temp sweep destroys it — and
# it must never be caught by the routine that disposes of throwaway working
# copies. Both used to be true: every backup and working copy shared the
# ``nugget_protective_`` prefix under ``tempfile.gettempdir()``, so a failed
# apply had its only surviving copy deleted one hour later, with no prompt.
# The default live-backup location is ``protective_base()`` in
# ``src/restore/storage.py`` (Settings -> Backup -> "Backup/Cache Location"
# can move it off the system drive).

# Disposable working copies carry a prefix of their own so the periodic sweep
# in restore.py can never match a real backup.

# Retention for finished live backups: how many to keep per device. A new run
# replaces the previous one — old full copies just burn the very disk space an
# apply needs (the fresh run is what actually gets restored), and a retained
# run is pruned in place anyway once the restore consumes it.
PROTECTIVE_KEEP_RUNS = 1


def protective_persistent_base() -> Path:
    """Per-user folder holding live protective backups that survive reboots."""
    from src.restore.storage import protective_base
    return protective_base()


def new_protective_backup_dir(udid: str) -> str:
    """Create a fresh, persistent directory for one live protective backup.

    Layout: ``<persistent base>/<udid>/<timestamp>-<pid>/device_backup``.

    A new directory per run means a failed or interrupted backup can never
    damage the previous run's copy — the one thing standing between a wiped
    device and permanent data loss. The returned path is the directory that
    *contains* the device folder, matching what ``clean_backup_for_restore``
    and ``make_protective_working_copy`` expect.
    """
    safe_udid = udid or "unknown"
    # The random suffix keeps two runs in the same second apart: sharing a
    # directory would let a failing backup overwrite the previous run's copy.
    run_dir = (protective_persistent_base() / safe_udid
               / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{_uuid.uuid4().hex[:8]}")
    backup_root = run_dir / "device_backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    return str(backup_root)


def list_protective_backups(udid: str) -> list:
    """Completed, usable live backup run directories for ``udid``, newest first.

    A run qualifies only when its Manifest.db landed AND reads as a backup
    that can actually be restored:

    - a run still being taken has no Manifest.db yet — excluded (and thus
      never a prune candidate);
    - a run interrupted mid-upload can leave a truncated/corrupt Manifest.db
      behind. Restoring from it silently skips pruning
      (``clean_backup_for_restore`` returns (0, 0) on an unreadable manifest)
      and ``verify_backup_payloads`` then returns no findings for a
      non-sqlite file, so Phase 3 would ship a backup full of payload-less
      rows and fail with MBErrorDomain/205. Such runs are excluded here, so
      the recovery path falls through to the next newest intact run instead.
    - encrypted manifests are not sqlite and cannot be validated as such;
      they are recognised via ``_is_encrypted_backup`` and kept (the prune
      and verify paths handle decryption downstream).
    """
    safe_udid = udid or "unknown"
    root = protective_persistent_base() / safe_udid
    if not root.is_dir():
        return []
    runs = []
    for entry in root.iterdir():
        device_dir = entry / "device_backup" / safe_udid
        manifest_db = device_dir / "Manifest.db"
        if not entry.is_dir() or not manifest_db.is_file():
            continue
        if (not _validate_sqlite_db(manifest_db)
                and not _is_encrypted_backup(device_dir)):
            log_warn(f"Skipping protective backup {entry.name}: Manifest.db is "
                     f"corrupt or incomplete (interrupted upload?)")
            continue
        runs.append(entry)
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs


def find_latest_protective_backup(udid: str) -> Optional[str]:
    """``backup_root`` of the newest live protective backup for ``udid``.

    Used by the post-failure "Restore data" recovery path. Returns None when
    the device has no stored backup.
    """
    runs = list_protective_backups(udid)
    return str(runs[0] / "device_backup") if runs else None


def prune_protective_backups(udid: str, keep: int = PROTECTIVE_KEEP_RUNS) -> int:
    """Drop older live backups for ``udid``, keeping the newest ``keep``.

    Deletes every older run outright; the newest ``keep`` runs are left
    untouched. Returns the number of run directories removed.
    """
    runs = list_protective_backups(udid)
    removed = 0
    for old in runs[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        if not old.exists():
            removed += 1
            log_info(f"Pruned old protective backup: {old}")
    return removed


def _copy_backup_tree(src_root: Path, dst_root: Path) -> None:
    """Faithfully copy one backup device dir into ``dst_root``.

    Metadata (incl. sqlite sidecars) is real-copied — pruning rewrites
    Manifest.db, and a hardlink would corrupt the cache master through the
    shared inode/-wal. Everything else is hardlinked (near-instant, size-free),
    with a copy fallback for cross-device destinations.
    """
    dst_root.mkdir(parents=True, exist_ok=True)
    always_copy = set(_BACKUP_METADATA_FILES) | {"Manifest.db-wal", "Manifest.db-shm"}
    for dirpath, _dirnames, filenames in os.walk(src_root):
        rel = Path(dirpath).relative_to(src_root)
        (dst_root / rel).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            src_file = Path(dirpath) / name
            dst_file = dst_root / rel / name
            if name in always_copy:
                shutil.copy2(src_file, dst_file)
            else:
                try:
                    os.link(src_file, dst_file)
                except OSError:
                    shutil.copy2(src_file, dst_file)


def make_restore_view(master_root: str, udid: str, view_root: str) -> str:
    """Build a disposable restore *view* of the cache master.

    The master is the pristine copy the incremental refresh diffs against, so
    it must never be modified by an apply. The prune and the tweak injection
    therefore run against a view: a hardlink copy of the master's payloads
    plus real copies of its metadata files.

    The metadata is copied for real because the prune rewrites Manifest.db in
    place — a hardlinked manifest would corrupt the master. The payloads are
    hardlinked, which costs no disk space and no data copy; unlinking one in
    the view leaves the master's file untouched.

    ``view_root`` must live on the same filesystem as ``master_root`` so the
    hardlinks stay links instead of degrading into full copies.

    Returns the view's parent directory — the layout the restore code expects
    (``<parent>/<udid>/Manifest.db``).
    """
    src_root = Path(master_root) / udid
    if not src_root.is_dir():
        # Tolerate a root pointing directly at the device directory.
        if (Path(master_root) / "Manifest.db").is_file():
            src_root = Path(master_root)
        else:
            raise NuggetException("Cache master is missing its payload.")

    view_parent = Path(view_root)
    view_device = view_parent / udid
    shutil.rmtree(view_device, ignore_errors=True)
    view_device.mkdir(parents=True, exist_ok=True)
    _copy_backup_tree(src_root, view_device)
    return str(view_parent)


def discard_restore_view(view_root: str, udid: str) -> None:
    """Remove a per-apply restore view.

    The view is a disposable hardlink farm over the master, so deleting it
    frees the directory entries without touching a single byte of payload
    data (the master's own files stay exactly where they are).
    """
    if not view_root:
        return
    shutil.rmtree(Path(view_root) / udid, ignore_errors=True)


def make_protective_working_copy(backup_root: str, udid: str) -> str:
    """Build a throwaway hardlink copy of a protective backup for prune + injection.

    Hardlinks keep it near-instant and size-free; pruning unlinks orphans
    without touching the source's own files (the cache master stays intact).

    The copy is disposable, so it uses ``WORKING_COPY_PREFIX`` — the periodic
    sweep in restore.py cleans up leftovers from crashed runs under that
    prefix only.
    """
    working_root = Path(tempfile.mkdtemp(prefix=WORKING_COPY_PREFIX)) / "device_backup"
    src_root = Path(backup_root) / udid
    if not src_root.is_dir():
        # Tolerate a root pointing directly at the device directory.
        if (Path(backup_root) / "Manifest.db").is_file():
            src_root = Path(backup_root)
        else:
            raise NuggetException("Protective backup is missing its payload.")

    _copy_backup_tree(src_root, working_root / udid)
    return str(working_root)


def make_cache_snapshot(backup_root: str, udid: str, inject_files: list = None) -> str:
    """Deprecated: the cache master is no longer modified in place.

    Applies now build a disposable restore *view* of the master
    (``make_restore_view``) instead of pruning and injecting the master
    itself and then rebuilding it from a snapshot. The master therefore
    stays pristine and there is nothing to snapshot or regenerate.
    """
    raise NotImplementedError(
        "the cache master is immutable — use make_restore_view() instead")


def regenerate_cache_from_snapshot(snapshot_dir: str, backup_root: str, udid: str) -> str:
    """Deprecated: the cache master is never modified, so nothing regenerates it."""
    raise NotImplementedError(
        "the cache master is immutable — it needs no regeneration")


def verify_backup_payloads(backup_dir: "str | Path", udid: str,
                           manifest_password: str = "") -> list[str]:
    """Return missing paths, raising when verification could not be performed."""
    from src.restore.verification import inspect_backup_payloads
    return inspect_backup_payloads(
        backup_dir, udid, manifest_password, inventory=_payload_inventory,
        is_sqlite=_validate_sqlite_db, is_encrypted=_is_encrypted_backup,
        decrypt=Mobilebackup2Service._decrypt_backup_manifest_db,
    ).require_verified()


def posterboard_structure_version(rel_path: str) -> int:
    """Derive the PosterBoard store structure version from a manifest path.

    The store directory carries a structure version (61, 62, ...) that varies
    between iOS releases (the codebase historically hardcoded 61, which is
    wrong on newer 26.x builds where Apple bumped the store layout — a
    mismatch makes the injected database land in a dead directory the device
    never reads). The version is the numeric chunk right after the store-dir
    name; when the tree name is absent (some iOS 27 upload paths) it falls
    back to 61, the oldest supported layout.
    """
    marker = f"{POSTERBOARD_DB_STORE_DIR}/"
    idx = rel_path.find(marker)
    if idx >= 0:
        num = ""
        for ch in rel_path[idx + len(marker):]:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            return int(num)
    return 61


def _require_usable_pb_snapshot(db_path) -> None:
    """Gate a pulled PosterBoard database on the strong snapshot check.

    ``mobilebackup2`` streams the database while PosterBoard keeps writing and
    iOS 26 leaves the ``-wal`` sibling out of the backup, so the payload is a
    plain copy of a live file. When that copy races a checkpoint it is torn and
    every later step (inject, rewrite, restore) would operate on a corrupt
    database — or lose the user's wallpapers to it. Raise instead, so the
    caller can pull the file again.
    """
    from src.tweaks.posterboard.db_validate import require_usable_snapshot
    require_usable_snapshot(str(db_path))


def extract_posterboard_db(backup_root: str, udid: str, dest_path: str) -> Optional[tuple[str, int]]:
    """Pull the PosterBoard sqlite database out of a (refreshed) protective backup.

    Call this AFTER ``ProtectiveBackupCache.refresh(include_posterboard=True)``
    so the extracted database mirrors the live on-device state. Returns
    ``(destination_path, structure_version)`` — the structure version as parsed
    from the database's manifest path, so the restore can write it back to the
    same store directory it came from — or None when the backup does not carry
    the database (e.g. container inclusion was rejected by the device).

    Raises ``IncompletePosterBoardSnapshot`` when the backup *does* carry the
    file but the copy is torn (see ``_require_usable_pb_snapshot``); that one is
    worth retrying, unlike a container that is simply absent.
    """
    device_dir = Path(backup_root) / udid
    if not device_dir.is_dir():
        if (Path(backup_root) / "Manifest.db").is_file():
            device_dir = Path(backup_root)
        else:
            log_debug(f"extract_posterboard_db: no device dir and no Manifest.db under {backup_root}")
            return None
    manifest_db = device_dir / "Manifest.db"
    if _is_encrypted_backup(device_dir):
        from src.exceptions.nugget_exception import PosterBoardBackupEncryptionError
        raise PosterBoardBackupEncryptionError(
            'PosterBoard extraction requires a readable manifest and decrypted payloads. '
            'This backup is encrypted, not proven corrupted. Automatic re-backup will not fix it.')
    if not _validate_sqlite_db(manifest_db):
        log_warn(f"extract_posterboard_db: Manifest.db at {manifest_db} is missing/encrypted/"
                 f"not a valid SQLite db (backup may be incomplete)")
        return None
    log_debug(f"extract_posterboard_db: scanning {manifest_db}")
    conn = sqlite3.connect(str(manifest_db))
    try:
        pb_rows = conn.execute(
            "SELECT fileID, relativePath FROM Files "
            "WHERE relativePath LIKE ? OR relativePath LIKE ? "
            "ORDER BY relativePath",
            (f"%{POSTERBOARD_DB_NAME}%", f"%{POSTERBOARD_DB_STORE_DIR}%"),
        ).fetchall()
        if not pb_rows:
            # Diagnostics: was the container just not uploaded (no Containers/
            # rows and no Poster-ish rows) or uploaded under an unexpected name
            # (Containers exist, but no row matches the DB name)?
            total_rows = conn.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
            container_count = conn.execute(
                "SELECT COUNT(*) FROM Files WHERE relativePath LIKE '%Containers/%'").fetchone()[0]
            poster_rows = conn.execute(
                "SELECT relativePath FROM Files WHERE relativePath LIKE '%Poster%' "
                "ORDER BY relativePath LIMIT 20").fetchall()
            log_warn(
                f"Master manifest has NO PosterBoard rows ({total_rows} rows total, "
                f"{container_count} under Containers/; Poster-ish sample: "
                f"{[r[0] for r in poster_rows]})")
            return None
    finally:
        conn.close()

    # resolve by FILE NAME: the store dir carries a structure version that
    # varies between iOS releases; prefer the highest-versioned match
    candidates = sorted((r for r in pb_rows if r[1].endswith(POSTERBOARD_DB_NAME)),
                        key=lambda r: r[1], reverse=True)
    if not candidates:
        log_warn(f"No {POSTERBOARD_DB_NAME} among the PosterBoard rows; "
                 f"sample rows: {[r[1] for r in pb_rows[:5]]}")
        return None
    file_id, rel_path = candidates[0]
    structure_version = posterboard_structure_version(rel_path)

    def _payload_for(suffix: str) -> Optional[Path]:
        target = rel_path + suffix
        for fid, rp in pb_rows:
            if rp == target:
                p = device_dir / fid[:2] / fid
                return p if p.is_file() else None
        return None

    main_payload = _payload_for("")
    if main_payload is None:
        log_warn(f"extract_posterboard_db: manifest row for {rel_path} exists but its "
                 f"payload file {device_dir / file_id[:2] / file_id} is missing "
                 f"(mid-stream filter dropped it?)")
        return None

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    log_debug(f"extract_posterboard_db: using {rel_path} (fileID={file_id}) -> {dest}")

    wal_payload = _payload_for("-wal")
    if wal_payload is None:
        # No WAL sibling — which is what iOS 26 actually uploads, so this is the
        # normal path there: a plain copy of a database the device is still
        # writing. A copy that races a checkpoint is torn, so validate before
        # handing it out (see db_validate) and let the caller re-pull.
        shutil.copyfile(main_payload, dest)
        _require_usable_pb_snapshot(dest)
        return str(dest), structure_version

    # The on-device database runs in WAL mode: recent wallpaper data may live
    # in the -wal sibling rather than the main file. Copy main + wal into a
    # scratch directory (NEVER the -shm: a stale shm desyncs against the wal
    # and is a classic source of "database disk image is malformed"), then
    # use SQLite's online-backup API to fold the wal frames into one clean
    # database file. Plain-copying the bare main file would lose that data.
    work_dir = Path(tempfile.mkdtemp(prefix="nugget_pbwal_"))
    try:
        work_main = work_dir / "posterboard.sqlite3"
        shutil.copyfile(main_payload, work_main)
        shutil.copyfile(wal_payload, str(work_main) + "-wal")
        dest.unlink(missing_ok=True)
        try:
            src = sqlite3.connect(str(work_main))
            merged = sqlite3.connect(str(dest))
            try:
                src.backup(merged)  # snapshot of main + wal in one atomic file
                merged.execute("PRAGMA journal_mode=DELETE")
                merged.commit()
            finally:
                src.close()
                merged.close()
        except Exception:
            log_warn("WAL consolidation failed — falling back to the plain database file")
        if not _validate_sqlite_db(dest):
            log_warn("Consolidated PosterBoard DB failed validation — "
                     "falling back to the plain database file")
            dest.unlink(missing_ok=True)
            shutil.copyfile(main_payload, dest)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    _require_usable_pb_snapshot(dest)

    return str(dest), structure_version


from src.restore.verification import PruneResult


def _keep_protective_entry(domain: str, relative_path: str, include_photos: bool = True,
                           include_keychain: bool = False,
                           exclude_afc_media_trees: bool = False) -> bool:
    """Keep-set predicate shared by the plain and encrypted prune paths."""
    if is_preference_parent(domain, relative_path):
        return True
    if domain and relative_path and (_is_protective_file(domain, relative_path, include_photos, include_keychain,
                                                         exclude_afc_media_trees)
                                     or domain == "SystemPreferencesDomain"):
        return True
    # the domain root directory row — without it the restore agent may skip
    # the whole domain
    if relative_path == "" and domain in ("SystemPreferencesDomain", "MessagesDomain", "KeyboardDomain"):
        return True
    if include_keychain and relative_path == "" and domain == KEYCHAIN_DOMAIN:
        return True
    return False


def clean_backup_for_restore(backup_dir: "str | Path", udid: str,
                             include_photos: bool = True,
                             include_keychain: bool = False,
                             manifest_password: str = "",
                             exclude_afc_media_trees: bool = False,
                             collect_inode: bool = False) -> PruneResult:
    """Prune a backup directory down to its protective payload.

    1. Deletes every non-protective row from Manifest.db in a single DELETE
       (keep-set staged in a temp table instead of per-row DELETEs).
    2. Deletes payload files not referenced by the keep-set, scanning hash
       subdirectories too (iOS may store payloads as "<aa>/<fileID>").
    3. Removes directories left empty by the pruning.

    Encrypted backups are supported when ``manifest_password`` is given:
    pymobiledevice3 decrypts the manifest, prunes it and re-encrypts it in
    place. A cache master is never passed here directly — the caller prunes a
    disposable restore *view* of it (``make_restore_view``), whose metadata is
    real-copied, so the master keeps its own full-manifest encrypted state. A
    fresh live backup is pruned in place: the pruned directory IS the restore
    source.

    Returns (removed_manifest_rows, removed_payload_files).
    """
    device_dir = Path(backup_dir) / udid
    if not device_dir.is_dir():
        # Tolerate backup_dir already pointing at the device directory.
        if (Path(backup_dir) / "Manifest.db").exists():
            device_dir = Path(backup_dir)
        else:
            return PruneResult()

    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.exists():
        return PruneResult()

    include_keychain = include_keychain or _is_encrypted_backup(device_dir)
    if _is_encrypted_backup(device_dir):
        if not manifest_password:
            log_info("Backup is encrypted and no password was given — skipping local manifest pruning")
            return PruneResult()
        def _keep(bf) -> bool:
            if bf.domain is None or bf.relative_path is None:
                return False
            return _keep_protective_entry(bf.domain, bf.relative_path, include_photos, include_keychain,
                                          exclude_afc_media_trees)
        allowed_ids = Mobilebackup2Service.prune_backup_manifest(
            device_dir, _keep, password=manifest_password)
        removed_files = _remove_orphan_payloads(_payload_inventory(device_dir), allowed_ids)
        log_info(f"Encrypted manifest pruned with password (-{removed_files} orphan payloads)")
        return PruneResult(removed_files=removed_files)

    if not _validate_sqlite_db(manifest_db):
        log_error(f"Manifest.db at {manifest_db} is not a valid SQLite database. Skipping cleanup.")
        return PruneResult()

    keep_ids = set()
    removed_rows = 0
    missing_payloads = []
    inventory = _payload_inventory(device_dir)
    present = inventory[3]
    max_inode = None
    conn = sqlite3.connect(str(manifest_db))
    try:
        cur = conn.cursor()
        cur.execute("SELECT fileID, domain, relativePath, flags FROM Files")
        for file_id, domain, rel_path, flags in cur:
            if _keep_protective_entry(domain, rel_path, include_photos, include_keychain,
                                      exclude_afc_media_trees):
                # only regular files carry a <aa>/<fileID> payload; directory
                # rows (flags=2) MUST survive without one — dropping them
                # makes the restore agent fail with renameatx ENOENT
                if flags == 1 and file_id not in present:
                    # a file row without a payload makes the restore fail with
                    # MBErrorDomain/205 — drop it and let the device's own
                    # data stand
                    missing_payloads.append(rel_path)
                else:
                    keep_ids.add(file_id)

        if missing_payloads:
            raise NuggetException(
                f'The backup is missing {len(missing_payloads)} protected file payload(s). '
                'No manifest rows were pruned. Do not restore this incomplete backup.')

        cur.execute("CREATE TEMP TABLE nugget_keep (fileID TEXT PRIMARY KEY)")
        cur.executemany("INSERT INTO nugget_keep (fileID) VALUES (?)",
                        ((fid,) for fid in keep_ids))
        cur.execute("DELETE FROM Files WHERE fileID NOT IN (SELECT fileID FROM nugget_keep)")
        removed_rows = max(cur.rowcount, 0)
        if collect_inode:
            # Only read blobs surviving the prune. Reading all original blobs
            # would make a mostly-drained master needlessly expensive to scan.
            from src.restore.inject import _max_inode_in_manifest
            max_inode = _max_inode_in_manifest(conn)
        conn.commit()
    finally:
        conn.close()

    removed_files = _remove_orphan_payloads(inventory, keep_ids)
    return PruneResult(removed_rows, removed_files, max_inode)
