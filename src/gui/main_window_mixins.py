"""Mixins for :class:`MainWindow`, breaking the monolithic GUI shell into
focused pieces: device-bar handling, settings/presets/theme, navigation and
the apply/reset flow. Each mixin only reaches ``self`` attributes that
``MainWindow.__init__`` installs, so they stay plain objects mixed into
``class MainWindow(QtWidgets.QMainWindow, DeviceBarMixin, SettingsMixin,
NavigationMixin, ApplyMixin)``.
"""

from typing import Optional
import os
import time

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QCoreApplication

from src.controllers.video_handler import set_ignore_frame_limit
from src.devicemanagement.constants import Version
from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.logger import get_logger
from src.gui.autosave import AutosaveMixin
from src.devicemanagement.device_capabilities import device_text, device_os_name
from src.gui.theme import ColorThemeManager, theme_icon
from src.gui.thread_workers.apply_worker import (
    ApplyAlertMessage,
    ApplyThread,
    RefreshDevicesThread,
    get_sudo_pwd,
    set_sudo_pwd,
)
from src.gui.version import App_Build, App_Version
from src.gui.ios.theme_manager import ThemeManager
from src.gui.ios.tweaks import _hidden_feature_names
from src.gui.pages.pages_list import Page
from src.tweaks.tweak_classes import set_tweak_change_callback
from src.tweaks.tweaks import tweaks, TweakID


