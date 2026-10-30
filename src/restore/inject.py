"""Manifest.db tweak injection for the iOS 27 protective restore.

The iOS 27 "safe state recovery" wipe clears HomeDomain files that were
staged by the sparse restore but are absent from the protective backup.
Files the tweak writes can be re-added here with their *new* content so
Phase 3's mobilebackup2 restore lays them down natively (AFC cannot reach
HomeDomain, so that is the only reliable path on iOS 27).

This module is a leaf: it depends only on stdlib + pymobiledevice3 and knows
nothing about the backup/restore flow in ``protective.py``.
"""

# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "pymobiledevice3.services.mobilebackup2",
    "sqlite3",
)

from contextlib import closing
import hashlib
import logging
import os
import plistlib
import sqlite3
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from src.utils.payload import install_payload
from .mbfile import MBFileArchive, InvalidMBFile
from src.exceptions.nugget_exception import NuggetException

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
from .preference_scope import is_preference_file as _is_preference_target
from src.utils.preference_reset import PreferenceKeyReset

_logger = logging.getLogger("GoldenNugget.inject")
preference_delivery_warnings = ContextVar('preference_delivery_warnings', default=None)
preference_baseline_skips = ContextVar('preference_baseline_skips', default=None)
# Baselines whose manifest row is absent AND that were delivered anyway as a
# new file (see _prepare_preference_merges). Recorded so the apply summary can
# say the file was created from the tweak's keys only.
preference_baseline_creates = ContextVar('preference_baseline_creates', default=None)
_OPTIONAL_MISSING_BASELINE_PATHS = frozenset({
    ('HomeDomain', 'Library/Preferences/com.apple.SwiftUI.plist'),
    ('HomeDomain', 'Library/Preferences/com.apple.AvatarUI.Staryu.plist'),
    ('HomeDomain', 'Library/Preferences/com.apple.bg.system.task.plist'),
    ('SystemPreferencesDomain', 'FeatureFlags/Global.plist'),
})


def _can_skip_missing_preference_baseline(domain, path):
    return (domain, path) in _OPTIONAL_MISSING_BASELINE_PATHS


class FeatureFlagBaselineUnavailable(ValueError):
    pass


def _merge_preference_payload(original, patch, *, feature_flags=False):
    if isinstance(patch,Path):
        patch=patch.read_bytes()
    existing = plistlib.loads(original)
    if isinstance(patch, PreferenceKeyReset):
        if not isinstance(existing, dict) or '$archiver' in existing:
            raise ValueError('Preference reset requires an ordinary dictionary plist.')
        for path in patch.paths:
            target = existing
            for key in path[:-1]:
                if key not in target:
                    break
                target = target[key]
                if not isinstance(target, dict):
                    raise ValueError('Preference reset encountered a non-dictionary parent.')
            else:
                target.pop(path[-1], None)
        return plistlib.dumps(existing, fmt=plistlib.FMT_BINARY, sort_keys=False)
    changes = plistlib.loads(patch)
    if (not isinstance(existing, dict) or not isinstance(changes, dict)
            or '$archiver' in existing or '$archiver' in changes):
        raise ValueError('Preference edits require ordinary dictionary plists, not keyed archives.')
    if not changes:
        raise ValueError('An empty preference dictionary is not a verified reset.')
    if feature_flags:
        for domain, flags in changes.items():
            if not isinstance(flags, dict) or not isinstance(existing.get(domain, {}), dict):
                raise ValueError('Feature flag domains must be dictionaries.')
            target = existing.setdefault(domain, {})
            for key, values in flags.items():
                if not isinstance(values, dict) or not isinstance(target.get(key, {}), dict):
                    raise ValueError('Feature flag entries must be dictionaries.')
                target.setdefault(key, {}).update(values)
    else:
        _merge_preference_dictionary(existing, changes)
    return plistlib.dumps(existing, fmt=plistlib.FMT_BINARY, sort_keys=False)


def _merge_preference_dictionary(existing, changes):
    for key, value in changes.items():
        if isinstance(value, dict) and value and '$archiver' not in value:
            current = existing.get(key)
            if current is None and key not in existing:
                existing[key] = value
            elif not isinstance(current, dict) or '$archiver' in current:
                raise ValueError('Nested preference edits require a dictionary baseline.')
            else:
                _merge_preference_dictionary(current, value)
        else:
            existing[key] = value


