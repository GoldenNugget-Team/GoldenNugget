"""Backend settings store (compatibility import path).

The implementation lives in :mod:`src.utils.settings` so the backend no longer
imports Qt. This module keeps the historical ``src.controllers.settings``
import path working for both the backend and the GUI.
"""

from src.utils.settings import LEGACY_ORG, NEW_ORG, Settings, reset_for_tests

__all__ = ["Settings", "NEW_ORG", "LEGACY_ORG", "reset_for_tests"]
