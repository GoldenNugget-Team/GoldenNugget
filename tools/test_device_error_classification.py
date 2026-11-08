"""Backup errors must not be mistaken for a locked device."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymobiledevice3.exceptions import PasswordRequiredError

from src.exceptions.device_errors import is_device_locked_error


class DeviceErrors(unittest.TestCase):
    def test_explicit_lock_errors_are_recognized(self):
        for error in (RuntimeError("Device locked"), RuntimeError("The device is locked"),
                      RuntimeError("MBErrorDomain/208"), PasswordRequiredError(),
                      RuntimeError("{'ErrorCode': 208, 'ErrorDescription': 'Locked'}"),
                      RuntimeError("ErrorCode 208")):
            with self.subTest(error=error):
                self.assertTrue(is_device_locked_error(error))

    def test_other_backup_errors_keep_their_original_meaning(self):
        for message in ("{'ErrorCode': 205, 'ErrorDomain': 'MBErrorDomain'}",
                        "ErrorCode 105: MBErrorDomain: disk full",
                        "ErrorCode 1208", "ErrorCode 2080",
                        "ErrorCode 205: missing payload in backup 208"):
            with self.subTest(message=message):
                self.assertFalse(is_device_locked_error(RuntimeError(message)))


if __name__ == "__main__":
    unittest.main()
