"""GoldenNugget Mobile helper — sideload the mobile app and deliver its pairing file.

GoldenNugget Mobile (github.com/GoldenNugget-Team/GoldenNugget-mobile) is the
on-device port of this app. It is a sideloaded IPA whose minimuxer core needs a
lockdown pairing record to talk to the phone it runs on. The device is already
paired with this desktop app over usbmuxd, so GoldenNugget is the right host to
produce that record and hand it to the mobile app:

* the record is whatever the lockdown client holds (``ld.pair_record``) —
  the same shape ``jitterbugpair`` writes — dumped as an **XML plist**
  (the mobile app's importer only accepts UTF-8 text plists, never binary);
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

import logging
import os
import plistlib
import shutil
import sys
from pathlib import Path

from pymobiledevice3.exceptions import AppNotInstalledError
from pymobiledevice3.services.installation_proxy import InstallationProxyService
from pymobiledevice3.services.house_arrest import HouseArrestService

from src.exceptions.nugget_exception import NuggetException
from src.devicemanagement.session import lockdown_session

log = logging.getLogger("GoldenNugget.mobile_helper")

MOBILE_APP_BUNDLE_ID = "com.awesomenull.goldennugget"
MOBILE_APP_NAME = "GoldenNugget Mobile"
PAIRING_FILE_NAME = "pairingfile.mobiledevicepairing"
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




async def read_pairing_record(udid: str) -> dict:
    """The device's current pair record as a dict.

    Uses the record the host already holds — no re-pair, so previously
    delivered records stay valid. Raises :class:`NuggetException` when the
    device never confirmed trust.
    """
    async with lockdown_session(udid) as ld:
        record = getattr(ld, "pair_record", None)
    return record or {}


def pairing_record_xml(record: dict) -> bytes:
    """The pair record as an XML plist (UTF-8 text — the mobile app's only input)."""
    if not isinstance(record, dict) or not record:
        raise NuggetException(
            "The device did not return a pairing record. Re-pair the device "
            "(tap Trust on the phone) and try again.")
    if "EscrowBag" not in record:
        log.warning("pairing record has no EscrowBag — on-device minimuxer may "
                    "refuse backup-driven operations")
    return plistlib.dumps(dict(record), fmt=plistlib.FMT_XML)


async def export_pairing_file(udid: str, dest: str) -> bytes:
    """Dump the device's current pair record to ``dest`` and return its bytes."""
    xml = pairing_record_xml(await read_pairing_record(udid))
    data = Path(dest)
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_bytes(xml)
    log.info("pairing record exported to %s", dest)
    return xml


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
                              app_name: str = MOBILE_APP_NAME) -> None:
    """Write a pairing record to ``Documents/pairingfile.mobiledevicepairing``.

    The record rides house_arrest (AFC into one app's container). The file must
    land exactly at ``Documents/pairingfile.mobiledevicepairing`` — the spot
    the mobile app's minimuxer reads at launch.

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
    async with lockdown_session(udid) as ld:
        house = HouseArrestService(lockdown=ld, documents_only=False)
        try:
            await house.send_command(bundle_id, "VendContainer")
            listing = await house.listdir(".")
            if "Documents" not in listing:
                await house.mkdir("Documents")
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
    log.info("pairing record delivered to %s/Documents/%s", bundle_id,
             PAIRING_FILE_NAME)
