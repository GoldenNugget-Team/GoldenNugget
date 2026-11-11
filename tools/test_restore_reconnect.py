"""Offline reconnect regressions. Run: python -m unittest tools.test_restore_reconnect"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from pymobiledevice3.exceptions import DeviceNotFoundError, MuxException, NotPairedError

from src.restore import restore


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 0.0
        self.client = SimpleNamespace(paired=True)
        self.connect = AsyncMock()
        self.progress = Mock()

        async def sleep(delay):
            self.now += delay

        for target, replacement in (
            ("create_using_usbmux", self.connect),
            ("time", SimpleNamespace(monotonic=lambda: self.now)),
            ("asyncio", SimpleNamespace(sleep=AsyncMock(side_effect=sleep),
                                        TimeoutError=asyncio.TimeoutError)),
        ):
            patcher = patch.object(restore, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_broken_mux_socket_retries_until_paired(self):
        self.connect.side_effect = [MuxException("socket connection broken"),
                                    self.client]
        result = await restore._wait_for_device("device", self.progress)
        self.assertIs(result, self.client)
        self.assertEqual(self.connect.await_args_list, [
            call(serial="device", autopair=False),
            call(serial="device", autopair=False)])
        self.assertEqual(self.now, 1.0)

    async def test_transport_drop_during_repair_keeps_polling(self):
        repair_attempted = False

        async def connect(**kwargs):
            nonlocal repair_attempted
            if kwargs["autopair"]:
                repair_attempted = True
                raise MuxException("socket connection broken")
            if not repair_attempted:
                raise NotPairedError()
            return self.client

        self.connect.side_effect = connect
        result = await restore._wait_for_device("device", self.progress)
        self.assertIs(result, self.client)
        self.assertIn(call(serial="device", autopair=True),
                      self.connect.await_args_list)

    async def test_persistent_mux_failure_uses_existing_timeout(self):
        self.connect.side_effect = MuxException("socket connection broken")
        with self.assertRaises(DeviceNotFoundError):
            await restore._wait_for_device("device", self.progress, timeout=0)
        self.assertEqual(self.connect.await_count, 1)

    async def test_timeout_can_resume_after_mux_failure(self):
        self.connect.side_effect = [MuxException("socket connection broken"),
                                    self.client]
        prompt = Mock(return_value="resume")
        result = await restore._wait_for_device(
            "device", self.progress, timeout=0, prompt_choice=prompt)
        self.assertIs(result, self.client)
        prompt.assert_called_once()

    async def test_cancellation_is_not_retried(self):
        self.connect.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await restore._wait_for_device("device", self.progress)
        self.assertEqual(self.connect.await_count, 1)

    async def test_unexpected_error_is_not_retried(self):
        self.connect.side_effect = ValueError("unexpected")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            await restore._wait_for_device("device", self.progress)
        self.assertEqual(self.connect.await_count, 1)


if __name__ == "__main__":
    unittest.main()
