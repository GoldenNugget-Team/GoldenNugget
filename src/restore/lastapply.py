"""Persistent record of the last successfully applied tweak set.

When the user leaves every already-applied tweak untouched and only adds
wallpapers, the Phase 2 sparse/partial pass has nothing new to deliver — the
device already carries those tweak files. Comparing the freshly generated
sparse payload against this record lets ``restore_files`` skip Phase 2 and go
straight to Phase 3's protective restore, which delivers the wallpapers.

A fresh record is written after every successful apply (device_manager) and
cleared after a successful reset (the device is back to stock, so a stale
record must never trigger a skip).
"""

import hashlib
import json
import logging
import os

from src.utils.paths import app_data_dir

log = logging.getLogger("GoldenNugget.lastapply")


# PosterBoard files are delivered via Phase 3's protective restore, never via
# the sparse pass — so they never decide whether Phase 2 has something new.
PB_DOMAIN = "AppDomain-com.apple.PosterBoard"


def is_ios27_scaffolding(domain: str, path: str) -> bool:
    """True for incidental files written AROUND the real tweak payload on the
    iOS 27 path (they never decide whether Phase 2 has anything new to
    deliver): the HomeDomain ``.GlobalPreferences.plist`` secondary copy and
    the skip-setup plists that Phase 5 re-applies natively on iOS 27.
    """
    if (domain == "HomeDomain"
            and path == "Library/Preferences/.GlobalPreferences.plist"):
        return True
    if (domain == "ManagedPreferencesDomain"
            and path == "mobile/com.apple.purplebuddy.plist"):
        return True
    if (domain == "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles"
            and path == "Library/ConfigurationProfiles/CloudConfigurationDetails.plist"):
        return True
    return False


def sparse_signature(files) -> dict:
    """Map ``"{domain}/{restore_path}"`` -> sha1(contents) for every file the
    Phase 2 sparse pass would write on this apply.

    Files without a real domain (path-traversal era), PosterBoard AppDomain
    files and the incidental iOS 27 scaffolding are excluded. The signature is
    order-independent and deterministic for a given UI state, so two applies
    with identical tweak selections hash identically.
    """
    signature: dict = {}
    for f in files:
        domain = getattr(f, "domain", "") or ""
        path = getattr(f, "restore_path", None)
        if path is None:
            path = getattr(f, "path", "") or ""
        path = path.lstrip("/")
        if not domain or domain == "z" or not path:
            continue
        if domain == PB_DOMAIN:
            continue
        if is_ios27_scaffolding(domain, path):
            continue
        data = getattr(f, "contents", None)
        if data is None:
            src = getattr(f, "contents_path", None)
            if src:
                try:
                    from src.utils.payload import copy_payload
                    _, digest = copy_payload(src)
                    signature[f"{domain}/{path}"] = digest.hex()
                    continue
                except OSError:
                    continue
        if data is None:
            continue
        if isinstance(data, str):
            data = data.encode("utf-8")
        signature[f"{domain}/{path}"] = hashlib.sha1(data).hexdigest()
    return signature


def _store_dir() -> str:
    base = str(app_data_dir())
    folder = os.path.join(base, "LastApply")
    os.makedirs(folder, exist_ok=True)
    return folder


def _safe_udid(udid) -> str:
    return "".join(c for c in str(udid) if c.isalnum() or c in "._-")


def lastapply_path(udid) -> str:
    return os.path.join(_store_dir(), f"{_safe_udid(udid)}.json")


def load_lastapply(udid) -> dict:
    """Return the stored signature, or ``{}`` when there is no record yet."""
    try:
        with open(lastapply_path(udid), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_lastapply(udid, signature: dict) -> None:
    try:
        with open(lastapply_path(udid), "w", encoding="utf-8") as f:
            json.dump(signature, f, sort_keys=True, indent=2)
    except OSError as e:
        log.warning("Could not write lastapply record: %s", e)


def clear_lastapply(udid) -> None:
    path = lastapply_path(udid)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        log.warning("Could not clear lastapply record: %s", e)
