"""Explicit, fail-closed verification of local backup manifests and payloads."""
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.exceptions.nugget_exception import NuggetException


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    missing: tuple[str, ...] = ()
    reason: str = ""

    def require_verified(self) -> list[str]:
        if self.status != VerificationStatus.VERIFIED:
            raise NuggetException(
                "The protective backup could not be verified. Restore stopped.",
                detailed_text=self.reason)
        return list(self.missing)


def inspect_backup_payloads(backup_dir, udid, password, *, inventory,
                            is_sqlite, is_encrypted, decrypt) -> VerificationResult:
    """Inspect without modifying the source; only a complete scan is verified.

    Dependencies are explicit so protocol adapters and local FS faults can be
    tested without opening a device session. Decryption only targets a scratch
    file whose lifetime covers every failure path.
    """
    root = Path(backup_dir)
    device_dir = root / udid
    if not device_dir.is_dir() and (root / "Manifest.db").is_file():
        device_dir = root
    manifest = device_dir / "Manifest.db"
    if not manifest.is_file():
        return VerificationResult(VerificationStatus.UNAVAILABLE,
                                  reason=f"Manifest.db not found at {manifest}")
    temporary = None
    try:
        if not is_sqlite(manifest):
            if not is_encrypted(device_dir):
                return VerificationResult(VerificationStatus.FAILED,
                                          reason=f"Invalid SQLite manifest: {manifest}")
            if not password:
                return VerificationResult(VerificationStatus.UNAVAILABLE,
                                          reason="The encrypted manifest requires a backup password.")
            with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as stream:
                temporary = Path(stream.name)
            decrypt(device_dir, password, temporary)
            manifest = temporary
            if not is_sqlite(manifest):
                return VerificationResult(VerificationStatus.FAILED,
                                          reason="The decrypted manifest is not a valid SQLite database.")
        with closing(sqlite3.connect(f"{manifest.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            present = inventory(device_dir)[3]
            missing = tuple(relative for file_id, relative in connection.execute(
                "SELECT fileID, relativePath FROM Files WHERE flags = 1")
                if file_id not in present)
        return VerificationResult(VerificationStatus.VERIFIED, missing)
    except Exception as exc:
        return VerificationResult(VerificationStatus.FAILED,
                                  reason=f"{type(exc).__name__}: {exc}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class PruneResult:
    removed_rows: int = 0
    removed_files: int = 0
    max_inode: int | None = None

    def __iter__(self):
        """Compatibility for callers still unpacking the two removal counts."""
        yield self.removed_rows
        yield self.removed_files