class DeviceBarMixin:
    """Device refresh, selection and per-device interface updates."""

    def _expect_device_reboot(self):
        self._reconnecting_udid = self.device_manager.get_current_device_udid()
        self._device_reconnect_until = time.monotonic() + 90
        self._device_change_refresh_pending = True

    def _device_reconnect_expected(self):
        return time.monotonic() < getattr(self, "_device_reconnect_until", 0)

    def continue_without_device(self):
        """Allow browsing for this session, without creating a mock device."""
        self._browse_without_device = True
        self.content_stack.setCurrentIndex(1)
        self.set_ios_page(0, animate=False)
        self._update_shared_nav(0)
        self._refresh_preset_widgets()
        self._update_device_gate()

    def _update_device_gate(self):
        """Show the connect-device placeholder while no iPhone is available.

        The placeholder lives on its own in ``content_stack`` (index 3), so it
        replaces the whole iOS shell — no nav bar, no feature cards — until a
        supported device shows up. It auto-dismisses back to the iOS home.

        Only routed to once the first device scan has finished
        (``device_scan_completed``): the scan runs on a worker thread and the
        device list is empty until it returns, so gating on that list right away
        flashed the "No device connected" screen for the whole scan even when a
        supported phone was already connected.
        """
        placeholder = getattr(self, "connect_placeholder", None)
        stack = getattr(self, "content_stack", None)
        if placeholder is None or stack is None:
            return
        if hasattr(self, "ios_apply"):
            self.ios_apply.set_busy(self.apply_in_progress or getattr(self, '_cache_restore_in_progress', False))
        no_device = (len(self.device_manager.devices) == 0
                     and not getattr(self, "_browse_without_device", False))
        keep_operation_visible = (self.apply_in_progress or getattr(self, '_cache_restore_in_progress', False)
                                  or getattr(self, "_operation_result_visible", False))
        if no_device and not keep_operation_visible and getattr(self, "device_scan_completed", False):
            if stack.currentWidget() is not placeholder:
                self._device_gate_return_page = self.ios_pages.currentIndex()
            stack.setCurrentWidget(placeholder)
        elif stack.currentWidget() is placeholder:
            stack.setCurrentIndex(1)
            page = getattr(self, '_device_gate_return_page', 0)
            self.set_ios_page(page, animate=False)
            self._update_shared_nav(page)

    def updateInterfaceForNewDevice(self):
        # update the home page
        self.pages[Page.Home].updatePhoneInfo()

        device = self.device_manager.data_singleton.current_device
        if device is None:
            return
        signature = (getattr(device, "udid", None), getattr(device, "model", None), getattr(device, "version", None),
                     getattr(device, "build", None))
        if signature == getattr(self, "_section_device_signature", None):
            return
        self._section_device_signature = signature
        posterboard=getattr(self,'ios_posterboard',None)
        preferences=getattr(posterboard,'preferences_page',None)
        if preferences is not None and preferences.content._inner is not None:
            preferences.rebuild()
        for page in ("ios_tweaks", "ios_springboard", "ios_internal", "ios_liquidglass"):
            section_page = getattr(self, page, None)
            if section_page is not None:
                section_page._device_rebuild_pending = True
                if page == 'ios_tweaks' or self.ios_pages.currentWidget() is section_page:
                    section_page.rebuild()
                    section_page._device_rebuild_pending = False


    def _apply_hidden_feature_gating(self):
        """Hide the Sidebar buttons and iOS home cards for HotLoad-hidden
        features on this device. Kept central so the gating survives every
        re-apply point (device refresh / selection).

        Only ever HIDES — it never re-shows a button that HotLoad hid. The
        Status Bar page used to be force-hidden on iOS 27 because the Speakeasy
        feature flag could not be written; it now delivers the carrier name
        through StatusBarOverrides.archive, so the page stays reachable there
        (trimmed down to the carrier rows by the page itself).
        """
        hidden = _hidden_feature_names()
        if hidden:
            print(f"[HotLoad] Hiding feature pages: {', '.join(sorted(hidden))}")
        statusbar_hidden = "Status Bar" in hidden
        # Sidebar (classic shell) buttons
        btn_map = {
            "Liquid Glass": self.ui.liquidGlassPageBtn,
            "Springboard": self.ui.springboardOptionsPageBtn,
            "Internal": self.ui.internalOptionsPageBtn,
            "PosterBoard": self.ui.posterboardPageBtn,
            "Templates": self.ui.templatesPageBtn,
            "Daemons": self.ui.daemonsPageBtn,
        }
        for feat, btn in btn_map.items():
            btn.setVisible(feat not in hidden)
        self.ui.statusBarPageBtn.setVisible(not statusbar_hidden)
        # iOS home cards
        card_map = {
            "PosterBoard": self.ios_home.posterboard_card,
            "Daemons": self.ios_home.daemons_card,
        }
        for feat, card in card_map.items():
            card.setVisible(feat not in hidden)
        dock=getattr(self,'bottom_navigation',None)
        if dock is not None and hasattr(dock,'set_hidden_features'):
            dock.set_hidden_features(hidden)
        self.ios_home.set_statusbar_visible(not statusbar_hidden)
        self.ios_home.update_passcode_support()
        from src.devicemanagement.passcode_support import current_passcode_theme_reason
        reason = current_passcode_theme_reason(self.device_manager)
        self.ui.passcodePageBtn.setEnabled(not reason)
        self.ui.passcodePageBtn.setToolTip(reason or "")
        if reason and self.ios_pages.currentIndex() == 11:
            self.show_ios_page(0)


    def _maybe_show_mobile_promo(self):
        """One-shot "did you know" pop-up when a phone connects.

        GoldenNugget Mobile runs on the iPhone itself, so a freshly connected
        phone is exactly the moment to mention it. Shown once per session, and
        never again after the user picked "Don't show me this again"
        (``mobile_helper/promo_dismissed``). Kept out of the way while an apply
        or restore runs — those re-connect the phone on their own.
        """
        connected_now = bool(self.device_manager.devices)
        try:
            prev = self._mobile_promo_prev_connected
        except AttributeError:
            prev = None
        self._mobile_promo_prev_connected = connected_now
        # Dev/test hook: GOLDENNUGGET_SHOW_MOBILE_PROMO=1 reveals the pop-up on
        # the FIRST device scan (no unplug/replug dance, no session/persisted
        # dismissal) without altering the production trigger logic.
        debug_force = os.environ.get("GOLDENNUGGET_SHOW_MOBILE_PROMO") == "1"
        if debug_force:
            if getattr(self, "_mobile_promo_shown", False):
                return
        elif not connected_now or prev is not False:
            return
        if getattr(self, "_mobile_promo_shown", False):
            return
        if self.settings.value("mobile_helper/promo_dismissed", False, type=bool):
            return
        if (self.apply_in_progress or getattr(self, "_cache_restore_in_progress", False)):
            if not debug_force:
                return

        from src.gui.dialogs.mobile_helper_dialog import MobileHelperDialog

        def _show():
            self._mobile_promo_shown = True
            dialog = QtWidgets.QMessageBox(self)
            dialog.setWindowTitle(QCoreApplication.translate("Nugget", "GoldenNugget Mobile"))
            dialog.setIcon(QtWidgets.QMessageBox.Information)
            dialog.setText(QCoreApplication.translate(
                "Nugget",
                "Did you know that GoldenNugget has a mobile version?\n\n"
                "You can use it right on your iPhone without even touching "
                "the PC."))
            install_btn = dialog.addButton(
                QCoreApplication.translate("Nugget", "Install"),
                QtWidgets.QMessageBox.AcceptRole)
            dialog.addButton(
                QCoreApplication.translate("Nugget", "Later"),
                QtWidgets.QMessageBox.RejectRole)
            never_btn = dialog.addButton(
                QCoreApplication.translate("Nugget", "Don't show me this again"),
                QtWidgets.QMessageBox.ActionRole)
            dialog.setDefaultButton(install_btn)
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked is never_btn:
                self.settings.setValue("mobile_helper/promo_dismissed", True)
                self.settings.sync()
                return
            if clicked is install_btn:
                helper = MobileHelperDialog(self)
                helper.exec()

        # Let the shell finish re-drawing around the new device first; the
        # pop-up should feel like a nudge, not a race with the device pages.
        QtCore.QTimer.singleShot(800, _show)

    @QtCore.Slot()
    def refresh_devices(self):
        if not self.refresh_in_progress:
            self.refresh_in_progress = True
            self._scan_usb_generation = getattr(self, "_usb_event_generation", 0)
            self._refresh_previous_device_udid = self.device_manager.get_current_device_udid()
            self._last_connection_error = ""
            self._connection_action = None
            self.connect_placeholder.set_scan_status(
                QCoreApplication.translate("Nugget", "Checking connected devices…"), busy=True)
            self.ui.refreshBtn.setDisabled(True)
            self.refresh_worker_thread = RefreshDevicesThread(manager=self.device_manager, settings=self.settings)
            self.refresh_worker_thread.alert.connect(self._connection_alert)
            self.refresh_worker_thread.finished.connect(self.refresh_devices_finished)
            self.refresh_worker_thread.finished.connect(self.refresh_worker_thread.deleteLater)
            self.refresh_worker_thread.start()


    @QtCore.Slot(object)
    def _on_usb_devices_changed(self, udids):
        from src.devicemanagement.constants import normalize_udid
        self._usb_event_generation = getattr(self, "_usb_event_generation", 0) + 1
        self._usb_monitor_ready = True
        self._connected_usb_udids = frozenset(udids)
        connected = {normalize_udid(udid) for udid in udids}
        self._device_change_refresh_pending = True
        if self.apply_in_progress or getattr(self, "_cache_restore_in_progress", False):
            return
        current = self.device_manager.get_current_device_udid()
        if current and normalize_udid(current) not in connected:
            self.device_manager.set_current_device(index=None)
            self._posterboard_selection_generation = getattr(self, "_posterboard_selection_generation", 0) + 1
            self._posterboard_selection_udid = None
            self._posterboard_selection_pending = False
            self._posterboard_waiting = {}
            self._posterboard_selection_error = ""
            self._storage_info = None
            self._battery_info = None
        if not self.device_manager.get_current_device_udid():
            for index, device in enumerate(self.device_manager.devices):
                if normalize_udid(device.udid) in connected:
                    self.change_selected_device(index)
                    break
        self._device_change_refresh_pending = True
        self._schedule_device_event_refresh()
        if hasattr(self, "ios_home"):
            self.ios_home.populate_device_picker()
            self.ios_home.update_device_info()
            self.ios_home.update_status()

    @QtCore.Slot()
    def _on_device_connection_changed(self):
        self._device_change_refresh_pending = True
        self._schedule_device_event_refresh()


    def _schedule_device_event_refresh(self):
        if not self._device_change_refresh_pending:
            return
        if (self.refresh_in_progress or self.apply_in_progress
                or getattr(self, "_cache_restore_in_progress", False)):
            return
        retrying = self._device_reconnect_expected() or getattr(self, "_device_discovery_retry_pending", False)
        self._device_refresh_timer.start(2000 if retrying else 450)


    @QtCore.Slot()
    def _refresh_after_device_event(self):
        if (self.refresh_in_progress or self.apply_in_progress
                or getattr(self, "_cache_restore_in_progress", False)):
            return
        if self._device_change_refresh_pending:
            self._device_change_refresh_pending = False
            self.refresh_devices()


    def _connection_alert(self, alert):
        if alert is None:
            return
        import logging
        from src.exceptions.device_errors import is_connection_error
        if self._device_reconnect_expected() and is_connection_error(alert.exc_value):
            logging.getLogger('GoldenNugget.refresh').debug(
                'Device is reconnecting after reboot: %s', alert.exc_value)
            self._device_change_refresh_pending = True
            self.connect_placeholder.set_scan_status(
                QCoreApplication.translate("Nugget", "Waiting for device after reboot…"), busy=True)
            return
        self._device_reconnect_until = 0
        self._last_connection_error = alert.txt
        from pymobiledevice3.exceptions import PasswordRequiredError, PairingDialogResponsePendingError, UserDeniedPairingError
        error = getattr(alert, "exc_value", None)
        if isinstance(error, PasswordRequiredError):
            self._connection_action = "unlock"
        elif isinstance(error, PairingDialogResponsePendingError):
            self._connection_action = "trust"
        elif isinstance(error, UserDeniedPairingError):
            self._connection_action = "denied"
        if getattr(self, "_connection_action", None):
            self.connect_placeholder.set_connection_action(self._connection_action)
            self.ios_home.connection_notice.setText(alert.txt)
            self.ios_home.connection_notice.show()
        logging.getLogger('GoldenNugget.refresh').warning('%s\n%s', alert.txt, alert.detailed_txt or '')
        self.connect_placeholder.set_scan_status(alert.txt, busy=True)

    def _retry_pending_connection(self):
        if getattr(self, "_connection_action", None) not in {"unlock", "trust"}:
            return
        self._device_change_refresh_pending = True
        self._schedule_device_event_refresh()

    def warn_for_dev_beta(self):
        if (getattr(self, "_dev_beta_warning_shown", False)
                or self.settings.value("hide_dev_beta_warning", False, type=bool)):
            return
        ver = self.device_manager.get_current_device_version()
        if ver == "":
            return
        if Version(ver) > Version("26.0") and not self.device_manager.get_current_device_build()[-1].isdigit():
            self._dev_beta_warning_shown = True
            # Keep the same standard warning dialog shape used previously by
            # alert_message; only the optional persistent checkbox is new.
            dialog = QtWidgets.QMessageBox()
            dialog.setIcon(QtWidgets.QMessageBox.Warning)
            dialog.setWindowTitle(self.tr("Warning"))
            dialog.setText(device_text(self.tr(
                "Warning: You are on iOS 26 beta.\n\n"
                "This has been known to cause problems and potentially lead to bootloops.\n\n"
                "Use at your own risk!"), self.device_manager.get_current_device_model()))
            dialog.setCheckBox(QtWidgets.QCheckBox(self.tr("Don't show this warning again"), dialog))
            dialog.exec()
            if dialog.checkBox().isChecked():
                self.settings.setValue("hide_dev_beta_warning", True)
                self.settings.sync()


    def refresh_devices_finished(self):
        self.refresh_in_progress = False
        if not getattr(self, "_usb_monitor_ready", False):
            self._connected_usb_udids = frozenset(device.udid for device in self.device_manager.devices
                                                 if device.connected_via_usb)
        from src.devicemanagement.constants import normalize_udid
        connected = {normalize_udid(udid) for udid in getattr(self, "_connected_usb_udids", ())}
        discovered = {normalize_udid(device.udid) for device in self.device_manager.devices
                      if device.connected_via_usb}
        self._device_discovery_retry_pending = bool(connected - discovered)
        if self._device_discovery_retry_pending:
            self._device_change_refresh_pending = True
        # From now on the device list is authoritative, so the connect
        # placeholder (when there is no device) may be shown.
        self.device_scan_completed = True
        action = getattr(self, "_connection_action", None)
        self.connect_placeholder.set_connection_action(action)
        self.ios_home.connection_notice.setVisible(bool(action))
        if action in {"unlock", "trust"}:
            QtCore.QTimer.singleShot(3000, self._retry_pending_connection)
        self.connect_placeholder.set_scan_status(
            QCoreApplication.translate("Nugget", "Device found.") if self.device_manager.devices else
            getattr(self, '_last_connection_error', '') or QCoreApplication.translate(
                "Nugget", "No device found. Check the cable, unlock the device and confirm Trust on its screen."), busy=False)
        # The thread's own ``finished -> deleteLater`` already freed the C++
        # object; drop our reference so closeEvent never probes a dead wrapper.
        try:
            self.refresh_worker_thread = None
        except Exception:
            pass
        self.toggle_thread_btns(disabled=False)
        # Rebuild without exposing transient -1/0 index changes to the device
        # selection handler while the new list is being populated.
        self.ui.devicePicker.blockSignals(True)
        self.ui.devicePicker.clear()

        if len(self.device_manager.devices) == 0:
            self.ui.devicePicker.setEnabled(False)
            self.ui.devicePicker.addItem(self.noneText)

            # hide all pages
            self.ui.sidebarDiv1.hide()

            self.ui.gestaltPageBtn.hide()
            self.ui.statusBarPageBtn.hide()
            self.ui.springboardOptionsPageBtn.hide()
            self.ui.internalOptionsPageBtn.hide()
            self.ui.liquidGlassPageBtn.hide()
            self.ui.daemonsPageBtn.hide()
            self.ui.iconThemesPageBtn.hide()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.hide()

            self.ui.sidebarDiv2.hide()
            self.ui.applyPageBtn.hide()
            self.ui.jjtechBtn.hide()
            self.ui.duyBtn.show()

            # mirror in the iOS UI: no device → no status bar card
            if hasattr(self, "ios_home"):
                self.ios_home.set_statusbar_visible(False)
        else:
            self.ui.devicePicker.setEnabled(True)
            # populate the ComboBox with device names
            for device in self.device_manager.devices:
                if not device.connected_via_usb:
                    continue
                icon = theme_icon(":/icon/phone.svg", ColorThemeManager.instance().colors.text_primary)
                self.ui.devicePicker.addItem(icon, device.name)
                self.ui.devicePicker.setItemData(
                    self.ui.devicePicker.count() - 1,
                    QCoreApplication.translate("Nugget", "Connected over USB"),
                    QtCore.Qt.ItemDataRole.ToolTipRole,
                )

            # show all pages
            self.ui.sidebarDiv1.show()
            self.ui.statusBarPageBtn.show()
            self.ui.springboardOptionsPageBtn.show()
            self.ui.internalOptionsPageBtn.show()
            self.ui.liquidGlassPageBtn.show()
            self.ui.daemonsPageBtn.show()
            self.ui.iconThemesPageBtn.show()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.show()

            self.ui.sidebarDiv2.show()
            self.ui.applyPageBtn.show()

            # HotLoad-hidden features are carved out of the Sidebar and iOS home
            self._apply_hidden_feature_gating()
        
        # Keep the same phone selected when it remains connected; otherwise
        # DeviceManager selects the first newly discovered phone (or none).
        preferred = getattr(self, "_preferred_device_udid", None)
        selected_index = next((index for index, device in enumerate(self.device_manager.devices)
                               if device.udid == preferred),
                              self.device_manager.current_device_index if self.device_manager.devices else 0)
        if self.device_manager.devices:
            self.device_manager.set_current_device(selected_index)
            self._preferred_device_udid = self.device_manager.get_current_device_udid()
        self.ui.devicePicker.setCurrentIndex(selected_index)
        self.ui.devicePicker.blockSignals(False)
        if self.device_manager.devices:
            selected_udid = self.device_manager.get_current_device_udid()
            self.change_selected_device(
                selected_index,
                warn_for_beta=selected_udid != getattr(self, "_refresh_previous_device_udid", None),
            )
        # HotLoad-hidden features are carved out of the Sidebar and iOS home
        self._apply_hidden_feature_gating()
        # keep the iOS home in sync
        self.ios_home.refresh_device_combo()
        self.ios_home.update_device_info()
        self.ios_home.update_status()
        # no device -> gate the whole iOS shell behind the connect placeholder
        self._update_device_gate()
        self._maybe_show_mobile_promo()
        if self._device_reconnect_expected():
            target = getattr(self, '_reconnecting_udid', None)
            if any(device.udid == target for device in self.device_manager.devices):
                self._device_reconnect_until = 0
            else:
                # A USB endpoint can exist before lockdownd is ready. Keep
                # scanning even when no further USB attach event arrives.
                self._device_change_refresh_pending = True
        self._schedule_device_event_refresh()


    def change_selected_device(self, index, warn_for_beta=True):
        if len(self.device_manager.devices) > 0 and 0 <= index < len(self.device_manager.devices):
            self.device_manager.set_current_device(index=index)
            # hide sidebar buttons that are for newer versions
            MinTweakVersions = {
                "no_patch": [self.ui.gestaltPageBtn],
                "26.0": [self.ui.liquidGlassPageBtn],
            }

            device_ver = Version(self.device_manager.data_singleton.current_device.version)
            # toggle option visibility for the minimum versions
            for version, views in MinTweakVersions.items():
                if version == "no_patch":
                    # these items only apply to unpatched devices, which do not exist on this fork
                    for view in views:
                        view.hide()
                else:
                    # show views if the version is higher
                    parsed_ver = Version(version)
                    for view in views:
                        view.setVisible(device_ver >= parsed_ver)
            # The Status Bar page is no longer force-hidden on iOS 27 -- the
            # carrier name is delivered through StatusBarOverrides.archive.
            # Visibility is owned by _apply_hidden_feature_gating() (HotLoad
            # aware), so just re-apply it here. The Solarium fallback tweak is
            # a different, iOS 26-only tweak and keeps its own gating.
            if device_ver >= Version("27.0"):
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(False)
            else:
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(True)
            self._apply_hidden_feature_gating()

            # force video looping on iPads (loop gated off the classic widgets)
            is_iphone = self.device_manager.get_current_device_model().startswith("iPhone")
            if not is_iphone:
                # force looping
                tweaks[TweakID.PosterBoard].loop_video = True

            # sparse-restore book credits do not apply to this fork
            self.ui.jjtechBtn.hide()
            # swap out the current posterboard file
            self._load_selected_posterboard(self.device_manager.get_current_device_udid())

            # show the PB if initial load is true
            if self.initial_load:
                self.initial_load = False
                if len(tweaks[TweakID.PosterBoard].tendies) > 0:
                    self.show_ios_page(2)
                elif len(tweaks[TweakID.Templates].templates) > 0:
                    self.show_ios_page(14)
                self._sync_sidebar_selection()
        else:
            self.device_manager.set_current_device(index=None)

        # update the interface
        self.updateInterfaceForNewDevice()
        self.ios_home.update_device_info()
        self.ios_home.update_status()
        if warn_for_beta and index > -1:
            self.warn_for_dev_beta()



    def _load_selected_posterboard(self, udid):
        if (getattr(self, "_posterboard_selection_udid", None) == udid
                and not getattr(self, "_posterboard_selection_error", "")):
            return
        self._posterboard_selection_generation = getattr(self, "_posterboard_selection_generation", 0) + 1
        self._device_selection_closing = False
        self._posterboard_selection_udid = udid
        self._posterboard_selection_pending = True
        self._posterboard_selection_error = ""
        self._posterboard_waiting = {}
        manager = tweaks[TweakID.PosterBoard].config_manager
        manager.database = None
        manager.staged_database = None
        manager.saved_items = []
        if not hasattr(self, "_posterboard_selection_workers"):
            self._posterboard_selection_workers = {}
        if udid in self._posterboard_selection_workers:
            return
        from src.gui.thread_workers.posterboard_selection import PosterBoardSelectionWorker
        worker = PosterBoardSelectionWorker(udid, self)
        self._posterboard_selection_workers[udid] = worker
        worker.ready.connect(self._posterboard_selection_ready)
        worker.finished.connect(self._posterboard_selection_finished)
        worker.start()

    def _posterboard_selection_ready(self, udid, snapshot, error):
        if (udid != self.device_manager.get_current_device_udid()
                or udid != getattr(self, "_posterboard_selection_udid", None)):
            return
        self._posterboard_selection_pending = False
        self._posterboard_selection_error = error
        if snapshot is not None:
            manager = tweaks[TweakID.PosterBoard].config_manager
            manager.database, manager.saved_items = snapshot
        if hasattr(self, "ios_settings"):
            self.ios_settings._refresh_saved_ids()
        callbacks = list(getattr(self, "_posterboard_waiting", {}).values())
        self._posterboard_waiting = {}
        generation = self._posterboard_selection_generation
        if callbacks and not self.apply_in_progress:
            self.ios_home.hide_process_status()
        for callback in callbacks:
            QtCore.QTimer.singleShot(0, lambda action=callback, expected=udid, revision=generation:
                action() if (self.device_manager.get_current_device_udid() == expected
                             and self._posterboard_selection_generation == revision
                             and not getattr(self, "_device_selection_closing", False)) else None)

    def _posterboard_selection_finished(self):
        worker = self.sender()
        if self._posterboard_selection_workers.get(worker.udid) is worker:
            del self._posterboard_selection_workers[worker.udid]
        worker.deleteLater()
        if (worker.udid == self.device_manager.get_current_device_udid()
                and getattr(self, "_posterboard_selection_pending", False)):
            self._posterboard_selection_udid = None
            self._load_selected_posterboard(worker.udid)

    def _defer_until_posterboard_ready(self, key, callback):
        if (not getattr(self, "_posterboard_selection_pending", False)
                or self.device_manager.get_current_device_udid() != getattr(self, "_posterboard_selection_udid", None)):
            return False
        self._posterboard_waiting[key] = callback
        self.ios_home.show_process_status(self.tr("Reading saved device configuration…"))
        return True


