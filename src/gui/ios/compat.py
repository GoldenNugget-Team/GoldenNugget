"""Device compatibility for tweaks.

The constraints themselves live in the tweak registry
(``TweakSpec.min_version`` / ``iphone_only`` / ``ipad_only``); this module
only evaluates them.
"""
import re

from src.devicemanagement.constants import Version
from src.tweaks.registry import SPECS_BY_ID


def device_family(model: str) -> str | None:
    """Return the normalized family for an Apple hardware identifier."""
    value = str(model or "").strip().casefold()
    if value.startswith(("iphone", "ipod")):
        return "iphone"
    if value.startswith("ipad"):
        return "ipad"
    return None


def _parse_version(value: str) -> Version:
    """Accept both lockdown versions (``27.0``) and display strings (``iOS 27.0``)."""
    match = re.search(r"\d+(?:\.\d+){0,3}", str(value or ""))
    if not match:
        raise ValueError(f"Invalid iOS version: {value!r}")
    return Version(match.group(0))


def compatibility_reasons(tweak_id, device_version: str, model: str = "",
                          is_iphone: bool | None = None) -> list[str]:
    """Return precise reasons a tweak cannot run on the selected device."""
    spec = SPECS_BY_ID.get(tweak_id)
    if spec is None:
        return []

    reasons = []
    parsed_device = None
    if device_version:
        try:
            parsed_device = _parse_version(device_version)
        except ValueError:
            reasons.append("the iOS version could not be verified")

    if parsed_device is not None and spec.min_version:
        minimum = _parse_version(spec.min_version)
        if parsed_device < minimum:
            reasons.append(f"requires iOS {spec.min_version} or newer")
    if parsed_device is not None and spec.max_version:
        maximum = _parse_version(spec.max_version)
        if parsed_device > maximum:
            reasons.append(f"supports iOS {spec.max_version} or older")

    family = device_family(model)
    if family is None and is_iphone is not None:
        family = "iphone" if is_iphone else "ipad"
    if spec.ipad_only and family != "ipad":
        reasons.append("is for iPad only")
    if spec.iphone_only and family != "iphone":
        reasons.append("is for iPhone only")
    return reasons


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
    return not compatibility_reasons(tweak_id, device_version, model, is_iphone)