def _same_plist_value(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_plist_value(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_plist_value(a, b) for a, b in zip(left, right))
    return left == right


def _native_patch_covers(managed, native):
    if isinstance(managed, PreferenceKeyReset) or isinstance(native, PreferenceKeyReset):
        return (isinstance(managed, PreferenceKeyReset)
                and isinstance(native, PreferenceKeyReset)
                and set(managed.paths) <= set(native.paths))
    if native is None:
        return False
    try:
        managed_values = plistlib.loads(managed)
        native_values = plistlib.loads(native)
    except (ValueError, TypeError, plistlib.InvalidFileException):
        return False
    if (not isinstance(managed_values, dict) or not managed_values
            or not isinstance(native_values, dict)
            or '$archiver' in managed_values or '$archiver' in native_values):
        return False
    return all(key in native_values and _same_plist_value(value, native_values[key])
               for key, value in managed_values.items())


def _prepare_preference_merges(conn, device_dir, files):
    prepared = []
    missing = []
    native_mirrors = {path: contents for domain, path, contents, *_ in files
                      if domain == 'HomeDomain'}
    omitted_managed = []
    for domain, path, contents, mode, owner, group in files:
        if _is_preference_target(domain, path) or isinstance(contents, PreferenceKeyReset):
            row = conn.execute('SELECT fileID FROM Files WHERE domain=? AND relativePath=? AND flags=1',
                               (domain, path)).fetchone()
            if row is None:
                if (_can_skip_missing_preference_baseline(domain, path)
                        and not isinstance(contents, PreferenceKeyReset)):
                    skipped = preference_baseline_skips.get()
                    if skipped is not None:
                        skipped.append(f'{domain}/{path}')
                    _logger.warning(
                        'Skipping preference edits for %s because its current baseline '
                        'is absent from the backup', f'{domain}/{path}')
                    continue
                if (domain == 'SystemPreferencesDomain'
                        and path == 'FeatureFlags/Global.plist'):
                    # A feature-flag RESET was requested and no Global.plist
                    # exists to take the negative keys out of. Refuse with the
                    # explicit instruction instead of guessing at a baseline.
                    raise FeatureFlagBaselineUnavailable(
                        'Feature flag overrides cannot be safely prepared from this backup: '
                        f'{domain}/{path} has no file row in the backup. No injection started. '
                        'Set feature-flag controls to Not Used to leave them out of this apply. '
                        'This includes controls outside Internal Options '
                        'that also use FeatureFlags/Global.plist. Another full backup is not guaranteed '
                        'to expose this file. No empty baseline was substituted; this does not prove '
                        'the file is absent from the phone or that iOS accepts these overrides.')
                if isinstance(contents, PreferenceKeyReset):
                    # A reset removes keys the tweaks previously set. A file
                    # the backup has no row for does not exist on the device,
                    # so there is nothing to remove — the reset is vacuous.
                    skipped = preference_baseline_skips.get()
                    if skipped is not None:
                        skipped.append(f'{domain}/{path}')
                    _logger.warning(
                        'Preference reset for %s skipped because no baseline file '
                        'exists in the backup (nothing to reset)', f'{domain}/{path}')
                    continue
                if (domain == 'ManagedPreferencesDomain'
                        and path in ('mobile/com.apple.UIKit.plist',
                                     'mobile/com.apple.springboard.plist')):
                    mirror_path = 'Library/Preferences/' + path[len('mobile/'):]
                    mirror = native_mirrors.get(mirror_path)
                    if _native_patch_covers(contents, mirror):
                        omitted_managed.append(path)
                        continue
                # The protective capture keeps EVERY preference file in these
                # domains (mid-stream filter and prune keep-set), so a missing
                # manifest row means the device does not have this file.
                # Delivering the tweak payload as the whole file is then the
                # same thing the sparse restore used to lay down for a new
                # file before delivery moved into Phase 1's injection — not a
                # clobbering of unseen content. (A row that exists with a
                # unreadable/missing payload IS still an error below.)
                created = preference_baseline_creates.get()
                if created is not None:
                    created.append(f'{domain}/{path}')
                _logger.warning(
                    'No baseline row for %s in the backup; the file does not exist '
                    'on the device, so the tweak payload is delivered as a new file',
                    f'{domain}/{path}')
                prepared.append((domain, path, contents, mode, owner, group))
                continue
            file_id = row[0]
            payload = device_dir / file_id[:2] / file_id
            if not payload.is_file():
                payload = device_dir / file_id
            if not payload.is_file():
                missing.append((domain, path, 'missing payload'))
                continue
            try:
                contents = _merge_preference_payload(
                    payload.read_bytes(), contents,
                    feature_flags=domain == 'SystemPreferencesDomain' and path == 'FeatureFlags/Global.plist')
            except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as error:
                missing.append((domain, path, f'invalid or unreadable preference data ({type(error).__name__})'))
                continue
        prepared.append((domain, path, contents, mode, owner, group))
    if missing:
        details = '; '.join(f'{domain}/{path}: {reason}' for domain, path, reason in missing[:12])
        if len(missing) > 12:
            details += f'; and {len(missing) - 12} more'
        if all(domain == 'SystemPreferencesDomain' and path == 'FeatureFlags/Global.plist'
               for domain, path, _ in missing):
            raise FeatureFlagBaselineUnavailable(
                'Feature flag overrides cannot be safely prepared from this backup: '
                f'{details}. No injection started. Set feature-flag controls to Not Used '
                'to leave them out of this apply. This includes controls outside Internal Options '
                'that also use FeatureFlags/Global.plist. Another full backup is not guaranteed '
                'to expose this file. No empty baseline was substituted; this does not prove '
                'the file is absent from the phone or that iOS accepts these overrides.')
        raise ValueError(
            f'{len(missing)} current preference baseline(s) could not be merged: {details}. '
            'No injection started. Retry the apply so the backup is captured again; '
            'missing backup entries are not proof that the files do not exist on the phone.')
    for path in omitted_managed:
        warnings = preference_delivery_warnings.get()
        if warnings is not None:
            warnings.append(path)
        _logger.warning(
            'No managed baseline for %s; leaving that managed file untouched. '
            'Only the identical, explicitly staged HomeDomain edit will be delivered. '
            'Native preferences are not equivalent to managed policy; the tweak effect is unverified.', path)
    return prepared


def _is_encrypted_backup(device_dir: Path) -> bool:
    """Check if a backup directory has an encrypted Manifest.db."""
    try:
        return Mobilebackup2Service._is_encrypted_backup(device_dir)
    except Exception as exc:
        raise NuggetException(
            f"Could not determine backup encryption at {device_dir}. "
            "The backup was not modified.", detailed_text=str(exc)) from exc


def _validate_sqlite_db(db_path) -> bool:
    """Check if a file is a valid SQLite database (accepts str or Path)."""
    if isinstance(db_path, str):
        db_path = Path(db_path)
    if not db_path.exists() or db_path.stat().st_size < 100:
        return False
    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return True
    except sqlite3.DatabaseError:
        return False


def _build_mbfile_blob(relative_path: str, contents: bytes, mode: int = 33188,
                       owner: int = 501, group: int = 501, *,
                       size=None, digest=None, inode=None, protection_class=None) -> bytes:
    """Build a ``MBFile`` archive blob for an injected backup file.

    Matches the NSKeyedArchiver structure BackupAgent2 writes to the
    ``file`` column of Manifest.db: an ``MBFile`` object carrying the file's
    metadata plus a ``Digest`` (SHA1 of the payload) and the data-protection
    extended attribute. Mode/ownership mirror a regular mobile-owned
    HomeDomain file; the extended attribute marks the file as exempt from
    data protection by SpringBoard (same as IconState.plist and friends).
    """
    now = int(time.time())
    extended_attributes = plistlib.dumps(
        {"com.apple.dataprotection.policy.exception-applied-by": b"com.apple.springboard"},
        fmt=plistlib.FMT_BINARY,
    )
    objects = [
        "$null",
        {
            "Birth": now,
            "LastModified": now,
            "LastStatusChange": now,
            "Flags": 0,
            "GroupID": group,
            "UserID": owner,
            "Mode": mode,
            "ProtectionClass": 4,
            "Size": len(contents) if size is None else size,
            "RelativePath": plistlib.UID(2),
            "Digest": plistlib.UID(3),
            "ExtendedAttributes": plistlib.UID(4),
            "$class": plistlib.UID(5),
        },
        relative_path,
        hashlib.sha1(contents).digest() if digest is None else digest,
        extended_attributes,
        {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
    ]
    if inode is not None:
        objects[1]["InodeNumber"] = inode
    if protection_class is not None:
        objects[1]["ProtectionClass"] = protection_class
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def _patch_donor_blob(donor_blob: bytes, relative_path: str, contents: bytes,
                      mode: Optional[int] = None, owner: Optional[int] = None,
                      group: Optional[int] = None, *, size=None, digest=None, inode=None, protection_class=None) -> bytes:
    """Re-target a real MBFile blob from the same backup for a new payload.

    Cloning a row the device itself produced guarantees byte-exact metadata
    (extended attributes, protection class) instead of risking a hand-built
    archive the restore agent might reject. Only the path, digest, size and
    (optionally) mode/ownership change.
    """
    template = donor_blob if isinstance(donor_blob, MBFileArchive) else MBFileArchive.decode(donor_blob)
    blob = template.clone()
    info = blob.fields
    blob.set_reference("RelativePath", relative_path)
    blob.set_reference("Digest", hashlib.sha1(contents).digest() if digest is None else digest)
    info["Size"] = len(contents) if size is None else size
    for key, value in (("Mode", mode), ("UserID", owner), ("GroupID", group),
                       ("InodeNumber", inode), ("ProtectionClass", protection_class)):
        if value is not None:
            info[key] = value
    return blob.encode()


def _pick_donor_blob(conn, domain: str, relative_path: str) -> "Optional[bytes]":
    """Pick a donor MBFile blob the restore agent will accept.

    The iOS 27 restore agent silently skips rows whose blob it considers
    invalid, and it deduplicates by inode. A safe donor is a regular (0644)
    file with a SpringBoard data-protection exception and a real inode:
    ``IconState.plist`` is the canonical such file in the protective scope.
    Falls back to any regular row carrying a digest, then to the old
    arbitrary-row behavior.
    """
    preferred = ("Library/SpringBoard/IconState.plist",)
    for candidate in preferred:
        row = conn.execute(
            "SELECT file FROM Files WHERE domain = ? AND relativePath = ? "
            "AND flags = 1 AND file IS NOT NULL",
            (domain, candidate),
        ).fetchone()
        if row is not None:
            return row[0]

    for _candidate_flags, candidate_blob in conn.execute(
        "SELECT flags, file FROM Files WHERE domain = ? AND file IS NOT NULL "
        "AND relativePath != ? AND flags = 1",
        (domain, relative_path),
    ):
        try:
            info = MBFileArchive.decode(candidate_blob).fields
            if (info.get("Mode", 0) & 0o777) == 0o644 and isinstance(
                info.get("InodeNumber"), int
            ):
                return candidate_blob
        except Exception:
            continue

    for _candidate_flags, candidate_blob in conn.execute(
        "SELECT flags, file FROM Files WHERE domain = ? AND file IS NOT NULL "
        "AND relativePath != ? AND flags = 1",
        (domain, relative_path),
    ):
        try:
            info = MBFileArchive.decode(candidate_blob).fields
            if "Digest" in info and "ExtendedAttributes" in info:
                return candidate_blob
        except Exception:
            continue
    return None


def _owned(value, default: int = 501) -> int:
    """Resolve a uid/gid for a manifest blob — ``None`` means "unspecified".

    ``owner or 501`` (the original form) silently re-owned every injected file
    whose owner was 0. That is *not* an unspecified value, it is root: the
    daemons plist (``/var/db/com.apple.xpc.launchd/disabled.plist``) and the
    rest of ``DatabaseDomain`` are root-owned in a real backup, and the device
    ignores a root path restored as mobile-owned (silently — the launchd
    disabled list simply does not take). Only a genuinely missing value may
    fall back to the mobile default.
    """
    return default if value is None else value


def _build_mbdir_blob(relative_path: str, mode: int = 16877) -> bytes:
    """Build an ``MBFile``-style archive blob for a directory row.

    Mirrors what BackupAgent2 writes for flag=2 rows (dump of the device's
    own SystemPreferencesDomain dir rows): no digest, size 0, S_IFDIR mode,
    root-owned. The device's real rows carry a real inode, so a unique one
    must be stamped by the caller.
    """
    now = int(time.time())
    objects = [
        "$null",
        {
            "Birth": now,
            "LastModified": now,
            "LastStatusChange": now,
            "Flags": 0,
            "GroupID": 0,
            "UserID": 0,
            "Mode": mode,
            "ProtectionClass": 4,
            "Size": 0,
            "RelativePath": plistlib.UID(2),
            "InodeNumber": 0,
            "$class": plistlib.UID(3),
        },
        relative_path,
        {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
    ]
    return plistlib.dumps(
        {
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": objects,
        },
        fmt=plistlib.FMT_BINARY,
    )


def _ensure_directory_rows(conn, domain: str, relative_dir: str,
                           next_inode: int = None, known_dirs: set = None,
                           donor_blob: bytes = None,
                           owner: int = None, group: int = None) -> int:
    """Insert flags=2 directory rows for every missing path component.

    The iOS 27 restore agent skips a file whose parent directories have no
    manifest rows, so before injecting a tweak file its directory chain must
    exist in Manifest.db. Rows are cloned from a real directory blob of the
    backup (byte-exact metadata) with a unique inode; falls back to a
    hand-built blob when the backup has no directory rows at all.

    Batch-aware: when ``next_inode`` / ``known_dirs`` / ``donor_blob`` are
    supplied the directory state is reused across calls — ``known_dirs`` is a
    set of ``(domain, relativePath)`` tuples already present (so repeated
    chains skip the SELECT) and ``next_inode`` is an in-memory counter picked
    up where the previous call left it, avoiding a fresh manifest scan per
    file. Returns the current inode counter (one call passes it forward).

    ``owner``/``group`` (when not ``None``) are stamped onto every row written
    here. A donor dir blob is cloned from whatever directory row the backup
    happens to have — on a pruned protective backup that is a HomeDomain one,
    so a new root-owned domain would otherwise inherit mobile ownership on its
    own directory rows (DatabaseDomain's ``com.apple.xpc.launchd`` is
    uid 0 / mode 0755 on a real device).
    """
    if donor_blob is None:
        donor = conn.execute(
            "SELECT file FROM Files WHERE flags = 2 AND file IS NOT NULL LIMIT 1"
        ).fetchone()
        donor_blob = donor[0] if donor else None
    if next_inode is None:
        next_inode = _max_inode_in_manifest(conn)
    rel = ""
    for component in [""] + (relative_dir.split("/") if relative_dir else []):
        if component:
            rel = f"{rel}/{component}" if rel else component
        if known_dirs is not None:
            if (domain, rel) in known_dirs:
                continue
            exists = conn.execute(
                "SELECT 1 FROM Files WHERE domain = ? AND relativePath = ? AND flags = 2",
                (domain, rel),
            ).fetchone()
            if exists:
                known_dirs.add((domain, rel))
                continue
        else:
            exists = conn.execute(
                "SELECT 1 FROM Files WHERE domain = ? AND relativePath = ? AND flags = 2",
                (domain, rel),
            ).fetchone()
            if exists:
                continue
        next_inode += 1
        if donor_blob is not None:
            template = donor_blob if isinstance(donor_blob, MBFileArchive) else MBFileArchive.decode(donor_blob)
            metadata = template.clone()
            metadata.set_reference("RelativePath", rel)
        else:
            metadata = MBFileArchive.decode(_build_mbdir_blob(rel))
        info = metadata.fields
        info["InodeNumber"] = next_inode
        if domain == "SysContainerDomain-com.apple.eligibilityd":
            info["ProtectionClass"] = 0
            info["Mode"] = 0o40755
        if owner is not None:
            info["UserID"] = owner
        if group is not None:
            info["GroupID"] = group
        blob = metadata.encode()
        dir_id = hashlib.sha1(f"{domain}-{rel}".encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO Files (fileID, domain, relativePath, flags, file) "
            "VALUES (?, ?, ?, ?, ?)",
            (dir_id, domain, rel, 2, sqlite3.Binary(blob)),
        )
        if known_dirs is not None:
            known_dirs.add((domain, rel))
    return next_inode


def _max_inode_in_manifest(conn) -> int:
    """Largest inode claimed by any regular or directory row (0 when none has one)."""
    max_inode = 0
    for (candidate_blob,) in conn.execute(
        "SELECT file FROM Files WHERE flags IN (1, 2) AND file IS NOT NULL"
    ):
        try:
            ino = MBFileArchive.decode(candidate_blob).fields.get("InodeNumber")
            if ino is not None:
                if type(ino) is not int or ino < 0:
                    raise InvalidMBFile("InodeNumber must be a nonnegative integer")
                max_inode = max(max_inode, ino)
        except InvalidMBFile as exc:
            raise NuggetException(
                "The backup contains unreadable file metadata. Injection stopped.",
                detailed_text=str(exc)) from exc
    return max_inode


def inject_files_into_backup(backup_dir: "str | Path", udid: str, files: list,
                             manifest_password: str = "", *, max_inode_hint=None):
    """Add many files to a pruned backup in a single Manifest.db transaction.

    The iOS 27 "safe state recovery" wipe clears HomeDomain files that were
    staged by the sparse restore but are absent from the protective backup.
    Files the tweak writes can therefore be re-added here with their *new*
    content so Phase 3's mobilebackup2 restore lays them down natively (AFC
    cannot reach HomeDomain, so that is the only reliable path on iOS 27).

    Batch mode: the Manifest.db connection is opened once, the maximum inode
    is scanned once, and everything else rides on in-memory state carried
    across the whole batch — an inode counter, per-domain donor blobs, and
    the set of known directory rows. Payloads whose bytes already match the
    file on disk are left untouched (no unlink, no rewrite). All rows are
    committed together at the end. This removes the per-file
    open-Connection / scan-max-inode / prepare-dirs / commit cycle that made
    Phase 1 quadratic for large tweak payloads.

    ``files`` is a list of ``(domain, relative_path, contents, mode, owner,
    group)`` tuples; contents may be bytes or a Path and is streamed in bounded
    buffers. ``max_inode_hint`` is accepted only from the immediately preceding
    prune of this same manifest, before any other writer can change it. The iOS 27 restore agent requires a well-formed
    regular-file blob with a real, *unique* inode (it deduplicates by inode —
    a clone sharing the donor's inode gets restored with the donor's content,
    and a fresh blob without an inode is skipped outright). The mode is
    normalized to a regular 0644-style file so the agent accepts the row;
    the uid/gid are written **verbatim** (owner 0 = root is meaningful — the
    daemons plist lives in root-owned DatabaseDomain), and the parent
    directory rows inherit the same ownership.

    The file ID follows the standard ``SHA1("<domain>-<relativePath>")``
    convention and the payload is placed in the ``<aa>/<fileID>`` layout the
    restore agent expects. Returns ``(injected, unchanged, failed)``.

    Encrypted backups are NOT supported here: their payloads are written to
    disk encrypted (each with a per-file key wrapped by the manifest keybag),
    and a locally-injected plaintext payload has no matching wrapped key — the
    Phase 3 restore agent fails to decrypt it (MBErrorDomain/205). Injection
    is skipped for encrypted backups rather than corrupting the restore.
    """
    device_dir = Path(backup_dir) / udid
    if not device_dir.is_dir():
        # Tolerate backup_dir already pointing at the device directory.
        if (Path(backup_dir) / "Manifest.db").exists():
            device_dir = Path(backup_dir)
        else:
            return 0, 0, len(files)

    manifest_db = device_dir / "Manifest.db"
    if not manifest_db.exists():
        return 0, 0, len(files)

    if _is_encrypted_backup(device_dir):
        # See the docstring: plaintext injection into an encrypted backup makes
        # the Phase 3 restore fail with MBErrorDomain/205.
        _logger.warning(f"Skipping injection into encrypted backup for {len(files)} files")
        return 0, 0, len(files)

    if not _validate_sqlite_db(manifest_db):
        _logger.error(f"Manifest.db at {manifest_db} is not a valid SQLite database. Cannot inject files.")
        return 0, 0, len(files)

    conn = sqlite3.connect(str(manifest_db))
    injected = unchanged = 0
    try:
        reset_targets = {(domain, path) for domain, path, contents, *_ in files
                         if isinstance(contents, PreferenceKeyReset)}
        files = _prepare_preference_merges(conn, device_dir, files)
        # Batch-level state, computed once instead of per file:
        #   next_inode   - in-memory inode counter (one manifest scan total)
        #   donor_cache  - per-domain donor blob (the device's own row format)
        #   known_dirs   - directory rows already present / inserted
        #   dir_donor    - one real directory blob reused for dir rows
        next_inode = _max_inode_in_manifest(conn) if max_inode_hint is None else max_inode_hint
        donor_cache: dict = {}
        known_dirs: set = set()
        dir_donor = conn.execute(
            "SELECT file FROM Files WHERE flags = 2 AND file IS NOT NULL LIMIT 1"
        ).fetchone()
        dir_donor = MBFileArchive.decode(dir_donor[0]) if dir_donor else None
        for domain, relative_path, contents, mode, owner, group in files:
            file_id = hashlib.sha1(f"{domain}-{relative_path}".encode("utf-8")).hexdigest()
            original_row = conn.execute(
                'SELECT file FROM Files WHERE domain=? AND relativePath=? AND flags=1',
                (domain, relative_path)).fetchone()
            original_blob = original_row[0] if original_row else None

            # The restore agent skips a file whose parent directory rows are
            # missing, so ensure the whole directory chain first.
            dir_path, _ = os.path.split(relative_path)
            next_inode = _ensure_directory_rows(
                conn, domain, dir_path, next_inode, known_dirs, dir_donor,
                owner=owner, group=group)

            # The restore agent validates the blob and deduplicates by inode:
            # pick a donor the agent accepts, then stamp a unique inode so the
            # restored file cannot be confused with the donor's own file.
            if domain not in donor_cache:
                donor_bytes = _pick_donor_blob(conn, domain, relative_path)
                donor_cache[domain] = MBFileArchive.decode(donor_bytes) if donor_bytes else None
            donor = donor_cache[domain]
            unique_inode = next_inode + 1
            next_inode += 1
            safe_mode = (mode or 33188) & 0o100777
            if safe_mode & 0o777 == 0:
                safe_mode |= 0o644
            # Ownership is carried verbatim: 0 (root) is a real uid, not a
            # missing value — see _owned().
            payload = device_dir / file_id[:2] / file_id
            size, digest, changed = install_payload(contents, payload)
            if original_blob is not None and (_is_preference_target(domain, relative_path)
                                             or (domain, relative_path) in reset_targets):
                blob = _patch_donor_blob(original_blob, relative_path, contents, size=size, digest=digest)
            elif donor is None:
                blob = _build_mbfile_blob(
                    relative_path, contents,
                    mode=safe_mode, owner=_owned(owner), group=_owned(group),
                    size=size, digest=digest, inode=unique_inode,
                    protection_class=4 if domain == "SysContainerDomain-com.apple.eligibilityd" else None)
            else:
                blob = _patch_donor_blob(
                    donor, relative_path, contents,
                    mode=safe_mode, owner=_owned(owner), group=_owned(group),
                    size=size, digest=digest, inode=unique_inode,
                    protection_class=4 if domain == "SysContainerDomain-com.apple.eligibilityd" else None)
            conn.execute(
                "INSERT OR REPLACE INTO Files (fileID, domain, relativePath, flags, file) "
                "VALUES (?, ?, ?, ?, ?)",
                (file_id, domain, relative_path, 1, sqlite3.Binary(blob)),
            )
            injected += int(changed)
            unchanged += int(not changed)
        conn.commit()
    finally:
        conn.close()

    return injected, unchanged, len(files) - injected - unchanged