class SettingsMixin(AutosaveMixin):
    """Settings/preset loading, theme switching and app-version label."""

    def loadSettings(self):
        try:
            # load the settings
            auto_reboot = self.settings.value("auto_reboot", True, type=bool)
            ignore_frame_limit = self.settings.value("ignore_pb_frame_limit", False, type=bool)
            disable_tendies_limit = self.settings.value("disable_tendies_limit", False, type=bool)
            auto_refresh_posterboard = self.settings.value("auto_refresh_posterboard", True, type=bool)
            use_backup_cache = self.settings.value("use_backup_cache", True, type=bool)

            skip_setup = self.settings.value("skip_setup", True, type=bool)
            supervised = self.settings.value("supervised", False, type=bool)
            organization_name = self.settings.value("organization_name", "", type=str)
            use_encrypted_backup = self.settings.value("use_encrypted_backup", False, type=bool)
            use_afc_media = self.settings.value("use_afc_media", True, type=bool)
            tweak_autosave = self.settings.value("tweak_autosave", True, type=bool)

            self.device_manager.pref_manager.auto_reboot = auto_reboot
            set_ignore_frame_limit(ignore_frame_limit)
            self.device_manager.pref_manager.disable_tendies_limit = disable_tendies_limit
            self.device_manager.pref_manager.auto_refresh_posterboard = auto_refresh_posterboard
            self.device_manager.pref_manager.use_backup_cache = use_backup_cache
            self.device_manager.pref_manager.use_encrypted_backup = use_encrypted_backup
            self.device_manager.pref_manager.use_afc_media = use_afc_media
            self.device_manager.pref_manager.skip_setup = skip_setup
            self.device_manager.pref_manager.supervised = supervised
            self.device_manager.pref_manager.organization_name = organization_name
            self.device_manager.pref_manager.tweak_autosave = tweak_autosave
        except Exception as e:
            # Never silent: a NameError here used to abort every assignment
            # below it, so the app quietly booted with default preferences
            # (and the Settings switches read back OFF after a restart).
            get_logger("gui").warning("loadSettings failed: %s", e, exc_info=True)


    def autosave_enabled(self) -> bool:
        """Whether the AutoSave preset is written/loaded at all.

        Read through instead of cached on the window so flipping the Settings
        switch takes effect immediately, with no restart.
        """
        try:
            return bool(self.device_manager.pref_manager.tweak_autosave)
        except Exception:
            # never let a missing pref break tweak handling: autosave is the
            # historical default, so fall back to it
            return True


    def _load_last_preset(self):
        """Load the latest autosaved preset on startup.

        Prefers the AutoSave preset (written on every tweak change) so the UI
        restores the most recent configuration. Falls back to the last
        manually-loaded preset when no autosave exists.

        With autosave turned off the AutoSave preset is NOT loaded: the file is
        deliberately left on disk (it can still be loaded by hand), but
        restoring a frozen snapshot on every launch would be misleading when
        the app no longer keeps it up to date.
        """
        if self.autosave_enabled() and "AutoSave" in self.preset_manager.list_presets():
            if not self.preset_manager.load_preset("AutoSave"):
                get_logger().error("Could not restore AutoSave: %s", self.preset_manager.last_transfer_error)
            return
        last_preset = self.settings.value("last_loaded_preset", "", type=str)
        if last_preset:
            self.preset_manager.load_preset(last_preset)




    def sidebar_enabled(self) -> bool:
        return self.settings.value("ui/show_sidebar", False, type=bool)

    def set_sidebar_enabled(self, enabled: bool):
        self.settings.setValue("ui/show_sidebar", bool(enabled))
        self._sync_settings()
        show_sidebar = self.theme_manager.current_theme == ThemeManager.CLASSIC or bool(enabled)
        self.ui.sidebar.setVisible(show_sidebar)
        self.bottom_navigation.setVisible(not show_sidebar)
        self.bottom_navigation.popup.hide()
        self.ios_home.cards_grid.setVisible(not show_sidebar)
        self.ios_home.apply_btn.setVisible(not show_sidebar)
        self._update_shared_nav(self.ios_pages.currentIndex())
        self._sync_sidebar_selection()

    def apply_theme(self, theme: int):
        """Apply the UI mode WITHOUT navigating away.

        CLASSIC: sidebar + classic home; iOS-style pages open as actions.
        IOS: iOS UI with an optional sidebar and the shared header providing
        back navigation. Only the chrome changes — the current page stays put.
        """
        self.theme_manager.save_theme(theme)
        is_ios = theme == ThemeManager.IOS
        show_sidebar = not is_ios or self.sidebar_enabled()
        self.ui.sidebar.setVisible(show_sidebar)
        self.bottom_navigation.setVisible(not show_sidebar)
        self.bottom_navigation.popup.hide()
        self.ios_home.cards_grid.setVisible(not show_sidebar)
        self.ios_home.apply_btn.setVisible(not show_sidebar)
        self.ui.deviceBar.setVisible(not is_ios)
        if is_ios:
            # iOS mode: full-screen, no padding
            self.shell_layout.setContentsMargins(0, 0, 0, 0)
            self.shell_layout.setSpacing(0)
            self.body_row.setSpacing(0)
            # entering the new UI: land on its home unless already inside it.
            # A UI-mode switch re-lays out the whole shell, so no page slide.
            if self.content_stack.currentIndex() != 1:
                self.content_stack.setCurrentIndex(1)
                self.set_ios_page(0, animate=False)
            self._update_shared_nav(self.ios_pages.currentIndex())
        else:
            # Classic mode: add padding around the shell
            self.shell_layout.setContentsMargins(16, 16, 16, 16)
            self.shell_layout.setSpacing(12)
            self.body_row.setSpacing(16)
            # classic UI hides the shared header except on pages that need it
            # (Icon Themes keeps "+ Add Icon")
            self._update_shared_nav(self.ios_pages.currentIndex())
            if self.ios_pages.currentIndex() == 0:
                # the iOS home has no meaning inside the classic shell
                self.show_home()
        self._sync_sidebar_selection()


    def updateAppVersionLabel(self):
        new_text: str = self.ui.appVersionLbl.text()
        new_text = new_text.replace("%VERSION", App_Version)
        if App_Build > 0:
            new_text = new_text.replace("%BETATAG", f"(beta {App_Build})")
        else:
            new_text = new_text.replace("%BETATAG", "")
        self.ui.appVersionLbl.setText(new_text)


    def _sync_settings(self):
        """Sync settings to disk immediately after critical changes."""
        try:
            self.settings.sync()
        except Exception:
            pass  # Best effort



