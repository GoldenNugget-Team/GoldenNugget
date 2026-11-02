"""Throwaway settings store for offline UI tests.

The theme/interaction suites need a real ``Settings`` store (accent colours are
persisted through it) that:

* behaves like the shipped store, so a test exercises the same code path;
* keeps every value inside a temporary folder — the machine's own preferences
  are never read or written;
* never reads the legacy ``QSettings`` data of the person running the tests
  (a developer's accent colour must not leak into a test).

Usage::

    with SettingsSandbox(Path(tmpdir)) as make_settings:
        settings = make_settings("settings")
        ...
"""

from __future__ import annotations

import os
from unittest.mock import patch

from src.utils import settings as settings_module


class SettingsSandbox:
    """Redirect ``src.utils.settings`` at *directory* for the duration."""

    def __init__(self, directory):
        self.directory = directory
        self._patches = []

    def __enter__(self):
        env = patch.dict(os.environ,
                         {"GOLDENNUGGET_PREFERENCES_DIR": str(self.directory)})
        env.start()
        self._patches.append(env)
        # Read-through to the legacy plist/INI/registry would make a test
        # depend on the machine it runs on.
        legacy = patch.object(settings_module, "_legacy_native",
                              lambda org, app: {})
        legacy.start()
        self._patches.append(legacy)
        # Stores cache the folder they were created with.
        settings_module.reset_for_tests()
        return settings_module.Settings

    def __exit__(self, *exc_info):
        for started in reversed(self._patches):
            started.stop()
        self._patches.clear()
        settings_module.reset_for_tests()
        return False
