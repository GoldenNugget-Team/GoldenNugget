#!/usr/bin/env python3
"""Offline regression suite for the Windows-safe encrypted-manifest prune shim.

Upstream ``Mobilebackup2Service.prune_backup_manifest`` (pymobiledevice3
10.7.1) wraps the decrypted manifest in ``NamedTemporaryFile(delete=True)``
and keeps it OPEN while ``_decrypt_backup_manifest_db`` reopens that exact
path by name. On Windows the temp file is created with ``O_TEMPORARY`` and
re-opening an already-open temp file fails with
``PermissionError: [Errno 13] Permission denied`` — every mac/CI run passes,
so only Windows users on encrypted backups hit it (issue #87).

``src/restore/protective._install_encrypted_manifest_prune_shim`` replaces
the classmethod: close the temp file before writing to it, unlink it in a
``finally``. This suite monkeypatches the three helper steps and asserts the
contract the shim promises:

1. decryption sees a WRITABLE, closed temp file (no O_TEMPORARY handle held);
2. pruning runs on the freshly decrypted bytes and its result is returned;
3. re-encryption lands on ``<device>/Manifest.db``;
4. no ``.sqlite3`` temp file is left behind afterwards.

Run: ``python tools/test_encrypted_manifest_prune.py``
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service


def main() -> int:
    # importing the module installs the production shim
    import src.restore.protective  # noqa: F401

    calls = []
    originals = (
        Mobilebackup2Service._decrypt_backup_manifest_db,
        Mobilebackup2Service._prune_manifest_db,
        Mobilebackup2Service._encrypt_backup_manifest_db,
        Mobilebackup2Service._is_encrypted_backup,
    )

    def decrypt(device_directory, password, out_path):
        calls.append(("decrypt", Path(out_path).exists()))
        Path(out_path).write_bytes(b"decrypted")
        return b"KEY"

    def prune(path, callback):
        assert Path(path).read_bytes() == b"decrypted"
        calls.append(("prune", str(path)))
        return {"fid1", "fid2"}

    def encrypt(path, db_path, key):
        assert key == b"KEY"
        assert Path(path).read_bytes() == b"decrypted"
        calls.append(("encrypt", db_path.name))
        Path(db_path).write_bytes(b"ciphertext")

    def is_encrypted(device_directory):
        return True

    Mobilebackup2Service._decrypt_backup_manifest_db = staticmethod(decrypt)
    Mobilebackup2Service._prune_manifest_db = staticmethod(prune)
    Mobilebackup2Service._encrypt_backup_manifest_db = staticmethod(encrypt)
    Mobilebackup2Service._is_encrypted_backup = staticmethod(is_encrypted)

    try:
        with tempfile.TemporaryDirectory() as td:
            device_directory = Path(td) / "dev"
            device_directory.mkdir()

            kept = Mobilebackup2Service.prune_backup_manifest(
                device_directory, None, password="pw")

            leftovers = list(Path(td).glob("*.sqlite3"))
            manifest_cipher = (device_directory / "Manifest.db").read_bytes()
    finally:
        (Mobilebackup2Service._decrypt_backup_manifest_db,
         Mobilebackup2Service._prune_manifest_db,
         Mobilebackup2Service._encrypt_backup_manifest_db,
         Mobilebackup2Service._is_encrypted_backup) = originals

    assert kept == {"fid1", "fid2"}, kept
    assert [c[0] for c in calls] == ["decrypt", "prune", "encrypt"], calls
    assert calls[0][1] is True, "temp file must be closed (writable) before decrypt"
    assert leftovers == [], f"temp file leaked: {leftovers}"
    assert manifest_cipher == b"ciphertext"

    print("ENCRYPTED_MANIFEST_PRUNE_SHIM_OK:",
          [c[0] for c in calls], "| temp leak: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