class NavigationMixin:
    """Page structure, shared IOS nav bar and sidebar selection."""

    # Icon Themes retains the shared navigation header in the classic shell.
    _classic_nav_pages = (10,)

    def _update_shared_nav(self, index: int):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            use_nav = index in self._classic_nav_pages
            self.ios_nav.setVisible(use_nav)
            if not use_nav:
                return
        # the iOS home page is full-screen — no header at all
        self.ios_nav.setVisible(index != 0)
        if index == 0:
            self.ios_nav.clear_right_action()
            return
        title = self._ios_page_titles.get(index, "")
        self.ios_nav.set_title(title)
        self.ios_nav.set_back_visible(
            self.theme_manager.current_theme != ThemeManager.CLASSIC
            and not self.sidebar_enabled())
        icons = {
            1: "toggles", 2: "wallpaper", 3: "hdd", 4: "gear",
            5: "app-indicator", 6: "check-circle", 7: "phone",
            8: "gear", 9: "liquid-glass", 10: "brush",
            11: "lock", 12: "folder",
        }
        from src.gui.ios.feature_icons import FEATURE_PAGE_ICONS
        icon = icons.get(index)
        path = FEATURE_PAGE_ICONS.get(index, f":/icon/{icon}.svg" if icon else None)
        self.ios_nav.set_icon(path)
        page = self.ios_pages.widget(index)
        categories = []
        seen = set()
        for label, _ in self._page_section_targets(page):
            if label in seen:
                continue
            seen.add(label)
            categories.append((label, lambda p=page, name=label:
                               self._jump_to_page_section(p, name)))
        self.ios_nav.set_categories(categories)
        right = self._nav_right_actions.get(index)
        if right:
            self.ios_nav.set_right_action(right[0], right[1])
        else:
            self.ios_nav.clear_right_action()


    def _page_section_targets(self, page):
        from src.gui.widgets import IOSCollapsibleSection, IOSSectionHeader
        scrolls = page.findChildren(QtWidgets.QScrollArea)
        headers = page.findChildren(IOSCollapsibleSection) + page.findChildren(IOSSectionHeader)
        for widget in headers:
            if not widget.isVisibleTo(page):
                continue
            if not any(area.widget() is not None and
                       area.widget().isAncestorOf(widget) for area in scrolls):
                continue
            if isinstance(widget, IOSCollapsibleSection):
                yield widget._title, widget
            elif isinstance(widget, IOSSectionHeader):
                yield widget.property("navigationTitle") or widget.text(), widget

    def _jump_to_page_section(self, page, name):
        from src.gui.widgets import IOSCollapsibleSection
        for label, target in self._page_section_targets(page):
            if label != name:
                continue
            if isinstance(target, IOSCollapsibleSection):
                target.set_expanded(True)
            for scroll in page.findChildren(QtWidgets.QScrollArea):
                content = scroll.widget()
                if content is None or not content.isAncestorOf(target):
                    continue
                def jump(area=scroll, item=target, body=content):
                    if body.layout():
                        body.layout().activate()
                    position = item.mapTo(body, QtCore.QPoint(0, 0)).y()
                    bar = area.verticalScrollBar()
                    target = max(0, min(bar.maximum(), position - 12))
                    if hasattr(self, 'liquid'):
                        from src.gui.liquid.motion import animate
                        animate(area, bar.value(), target, lambda value: bar.setValue(round(value)), duration=320)
                    else:
                        bar.setValue(target)
                QtCore.QTimer.singleShot(0, jump)
                return

    def _sync_sidebar_selection(self):
        """Move the checked highlight of the sidebar to the active view."""
        btns = (self.ui.homePageBtn, self.ui.posterboardPageBtn,
            self.ui.springboardOptionsPageBtn, self.ui.internalOptionsPageBtn,
            self.ui.liquidGlassPageBtn, self.ui.daemonsPageBtn,
            self.ui.applyPageBtn, self.ui.settingsPageBtn,
            self.ui.statusBarPageBtn, self.ui.iconThemesPageBtn,
            self.ui.presetsPageBtn, self.ui.templatesPageBtn)
        page_to_btn = {
            0: 0,   # home
            2: 1,   # posterboard
            7: 2,   # springboard
            8: 3,   # internal
            9: 4,   # liquid glass
            3: 5,   # daemons
            6: 6,   # apply
            4: 7,   # settings
            5: 8,   # status bar
            10: 9,  # icon themes
            12: 10, # presets
            14: 11, # templates
        }
        idx = None
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            if self.content_stack.currentIndex() == 0:
                idx = 0
            elif self.content_stack.currentIndex() == 1:
                idx = page_to_btn.get(self.ios_pages.currentIndex())
            elif self.content_stack.currentIndex() == 2:
                idx = 5
        else:
            idx = page_to_btn.get(self.ios_pages.currentIndex())
        target = btns[idx] if idx is not None else None
        for b in btns:
            b.setChecked(b is target)


    def show_home(self):
        """Open the home page of the ACTIVE UI mode."""
        if self.theme_manager.current_theme == ThemeManager.IOS:
            self.content_stack.setCurrentIndex(1)
            self.set_ios_page(0)
            self._update_shared_nav(0)
        else:
            self.content_stack.setCurrentIndex(0)
        self._refresh_preset_widgets()
        self._sync_sidebar_selection()


    def _refresh_preset_widgets(self):
        """Keep the active-preset banners on both home pages in sync."""
        try:
            self.pages[Page.Home].refresh_preset_widget()
        except Exception:
            pass
        try:
            self.ios_home.refresh_preset_widget()
        except Exception:
            pass


    def show_ios_page(self, index: int):
        if index == 11:
            from src.devicemanagement.passcode_support import current_passcode_theme_reason
            if current_passcode_theme_reason(self.device_manager):
                self.ios_home.update_passcode_support()
                return
        self.content_stack.setCurrentIndex(1)
        self.set_ios_page(index)


    # iOS-style page transition: the incoming page slides in from the right, one
    # full page width, so it enters from off-screen rather than merely nudging.
    # Only the content area moves — the shared nav bar above the stack stays put,
    # which is what the stock iOS push looks like.
    #
    # The curve is deliberately soft and the duration long: a short OutCubic
    # reads as a snap on a page as tall as the window, so it drifts in instead.
    # Returning to Home uses the reverse direction so the back navigation feels
    # like a real stack pop instead of an abrupt page replacement.
    PAGE_SLIDE_MS = 240
    HOME_PAGE = 0

    def set_ios_page(self, index: int, animate: bool = True):
        """The only place that switches the iOS page stack.

        Guards the index, snaps any page still mid-slide to its final spot and
        then slides the incoming page in. Home enters from the left when it is
        opened as the destination of a back navigation.
        """
        stack = self.ios_pages
        if not isinstance(index, int) or index < 0 or index >= stack.count():
            return
        if getattr(self, "_posterboard_selection_pending", False):
            self._posterboard_waiting.pop("navigation", None)
        if index in (2, 4) and self._defer_until_posterboard_ready(
                "navigation", lambda: self.set_ios_page(index, animate)):
            return
        target = stack.widget(index)
        if getattr(target, "_device_rebuild_pending", False):
            device = self.device_manager.data_singleton.current_device
            signature = tuple(getattr(device, key, None)
                              for key in ("udid", "model", "version", "build"))
            content = getattr(target, "content", None)
            if getattr(content, "_device_signature", None) != signature:
                target.rebuild()
            target._device_rebuild_pending = False
        if stack.currentIndex() == index:
            return
        self._stop_page_slide()
        stack.setCurrentIndex(index)
        page = stack.widget(index)
        if (hasattr(page, "_retheme")
                and getattr(page, "_applied_theme_revision", -1)
                != self._color_theme.revision):
            page._retheme()
            page._applied_theme_revision = self._color_theme.revision
        if animate and not hasattr(self, "liquid") and stack.isVisible() and index not in (1, 3):
            self._slide_page_in(page, from_left=index == self.HOME_PAGE)

    def _slide_page_in(self, page, from_left=False):
        y = page.y()
        if page.width() <= 0 or page.height() <= 0:
            page.move(QtCore.QPoint(0, y))
            return
        anim = QtCore.QPropertyAnimation(page, b"pos", self)
        start_x = -page.width() if from_left else page.width()
        start_pos = QtCore.QPoint(start_x, y)
        end_pos = QtCore.QPoint(0, y)
        # Move before starting the animation so the freshly selected page is
        # never painted once at its final position and then snapped away.
        page.move(start_pos)
        anim.setDuration(self.PAGE_SLIDE_MS + (40 if from_left else 0))
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._page_slide_anim = anim
        anim.finished.connect(self._stop_page_slide)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_page_slide(self):
        """End a running page slide at once, so no page is left half-slid."""
        anim = getattr(self, "_page_slide_anim", None)
        if anim is None:
            return
        self._page_slide_anim = None
        try:
            page = anim.targetObject()
            anim.stop()
        except RuntimeError:
            return
        if page is not None:
            try:
                page.move(QtCore.QPoint(0, page.y()))
            except RuntimeError:
                pass


    def open_presets_section(self):
        """Open the dedicated preset manager page."""
        self.content_stack.setCurrentIndex(1)
        self.set_ios_page(12)
        self._update_shared_nav(12)
        self._sync_sidebar_selection()


    def eventFilter(self, obj, event):
        """Handle ESC and the mouse back button as navigation-back."""
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        # The filter is application-wide; separate windows own their Escape
        # and mouse-back events, even when parented to the main window.
        if not isinstance(obj, QtWidgets.QWidget) or obj.window() is not self:
            return False
        try:
            etype = event.type()
        except (AttributeError, TypeError):
            return False
        if etype == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            return self._go_back()
        if etype == QtCore.QEvent.Type.MouseButtonPress and event.button() in (
                QtCore.Qt.MouseButton.BackButton, QtCore.Qt.MouseButton.ExtraButton1):
            return self._go_back()
        return False


    def _go_back(self) -> bool:
        """Navigate back.

        IOS mode: subpage -> iOS home (stay there).
        CLASSIC mode: any action page backs out to the classic home.
        """
        if self.content_stack.currentIndex() == 1:
            if self.theme_manager.current_theme == ThemeManager.IOS:
                if self.ios_pages.currentIndex() != 0:
                    self.set_ios_page(0)
                    return True
                return False
            # classic shell: action pages back out straight to classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        if self.content_stack.currentIndex() == 2:
            # classic daemons page -> classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        return False


    def on_homePageBtn_clicked(self):
        self.show_home()


    def on_statusBarPageBtn_clicked(self):
        self.show_ios_page(5)
        self._sync_sidebar_selection()


    def on_springboardOptionsPageBtn_clicked(self):
        self.show_ios_page(7)
        self._sync_sidebar_selection()


    def on_internalOptionsPageBtn_clicked(self):
        self.show_ios_page(8)
        self._sync_sidebar_selection()


    def on_liquidGlassPageBtn_clicked(self):
        self.show_ios_page(9)
        self._sync_sidebar_selection()


    def on_daemonsPageBtn_clicked(self):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            self.pages[Page.Daemons].load()
            self.pages[Page.Daemons].refresh()
            self.content_stack.setCurrentIndex(2)
        else:
            self.ios_daemons.refresh_from_tweaks()
            self.show_ios_page(3)
        self._sync_sidebar_selection()


    def on_iconThemesPageBtn_clicked(self):
        self.show_ios_page(10)
        self._sync_sidebar_selection()


    def on_posterboardPageBtn_clicked(self):
        self.show_ios_page(2)
        self._sync_sidebar_selection()

    def on_templatesPageBtn_clicked(self):
        self.show_ios_page(14)
        self._sync_sidebar_selection()


    def on_applyPageBtn_clicked(self):
        self.show_ios_page(6)
        self._sync_sidebar_selection()


    def on_settingsPageBtn_clicked(self):
        self.show_ios_page(4)
        self._sync_sidebar_selection()


    def on_presetsPageBtn_clicked(self):
        self.show_ios_page(12)
        self._sync_sidebar_selection()


