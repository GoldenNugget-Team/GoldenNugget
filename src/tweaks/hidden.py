"""Resolve HotLoad-hidden features/tweaks for the current device.

Shared by the GUI (hiding sections, sidebar gating) and the preset loader
(never re-enable hidden features on load). Replicates the old GUI-internal
helpers: reads the current device from ``DataSingleton`` and evaluates the
local HotLoad rules with whatever settings object the running app exposes.
"""

from src.utils.i18n import QCoreApplication

from src.controllers.hotload import HotLoad
from src.devicemanagement.data_singleton import DataSingleton


def _hotload() -> HotLoad:
    try:
        app = QCoreApplication.instance()
        window = getattr(app, "main_window", None)
        settings = getattr(window, "settings", None) if window is not None else None
    except Exception:
        settings = None
    return HotLoad(settings)


def _current_device() -> tuple:
    current = DataSingleton().current_device
    version = current.version if current is not None else ""
    model = current.model if current is not None else ""
    return version, model


def current_hidden_feature_names() -> set:
    """Names of HotLoad-hidden features for the current setup, as a set."""
    version, model = _current_device()
    return _hotload().hidden_features(device_version=version,
                                      device_model=model)


def current_hidden_tweak_names() -> set:
    """Names of the tweaks that belong to HotLoad-hidden features for the
    current setup. Used by the preset loader to strip them during load."""
    version, model = _current_device()
    return _hotload().hidden_tweak_names(device_version=version,
                                         device_model=model)