"""Device eligibility shared by GUI, preview, CLI plans and compilation."""
import re

from src.devicemanagement.constants import Version
from src.devicemanagement.device_capabilities import (
    has_action_button,
    has_always_on_display,
    has_apple_intelligence,
    has_camera_control,
    has_dynamic_island,
    has_home_button,
)
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


def version_override_allowed(device_version, opted_in):
    try:
        return bool(opted_in) and Version("26") <= _parse_version(device_version) < Version("27")
    except ValueError:
        return False


def hardware_reasons(spec, model, is_iphone=None, *, translate=None):
    reasons = []
    tr = translate or (lambda text: text)
    family = device_family(model)
    if family is None and is_iphone is not None:
        family = "iphone" if is_iphone else "ipad"
    if spec.ipad_only and family != "ipad":
        reasons.append(tr("is for iPad only"))
    if spec.iphone_only and family != "iphone":
        reasons.append(tr("is for iPhone only"))
    if spec.requires_apple_intelligence and not has_apple_intelligence(model):
        reasons.append(tr("requires iPhone 15 Pro or later with Apple Intelligence hardware"))
    if spec.requires_dynamic_island and not has_dynamic_island(model):
        reasons.append(tr("requires an iPhone with Dynamic Island hardware"))
    if spec.requires_camera_control and not has_camera_control(model):
        reasons.append(tr("requires an iPhone with physical Camera Control"))
    if spec.requires_always_on and not has_always_on_display(model):
        reasons.append(tr("requires Always-On display hardware"))
    if spec.requires_home_button and not has_home_button(model):
        reasons.append(tr("requires a physical Home button"))
    if spec.requires_action_button and not has_action_button(model):
        reasons.append(tr("requires an iPhone with an Action Button"))
    return reasons


def compatibility_reasons(tweak_id, device_version: str, model: str = "",
                          is_iphone: bool | None = None, *, allow_untested=False, translate=None) -> list[str]:
    """Return precise reasons a tweak cannot run on the selected device."""
    spec = SPECS_BY_ID.get(tweak_id)
    if spec is None:
        return []

    reasons = []
    tr = translate or (lambda text: text)
    if spec.disabled:
        reasons.append(tr("this control is no longer supported"))
    if spec.unavailable_reason:
        reasons.append(tr(spec.unavailable_reason))
    if spec.supported_models and model not in spec.supported_models:
        reasons.append(tr("is only verified on these models: {0}").format(', '.join(spec.supported_models)))
    parsed_device = None
    if device_version:
        try:
            parsed_device = _parse_version(device_version)
        except ValueError:
            reasons.append(tr("the iOS version could not be verified"))

    ignore_version = allow_untested
    if parsed_device is not None and spec.min_version and not ignore_version:
        minimum = _parse_version(spec.min_version)
        if parsed_device < minimum:
            reasons.append(tr("requires iOS {0} or newer").format(spec.min_version))
    if parsed_device is not None and spec.max_version and not ignore_version:
        maximum = _parse_version(spec.max_version)
        if parsed_device > maximum:
            reasons.append(tr("supports iOS {0} or older").format(spec.max_version))

    reasons.extend(hardware_reasons(spec, model, is_iphone, translate=tr))
    return reasons