class ApplyMixin:
    """Apply/reset orchestration, alerts and dialog prompts."""

    # IOSSummaryDialog extra-button result when the user asks to update the
    # backup cache from the pre-apply summary (QDialog.Accepted=1/Rejected=0).
    _SUMMARY_UPDATE_CACHE = 2

    def update_label(self, txt: str):
        # Mirror progress into the iOS surfaces (home indicator + Apply page)
        try:
            if txt:
                self.ios_home.show_process_status(txt)
                self.ios_apply.set_status(txt)
        except Exception:
            pass


    def remove_tweaks_clicked(self):
        if not self.device_manager.get_current_device_udid():
            return
        dialog = ResetDialog(device_manager=self.device_manager, apply_reset=self.apply_changes)
        dialog.exec()


    @QtCore.Slot()
    def apply_tweaks_clicked(self):
        self.apply_changes()


    def _build_apply_summary(self) -> tuple:
        """Human-readable breakdown of what an apply would change.

        Returns ``(lines, total)`` — ``lines`` feed the pre-apply summary
        dialog, ``total`` is the summed change count (0 = nothing to do).
        """
        from src.tweaks.registry import SPECS_BY_SECTION, Section
        from src.tweaks.tweak_loader import load_plist_tweaks, load_daemons
        load_plist_tweaks()
        load_daemons()

        lines = []
        total = 0

        def add(label, count):
            nonlocal total
            if count > 0:
                total += count
                lines.append(f"• {label}: {count}")

        for section in Section:
            enabled = sum(
                1 for spec in SPECS_BY_SECTION[section]
                if getattr(tweaks.get(spec.id), "enabled", False))
            if enabled:
                add(QCoreApplication.translate("Nugget", section.value), enabled)

        pb = tweaks.get(TweakID.PosterBoard)
        if pb is not None:
            add(QCoreApplication.translate("Nugget", "PosterBoard"), len(pb.tendies))

        tmpl = tweaks.get(TweakID.Templates)
        if tmpl is not None:
            add(QCoreApplication.translate("Nugget", "Templates"), len(tmpl.templates))

        st = tweaks.get(TweakID.StatusBar)
        if st is not None:
            try:
                add(QCoreApplication.translate("Nugget", "Status Bar"), st.count_overrides())
            except Exception:
                pass

        dm = tweaks.get(TweakID.Daemons)
        if dm is not None:
            add(QCoreApplication.translate("Nugget", "Daemons"),
                sum(1 for v in getattr(dm, "value", {}).values() if v))

        it = tweaks.get(TweakID.IconThemes)
        if it is not None:
            add(QCoreApplication.translate("Nugget", "Icon Themes"), len(it.themes))

        return lines, total


    def _confirm_apply_summary(self) -> bool:
        """Show the pre-apply summary; True only if the user confirms.

        When the backup cache is enabled, an extra "Update Cache" button lets
        the user force a cache refresh right here — the running summary shows
        the cache's creation date, the refresh runs in a background thread,
        and the dialog re-opens with the fresh date.
        """
        if not self.device_manager.get_current_device_udid():
            QtWidgets.QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "No iPhone connected"),
                QCoreApplication.translate(
                    "Nugget", "Connect and unlock an iPhone before applying tweaks."))
            return False
        liquid = getattr(self, 'liquid', None)
        if liquid is not None and liquid.restore._confirming:
            return liquid.restore.confirm_review()
        cache_enabled = self._backup_cache_enabled()
        while True:
            lines, total = self._build_apply_summary()
            if not lines:
                QtWidgets.QMessageBox.information(
                    self,
                    QCoreApplication.translate("Nugget", "Nothing to apply"),
                    QCoreApplication.translate(
                        "Nugget",
                        "No tweaks, daemons, wallpapers or templates are enabled. "
                        "Enable something first."))
                return False
            if cache_enabled:
                cache_line = self._backup_cache_summary_line()
                if cache_line:
                    lines.append(cache_line)
            storage_warning = self._storage_warning_line()
            if storage_warning:
                lines.append(storage_warning)
            storage_estimate = self._storage_estimate_line()
            if storage_estimate:
                lines.append(storage_estimate)
            lines.append(self._time_estimate_line(total))
            battery_warning = self._battery_warning_line()
            if battery_warning:
                lines.append(battery_warning)
            compatibility_warning = self._compatibility_warning_line()
            if compatibility_warning:
                lines.append(compatibility_warning)
            from src.gui.ios.components import IOSSummaryDialog
            report = self._risk_report()
            risk_panel = acknowledge = None
            if report is not None:
                from src.controllers.risk_assessment import RiskLevel
                from src.gui.ios.risk_panel import RiskPanel
                risk_panel = RiskPanel(report)
                if report.level == RiskLevel.HIGH:
                    acknowledge = QCoreApplication.translate(
                        "RiskAssessment", "I understand the risks and want to apply anyway")
            dlg = IOSSummaryDialog(
                title=QCoreApplication.translate("Nugget", "Apply Tweaks"),
                lines=lines,
                muted=QCoreApplication.translate(
                    "Nugget",
                    "Your device reboots when it's done. If you turn Find My off "
                    "for this apply, turn it back on afterwards. A protective "
                    "backup runs first."),
                confirm_text=QCoreApplication.translate("Nugget", "Apply"),
                extra_button=(QCoreApplication.translate("Nugget", "Update Cache")
                              if cache_enabled else ""),
                parent=self, details_callback=self._show_apply_preview,
                header_widget=risk_panel, acknowledge_text=acknowledge or "",
                preview_callback=self.show_device_twin)
            res = dlg.exec()
            if res == self._SUMMARY_UPDATE_CACHE:
                self._run_cache_update()
                # Re-open the summary (with the refreshed cache date) so the
                # user can review and then confirm or cancel.
                continue
            if res != QtWidgets.QDialog.Accepted:
                return False
            return self._confirm_tweak_conflicts()

    def show_device_twin(self, parent=None):
        from src.gui.dialogs.device_twin import show_current_twin
        show_current_twin(self, parent if isinstance(parent, QtWidgets.QWidget) else self)

    def _risk_report(self):
        """Risk verdict for the current selection, or None if it cannot be built."""
        try:
            from src.controllers.apply_preview import load_preview
            from src.controllers.hotload import HotLoad
            from src.controllers.preset_manager import PresetManager
            from src.controllers.risk_assessment import assess, apply_factors
            from src.controllers.tweak_conflicts import current_conflicts
            manager = self.device_manager
            version = manager.get_current_device_version() or ""
            model = manager.get_current_device_model() or ""
            hotload = HotLoad(manager.pref_manager.settings)
            context = dict(device_version=version, device_model=model)
            hidden = hotload.hidden_tweak_names(**context)
            data = {name: entry for name, entry in PresetManager()._serialize()["tweaks"].items()
                    if name not in hidden and hotload.rule_for(name, **context) is None}
            battery = getattr(self, "_battery_info", None)
            if not battery or battery.get("udid") != manager.get_current_device_udid():
                battery = None
            board = tweaks.get(TweakID.PosterBoard)
            extra = apply_factors(
                conflicts=len(current_conflicts(manager)),
                battery=battery,
                storage_low=bool(self._storage_warning_line()),
                first_apply=load_preview(manager.get_current_device_udid(), version) is None,
                wallpapers=len(board.tendies) if board is not None else 0)
            templates = tweaks.get(TweakID.Templates)
            if templates is not None and "Templates" in data:
                from src.controllers.risk_assessment import community_factors
                from src.tweaks.posterboard.community_tweaks import active
                extra += community_factors(active(
                    [(item.name, getattr(item, "tweaks", [])) for item in templates.templates], version))
            return assess(data, version, model, hotload=hotload, extra=extra)
        except Exception:
            import logging
            logging.getLogger("GoldenNugget.risk").exception("Could not assess apply risk")
            return None

    def _storage_warning_line(self):
        """Return a warning when the selected device has little free space."""
        info = getattr(self, "_storage_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or not current_udid or info.get("udid") != current_udid:
            return None
        total = int(info.get("total", 0) or 0)
        free = int(info.get("free", 0) or 0)
        if total <= 0 or free < 0:
            return None
        # iOS restores need working room in addition to the tweak payloads.
        # Use the larger of 5 GiB or 10% of the data volume as a conservative
        # warning threshold; this warns without blocking the user's choice.
        threshold = max(5 * 1024 ** 3, int(total * 0.10))
        if free >= threshold:
            return None
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Low iPhone storage: {0} GB free. Restoring tweaks may require "
            "at least {1} GB free and could fail if the device runs out of space."
        ).format(f"{free / (1024 ** 3):.1f}", f"{threshold / (1024 ** 3):.1f}")

    def _storage_estimate_line(self):
        """Show the recommended working room for backup and restore."""
        info = getattr(self, "_storage_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or not current_udid or info.get("udid") != current_udid:
            return None
        total = int(info.get("total", 0) or 0)
        if total <= 0:
            return None
        recommended = max(5 * 1024 ** 3, int(total * 0.10))
        return QCoreApplication.translate(
            "Nugget",
            "Estimated working space: keep at least {0} GB free for the backup and restore."
        ).format(f"{recommended / (1024 ** 3):.1f}")

    def _time_estimate_line(self, selected_count):
        """Give a deliberately conservative estimate for the apply flow."""
        count = max(1, int(selected_count or 0))
        seconds = 120 + (count * 8)
        minutes, remainder = divmod(seconds, 60)
        if remainder >= 30:
            minutes += 1
        return QCoreApplication.translate(
            "Nugget",
            "Estimated time: about {0} minutes, depending on the iPhone and connection."
        ).format(minutes)

    def _battery_warning_line(self):
        info = getattr(self, "_battery_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or info.get("udid") != current_udid:
            return None
        percent = info.get("percent")
        if percent is None or bool(info.get("charging", False)) or percent > 20:
            return None
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Low iPhone battery: {0}%. Connect the charger before restoring."
        ).format(int(percent))

    def _compatibility_warning_line(self):
        from src.gui.ios.compat import compatibility_reasons, device_family
        from src.tweaks.registry import SPECS_BY_ID
        version = self.device_manager.get_current_device_version() or ""
        model = self.device_manager.get_current_device_model() or ""
        if not version or not model:
            return None
        family = device_family(model)
        is_iphone = None if family is None else family == "iphone"
        incompatible = []
        for tweak_id, spec in SPECS_BY_ID.items():
            tweak = tweaks.get(tweak_id)
            if tweak is None or not getattr(tweak, "enabled", False):
                continue
            reasons = compatibility_reasons(tweak_id, version, model, is_iphone)
            if reasons:
                incompatible.append((spec.title, "; ".join(reasons)))
        if not incompatible:
            return None
        names = ", ".join(f"{title} ({reason})" for title, reason in incompatible[:4])
        if len(incompatible) > 4:
            names += QCoreApplication.translate("Nugget", " and more")
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Compatibility warning: {0} selected tweak(s) do not match {1} ({2}): {3}."
        ).format(len(incompatible), version, model, names)

    def _confirm_tweak_conflicts(self):
        from src.controllers.tweak_conflicts import current_conflicts
        from src.gui.theme import t
        conflicts = current_conflicts(self.device_manager)
        if not conflicts:
            return True
        dialog = QtWidgets.QMessageBox(self)
        dialog.setStyleSheet(t("confirm_dialog"))
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        dialog.setWindowTitle(QCoreApplication.translate("TweakConflicts", "Conflicting tweaks"))
        dialog.setText(QCoreApplication.translate(
            "TweakConflicts", "Some selected tweaks contradict or overwrite each other. "
            "Return to the list to change your selection, or continue with the current selection."))
        dialog.setInformativeText("\n\n".join(item.description() for item in conflicts[:5]))
        dialog.setDetailedText("\n\n".join(item.description() for item in conflicts))
        back = dialog.addButton(QCoreApplication.translate("TweakConflicts", "Review selection"),
                                QtWidgets.QMessageBox.RejectRole)
        proceed = dialog.addButton(QCoreApplication.translate("TweakConflicts", "Continue anyway"),
                                   QtWidgets.QMessageBox.AcceptRole)
        proceed.setObjectName("cancelBtn")
        dialog.setDefaultButton(back)
        dialog.setEscapeButton(back)
        dialog.exec()
        return dialog.clickedButton() is proceed

    def _show_apply_preview(self, parent):
        from src.controllers.apply_preview import load_preview, safe_capture_preview
        from src.gui.dialogs.apply_preview import ApplyPreviewDialog
        manager = self.device_manager
        preview = safe_capture_preview(manager)
        previous = None
        conflicts = []
        lines = []
        if preview is None:
            lines = [QCoreApplication.translate(
                "ApplyPreview", "The preview could not be built. See the session log for details.")]
        else:
            previous = load_preview(manager.get_current_device_udid(),
                                    manager.get_current_device_version())
            from src.controllers.tweak_conflicts import current_conflicts
            conflicts = [item.description() for item in current_conflicts(manager)]
        dialog = ApplyPreviewDialog(lines, parent, preview=preview, previous=previous, conflicts=conflicts)
        dialog.exec()
        dialog.deleteLater()

    def _backup_cache_enabled(self) -> bool:
        return (self.device_manager.pref_manager.use_backup_cache
                and not os.environ.get("GOLDENNUGGET_NO_BACKUP_CACHE"))

    def _backup_cache_summary_line(self) -> str:
        udid = self.device_manager.get_current_device_udid()
        if not udid:
            return ""
        from src.restore.protective_cache import peek_cache_info
        info = peek_cache_info(udid)
        q = QCoreApplication.translate
        if info is None:
            return q(
                "Nugget",
                "• Backup cache: none yet (will be created on this apply)")
        return q(
            "Nugget",
            "• Backup cache from: {0} (reused if fresh)").format(
                info.get("created") or "unknown")

    def _run_cache_update(self) -> bool:
        """Force a backup-cache refresh in a background thread, modally.

        Returns True only when the refresh ran to completion. The progress
        dialog stays open until ``finished_with_result`` fires; a failure
        already surfaced through the alert pipeline.
        """
        from src.gui.thread_workers.apply_worker import CacheUpdateThread
        udid = self.device_manager.get_current_device_udid()
        if not udid:
            QtWidgets.QMessageBox.information(
                self,
                QCoreApplication.translate("Nugget", "Update Cache"),
                QCoreApplication.translate(
                    "Nugget", "No device is selected. Connect your device first."))
            return False
        worker = CacheUpdateThread(manager=self.device_manager)
        self._cache_update_thread = worker  # keep a strong ref while running
        prog = QtWidgets.QProgressDialog(
            QCoreApplication.translate(
                "Nugget", "Updating backup cache..."),
            "", 0, 0, self)
        prog.setWindowTitle(QCoreApplication.translate("Nugget", "Update Cache"))
        prog.setWindowModality(QtCore.Qt.WindowModal)
        prog.setCancelButton(None)
        prog.setMinimumDuration(0)
        result = [False]

        def _on_progress(txt):
            prog.setLabelText(txt)

        def _on_finish(ok: bool, _err: str):
            result[0] = ok
            prog.close()

        worker.progress.connect(_on_progress)
        worker.finished_with_result.connect(_on_finish)
        worker.alert.connect(self.alert_message)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        # Modal event loop — worker signals keep flowing until _on_finish closes it.
        prog.exec()
        return result[0]


    def apply_changes(self, reset_pages: list=None):
        if self.apply_in_progress or getattr(self, '_cache_restore_in_progress', False):
            self.show_ios_page(6)
            return
        if not self.device_manager.get_current_device_udid():
            QtWidgets.QMessageBox.information(
                self, QCoreApplication.translate("Nugget", "No device connected"),
                QCoreApplication.translate("Nugget", "Connect a device before applying or removing tweaks."))
            return
        if self._defer_until_posterboard_ready("apply", lambda: self.apply_changes(reset_pages)):
            return
        if getattr(self, "_posterboard_selection_error", ""):
            QtWidgets.QMessageBox.warning(self, self.tr("Device configuration unavailable"),
                self.tr("The saved wallpaper configuration could not be read. Reconnect the device before applying changes.")
                + "\n\n" + self._posterboard_selection_error)
            return
        if not self.apply_in_progress:
            # Applies (not resets) get a what-will-change summary first.
            if reset_pages is None and not self._confirm_apply_summary():
                return
            if reset_pages is None:
                self._prepare_rollback_preset()
            self.dismiss_operation_result()
            self.apply_in_progress = True
            self.show_ios_page(6)
            self.toggle_thread_btns(disabled=True)
            self.worker_thread = ApplyThread(manager=self.device_manager, settings=self.settings, reset_pages=reset_pages)
            self.worker_thread.progress.connect(self.update_label)
            self.worker_thread.operation_stage.connect(self.ios_apply.set_stage)
            self.worker_thread.operation_stage.connect(self.ios_home.progress_card.set_stage)
            self.worker_thread.alert.connect(self.alert_message)
            self.worker_thread.request_text.connect(self.on_password_request)
            self.worker_thread.choice_prompt.connect(self.on_choice_prompt)
            self.worker_thread.finished_with_result.connect(self.finish_apply_thread)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.start()

    def _prepare_rollback_preset(self):
        """Keep the last successful apply available as a one-click rollback."""
        import shutil
        try:
            source = self.preset_manager.get_preset_path("__LastApplied")
            target = self.preset_manager.get_preset_path("__Rollback")
            if os.path.isfile(source):
                shutil.copyfile(source, target)
        except Exception:
            pass

    def _save_last_applied_preset(self):
        try:
            self.preset_manager.save_preset(
                "__LastApplied", "Internal rollback snapshot", tags=["internal"],
                device_model=self.device_manager.get_current_device_model() or "",
                ios_version=self.device_manager.get_current_device_version() or "")
        except Exception:
            pass


    def alert_message(self, alert: Optional[ApplyAlertMessage], log_to_console: bool = True):
        if alert is None:
            # do sudo dialog input
            get_sudo_pwd() # clear if it is already there
            pwd, ok = QtWidgets.QInputDialog.getText(None, QCoreApplication.translate("Nugget", "Enter Sudo Password"), QCoreApplication.translate("Nugget", "Enter Your Computer's Password:"), QtWidgets.QLineEdit.Password, "")
            if ok and pwd:
                set_sudo_pwd(pwd)
            return
        alert.txt = device_text(alert.txt, self.device_manager.get_current_device_model())
        if log_to_console:
            print(alert.txt)
        # Backend messages that did not pick an explicit icon default to
        # the error renderer (QMessageBox.Critical).
        icon = alert.icon if alert.icon is not None else QtWidgets.QMessageBox.Critical
        # Apply/reset failures carry a traceback: route them through the same
        # parsed crash dialog (severity/likely cause + Copy Error + Report on
        # GitHub + Open Log), instead of a raw QMessageBox.
        if (icon == QtWidgets.QMessageBox.Critical
                and alert.exc_type is not None and alert.detailed_txt):
            from src.exceptions.crash_handler import _classify
            info = _classify(alert.exc_type, alert.exc_value)
            self._embedded_alert_error(alert, info)
            return
        detailsBox = QtWidgets.QMessageBox()
        detailsBox.setIcon(icon)
        detailsBox.setWindowTitle(alert.title)
        detailsBox.setText(alert.txt)
        if alert.detailed_txt != None:
            detailsBox.setDetailedText(alert.detailed_txt)
        restore_btn = None
        if alert.backup_path:
            restore_btn = detailsBox.addButton(
                self.tr("Restore data from backup"), QtWidgets.QMessageBox.AcceptRole)
        detailsBox.exec()
        if restore_btn is not None and detailsBox.clickedButton() is restore_btn:
            self._start_cache_restore()


    def _embedded_alert_error(self, alert: ApplyAlertMessage, info: dict):
        """Show an apply failure through the crash/error dialog."""
        # Need the restore callback to survive the dialog's exec() lifetime.
        def _restore():
            self._start_cache_restore()
        from src.exceptions.crash_handler import show_error_dialog
        show_error_dialog(
            summary=alert.txt,
            traceback_text=alert.detailed_txt,
            info=info,
            backup_path=alert.backup_path,
            on_restore=_restore if alert.backup_path else None,
        )


    def _start_cache_restore(self):
        from src.gui.thread_workers.apply_worker import RestoreCacheThread
        from src.restore.recovery_source import locate_restore_source
        if getattr(self, '_cache_restore_in_progress', False):
            return
        if self.apply_in_progress:
            # A restore and an apply/reset must never drive the device at the
            # same time — both open their own lockdown sessions.
            self.alert_message(ApplyAlertMessage(
                txt="Cannot restore data while an apply/reset is in progress.",
                title="Restore data",
                icon=QtWidgets.QMessageBox.Warning,
            ), log_to_console=False)
            return
        source, _ = locate_restore_source(self.device_manager.get_current_device_udid())
        if source is None:
            self.alert_message(ApplyAlertMessage(
                txt="No usable protective backup was found for the selected device. "
                    "Check Settings > Backup/Cache Location and select the folder containing your existing backup.",
                title="No backup available", icon=QtWidgets.QMessageBox.Warning,
            ), log_to_console=False)
            return
        self._cache_restore_in_progress = True
        self.show_ios_page(6)
        # Hold the thread on the window like ApplyThread/RefreshDevicesThread
        # do. A bare local reference lets the Python wrapper be garbage-
        # collected while the native thread is still running, which Qt reports
        # as the "QThread: Destroyed while thread '' is still running" crash
        # in the middle of a device restore.
        worker = RestoreCacheThread(manager=self.device_manager)
        self.ios_home.set_operation_busy(True)
        self.ios_home.progress_card.set_stage("restore")
        self.ios_apply.set_busy(True)
        self.ios_apply.set_stage('restore')
        self._cache_restore_thread = worker
        worker.progress.connect(self._update_restore_label)
        worker.alert.connect(self.alert_message)
        # The media push can hit a device that is paired but still locked after
        # the reboot, so the recovery needs the same Abort/Resume dialog the
        # apply gets.
        worker.choice_prompt.connect(self.on_choice_prompt)
        worker.finished_with_result.connect(self._finish_cache_restore)
        worker.finished.connect(self._cache_restore_thread_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()


    def _update_restore_label(self, txt: str):
        try:
            self.ios_home.show_process_status(txt)
            self.ios_apply.set_status(txt)
        except Exception:
            pass


    def _finish_cache_restore(self, success: bool, error_msg: str = ""):
        self._cache_restore_in_progress = False
        self._operation_result_visible = True
        self.ios_home.set_operation_busy(False)
        self.ios_apply.set_busy(False)
        self.ios_apply.result_card.show_result(success, error_msg or (
            self.tr('Backup restored.') if success else self.tr('Restore did not complete.')),
            False, False, self.device_manager.get_current_device_model())
        worker = getattr(self, "_cache_restore_thread", None)
        control = getattr(worker, "find_my_wait", None)
        cancelled = bool(control and control.snapshot()[2])
        if cancelled:
            self.ios_home.result_card.show_result(False, error_msg, False, False, self.device_manager.get_current_device_model())
        elif not success or error_msg:
            try:
                self.alert_message(ApplyAlertMessage(
                    txt=f"Restore data: {error_msg or 'failed'}",
                    title="Restore data",
                    icon=QtWidgets.QMessageBox.Critical,
                ), log_to_console=False)
            except Exception:
                pass
        self._schedule_device_event_refresh()


    def _cache_restore_thread_finished(self):
        # run() returned, so the native thread is done; drop the window's
        # reference (deleteLater is already queued via the other connection).
        try:
            self._cache_restore_thread = None
        except Exception:
            pass


    def on_password_request(self, title: str, label: str, box):
        try:
            password, ok = QtWidgets.QInputDialog.getText(
                self, title, label, QtWidgets.QLineEdit.Password)
            box.put(password if (ok and password) else None)
        except Exception:
            try:
                box.put(None)
            except Exception:
                pass


    def on_choice_prompt(self, title: str, text: str, box):
        """Main-thread Abort/Resume dialog (e.g. device locked too long after
        the security recovery). Built here — never on the worker thread — and
        the decision is boxed back to the waiting worker."""
        try:
            mbox = QtWidgets.QMessageBox(self)
            mbox.setWindowTitle(title)
            mbox.setIcon(QtWidgets.QMessageBox.Warning)
            mbox.setText(text)
            abort_btn = mbox.addButton(
                QCoreApplication.tr("Abort"), QtWidgets.QMessageBox.RejectRole)
            resume_btn = mbox.addButton(
                QCoreApplication.tr("Resume"), QtWidgets.QMessageBox.AcceptRole)
            mbox.setDefaultButton(resume_btn)
            mbox.exec()
            result = "resume" if mbox.clickedButton() is resume_btn else "abort"
        except Exception:
            result = "abort"
        try:
            box.put(result)
        except Exception:
            pass


    def finish_apply_thread(self, success: bool = False, error_msg: str = ""):
        if success and self.device_manager.pref_manager.auto_reboot:
            self._expect_device_reboot()
        self.apply_in_progress = False
        self._operation_result_visible = True
        self.toggle_thread_btns(disabled=False)
        try:
            self.ios_settings._refresh_history()
        except Exception:
            pass
        worker = getattr(self, 'worker_thread', None)
        is_reset = worker is not None and worker.reset_pages is not None
        from src.gui.ios.operation_result import result_text
        text = result_text(success, error_msg,
            reset_pages=worker.reset_pages if is_reset else None,
            preview=getattr(self.device_manager, '_last_operation_preview', None))
        self.ios_home._hide_timer.stop()
        self.ios_home.hide_process_status()
        restart_required = success and not self.device_manager.pref_manager.auto_reboot
        self.ios_home.result_card.show_result(success, text, is_reset, restart_required, self.device_manager.get_current_device_model())
        self.ios_apply.result_card.show_result(success, text, is_reset, restart_required, self.device_manager.get_current_device_model())
        if self.content_stack.currentWidget() is getattr(self, "connect_placeholder", None):
            self.show_ios_page(6)
        self.ios_home.device_details.update_info()
        self.ios_apply.set_status("")
        # Show completion indicator on the iOS home page
        if success:
            if worker is not None and not is_reset:
                self._save_last_applied_preset()
        else:
            # Show error notification if not already shown via alert
            if error_msg and not getattr(worker, "error_alert_sent", False) and "timed out" not in error_msg.lower():
                if "skip_setup27.py" in error_msg:
                    message = QCoreApplication.translate(
                        "Nugget",
                        "Restore finished, but Setup Assistant configuration failed. Check the device connection and restore the retained backup if needed.")
                elif "ConnectionTerminatedError" in error_msg:
                    message = QCoreApplication.translate(
                        "Nugget",
                        "The device disconnected during restore. The apply did not finish successfully.")
                else:
                    message = f"Operation failed: {error_msg}"
                self.alert_message(ApplyAlertMessage(
                    txt=message,
                    title="Error",
                    icon=QtWidgets.QMessageBox.Critical
                ), log_to_console=False)
        self._schedule_device_event_refresh()


    def dismiss_operation_result(self):
        self._operation_result_visible = False
        self.ios_home.result_card.hide()
        self.ios_apply.result_card.hide()

    def prompt_first_launch_backup(self) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Back up your device"))
        box.setText(QCoreApplication.translate(
            "Nugget",
            "Have you made a backup of your iPhone? Tweaks and daemon changes "
            "are risky — a bad tweak can bootloop the device or force a full "
            "restore, which erases everything. Create a backup in iTunes or "
            "Finder before using GoldenNugget."))
        # Informative text, not detailed text: the "Show Details..." button
        # would make a third button, and QMessageBox caps its width at 500px
        # (half the screen below 1000px), which truncated the button labels.
        box.setInformativeText(QCoreApplication.translate(
            "Nugget",
            "Back up your iPhone before tweaking:\n"
            "• Windows: iTunes → your device → Back Up Now\n"
            "• Mac: Finder → your device → Back Up Now\n\n"
            "GoldenNugget's own protected backup also runs automatically when "
            "you apply tweaks, but a full iTunes/Finder backup is the only "
            "complete safety net."))
        # Explicit opaque background: the dialog inherits the app's global
        # ``QWidget { background-color: transparent }`` rule otherwise and
        # would render see-through.
        c = ColorThemeManager.instance().colors
        box.setStyleSheet(f"""
            QMessageBox {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; background: transparent; }}
            QPushButton {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: 1px solid {c.border};
                border-radius: 6px;
                padding: 6px 16px;
                min-width: 80px;
            }}
            QPushButton:hover {{ background-color: {c.surface_hover}; }}
            QPushButton:pressed {{ background-color: {c.border}; }}
        """)
        got_it = box.addButton(
            QCoreApplication.translate("Nugget", "Got it, I'm backed up"),
            QtWidgets.QMessageBox.AcceptRole)
        box.addButton(
            QCoreApplication.translate("Nugget", "I'll do it later"),
            QtWidgets.QMessageBox.RejectRole)
        # Make sure the dialog comes to the front and grabs input focus
        # (otherwise clicks can be swallowed by the window around it).
        box.raise_()
        box.activateWindow()
        box.exec()
        return box.clickedButton() is got_it


    def toggle_thread_btns(self, disabled: bool):
        self.ios_home.support_panel.show()
        experience = getattr(self, 'liquid', None)
        if experience is not None:
            experience.restore_button.setDisabled(
                disabled or self.apply_in_progress or getattr(self, '_cache_restore_in_progress', False))
            if disabled:
                experience.restore.hide()
                experience.restore_changes_panel.hide()
        self.ios_home.set_operation_busy(self.apply_in_progress or getattr(self, "_cache_restore_in_progress", False))
        if disabled or not self.apply_in_progress:
            self.ios_apply.set_busy(disabled)
        if disabled or not self.refresh_in_progress:
            self.ui.refreshBtn.setDisabled(disabled)
