"""Device compatibility for tweaks (GUI re-export).

The evaluation itself is Qt-free and lives in :mod:`src.tweaks.compatibility`
(the backend needs it for risk assessment and apply gating); this module keeps
the historical import path working for the GUI pages and exposes the
translated variant the UI shows.
"""
from src.tweaks.compatibility import (  # noqa: F401 - re-exported API
    _parse_version,
    device_family,
    device_compatibility_reasons as compatibility_reasons,
    is_tweak_compatible,
    untested_tweaks_enabled,
)

__all__ = [
    "compatibility_reasons",
    "device_family",
    "is_tweak_compatible",
    "untested_tweaks_enabled",
]
