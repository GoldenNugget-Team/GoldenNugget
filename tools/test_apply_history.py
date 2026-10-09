"""Offline regression for bounded, atomic operation history."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.controllers import apply_history


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "operations.json"
        self.patch = patch.object(apply_history, "_path", lambda: str(self.path))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.manager = SimpleNamespace(
            get_current_device_name=lambda: "Test iPhone",
            get_current_device_model=lambda: "iPhone16,1",
            get_current_device_version=lambda: "27.0",
            get_current_device_udid=lambda: "test-udid",
        )

    def test_records_newest_first_in_ui_order_and_caps(self):
        for index in range(35):
            apply_history.record_operation(self.manager, "apply", index % 2 == 0,
                                            "failure" if index % 2 else "")
        records = apply_history.load_history()
        self.assertEqual(len(records), apply_history.MAX_ENTRIES)
        self.assertEqual(records[-1]["success"], True)
        self.assertEqual(records[-1]["device"], "Test iPhone")
        self.assertEqual(records[-1]["ios"], "27.0")
        json.loads(self.path.read_text(encoding="utf-8"))

    def test_corrupt_history_is_ignored_and_clear_is_safe(self):
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(apply_history.load_history(), [])
        apply_history.clear_history()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
