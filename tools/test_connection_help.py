"""Connection assistance stays inline and never pretends to detect Trust."""
import asyncio
import os
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pymobiledevice3.exceptions import ConnectionFailedError
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.ios.connect_placeholder import ConnectDevicePlaceholder
from src.gui.main_window_mixins import DeviceBarMixin
from src.gui.thread_workers.apply_worker import DeviceMonitorThread
from src.utils.alerts import ApplyAlertMessage


class ReconnectWindow(DeviceBarMixin):
    def __init__(self):
        self.device_manager = Mock(devices=[], current_device_index=0)
        self.device_manager.get_current_device_udid.return_value = 'target'
        self.ui = Mock()
        self.ui.devicePicker.count.return_value = 1
        self.ios_home = Mock()
        self.connect_placeholder = Mock()
        self._device_refresh_timer = Mock()
        self.refresh_in_progress = False
        self.apply_in_progress = False
        self._device_change_refresh_pending = False
        self._last_connection_error = ''
        self.noneText = 'None'
        self.show_home = Mock()
        self.toggle_thread_btns = Mock()
        self.change_selected_device = Mock()
        self._apply_hidden_feature_gating = Mock()
        self._update_device_gate = Mock()


class DeviceReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_expected_disconnect_is_retried_without_cable_warning(self):
        window = ReconnectWindow()
        error = ConnectionFailedError("got an error message: {'MessageType': 'Result', 'Number': 3}")
        with patch('src.gui.main_window_mixins.time.monotonic', return_value=100):
            window._expect_device_reboot()
            with self.assertLogs('GoldenNugget.refresh', level='DEBUG') as logs:
                window._connection_alert(ApplyAlertMessage('cable error', exc_value=error))
            self.assertTrue(all('WARNING' not in line for line in logs.output))
            self.assertEqual(window._last_connection_error, '')
            window._device_change_refresh_pending = False
            window.refresh_devices_finished()
            self.assertTrue(window._device_change_refresh_pending)
            window._device_refresh_timer.start.assert_called_with(2000)

    def test_reconnection_of_the_target_ends_the_grace_period(self):
        window = ReconnectWindow()
        with patch('src.gui.main_window_mixins.time.monotonic', return_value=100):
            window._expect_device_reboot()
            window.device_manager.devices = [SimpleNamespace(udid='target', name='iPhone', connected_via_usb=True)]
            window._device_change_refresh_pending = False
            window.refresh_devices_finished()
            self.assertFalse(window._device_reconnect_expected())
            window._device_refresh_timer.start.assert_not_called()

    def test_another_device_does_not_end_reconnection_of_the_target(self):
        window = ReconnectWindow()
        with patch('src.gui.main_window_mixins.time.monotonic', return_value=100):
            window._expect_device_reboot()
            window.device_manager.devices = [SimpleNamespace(udid='other', name='Other iPhone', connected_via_usb=True)]
            window.refresh_devices_finished()
            self.assertTrue(window._device_reconnect_expected())
            window._device_refresh_timer.start.assert_called_with(2000)

    def test_errors_after_grace_period_are_still_reported(self):
        window = ReconnectWindow()
        window._device_reconnect_until = 100
        with patch('src.gui.main_window_mixins.time.monotonic', return_value=101):
            with self.assertLogs('GoldenNugget.refresh', level='WARNING'):
                window._connection_alert(ApplyAlertMessage('persistent cable error',
                    exc_value=ConnectionFailedError('unreachable')))
        self.assertEqual(window._last_connection_error, 'persistent cable error')

    def test_unrelated_errors_during_grace_period_are_still_reported(self):
        window = ReconnectWindow()
        with patch('src.gui.main_window_mixins.time.monotonic', return_value=100):
            window._expect_device_reboot()
            with self.assertLogs('GoldenNugget.refresh', level='WARNING'):
                window._connection_alert(ApplyAlertMessage('invalid device data',
                    exc_value=ValueError('invalid model')))
        self.assertEqual(window._last_connection_error, 'invalid device data')

    def test_monitor_detects_new_usb_endpoint_for_the_same_serial(self):
        before = SimpleNamespace(serial='target', connection_type='USB', is_usb=True, devid=1)
        after = SimpleNamespace(serial='target', connection_type='USB', is_usb=True, devid=2)
        signature = DeviceMonitorThread._device_signature
        self.assertNotEqual(signature([before]), signature([after]))

    def test_scan_keeps_typed_mux_error_for_reboot_handling(self):
        from src.devicemanagement import device_manager
        from src.devicemanagement.device_manager import DeviceManager
        error = ConnectionFailedError("got an error message: {'MessageType': 'Result', 'Number': 3}")

        @asynccontextmanager
        async def connection(serial, **kwargs):
            raise error
            yield  # Keep the mock an async context manager.

        manager = DeviceManager()
        manager._test_mode = False
        alerts = []
        device = SimpleNamespace(serial='target', is_usb=True)
        with patch.object(device_manager.usbmux, 'list_devices', AsyncMock(return_value=[device])), \
             patch.object(device_manager, 'lockdown_session', connection):
            asyncio.run(manager._get_devices(Mock(), alerts.append))
        self.assertEqual(len(alerts), 1)
        self.assertIs(alerts[0].exc_value, error)


class ConnectionHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scan_status_and_help_are_inline(self):
        window = Mock()
        page = ConnectDevicePlaceholder(window)
        page._refresh_btn.click()
        window.refresh_devices.assert_called_once()
        page.set_scan_status('Checking devices', busy=True)
        self.assertFalse(page._refresh_btn.isEnabled())
        page.set_scan_status('Device locked', busy=False)
        self.assertTrue(page._refresh_btn.isEnabled())
        self.assertEqual(page._scan_status.text(), 'Device locked')
        page._diagnostics_btn.click()
        self.assertFalse(page._help_detail.isHidden())
        page._continue_btn.click()
        window.continue_without_device.assert_called_once()
        self.assertIsNone(self.app.activeModalWidget())
        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_restore_defaults_requires_a_section(self):
        manager = Mock()
        manager.get_current_device_version.return_value = '27.0'
        manager.get_current_device_model.return_value = 'iPhone17,3'
        dialog = ResetDialog(manager)
        button = dialog.buttonBox.button(QDialogButtonBox.Ok)
        self.assertFalse(button.isEnabled())
        from src.gui.pages.pages_list import Page
        dialog.toggle_page(True, Page.Springboard)
        self.assertTrue(button.isEnabled())
        dialog.toggle_page(False, Page.Springboard)
        self.assertFalse(button.isEnabled())
        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
