"""Shared helpers for the GoldenNugget CLI commands.

Everything here mirrors the GUI wiring (``apply_wallpaper.py`` / the ``Settings``
+ ``PreferencesMixin`` pattern) so a headless command exercises exactly the same
code paths the GUI does: a ``Settings`` store, one ``DeviceManager``, the
persisted preferences, and the registry/daemon/preset tweak loaders.
"""

import sys
from typing import Optional

from src.controllers.settings import Settings


def bootstrap() -> Settings:
    """Set up the settings store (no Qt, no windowing system required).

    The CLI is fully headless: the backend only needs the Qt-free settings
    store, and translations fall back to the source strings
    (:mod:`src.utils.i18n`).
    """
    return Settings("settings")


def make_device_manager(settings: Settings):
    """Build a DeviceManager wired to the settings store (mirrors the GUI)."""
    from src.devicemanagement.device_manager import DeviceManager
    dm = DeviceManager()
    dm.pref_manager.settings = settings
    return dm


def load_prefs(dm, settings: Settings):
    """Load persisted preferences into the manager (like the GUI's loadSettings)."""
    pm = dm.pref_manager
    try:
        pm.auto_reboot = settings.value("auto_reboot", True, type=bool)
        pm.disable_tendies_limit = settings.value("disable_tendies_limit", False, type=bool)
        pm.auto_refresh_posterboard = settings.value("auto_refresh_posterboard", True, type=bool)
        pm.use_backup_cache = settings.value("use_backup_cache", True, type=bool)
        pm.use_encrypted_backup = settings.value("use_encrypted_backup", False, type=bool)
        pm.use_afc_media = settings.value("use_afc_media", True, type=bool)
        pm.skip_setup = settings.value("skip_setup", True, type=bool)
        pm.supervised = settings.value("supervised", False, type=bool)
        pm.organization_name = settings.value("organization_name", "", type=str)
    except Exception:
        pass


def print_status(text):
    print(text, flush=True)


def print_alert(msg):
    """Render a backend ApplyAlertMessage (or exception) to stderr."""
    if msg is None:
        return
    title = getattr(msg, "title", None) or "Alert"
    txt = getattr(msg, "txt", None) or str(msg)
    print(f"[{title}] {txt}", file=sys.stderr, flush=True)
    detailed = getattr(msg, "detailed_txt", None)
    if detailed:
        print("[details]", file=sys.stderr, flush=True)
        print(detailed, file=sys.stderr, flush=True)


def list_devices(dm, settings: Settings):
    """Enumerate devices via the manager's own flow (populates dm.devices)."""
    dm.get_devices(settings, show_alert=print_alert)


def ensure_device(dm, settings: Settings, udid: Optional[str] = None):
    """Make sure a current device is selected; ``udid`` pins the target.

    Returns the selected ``Device`` or raises ``SystemExit`` with an error
    message when nothing suitable is connected.
    """
    list_devices(dm, settings)
    if not getattr(dm, "devices", None):
        print("ERROR: no device connected.", file=sys.stderr)
        raise SystemExit(1)
    if udid:
        for i, device in enumerate(dm.devices):
            if getattr(device, "udid", None) == udid:
                dm.set_current_device(i)
                return device
        print(f"ERROR: device {udid} not found.", file=sys.stderr)
        raise SystemExit(1)
    if dm.get_current_device_udid() is None:
        dm.set_current_device(0)
    return dm.data_singleton.current_device


def describe_device(device) -> str:
    return (f"{getattr(device, 'name', '?')} "
            f"{getattr(device, 'version', '?')} ({getattr(device, 'build', '?')})  "
            f"{getattr(device, 'udid', '?')}")


def load_core_tweaks():
    """Idempotently load the registry tweaks + daemons (like the GUI pages)."""
    from src.tweaks.tweak_loader import load_plist_tweaks, load_daemons
    load_plist_tweaks()
    load_daemons()


def seed_from_autosave():
    """Start tweak-state edits from the current AutoSave (GUI startup pattern).

    The registry loaders build a fresh all-off state; applying the stored
    AutoSave on top mirrors what the GUI pages show, so a single tweak
    change never resets the rest of the configuration to defaults.
    """
    from src.controllers.preset_manager import PresetManager
    pm = PresetManager()
    if "AutoSave" in pm.list_presets():
        pm.load_preset("AutoSave")


def resolve_tweak_id(name: str):
    """Map a CLI-provided tweak name to a TweakID (case-insensitive)."""
    from src.tweaks.tweak_names import TweakID
    for member in TweakID:
        if member.name == name or member.name.lower() == name.lower():
            return member
    return None


def autosave_preset(dm=None):
    """Persist the current tweak state to the AutoSave preset (GUI behaviour).

    Returns False when nothing was serializable (e.g. empty state).
    """
    from src.controllers.preset_manager import PresetManager
    model = dm.get_current_device_model() if dm is not None else ""
    version = dm.get_current_device_version() if dm is not None else ""
    return PresetManager().save_preset(
        "AutoSave", "Automatic save of last tweak configuration", tags=["auto"],
        device_model=model or "", ios_version=version or "")


def load_default_preset(source: Optional[str] = None, dm=None, preview_only=False):
    """Load a preset the CLI apply flow should start from.

    ``source`` given -> load exactly that preset. Otherwise mimic the GUI:
    AutoSave if it exists, else nothing.
    """
    from src.controllers.preset_manager import PresetManager
    pm = PresetManager()
    if source:
        if source.lower() == "none":
            return
        if not pm.load_preset(source, preview_only=preview_only):
            print(f"ERROR: preset '{source}' not found or failed to load.", file=sys.stderr)
            raise SystemExit(1)
        return
    if "AutoSave" in pm.list_presets():
        pm.load_preset("AutoSave", preview_only=preview_only)
