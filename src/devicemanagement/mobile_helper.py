"""GoldenNugget Mobile helper — sideload the mobile app and deliver its pairing file.

GoldenNugget Mobile (github.com/GoldenNugget-Team/GoldenNugget-mobile) is the
on-device port of this app. It is a sideloaded IPA whose minimuxer core needs a
pairing record to talk to the phone it runs on. The device is already paired
with this desktop app over usbmuxd, so GoldenNugget is the right host to
produce that record and hand it to the mobile app:

* the **RemotePairing** record (``identifier``, ``private_key``,
  ``public_key``) is the one the app needs on iOS 26.4+; it is produced by
  pair-setup on the lockdown link and needs no Wi-Fi pairing and no PIN;
* the older **lockdown** record is whatever the lockdown client holds
  (``ld.pair_record``) — the same shape ``jitterbugpair`` writes — and is a
  fallback for older systems;
* both are dumped as an **XML plist** (the mobile app's importer only accepts
  UTF-8 text plists, never binary);
* delivery rides ``com.apple.mobile.house_arrest`` (AFC onto one app's
  container): the app reads ``Documents/pairingfile.mobiledevicepairing``
  at launch, so the file must land exactly there, with that exact name;
* installing the IPA goes through InstallationProxy (the same channel Xcode
  deploys with). The IPA must already be signed — unsigned/sideloaded-store
  bundles fail here the same way they fail anywhere else, and an unsigned
  install on a modern iOS needs Developer Mode enabled on the device;
* the *Apple-ID sign-and-sideload engine* is the in-repo ``gn-sideload`` CLI
  (``tools/sideload-engine``, built on the Rust crate `isideload` from
  nab138/iloader — MIT): it performs the GrandSlam login (credentials go to
  Apple only), the free Developer Services registration and the re-signing
  that a plain unsigned IPA needs. GoldenNugget drives it as a subprocess
  through a line protocol and never stores the password.

All entry points are async and only ever talk through ``lockdown_session``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import plistlib
import shutil
import sys
from pathlib import Path

from pymobiledevice3.exceptions import AppNotInstalledError
from pymobiledevice3.services.house_arrest import HouseArrestService
from pymobiledevice3.services.installation_proxy import InstallationProxyService

from src.devicemanagement.session import lockdown_session
from src.exceptions.nugget_exception import NuggetException

log = logging.getLogger("GoldenNugget.mobile_helper")

MOBILE_APP_BUNDLE_ID = "com.awesomenull.goldennugget"
MOBILE_APP_NAME = "GoldenNugget Mobile"
PAIRING_FILE_NAME = "pairingfile.mobiledevicepairing"

# The keys GoldenNugget Mobile's lockdown parser requires before it will hand a
# record to minimuxer (``Vendor/MinimuxerCommon/PairingFile.swift``:
# ``LockdownPairingFile.missingKeys``). The host's stored record is keyed by its
# FILE NAME, so it carries no ``UDID`` at all — exporting it untouched produced
# a file the app rejected ("Missing keys: UDID") on every device.
PAIRING_RECORD_KEYS = (
    "DeviceCertificate",
    "EscrowBag",
    "HostCertificate",
    "HostID",
    "HostPrivateKey",
    "RootCertificate",
    "RootPrivateKey",
    "SystemBUID",
    "UDID",
    "WiFiMACAddress",
)

# An iOS 17+ RemotePairing record has none of the lockdown keys and needs no
# completion; the app parses it by its own shape.
REMOTE_PAIRING_KEYS = ("identifier", "private_key", "public_key")
REMOTE_PAIRING_TIMEOUT = 180.0
LATEST_RELEASE_API = (
    "https://api.github.com/repos/GoldenNugget-Team/GoldenNugget-mobile/releases/latest"
)
ENGINE_NAME = "gn-sideload"
ENGINE_BUILD_HINT = (
    "cd tools/sideload-engine && cargo build --release"
)

def _engine_relative_candidates() -> tuple[Path, ...]:
    binary = Path("gn-sideload.exe" if sys.platform == "win32" else "gn-sideload")
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller: binaries at the bundle root
    candidates: list[Path] = []
    if base:
        candidates.append(Path(base) / binary)
        candidates.append(Path(base) / "tools" / "sideload-engine" / "target" / "release" / binary)
    # Dev/checkout runs: the repo root, two levels up from this file.
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / "tools" / "sideload-engine" / "target" / "release" / binary)
    return tuple(candidates)


def find_engine(override: str | None = None) -> str | None:
    """Resolve the ``gn-sideload`` engine, or ``None``.

    Search order: explicit override → ``gn-sideload`` on PATH → bundled copy
    in the frozen app → a locally built copy in the checkout. ``override``
    (a user-picked binary path) always wins.
    """
    candidates = [override, shutil.which("gn-sideload"), *(str(p) for p in _engine_relative_candidates())]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def is_remote_pairing_record(record: dict) -> bool:
    """Whether ``record`` is an iOS 17+ RemotePairing record, not a lockdown one."""
    return all(key in record for key in REMOTE_PAIRING_KEYS)


def missing_pairing_keys(record: dict) -> list[str]:
    """The lockdown keys GoldenNugget Mobile needs that ``record`` lacks.

    Empty for a RemotePairing record: it is a different format with its own
    key list and is exported as-is.
    """
    if is_remote_pairing_record(record):
        return []
    return [key for key in PAIRING_RECORD_KEYS if not record.get(key)]


def complete_pairing_record(record: dict, udid: str, *,
                            wifi_mac: str | None = None) -> dict:
    """Complete a host pair record with the values only the device knows.

    The host's stored record (usbmuxd / ``~/Library/Lockdown/<udid>.plist``)
    names the device by its **file name**, so ``UDID`` is never one of its
    keys, and records written by older hosts omit ``WiFiMACAddress`` too.
    GoldenNugget Mobile's lockdown parser requires both, so an untouched
    record is refused before minimuxer ever sees it.

    Existing values are never overwritten — the record is the device's own
    answer, and a stale WiFi MAC is not improved by guessing.
    """
    if not isinstance(record, dict) or not record:
        return {}
    if is_remote_pairing_record(record):
        return dict(record)
    completed = dict(record)
    if not completed.get("UDID") and udid:
        completed["UDID"] = str(udid)
    if not completed.get("WiFiMACAddress") and wifi_mac:
        completed["WiFiMACAddress"] = str(wifi_mac)
    return completed


def pairing_file_action(existing: bytes | None) -> str:
    """Whether the record already on the phone is kept or replaced.

    GoldenNugget Mobile can pair **itself** over RemotePairing (iOS 17+): its
    setup guide writes an ``.rppairing`` record (``identifier``,
    ``private_key``, ``public_key``) to the same path, and that record rides a
    transport a lockdown record cannot provide. Delivering ours on top of it
    forced the lockdown path, which some iOS 26.4+ setups cannot serve
    (``InvalidVPN``) — the app then started unpaired. So an app-generated
    record is kept; anything else (no file, an old lockdown record, a damaged
    file) is ours to replace.
    """
    if not existing:
        return "replace"
    try:
        parsed = plistlib.loads(existing)
    except Exception:
        return "replace"
    if isinstance(parsed, dict) and is_remote_pairing_record(parsed):
        return "keep"
    return "replace"


async def _lockdown_values(ld, keys: tuple[str, ...]) -> dict:
    """Best-effort ``GetValue`` lookups; a key the device refuses is skipped."""
    found: dict = {}
    for key in keys:
        try:
            value = await ld.get_value(key=key)
        except Exception as exc:                       # noqa: BLE001 - best effort
            log.debug("lockdown lookup of %s failed: %s", key, exc)
            continue
        if isinstance(value, str) and value.strip():
            found[key] = value.strip()
    return found


async def read_pairing_record(udid: str) -> dict:
    """The device's current pair record, completed for the mobile app.

    Uses the record the host already holds — no re-pair, so previously
    delivered records stay valid — and fills the two keys it cannot carry
    (``UDID``, and ``WiFiMACAddress`` when absent) from the live device.
    Raises :class:`NuggetException` when the device never confirmed trust.
    """
    async with lockdown_session(udid) as ld:
        record = dict(getattr(ld, "pair_record", None) or {})
        serial = getattr(ld, "identifier", None) or udid
        values: dict = {}
        if record:
            # Only ask for what the record cannot answer on its own.
            wanted = ["UniqueDeviceID"]
            if not record.get("WiFiMACAddress"):
                wanted.append("WiFiMACAddress")
            values = await _lockdown_values(ld, tuple(wanted))
    return complete_pairing_record(
        record, values.get("UniqueDeviceID") or serial,
        wifi_mac=values.get("WiFiMACAddress"))


def pairing_record_xml(record: dict) -> bytes:
    """The pair record as an XML plist (UTF-8 text — the mobile app's only input)."""
    if not isinstance(record, dict) or not record:
        raise NuggetException(
            "The device did not return a pairing record. Re-pair the device "
            "(tap Trust on the phone) and try again.")
    missing = missing_pairing_keys(record)
    if "UDID" in missing:
        # Without a UDID the app cannot even name the record; refuse to write a
        # file it is guaranteed to reject instead of failing on the phone.
        raise NuggetException(
            "The pairing record has no UDID. GoldenNugget Mobile cannot use a "
            "lockdown record without it — reconnect and unlock the device, "
            "then export the pairing file again.")
    if missing:
        log.warning("pairing record is missing %s — GoldenNugget Mobile may "
                    "refuse it (a missing EscrowBag breaks backup-driven "
                    "operations)", ", ".join(missing))
    return plistlib.dumps(dict(record), fmt=plistlib.FMT_XML)


async def export_pairing_file(udid: str, dest: str) -> bytes:
    """Dump the device's current pair record to ``dest`` and return its bytes."""
    xml = pairing_record_xml(await read_pairing_record(udid))
    data = Path(dest)
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_bytes(xml)
    log.info("pairing record exported to %s", dest)
    return xml


# ---------------------------------------------------------------------------
# RemotePairing export (iOS 17+; required on iOS 26.4+)
#
# The lockdown record above only serves the lockdown transport, which some
# iOS 26.4+ setups cannot provide (``InvalidVPN`` on a userspace utun VPN).
# GoldenNugget Mobile's working transport is RemotePairing: its own setup guide
# pairs the phone with itself and stores an ``.rppairing`` record. The desktop
# produces the same kind of record with no Wi-Fi pairing, no PIN and no
# Settings → Developer → Paired Macs step: ``remotepairingdeviced`` is reachable
# through the lockdown link the helper already has
# (``com.apple.dt.remotepairingdeviced.lockdown``), and pair-setup on that
# already-trusted transport is promptless. That is the flow iLoader/AltStore
# use; pymobiledevice3 exposes it as ``RemotePairingLockdownService``.


def mobile_remote_pairing_xml(record: dict, identifier: str) -> bytes:
    """The rppairing record as GoldenNugget Mobile's XML plist.

    The service caches a record with the Ed25519 key pair and the remote-unlock
    key, but not the host identifier: pymobiledevice3's own pair record omits
    it because it re-derives the same UUIDv3-from-hostname on every run. The
    device stores that identifier as the host's ``accountID``, so the file
    handed to the phone has to carry it explicitly — GoldenNugget Mobile's
    ``RPPairingFile`` and the Rust ``RpPairingFile`` require all three keys.

    ``alt_irk`` is not included: it is the *device's* mDNS identity key, only
    used to authenticate Bonjour discovery. The phone reaches the device over
    the tunnel, where pair-verify uses the key pair alone.
    """
    private_key = record.get("private_key")
    public_key = record.get("public_key")
    if not isinstance(private_key, (bytes, bytearray)) or len(private_key) != 32:
        raise NuggetException(
            "The RemotePairing record has no 32-byte Ed25519 private key. "
            "Pair the device again.")
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != 32:
        raise NuggetException(
            "The RemotePairing record has no 32-byte Ed25519 public key. "
            "Pair the device again.")
    if not isinstance(identifier, str) or not identifier.strip():
        raise NuggetException(
            "The RemotePairing record has no host identifier. Pair the device "
            "again.")
    return plistlib.dumps({
        "identifier": identifier.strip(),
        "private_key": bytes(private_key),
        "public_key": bytes(public_key),
    }, fmt=plistlib.FMT_XML)


async def export_remote_pairing_file(
    dest: str,
    *,
    udid: str,
    connection_type: str | None = None,
    timeout: float = REMOTE_PAIRING_TIMEOUT,
) -> dict:
    """Pair the device over its lockdown link and write an rppairing record.

    ``dest`` receives the **mobile-compatible** XML (``identifier``,
    ``private_key``, ``public_key``) — the transport GoldenNugget Mobile needs,
    which a lockdown record cannot provide on iOS 26.4+.

    The pairing itself is host-initiated and promptless: pair-setup runs on the
    ``com.apple.dt.remotepairingdeviced.lockdown`` service, i.e. on the lockdown
    transport that is already trusted, so there is no "Trust This Computer?"
    dialog, no code to type and no Paired Macs screen to open. The device
    remembers this host under a UUIDv3-of-hostname identifier, and the key pair
    is cached by pymobiledevice3, so the next export pair-verifies instead of
    pairing again — a fresh key on every export would make GoldenNugget a new
    host each time.

    Returns a dict with ``path``, ``xml``, ``name``, ``model`` and ``udid``.
    """
    # Imported here: the pairing stack pulls in cryptography, and the
    # lockdown-only helpers above must stay importable even where that optional
    # stack is incomplete.
    from pymobiledevice3.exceptions import RemotePairingCompletedError
    from pymobiledevice3.remote.tunnel_service import RemotePairingLockdownService

    async with lockdown_session(udid, connection_type=connection_type) as ld:
        service = await RemotePairingLockdownService.create(ld)
        try:
            try:
                await asyncio.wait_for(
                    service.connect(autopair=True), timeout=timeout)
            except RemotePairingCompletedError:
                # First pairing: the service writes the record and the endpoint
                # then closes the connection (pair-verify runs on a fresh one).
                log.info("RemotePairing pair-setup completed over lockdown")
            record = service.pair_record or {}
            identifier = service.identifier
            peer = dict((service.handshake_info or {}).get("peerDeviceInfo") or {})
        finally:
            try:
                await service.close()
            except Exception:                      # noqa: BLE001 - best effort
                pass

    xml = mobile_remote_pairing_xml(record, identifier)
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(xml)
    log.info("RemotePairing record for %s (%s) written to %s",
             peer.get("name") or udid, peer.get("model") or "?", target)
    return {
        "path": str(target),
        "xml": xml,
        "name": peer.get("name") or "",
        "model": peer.get("model") or "",
        "udid": peer.get("identifier") or udid,
    }


async def is_mobile_app_installed(udid: str, bundle_id: str = MOBILE_APP_BUNDLE_ID) -> dict | None:
    """Info about the installed mobile app on the device, or ``None``.

    The bundle id is matched by PREFIX: our in-repo engine signs the app with
    free provisioning, which renames ``com.awesomenull.goldennugget`` to
    ``com.awesomenull.goldennugget.<TEAM_ID>`` (an exact-equality lookup
    returned None and the helper kept claiming the app was not installed).
    """
    apps = await _installed_apps(udid)
    info, actual_id = _match_mobile_app(apps, bundle_id)
    if not info:
        return None
    return {
        "bundle_id": actual_id,
        "display_name": (info or {}).get("CFBundleDisplayName") or (info or {}).get("CFBundleName") or bundle_id,
        "version": (info or {}).get("CFBundleVersion", ""),
    }


async def _installed_apps(udid: str) -> dict:
    async with lockdown_session(udid) as ld:
        async with InstallationProxyService(lockdown=ld) as ip:
            return (await ip.get_apps(application_type="Any", calculate_sizes=False)) or {}


def _match_mobile_app(apps: dict, bundle_id: str = MOBILE_APP_BUNDLE_ID) -> tuple[dict | None, str | None]:
    """(info, actual bundle id) for GoldenNugget Mobile in ``apps`` or (None, None)."""
    for key in apps:
        if key == bundle_id or key.startswith(bundle_id + "."):
            return apps[key], key
    return None, None


async def install_ipa(udid: str, ipa_path: str, progress=None) -> None:
    """Install a signed ``.ipa`` on the device via InstallationProxy.

    :param progress: optional callback receiving the device-reported install
        percentage (0.0-100.0).
    """
    path = Path(ipa_path)
    if not path.is_file() or path.suffix.lower() != ".ipa":
        raise NuggetException(f"{path.name} is not an .ipa package.")
    if not path.stat().st_size:
        raise NuggetException(f"{path.name} is empty — the download did not finish.")

    def handler(percent_complete, *_args):
        if progress is not None:
            progress(float(percent_complete or 0.0))

    log.info("installing %s onto %s", path, udid)
    async with lockdown_session(udid) as ld:
        async with InstallationProxyService(lockdown=ld) as ip:
            await ip.install_from_local(path, handler=handler)
    log.info("install finished: %s", path.name)


async def send_pairing_to_app(udid: str, xml: bytes,
                              bundle_id: str | None = None,
                              app_name: str = MOBILE_APP_NAME) -> str:
    """Write a pairing record to ``Documents/pairingfile.mobiledevicepairing``.

    The record rides house_arrest (AFC into one app's container). The file must
    land exactly at ``Documents/pairingfile.mobiledevicepairing`` — the spot
    the mobile app's minimuxer reads at launch.

    A record the app generated **itself** is never replaced (see
    :func:`pairing_file_action`): on iOS 17+ its setup guide writes a
    RemotePairing record to the same path, and that record uses a transport
    the app cannot get from a lockdown record — overwriting it cost the user a
    working install (``InvalidVPN`` on iOS 26.4+). Returns ``"delivered"`` or
    ``"kept"`` for the caller to report.

    Two device quirks drive the shape of this function:

    * the engine's free provisioning appends ``.<TEAM_ID>`` to the bundle id at
      signing time, so ``bundle_id`` defaults to a prefix lookup over the
      installed apps;
    * ``VendDocuments`` on this app serves an AFC root every operation fails
      on (READ_DIR / FILE_OPEN status 10), seen even when ``Documents``
      exists — so the WHOLE container is vended (``VendContainer``) and the
      file is delivered under its ``Documents/`` prefix instead.
    """
    if bundle_id is None:
        installed = await is_mobile_app_installed(udid)
        if not installed:
            raise NuggetException(
                f"{app_name} is not installed on the device. Install the app "
                "first, then try again.")
        bundle_id = installed["bundle_id"]
    status = "delivered"
    async with lockdown_session(udid) as ld:
        house = HouseArrestService(lockdown=ld, documents_only=False)
        try:
            await house.send_command(bundle_id, "VendContainer")
            listing = await house.listdir(".")
            if "Documents" not in listing:
                await house.mkdir("Documents")
            existing = None
            try:
                existing = await house.get_file_contents(
                    f"Documents/{PAIRING_FILE_NAME}")
            except Exception:                       # no record yet, or unreadable
                existing = None
            if pairing_file_action(existing) == "keep":
                status = "kept"
                log.info("kept the app's own RemotePairing record in %s — a "
                         "lockdown record cannot serve that transport",
                         bundle_id)
            else:
                await house.set_file_contents(
                    f"Documents/{PAIRING_FILE_NAME}", xml)
        except AppNotInstalledError as e:
            raise NuggetException(
                f"{app_name} is not installed on the device. Install the app "
                "first, then send the pairing file again.") from e
        finally:
            try:
                await house.close()
            except Exception:
                pass
    if status == "delivered":
        log.info("pairing record delivered to %s/Documents/%s", bundle_id,
                 PAIRING_FILE_NAME)
    return status
