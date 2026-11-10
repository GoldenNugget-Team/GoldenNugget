"""Offline coverage for the added opt-in preferences and daemon controls."""

import os
import plistlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.tweaks.additional_daemon_controls import ADDITIONAL_DAEMON_CONTROLS
from src.tweaks.daemons_tweak import ADDITIONAL_DAEMONS, INTERFACE_KEYS
from src.tweaks.registry import (
    ADDITIONAL_LOCAL_SPECS,
    ADDITIONAL_SPECS,
    SPECS,
    _existing_ids,
)
from src.tweaks.tweak_loader import _build_spec

NEW_SPECS = [spec for spec in SPECS if spec.id not in _existing_ids]


class AdditionalControlsTests(unittest.TestCase):
    def test_unique_registry_and_disabled_defaults(self):
        self.assertEqual(len(SPECS), len({spec.id for spec in SPECS}))
        self.assertEqual(len(NEW_SPECS), 90)
        for spec in NEW_SPECS:
            with self.subTest(tweak=spec.id.name):
                tweak = _build_spec(spec)
                self.assertFalse(tweak.enabled)
                self.assertEqual(tweak.apply_tweak({}), {})

    def test_new_preferences_build_valid_plists(self):
        from src.tweaks.candidate_preferences import InstalledAppSuggestionsBlacklist

        for spec in NEW_SPECS:
            with self.subTest(tweak=spec.id.name):
                tweak = _build_spec(spec)
                if spec.bundle_identifier:
                    tweak.set_value("com.example.app")
                else:
                    tweak.set_enabled(True)
                if isinstance(tweak, InstalledAppSuggestionsBlacklist):
                    tweak._bundle_ids = ["com.example.app", "com.apple.mobilephone"]
                payload = tweak.apply_tweak({})
                self.assertTrue(payload)
                for values in payload.values():
                    self.assertIsInstance(plistlib.loads(plistlib.dumps(values)), dict)

    def test_daemon_labels_are_unique_selectable_and_have_descriptions(self):
        labels = [label for daemon in ADDITIONAL_DAEMONS for label in daemon.value]
        self.assertEqual(len(ADDITIONAL_DAEMONS), 153)
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(set(labels) <= INTERFACE_KEYS)
        excluded = {"com.apple.sleepd", "com.apple.thermalmonitord", "com.apple.mobile.lockdown",
                    "com.apple.communicationtrustd", "com.apple.deviceconfigurationd",
                    "com.apple.devicerecoveryd", "com.apple.dt.remotepairingdeviced",
                    "com.apple.installcoordinationd", "com.apple.mobile.usermanagerd",
                    "com.apple.decisiond", "com.apple.siriactionsd", "com.apple.siriinferenced"}
        self.assertFalse(set(labels) & excluded)
        for daemon in ADDITIONAL_DAEMONS:
            title, description = ADDITIONAL_DAEMON_CONTROLS[daemon.name]
            self.assertTrue(title)
            self.assertTrue(description)

    def test_false_states_remain_false_when_staged(self):
        count = 0
        for spec in NEW_SPECS:
            tweak = _build_spec(spec)
            if not hasattr(tweak, "set_state"):
                continue
            with self.subTest(tweak=spec.id.name):
                tweak.set_state(False)
                self.assertFalse(tweak.state)
                self.assertTrue(tweak.enabled)
                self.assertTrue(tweak.apply_tweak({}))
                tweak.set_state(None)
                self.assertFalse(tweak.enabled)
                self.assertEqual(tweak.apply_tweak({}), {})
                count += 1
        self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
