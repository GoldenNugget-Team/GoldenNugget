"""Device compatibility for tweaks.

The constraints themselves live in the tweak registry
(``TweakSpec.min_version`` / ``iphone_only`` / ``ipad_only``); this module
only evaluates them.
"""
import re

from PySide6.QtCore import QCoreApplication

from src.devicemanagement.constants import Version
from src.devicemanagement.device_capabilities import (
    device_os_text,
    has_action_button,
    has_always_on_display,
    has_apple_intelligence,
    has_camera_control,
    has_dynamic_island,
    has_home_button,
)
from src.tweaks.compatibility import _parse_version, device_family
from src.tweaks.registry import SPECS_BY_ID


def untested_tweaks_enabled(device_version: str) -> bool:
    from src.controllers.settings import Settings
    from src.tweaks.compatibility import version_override_allowed
    return version_override_allowed(device_version,
        Settings().value("enable_incompatible_tweaks", False, type=bool))


def compatibility_reasons(tweak_id, device_version: str, model: str = "",
                          is_iphone: bool | None = None, *, allow_untested=False) -> list[str]:
    from src.tweaks.compatibility import compatibility_reasons as resolve
    return resolve(tweak_id, device_version, model, is_iphone,
                   allow_untested=allow_untested and untested_tweaks_enabled(device_version),
                   translate=lambda text: device_os_text(
                       QCoreApplication.translate("Compatibility", text), model))


def is_tweak_compatible(tweak_id, device_version: str, is_iphone: bool,
                        model: str = "") -> bool:
    """Return True if the tweak makes sense on the given device.

    Tweak IDs outside the registry (special tweaks like PosterBoard) carry no
    constraints here and are always compatible.
    """
    # No connected device yet: keep all controls visible while the page is
    # being constructed. Once a device is known, fail closed on bad metadata
    # so an uncertain tweak is never offered as definitely compatible.
    if not device_version and not model:
        return True
    return not compatibility_reasons(tweak_id, device_version, model, is_iphone,
                                    allow_untested=True)
