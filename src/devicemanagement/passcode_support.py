"""Passcode Themes on iOS 26 and 27; 27.2 builds distinguish betas."""
import re

from src.utils.i18n import QCoreApplication

_IOS_27_2_SUPPORTED_BUILDS = frozenset({"24B5084k", "24B5089g", "24B5099f"})


def passcode_theme_unavailable_reason(version, build, model):
    tr = lambda text: QCoreApplication.translate("Nugget", text)
    if not version or not model:
        return tr("Connect an iPhone to check version support.")
    if not str(model).startswith("iPhone"):
        return tr("Passcode themes require an iPhone.")
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", str(version).strip())
    if match is None:
        return tr("Your iOS version could not be verified.")
    parsed = tuple(int(part or 0) for part in match.groups())
    if (26, 0, 0) <= parsed < (27, 2, 0):
        return None
    if parsed == (27, 2, 0) and str(build).strip() in _IOS_27_2_SUPPORTED_BUILDS:
        return None
    if parsed == (27, 2, 0) and not build:
        return tr("Your iOS 27.2 beta build could not be verified.")
    return tr("Your version is not supported. Requires iOS 26.0 through 27.2 beta 3 (24B5099f).")


def current_passcode_theme_reason(manager):
    values = [getattr(manager, name, lambda: "")() for name in (
        "get_current_device_version", "get_current_device_build", "get_current_device_model")]
    return passcode_theme_unavailable_reason(*values)
