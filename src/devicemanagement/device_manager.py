from collections.abc import Mapping
# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "pymobiledevice3.services.mobile_config",
    "pymobiledevice3.services.mobilebackup2",
    "src.restore.skip_setup27",
    "src.restore.restore",
    "src.tweaks.status_bar.statusbar_archive",
)

import asyncio
import os.path
import plistlib
import re
import shutil
import sys
import traceback

from tempfile import TemporaryDirectory
from typing import Optional

from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QSettings, QCoreApplication

from pymobiledevice3 import usbmux
from pymobiledevice3.services.mobile_config import MobileConfigService
from pymobiledevice3.exceptions import PairingDialogResponsePendingError, UserDeniedPairingError, MuxException, PasswordRequiredError, ConnectionTerminatedError, AccessDeniedError, InvalidServiceError
from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
import pymobiledevice3.service_connection as _sc


from src.devicemanagement.session import lockdown_session
from src.exceptions.device_errors import (
    is_device_locked_error as _is_device_locked_error,
    is_find_my_error,
)
from src.controllers.hotload import HotLoad
from src.tweaks.compatibility import hardware_reasons
from src.restore.skip_setup27 import build_cloud_config

# Bump SSL handshake timeout from 10s to 60s for all lockdown services.
_sc.DEFAULT_SSL_HANDSHAKE_TIMEOUT = 60

# Temporarily allow writing up to this many PosterBoard tendies in a single
# restore. Applying more than one tendie at once can race PosterBoard's sqlite
# regeneration, so the count is capped.
MAX_TENDIES_PER_RESTORE = 5

from src.devicemanagement.constants import Device, Version, is_supported_by_fork
from src.devicemanagement.device_capabilities import has_dynamic_island, has_camera_control, has_action_button, has_home_button, has_always_on_display
from src.devicemanagement.data_singleton import DataSingleton
from src.devicemanagement.eta import ProgressEta
from .preference_manager import PreferenceManager

from src.utils.alerts import ApplyAlertMessage
from src.utils.pages import Page
from src.controllers.path_handler import fix_windows_path

from src.exceptions.nugget_exception import NuggetException, BackupStorageError, BackupDiskSpaceError
from src.exceptions.device_errors import is_restore_mode_error
from src.restore.find_my_wait import ApplyCancelledError

from src.tweaks.tweaks import tweaks, TweakID, BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak, StatusBarTweak
from src.tweaks.tweak_classes import ReversibleBooleanPlistTweak
from src.tweaks.candidate_preferences import InstalledAppSuggestionsBlacklist
from src.tweaks.status_bar.statusbar_archive import build_reset_archive
from src.tweaks.posterboard.posterboard_tweak import PosterboardTweak
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.tweaks.icon_themes.icon_themes_tweak import IconThemesTweak
from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.registry import HOME_PREFIX, SPECS, Section, managed_pref_target

from src.restore.restore import restore_files, FileToRestore
from src.restore.afc_media import (
    afc_media_dir_for, afc_media_enabled, describe_media_store,
    media_store_verified,
)
from src.restore.protective import log_error, log_info, log_warn

def get_files_list_str(files_list: list[FileToRestore] = None) -> str:
    files_str: str = ""
    if files_list != None:
        files_str = "FILES LIST:"
        print("\nFile List:\n")
        for file in files_list:
            file_info = f"\n    Domain: {file.domain}\n    Path: {file.restore_path}"
            files_str += file_info
            print(file_info)
    return files_str

def show_apply_error(e: Exception, update_label=lambda x: None, files_list: list[FileToRestore] = None):
    from src.restore.inject import FeatureFlagBaselineUnavailable
    traceback_text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    print(traceback_text)
    # _restore_ios27 attaches the path as an exception note, which only the
    # formatted traceback carries (str(e) does not)
    backup_match = re.search(
        r"Protective backup kept at:\s*(.+)", traceback_text)
    backup_path = backup_match.group(1).strip() if backup_match else None
    update_label("Failed to restore")
    from src.exceptions.device_errors import is_icloud_restore_in_progress
    if is_icloud_restore_in_progress(e):
        return ApplyAlertMessage(
            QCoreApplication.tr('The iPhone reports that an iCloud restore is still in progress. Wait for it to finish before applying or restoring changes.'),
            title=QCoreApplication.tr('iCloud restore in progress'),
            detailed_txt=QCoreApplication.tr('Keep the iPhone connected to Wi-Fi and power. Do not cancel the iCloud restore or erase the device to bypass this error. No automatic retry was started.') + '\n\n' + traceback_text,
            icon=QMessageBox.Warning)
    elif is_find_my_error(e):
        return ApplyAlertMessage(QCoreApplication.tr("Find My must be disabled in order to use this tool."),
                       detailed_txt=QCoreApplication.tr("Disable Find My from Settings (Settings -> [Your Name] -> Find My) and then try again."))
    elif "Encrypted Backup MDM" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("Nugget cannot be used on this device. Click Show Details for more info."),
                       detailed_txt=QCoreApplication.tr("Your device is managed and MDM backup encryption is on. This must be turned off in order for Nugget to work. Please do not use Nugget on your school/work device!"))
    elif is_restore_mode_error(e):
        return ApplyAlertMessage(
            QCoreApplication.tr("The device is still in restore mode. Completion has not been confirmed."),
            detailed_txt=QCoreApplication.tr("Keep the device connected while its restore progress is showing. Do not start another Apply operation. Any protective backup remains on this computer.") + "\n\n" + traceback_text)
    elif "SessionInactive" in str(e) or "ConnectionAbortedError" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("The session was terminated. Refresh the device list and try again."))
    elif "PasswordRequiredError" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("Device is password protected! You must trust the computer on your device."),
                       detailed_txt=QCoreApplication.tr("Unlock your device. On the popup, click \"Trust\", enter your password, then try again."))
    elif isinstance(e, ConnectionTerminatedError):
        files_str = get_files_list_str(files_list)
        is_setup_config = "skip_setup27.py" in traceback_text
        if "version_exchange" in traceback_text and "perform_protective_backup" in traceback_text:
            return ApplyAlertMessage(
                QCoreApplication.tr("The backup service closed its connection before the backup transfer started. This does not mean the USB cable disconnected. Tweaks were not applied."),
                detailed_txt="TRACEBACK:\n\n" + traceback_text)
        if is_setup_config:
            return ApplyAlertMessage(
                QCoreApplication.tr("The restore finished, but the device disconnected while configuring Setup Assistant."),
                detailed_txt="TRACEBACK:\n\n" + traceback_text,
                backup_path=backup_path)
        return ApplyAlertMessage(
            QCoreApplication.tr("The device service closed its connection. This can happen while USB remains connected and does not by itself mean the file list is corrupted. Click Show Details for more info."),
            detailed_txt=files_str + "TRACEBACK:\n\n" + traceback_text,
            backup_path=backup_path)
    elif isinstance(e, AccessDeniedError):
        return ApplyAlertMessage(QCoreApplication.tr("Access denied while sending files."), detailed_txt="Try running the program with sudo.")
    elif "MBErrorDomain/208" in str(e):
        return ApplyAlertMessage(QCoreApplication.tr("The device is locked. Unlock it and enter its passcode before retrying the backup. Tweaks were not applied."),
                                 detailed_txt="TRACEBACK:\n\n" + traceback_text)
    elif isinstance(e, InvalidServiceError):
        return ApplyAlertMessage(QCoreApplication.tr("The requested device service is unavailable. This error alone does not establish whether Developer Mode is enabled."),
                                 detailed_txt="TRACEBACK:\n\n" + traceback_text)
    elif isinstance(e, FeatureFlagBaselineUnavailable):
        return ApplyAlertMessage(
            QCoreApplication.tr('Feature flag overrides cannot be prepared from this backup. Set feature-flag controls to Not Used before applying other changes.'),
            title=QCoreApplication.tr('Feature flag baseline unavailable'),
            detailed_txt=str(e), backup_path=backup_path,
            exc_type=type(e), exc_value=e)
    elif isinstance(e, NuggetException):
        return ApplyAlertMessage(str(e), detailed_txt=e.detailed_text,
                                 backup_path=backup_path)
    else:
        files_str: str = get_files_list_str(files_list)
        error_msg = type(e).__name__ + ": " + repr(e)
        return ApplyAlertMessage(
            error_msg,
            detailed_txt=files_str + "TRACEBACK:\n\n" + traceback_text,
            backup_path=backup_path
        )

def _selection_store(manager):
    from src.tweaks.store import selection_store
    return selection_store(manager, tweaks)


class DeviceManager:
    ## Class Functions
    @property
    def tweak_store(self):
        selected = getattr(self, "_selected_store", None)
        return selected if selected is not None else tweaks

    def __init__(self, tweak_store=None):
        if tweak_store is not None and not isinstance(tweak_store, Mapping):
            raise TypeError("tweak_store must be a mapping")
        self._selected_store = tweak_store
        self.devices: list[Device] = []
        self.data_singleton = DataSingleton()
        self.current_device_index = 0

        # preferences
        self.pref_manager = PreferenceManager(None)
        
        # Backup password (for encrypted backups)
        self._backup_password: Optional[str] = None

        # Encryption state as last seen by Phase 0's backup (None = not yet
        # known). Lets _apply_tweak_pass skip its own lockdown round-trip on
        # most applies — Phase 0 already paid for the check.
        self._known_backup_encryption: Optional[bool] = None

        # Set when the user chose to continue without data protection (e.g.
        # out of disk space) — Phase 1 must not re-run the protective backup.
        self._protective_backup_skipped = False

        # ETA estimator for the three-phase restore (reset before each restore).
        self._restore_eta = ProgressEta()
        
        # Test mode
        self._test_mode = "--test-mode" in sys.argv
    
    def _get_backup_password(self) -> str:
        """Get backup password from settings or return empty string."""
        if self._backup_password:
            return self._backup_password
        # Try to get from settings
        if self.pref_manager.settings:
            pwd = self.pref_manager.settings.value("backup_password", "", type=str)
            if pwd:
                self._backup_password = pwd
                return pwd
        return ""
    
    def get_devices(self, settings: QSettings, show_alert=lambda x: None):
        # Guard against an unresponsive usbmuxd/lockdown hang blocking startup
        # forever. Enumeration of a handful of devices is normally near-instant,
        # so 60s is a generous ceiling.
        try:
            asyncio.run(asyncio.wait_for(self._get_devices(settings, show_alert), timeout=60))
        except asyncio.TimeoutError:
            self.devices.clear()
            self.set_current_device(index=None)
            show_alert(ApplyAlertMessage(
                txt=QCoreApplication.tr("Getting the device list timed out."),
                detailed_txt=QCoreApplication.tr(
                    "Device enumeration took too long. Check your USB connection and try again.")
            ))
    async def _get_devices(self, settings: QSettings, show_alert=lambda x: None):
        # Test mode: use mock device already set up in main_app.py
        if self._test_mode:
            self.pref_manager.settings = settings
            return
        
        # Keep the selected device stable across a rescan, but only if that
        # same UDID is present in the newly enumerated device list.
        selected_udid = self.get_current_device_udid()
        discovered = []
        # handle errors when failing to get connected devices
        try:
            connected_devices = [
                device for device in await usbmux.list_devices() if device.is_usb
            ]
        except Exception:
            sysmsg = QCoreApplication.tr("If you are on Linux, make sure you have usbmuxd and libimobiledevice installed.")
            if os.name == 'nt':
                sysmsg = QCoreApplication.tr("Make sure you have the \"Apple Devices\" app from the Microsoft Store or iTunes from Apple's website.")
            show_alert(ApplyAlertMessage(
                txt=QCoreApplication.tr("Failed to get device list. Click \"Show Details\" for the traceback.") + f"\n\n{sysmsg}", detailed_txt=str(traceback.format_exc())
            ))
            self.devices = []
            self.set_current_device(index=None)
            return
        unique = {}
        for device in sorted(connected_devices, key=lambda item: not item.is_usb):
            unique.setdefault(device.serial.replace("-", "").casefold(), device)

        async def inspect_device(device):
            try:
                async with lockdown_session(device.serial, pair_timeout=1, connection_type="USB") as ld:
                    # Check backup encryption status if experimental option not enabled
                    if not self.pref_manager.use_encrypted_backup:
                        try:
                            from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
                            mb = Mobilebackup2Service(ld)
                            try:
                                await mb.connect()
                                is_encrypted = await mb.get_will_encrypt()
                            finally:
                                try:
                                    await mb.close()
                                except Exception:
                                    pass
                            if is_encrypted:
                                show_alert(ApplyAlertMessage(
                                    txt=QCoreApplication.tr("Backup encryption is enabled on your iPhone."),
                                    detailed_txt=QCoreApplication.tr(
                                        "GoldenNugget needs to temporarily disable backup encryption to apply tweaks safely.\n\n"
                                        "Please choose one:\n"
                                        "1. Disable encryption on your iPhone: Settings → General → Transfer or Reset iPhone → Backup Password → Turn Off\n"
                                        "2. Or enable \"Use Encrypted Backups (Experimental)\" in GoldenNugget Settings → enter your backup password when prompted.\n\n"
                                        "Tip: Option 1 is simpler if you don't know your backup password."
                                    )
                                ))
                                # skip only this device; the others stay usable
                                return None
                        except Exception:
                            pass  # If we can't check, continue anyway
                    vals = ld.all_values
                    model = vals['ProductType']
                    hardware = vals['HardwareModel']
                    cpu = vals['HardwarePlatform']
                    try:
                        product_type = settings.value(device.serial + "_model", "", type=str)
                        hardware_type = settings.value(device.serial + "_hardware", "", type=str)
                        cpu_type = settings.value(device.serial + "_cpu", "", type=str)
                        if product_type == "":
                            # save the new product type
                            settings.setValue(device.serial + "_model", model)
                        else:
                            model = product_type
                        if hardware_type == "":
                            # save the new hardware model
                            settings.setValue(device.serial + "_hardware", hardware)
                        else:
                            hardware = hardware_type
                        if cpu_type == "":
                            # save the new cpu model
                            settings.setValue(device.serial + "_cpu", cpu)
                        else:
                            cpu = cpu_type
                    except Exception:
                        show_alert(ApplyAlertMessage(txt=QCoreApplication.tr("Click \"Show Details\" for the traceback."), detailed_txt=str(traceback.format_exc())))
                    locale = await ld.get_locale()
                    dev = Device(
                            udid=device.serial,
                            usb=device.is_usb,
                            name=vals['DeviceName'],
                            version=vals['ProductVersion'],
                            build=vals['BuildVersion'],
                            model=model,
                            hardware=hardware,
                            cpu=cpu,
                            locale=locale,
                        )
                    from src.devicemanagement.developer_mode import read_developer_mode
                    try:
                        dev.developer_mode = await read_developer_mode(ld)
                    except Exception:
                        dev.developer_mode = None
                    return dev
            except PasswordRequiredError as e:
                show_alert(ApplyAlertMessage(
                    txt=QCoreApplication.tr("Unlock your iPhone or iPad to connect. Enter the passcode on the device, not on this computer."),
                    exc_type=type(e), exc_value=e))
            except PairingDialogResponsePendingError as e:
                show_alert(ApplyAlertMessage(
                    txt=QCoreApplication.tr("Confirm Trust on your iPhone or iPad. Enter the device passcode there if requested."),
                    exc_type=type(e), exc_value=e))
            except UserDeniedPairingError as e:
                show_alert(ApplyAlertMessage(
                    txt=QCoreApplication.tr("Trust was declined on the device. Reconnect it and confirm Trust to connect."),
                    exc_type=type(e), exc_value=e))
            except MuxException as e:
                # The GUI can treat a temporary reboot disconnect separately
                # from a persistent connection failure when it has the cause.
                show_alert(ApplyAlertMessage(txt="MuxException: " + repr(e) + "\n\n" + QCoreApplication.tr("If you keep receiving this error, try using a different cable or port."),
                               detailed_txt=str(traceback.format_exc()), exc_type=type(e), exc_value=e))
            except Exception as e:
                print(f"ERROR with lockdown device with UUID {device.serial}")
                show_alert(ApplyAlertMessage(txt=f"{type(e).__name__}: {repr(e)}", detailed_txt=str(traceback.format_exc()),
                                            exc_type=type(e), exc_value=e))
        
        semaphore = asyncio.Semaphore(3)
        async def bounded_inspect(device):
            async with semaphore:
                try:
                    return await asyncio.wait_for(inspect_device(device), timeout=15)
                except asyncio.TimeoutError:
                    show_alert(ApplyAlertMessage(txt=QCoreApplication.tr("Getting the device list timed out.") + f" ({device.serial})"))
                    return None
        results = await asyncio.gather(*(bounded_inspect(device) for device in unique.values()))
        discovered = [device for device in results if device is not None]

        self.devices = discovered
        if len(self.devices) > 0:
            selected_index = next(
                (index for index, device in enumerate(self.devices)
                 if device.udid == selected_udid),
                0,
            )
            self.set_current_device(index=selected_index)
        else:
            self.set_current_device(index=None)

    ## CURRENT DEVICE
    def set_current_device(self, index: int = None):
        if index == None or len(self.devices) == 0:
            self.data_singleton.current_device = None
            self.data_singleton.device_available = False
            self.current_device_index = 0
        else:
            self.data_singleton.current_device = self.devices[index]
            if not is_supported_by_fork(self.devices[index].version):
                # hard-block old versions (< 26.2): the device is listed so the
                # user sees it, but every action is refused.
                self.data_singleton.device_available = False
            else:
                self.data_singleton.device_available = True
            self.current_device_index = index
        
    def get_current_device_name(self) -> str:
        device = self.data_singleton.current_device
        return device.name if device != None else QCoreApplication.tr("No Device")

    def get_current_device_version(self) -> str:
        device = self.data_singleton.current_device
        return device.version if device != None else ""

    def get_current_device_build(self) -> str:
        device = self.data_singleton.current_device
        return device.build if device != None else ""

    def get_current_device_udid(self) -> Optional[str]:
        device = self.data_singleton.current_device
        return device.udid if device != None else None

    def get_current_device_model(self) -> str:
        device = self.data_singleton.current_device
        return device.model if device != None else ""

    def get_current_device_is_supported_by_fork(self) -> bool:
        device = self.data_singleton.current_device
        return is_supported_by_fork(device.version) if device != None else False

    def get_current_device_partially_supported(self) -> bool:
        """iOS 27 devices use the experimental three-phase protective restore."""
        device = self.data_singleton.current_device
        if device == None:
            return False
        try:
            return Version(device.version) >= Version("27.0")
        except Exception:
            return False
        
    async def _reset_device_pairing(self):
        # first, unpair it
        if self.data_singleton.current_device is None:
            raise NuggetException("No device is selected. Connect the device before resetting pairing.")
        async with lockdown_session(self.data_singleton.current_device.udid) as ld:
            await ld.unpair()
            # next, pair it again
            await ld.pair()

    async def add_skip_setup(self, files_to_restore: list[FileToRestore], restoring_domains: bool):
        # TODO: Probably should move this to its own file
        # Build the cloud config with the same single-source builder that iOS 27
        # pushes natively (skip_all_setup27), so iOS 26's Phase 2 sparse restore
        # carries the byte-identical CloudConfigurationDetails.plist. On iOS 26
        # (MBDB sparse restore) every file is delivered through a real domain —
        # files with an empty domain are dropped during the restore. The
        # skip-setup plists always carry real domains, so they can always ride
        # the domain delivery on iOS 26, even when the selected tweaks are basic
        # plist tweaks that never set ``restoring_domains``.
        dev_version = self.get_current_device_version()
        if (self.pref_manager.skip_setup and dev_version
                and Version(dev_version) < Version("27.0")):
            # get the already existing cloud config info
            async with lockdown_session(self.data_singleton.current_device.udid) as ld:
                async with MobileConfigService(lockdown=ld) as mcs:
                    existing = await mcs.get_cloud_configuration()
            cloud_config_plist = build_cloud_config(
                existing,
                supervised=self.pref_manager.supervised,
                organization_name=self.pref_manager.organization_name)
            # add the 2 skip setup files
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(cloud_config_plist),
                restore_path="Library/ConfigurationProfiles/CloudConfigurationDetails.plist",
                domain="SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles"
            ))
            purplebuddy_plist: dict = {
                "SetupDone": True,
                "SetupFinishedAllSteps": True,
                "UserChoseLanguage": True
            }
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(purplebuddy_plist),
                restore_path="mobile/com.apple.purplebuddy.plist",
                domain="ManagedPreferencesDomain"
            ))

    def get_domain_for_path(self, path: str, owner: int = 501) -> str:
        # returns Domain: str?, Path: str
        from src.restore.path_mapping import split_path_into_domain

        mobile_domain, rel_path = split_path_into_domain(path)
        if mobile_domain is None:
            return path, ""
        return rel_path, mobile_domain
    
    def concat_file(self, contents: str, path: str, files_to_restore: list[FileToRestore], owner: int = 501, group: int = 501):
        # TODO: try using inodes here instead
        file_path, domain = self.get_domain_for_path(path, owner=owner)
        files_to_restore.append(FileToRestore(
            contents=contents,
            restore_path=file_path,
            domain=domain,
            owner=owner, group=group
        ))
    
    ## APPLYING OR REMOVING TWEAKS AND RESTORING
    def _raise_if_unsupported(self):
        if not self.get_current_device_is_supported_by_fork():
            raise NuggetException(QCoreApplication.tr(
                "This version of iOS is not supported by this fork.\n\n"
                "GoldenNugget only supports iOS 26.2 and newer. "
                "Please use the original Nugget for iOS 26.1 and earlier."))

    async def start_restore(self, files_to_restore: list[FileToRestore], update_label=lambda x: None, backup_password: str = "", prepared_backup_root: str = None, skip_protective_backup: bool = False, include_keychain: bool = False, prompt_choice=None, supervised: bool = False, organization_name: str = ""):
        # hard-block any restore on an unsupported (old) iOS version
        tweaks = _selection_store(self)
        self._raise_if_unsupported()
        self.update_label = update_label
        self._restore_eta.reset()
        self.do_not_unplug = ""
        if self.data_singleton.current_device.connected_via_usb:
            self.do_not_unplug = "\n" + QCoreApplication.tr("DO NOT UNPLUG")
        # Use manual try/finally instead of async with so that ld.close()
        # errors (e.g. ConnectionTerminatedError after device reboot) do not
        # propagate as a misleading "Connection Lost" error to the UI.
        # lockdown_session suppresses close() errors the same way.
        async with lockdown_session(self.data_singleton.current_device.udid) as ld:
            if not self.get_current_device_partially_supported():
                self._report_operation_stage("tweaks")
            update_label(QCoreApplication.tr("Preparing to restore...") + self.do_not_unplug)
            from src.restore.inject import (preference_baseline_creates,
                                            preference_baseline_skips,
                                            preference_delivery_warnings)
            delivery_warnings = []
            baseline_skips = []
            baseline_creates = []
            warning_token = preference_delivery_warnings.set(delivery_warnings)
            skip_token = preference_baseline_skips.set(baseline_skips)
            create_token = preference_baseline_creates.set(baseline_creates)
            try:
                await restore_files(
                    files=files_to_restore, reboot=self.pref_manager.auto_reboot,
                    lockdown_client=ld,
                    progress_callback=self.progress_callback,
                    backup_password=backup_password,
                    prepared_backup_root=prepared_backup_root,
                    skip_protective_backup=skip_protective_backup,
                    include_keychain=include_keychain,
                    prompt_choice=prompt_choice,
                    afc_media=afc_media_enabled(self.pref_manager.use_afc_media),
                    supervised=supervised,
                    organization_name=organization_name,
                    stage_callback=self._report_operation_stage,
                )
            finally:
                preference_delivery_warnings.reset(warning_token)
                preference_baseline_skips.reset(skip_token)
                preference_baseline_creates.reset(create_token)
            tweaks[TweakID.PosterBoard].config_manager.save_staged_ids(self.get_current_device_udid())
            if tweaks[TweakID.PosterBoard].full_reset:
                # the on-device PosterBoard container was wiped — the stale
                # locally-saved database and wallpaper IDs no longer match the
                # empty DB, so drop them or the next apply rebuilds ghosts.
                PreferenceManager.remove_pbconfig_data(self.get_current_device_udid())
                tweaks[TweakID.PosterBoard].config_manager.saved_items = []
                tweaks[TweakID.PosterBoard].config_manager.database = None
                tweaks[TweakID.PosterBoard].config_manager.staged_database = None
                tweaks[TweakID.PosterBoard].resetModes = []
                tweaks[TweakID.PosterBoard].full_reset = False
            msg = QCoreApplication.tr("Your device will now restart.\n\nRemember to turn Find My back on!")
            if not self.pref_manager.auto_reboot:
                msg = QCoreApplication.tr("Please restart your device to see changes.")
            if delivery_warnings:
                msg += QCoreApplication.tr(
                    "\n\nManaged preference baselines were unavailable for: {0}. "
                    "Only identical native preference edits were delivered; managed files were left untouched. "
                    "Some tweak effects may differ or not work.").format(', '.join(sorted(set(delivery_warnings))))
            if baseline_skips:
                msg += QCoreApplication.tr(
                    "\n\nPreference tweaks were skipped because the backup did not contain current baselines for: {0}. "
                    "Those preferences were left unchanged; other selected changes were applied.").format(
                        ', '.join(sorted(set(baseline_skips))))
            if baseline_creates:
                msg += QCoreApplication.tr(
                    "\n\nThe backup had no existing settings file for: {0}. "
                    "It was created new with only the selected tweaks' settings, "
                    "like on a device that never had that file.").format(
                        ', '.join(sorted(set(baseline_creates))))
            return ApplyAlertMessage(txt=QCoreApplication.tr("All done! ") + msg, title=QCoreApplication.tr("Success!"), icon=QMessageBox.Information)

    def _report_operation_stage(self, stage, category=""):
        if stage != getattr(self, "_progress_stage", None):
            self._progress_stage = stage
            if hasattr(self, "_restore_eta"):
                self._restore_eta.reset()
        callback = getattr(self, "operation_stage_callback", None)
        if callback is not None:
            callback(stage, category)

    def progress_callback(self, progress):
        if self.update_label == None:
            return
        if isinstance(progress, str):
            from src.devicemanagement.progress_status import BackupStatus, OperationStatus
            if isinstance(progress, BackupStatus):
                self._report_operation_stage("backup", progress.category)
            elif isinstance(progress, OperationStatus):
                stage = getattr(self, "_progress_stage", "restore")
                self._report_operation_stage(stage, "" if progress.category == "transfer_ready" else progress.category)
                self._restore_eta.reset()
            if getattr(self, "_progress_stage", None) == "media":
                import re
                match = re.search(r"(\d+(?:\.\d+)?)%", progress)
                if match:
                    remaining = self._restore_eta.update(float(match.group(1)))
                    if remaining:
                        progress += "\n" + QCoreApplication.tr("Time Left: {0}").format(remaining)
            self.update_label(progress)
            return
        if getattr(self, "_progress_stage", None) == "setup" and progress is not None and progress < 100:
            self.update_label(QCoreApplication.tr("Finishing setup…") + self.do_not_unplug)
            return
        prog = ""
        if progress != None:
            prog = f" ({round(progress):d}%)"
            remaining = self._restore_eta.update(progress)
        else:
            remaining = ""
        stage_label = {
            "backup": QCoreApplication.tr("Backing up device data…"),
            "tweaks": QCoreApplication.tr("Applying changes…"),
            "media": QCoreApplication.tr("Restoring photos & videos…"),
        }.get(getattr(self, "_progress_stage", None), QCoreApplication.tr("Restoring to device…"))
        label = stage_label + prog + self.do_not_unplug
        if remaining:
            label += "\n" + QCoreApplication.tr("Time Left: {0}").format(remaining)
        self.update_label(label)
    def _backup_progress(self, update_label, backup_path=None):
        """Progress callback for the pre-restore device backups.

        Unlike ``progress_callback`` it does not depend on ``self.update_label``
        (only set by ``start_restore``), so it is safe to call before any
        restore has started. Status strings pass through as labels; anything
        that is not a number is dropped so the bar never sees garbage.
        """
        eta = ProgressEta()
        current_stage = [QCoreApplication.tr("Backing up device data...")]
        last_space_check = [0.0]
        warned_low_space = [False]
        low_space_note = [""]

        def _cb(progress):
            if isinstance(progress, str):
                from src.devicemanagement.progress_status import BackupStatus
                from src.devicemanagement.progress_status import OperationStatus
                if isinstance(progress, OperationStatus):
                    category = "backup" if progress.category == "transfer_ready" else progress.category
                    self._report_operation_stage("backup", category)
                    if category == "authentication":
                        eta.reset()
                current_stage[0] = progress
                update_label(progress)
                return
            if isinstance(progress, bool) or not isinstance(progress, (int, float)):
                return
            label = QCoreApplication.tr("{0} ({1}%)").format(
                current_stage[0], round(progress))
            if backup_path:
                import shutil
                import time
                now = time.monotonic()
                if now - last_space_check[0] >= 5:
                    last_space_check[0] = now
                    try:
                        free = shutil.disk_usage(backup_path).free
                        from src.restore.protective import _min_free_disk_bytes
                        if free < _min_free_disk_bytes() and not warned_low_space[0]:
                            warned_low_space[0] = True
                            low_space_note[0] = QCoreApplication.tr(
                                "Low computer storage: {0:.1f} GB free. Free space now; the backup may fail if storage runs out.").format(free / (1024 ** 3))
                    except OSError:
                        pass
            remaining = eta.update(progress)
            if remaining:
                label += "\n" + QCoreApplication.tr("Time Left: {0}").format(remaining)
            if low_space_note[0]:
                label += "\n" + low_space_note[0]
            update_label(label)
        return _cb
    def _disable_unavailable_controls(self, update_label):
        tweaks = _selection_store(self)
        from src.gui.ios.compat import compatibility_reasons
        from src.tweaks.registry import SPECS_BY_ID

        version = self.get_current_device_version()
        model = self.get_current_device_model() or ""
        unavailable = set()
        disabled = []
        for tweak_id, spec in SPECS_BY_ID.items():
            reasons = compatibility_reasons(tweak_id, version, model)
            if not reasons:
                continue
            unavailable.add(tweak_id)
            tweak = tweaks.get(tweak_id)
            if tweak is not None and tweak.enabled:
                tweak.set_enabled(False)
                disabled.append(spec.title)
                log_info(f"Skipped unavailable control {spec.title}: {'; '.join(reasons)}")

        daemon = tweaks.get(TweakID.Daemons)
        if daemon is not None and isinstance(daemon.value, dict):
            filtered = daemon._filter_keys(daemon.value)
            removed = set(daemon.value) - set(filtered)
            if removed:
                daemon.set_value(filtered, toggle_enabled=False)
                disabled.extend(sorted(removed))
                log_info(f"Removed unsupported or protected daemon selections: {', '.join(sorted(removed))}")
        if disabled:
            update_label(QCoreApplication.tr("Unavailable options turned off: ") + ", ".join(disabled))
        return unavailable

    def apply_changes(self, update_label=lambda x: None, show_alert=lambda x: None, prompt_password=None, prompt_choice=None):
        return asyncio.run(self._apply_changes(update_label, show_alert, prompt_password, prompt_choice))
    async def _apply_changes(self, update_label=lambda x: None, show_alert=lambda x: None, prompt_password=None, prompt_choice=None):
        tweaks = _selection_store(self)
        files_to_restore: list[FileToRestore] = []
        final_alert = None
        self._last_operation_preview = None
        pb = tweaks[TweakID.PosterBoard]
        original_tendies = list(pb.tendies)
        try:
            self._raise_if_unsupported()
            self._disable_unavailable_controls(update_label)
            from src.tweaks.registry import SPECS, Kind
            from math import isfinite
            device_version = Version(self.get_current_device_version())
            device_model = self.get_current_device_model() or ""
            for spec in SPECS:
                selected = tweaks.get(spec.id)
                if not spec.experimental or selected is None or not selected.enabled:
                    continue
                if spec.unavailable_reason:
                    raise NuggetException(f"{spec.title}: {spec.unavailable_reason}")
                if spec.bundle_identifier:
                    from src.tweaks.preference_validation import valid_bundle_identifier
                    if not valid_bundle_identifier(selected.value):
                        raise NuggetException(f"Enter a valid app bundle identifier for {spec.title}, or clear the field.")
                if (hardware_reasons(spec, device_model)
                        or (spec.min_version and device_version < Version(spec.min_version))):
                    raise NuggetException(f"{spec.title} is not available for the connected device.")
                required_options = spec.requires if spec.kind != Kind.NUMBER or selected.value != spec.value else ()
                for required in required_options:
                    dependency = tweaks.get(required)
                    if dependency is None or not dependency.enabled:
                        raise NuggetException(
                            f"Enable {next(item.title for item in SPECS if item.id == required)} before applying {spec.title}.")
                peer = tweaks.get(spec.exclusive_with)
                if peer is not None and peer.enabled:
                    raise NuggetException(f"{spec.title} cannot be combined with {next(item.title for item in SPECS if item.id == spec.exclusive_with)}.")
                if spec.kind == Kind.NUMBER:
                    value = selected.value
                    if (isinstance(value, bool) or not isinstance(value, (int, float))
                            or not isfinite(value) or not spec.min_value <= value <= spec.max_value
                            or (spec.reset_value is not None and value < 0 and value != spec.reset_value)
                            or (float(spec.step).is_integer() and not float(value).is_integer())):
                        raise NuggetException(f"Enter a valid value for {spec.title} before applying.")
            experiment = tweaks.get(TweakID.DisableSystemAperture)
            if experiment is not None and experiment.enabled:
                if (Version(self.get_current_device_version()).major != 27
                        or not self.get_current_device_model().startswith("iPhone")):
                    raise NuggetException("The Dynamic Island availability experiment requires an iPhone on iOS 27.")
                if tweaks[TweakID.HideDICompletely].enabled:
                    raise NuggetException("Turn off Disable Dynamic Island before testing Dynamic Island Availability. Test one option at a time.")
            self._report_operation_stage("prepare")
            posterkit=tweaks.get(TweakID.PosterKitOverrides)
            if posterkit is not None and posterkit.enabled and posterkit.value:
                from src.restore.protective import is_backup_encrypted
                from src.devicemanagement.session import lockdown_session
                from src.exceptions.nugget_exception import PosterBoardBackupEncryptionError
                async with lockdown_session(self.get_current_device_udid()) as client:
                    if await is_backup_encrypted(client):
                        raise PosterBoardBackupEncryptionError(
                            'PosterKit archive editing cannot extract encrypted device backups in this build. '
                            'No backup or injection started. Do not disable encryption to bypass this check.')
            update_label(QCoreApplication.tr("Applying changes to files..."))
            self._protective_backup_skipped = False
            self._known_backup_encryption = None  # re-established by Phase 0

            # iOS 26.2+ (iOS 27 era) uses the heavy three-phase protective restore
            pb.tendies = original_tendies[:MAX_TENDIES_PER_RESTORE]

            needs_posterboard = not (
                len(pb.tendies) == 0 and pb.videoFile is None
                and len(tweaks[TweakID.Templates].templates) == 0)
            log_info(f'needs_posterboard={needs_posterboard}, tendies={len(pb.tendies)}, videoFile={pb.videoFile is not None}')

            # Phase 0: protective backup.
            #  - iOS 27+ (partial support): the heavy backup is built and later
            #    restored (Phase 1/3) to survive the security-recovery wipe. It
            #    also carries the PosterBoard sqlite when wallpapers are pending.
            #  - iOS 26.x: the apply is a plain sparse restore (no wipe, no Phase
            #    3), so NO Phase 0 runs here at all — PosterBoard delivery
            #    happens through the targeted PosterBoard-only backup below.
            prepared_root = None
            pb_from_cache = False
            raw_sparse = os.environ.get("GOLDENNUGGET_NO_PROTECTIVE_BACKUP") == "1"
            if raw_sparse:
                # Kill switch: straight raw sparse pass, no protective backup at
                # any phase. The whole Phase 0 is skipped — no live backup, no
                # cache, no PosterBoard delivery. Flip everything below to the
                # no-protection path.
                log_warn("GOLDENNUGGET_NO_PROTECTIVE_BACKUP=1 — raw sparse: "
                         "skipping Phase 0 protective backup entirely "
                         "(no data protection)")
                self._protective_backup_skipped = True
            partially_supported = self.get_current_device_partially_supported()
            should_prepare = partially_supported and not raw_sparse
            if should_prepare:
                self._report_operation_stage("backup")
                # On NotEnoughDiskSpaceError the user can choose to continue
                # without it — tweaks still apply, but there is no data
                # protection (photos/settings get wiped).
                try:
                    prepared_root, pb_from_cache = await self._prepare_protective_backup(
                        update_label, needs_posterboard=needs_posterboard,
                        prompt_password=prompt_password)
                except Exception as e:
                    log_error(f"Protective backup failed: {type(e).__name__}: {e}")
                    from pymobiledevice3.exceptions import NotEnoughDiskSpaceError
                    if isinstance(e, (BackupStorageError, NotEnoughDiskSpaceError)):
                        # The Yes/No decision must be asked on the main thread
                        # (this runs on ApplyThread — a QMessageBox here is a
                        # cross-thread-widget bug). Relay via ``prompt_choice``;
                        # "resume" == continue without protection, "abort" ==
                        # refuse. Without a callback (headless) default to abort.
                        if prompt_choice is None:
                            log_warn("Protective backup failed (disk space) and no "
                                     "prompt_choice callback — aborting apply")
                            return
                        decision = prompt_choice(
                            QCoreApplication.tr("Not Enough Disk Space"),
                            QCoreApplication.tr(
                                "The protective backup reported a storage error:\n{0}\n\n"
                                "Continue anyway WITHOUT data protection?\n"
                                "(Photos, settings and app data may be lost.)").format(str(e)))
                        if decision == "resume":
                            log_warn("User chose to continue without protective backup")
                            self._report_operation_stage("backup", "skipped")
                            prepared_root = None
                            pb_from_cache = False
                            self._protective_backup_skipped = True
                        else:
                            return
                    else:
                        raise
            else:
                log_info("Phase 0 skipped: no iOS 27 protective restore required")

            # PosterBoard delivery:
            #  - iOS 27+: the sqlite normally rides the Phase 0 backup (extracted
            #    inside _prepare_protective_backup); when it could not be read out
            #    of it (device rejected the container / encrypted backup), this
            #    targeted PosterBoard-only backup runs as the fallback.
            #  - iOS 26.x: no Phase 0 at all, so this targeted backup IS the
            #    delivery channel — tiny and fast, no full device backup.
            if needs_posterboard and not pb_from_cache and not raw_sparse:
                if os.environ.get("GOLDENNUGGET_SKIP_PB_BACKUP"):
                    log_warn("GOLDENNUGGET_SKIP_PB_BACKUP=1 set; skipping PosterBoard DB fetch")
                else:
                    self._report_operation_stage("backup", "wallpaper")
                    await self._backup_posterboard_database(update_label, force=True)

            self._apply_hotload_daemon_forcing()

            from src.controllers.apply_preview import safe_capture_preview, write_preview
            preview = safe_capture_preview(self)
            preview_udid = self.get_current_device_udid()
            preview_version = self.get_current_device_version()
            final_alert, files_to_restore = await self._apply_tweak_pass(
                update_label,
                templates=tweaks[TweakID.Templates].templates,
                prepared_backup_root=prepared_root,
                prompt_password=prompt_password,
                prompt_choice=prompt_choice,
                skip_protective_backup=self._protective_backup_skipped,
            )
            # Record what just got applied so a later "unchanged tweaks +
            # added wallpapers only" apply can skip the Phase 2 sparse pass.
            from src.restore.lastapply import sparse_signature, write_lastapply
            udid = self.get_current_device_udid()
            if udid:
                write_lastapply(udid, sparse_signature(files_to_restore))
                from src.tweaks.posterboard.community_tweaks import write_record
                community = getattr(self, "_last_community_writes", None)
                if isinstance(community, tuple) and len(community) == 2:
                    write_record(udid, *community)
            write_preview(preview_udid, preview_version, preview)
            self._last_operation_preview = preview
            if preview is not None:
                preview['skipped_packages'] = [item.name for item in original_tendies[MAX_TENDIES_PER_RESTORE:]]
            update_label(QCoreApplication.tr("Success!"))
            return True
        except ApplyCancelledError:
            raise
        except Exception as e:
            final_alert = show_apply_error(e, update_label, files_list=files_to_restore)
            return False
        finally:
            pb.tendies = original_tendies
            if final_alert is not None:
                show_alert(final_alert)

    def _apply_hotload_daemon_forcing(self):
        """HotLoad "disable_daemon" rules: force their daemons into the
        disabled-daemons plist for this exact apply, regardless of the UI
        toggles or whatever a loaded preset said. Runs right before the
        tweak pass so the forced keys ride along with every apply."""
        tweaks = _selection_store(self)
        try:
            dm_settings = getattr(getattr(self, "pref_manager", None), "settings", None)
            hotload = HotLoad(dm_settings)
            forced = hotload.disabled_daemon_keys(
                device_version=self.get_current_device_version(),
                device_model=self.get_current_device_model())
            if not forced:
                return
            from src.tweaks.tweak_loader import load_daemons
            load_daemons()
            daemons_tweak = tweaks.get(TweakID.Daemons)
            if daemons_tweak is None:
                return
            # Safety rules are authoritative: the forced keys must reach the
            # plist regardless of the interface whitelist (a rule may name a
            # daemon with no UI switch, e.g. ScreenTime). Extend allowed_keys
            # so set_multiple_values and the apply-pass filter both let them
            # through, then toggle them on.
            daemons_tweak.allowed_keys.update(forced)
            daemons_tweak.set_multiple_values(sorted(forced), value=True)
            log_info(f"[HotLoad] daemons force-disabled by safety rules: "
                     f"{', '.join(sorted(forced))}")
        except Exception as e:
            log_warn(f"[HotLoad] daemon forcing failed: {e}")

    async def _prepare_protective_backup(self, update_label=lambda x: None,
                                         needs_posterboard: bool = False,
                                         prompt_password=None,
                                         force_standard_media=False) -> tuple:
        """Phase 0: build the protective backup that Phase 3 will restore.

        Wraps ``_build_protective_backup`` and refuses to hand back a backup that
        has no verified copy of the photos. See that method for the two modes;
        this wrapper exists so the media gate cannot be bypassed by one of the
        several return paths inside it.
        """
        prepared, pb_ok = await self._build_protective_backup(
            update_label, needs_posterboard, prompt_password,
            force_standard_media=force_standard_media)
        media_src = getattr(prepared, "media_src", "") if prepared else ""
        media_verified = not media_src or await asyncio.to_thread(media_store_verified, media_src)
        if not media_verified:
            log_warn("AFC media backup could not be verified; creating a fresh standard backup with photos included. Existing backups will be retained.")
            update_label(QCoreApplication.tr("Photo backup over AFC could not be verified. Backing up photos and device data through the standard backup service…"))
            self._report_operation_stage("backup", "photos")
            prepared, pb_ok = await self._build_protective_backup(
                update_label, needs_posterboard, prompt_password,
                force_standard_media=True)
            media_src = getattr(prepared, "media_src", "") if prepared else ""
            media_verified = not media_src or await asyncio.to_thread(media_store_verified, media_src)
        self._require_media_copy(prepared, media_verified=media_verified)
        return prepared, pb_ok

    @staticmethod
    def _require_media_copy(prepared, *, media_verified=None) -> None:
        """Abort before the wipe if the photos are not safely on this computer.

        When the AFC media channel carries the bulk photo trees, those trees are
        NOT in the backup — the media store is their only copy once the device
        is wiped. An unverified store (never pulled, interrupted pull, cancelled
        parallel task) must stop the apply here, while the device is still
        intact, instead of letting Phase 5 push a fragment and report success.
        """
        media_src = getattr(prepared, "media_src", "") if prepared else ""
        if not media_src:
            return
        if media_verified is None:
            media_verified = media_store_verified(media_src)
        if media_verified:
            return
        raise NuggetException(
            f"The photos/videos could not be fully backed up "
            f"({describe_media_store(media_src, verified=False)}). Applying tweaks would wipe "
            f"the device with no complete copy of the media, so it was stopped "
            f"before anything was changed. The media backup could not be verified. "
            f"Check the application log; the backup cache can be refreshed from "
            f"the pre-apply summary.")

    async def _build_protective_backup(self, update_label=lambda x: None,
                                        needs_posterboard: bool = False,
                                        prompt_password=None, force_standard_media: bool = False) -> tuple:
        """Build the protective backup (LIVE or cached master) — see above.
    
        Two modes:

        * LIVE (default): runs a fresh ``perform_protective_backup`` right now,
          always including the PosterBoard container when wallpapers are being
          applied — so ``extract_posterboard_db`` yields the fresh sqlite and the
          config manager builds new wallpapers on top of the current on-device
          state. No caching involved.
    
        * CACHE (EXPERIMENTAL, off by default): reuses/refreshes the persistent
          per-device master ("Use Fast Backup Cache (Experimental)" in Settings).
          The master always refreshes before apply/reset, including when it was
          just created, so recently changed device preferences are captured.
    
Returns (PreparedBackup, posterboard_db_ok). When the PosterBoard
        container cannot be read out of the backup the caller falls back to the
        targeted ``_backup_posterboard_database``. Returns (None, False)
        only when there is no UDID at all.

        iOS 26 applies never take this path: their restore is a plain sparse
        pass, so the heavy backup serves no purpose there — PosterBoard
        delivery goes through ``_backup_posterboard_database`` instead.
        """
        tweaks = _selection_store(self)
        udid = self.get_current_device_udid()
        if not udid:
            return None, False
    
        from src.restore.protective import (
            PreparedBackup, extract_posterboard_db, is_backup_encrypted,
            new_protective_backup_dir, perform_protective_backup,
            prune_protective_backups)
    
        def _register_pb_db(backup_root: str) -> bool:
            """Extract the fresh PosterBoard sqlite and register it for editing.
    
            Returns False (so the legacy separate backup still runs) when the
            container is missing from the backup or the DB is unusable.
            """
            if not needs_posterboard or os.environ.get("GOLDENNUGGET_SKIP_PB_BACKUP"):
                return True
            import tempfile as _tempfile
            pb = tweaks[TweakID.PosterBoard]
            with _tempfile.TemporaryDirectory(prefix="nugget_pbdb_") as tmp_dir:
                # the extraction can also RAISE now (torn database copy), so it
                # belongs in this try — a bad copy must fall back to the separate
                # backup, never abort the apply
                try:
                    db_path_and_version = extract_posterboard_db(
                        backup_root, udid, os.path.join(tmp_dir, "posterboard.sqlite3"))
                    if db_path_and_version is None:
                        log_warn("PosterBoard DB missing from the protective backup — "
                                 "falling back to a separate backup")
                        return False
                    db_path, structure_version = db_path_and_version
                    if not pb.config_manager.update_database_file(
                            db_path, udid, structure_version=structure_version):
                        raise NuggetException("The PosterBoard database is not of the correct format!")
                    pb.config_manager.update_for_saved_database(udid)
                    update_label(QCoreApplication.tr("PosterBoard database backed up successfully."))
                except NuggetException as e:
                    log_warn(f"PosterBoard DB unusable ({e}) — falling back to a separate backup")
                    return False
            return True
    
        async def _live_backup(lc) -> tuple:
            """Fresh protective backup (no cache) with the PosterBoard container
            riding along whenever wallpapers are about to be applied.

            When the AFC media channel is enabled (``use_afc_media`` pref,
            off via ``GOLDENNUGGET_NO_AFC_MEDIA=1``), photos/videos are pulled
            over AFC in parallel with the mobilebackup2 backup; the backup then
            carries only the non-media protective scope. Either way the media
            dir is recorded on the PreparedBackup so Phase 3 pushes it back.
            """
            # Persistent, one directory per run. Once Phase 2 wipes the device
            # this backup is the ONLY copy of the user's photos, Apple ID and
            # settings, so it must survive a reboot and must never be swept as
            # a temp leftover. A fresh directory per run also means a failed
            # backup cannot damage the previous run's copy.
            backup_root = new_protective_backup_dir(udid)
            use_afc_media = not force_standard_media and afc_media_enabled(self.pref_manager.use_afc_media)
            update_label(QCoreApplication.tr("Backing up device..."))
            # include_keychain is left None (auto) so it follows the device's
            # live encryption state — one less round-trip before the backup.
            try:
                is_encrypted = await perform_protective_backup(
                    lc, backup_root, progress_callback=self._backup_progress(update_label, backup_root),
                    include_photos=True, include_posterboard=needs_posterboard,
                    include_keychain=None, include_afc_media=use_afc_media)
            except Exception:
                # A failed run carries no/useless Manifest.db, so
                # list_protective_backups excludes it and prune would never
                # reclaim it — remove the partial dir right here.
                shutil.rmtree(backup_root, ignore_errors=True)
                raise
            # Only retire the previous run once this one is solid — pruning
            # early would delete the last good backup before the new run exists.
            if not force_standard_media:
                prune_protective_backups(udid)
            self._known_backup_encryption = is_encrypted
            media_src = afc_media_dir_for(backup_root) if use_afc_media else ""
            log_info(f"Phase 0: live protective backup ready (always fresh; "
                     f"PosterBoard container {'included' if needs_posterboard else 'not needed'}; "
                     f"keychain {'included' if is_encrypted else 'excluded (backup not encrypted)'}; "
                     f"media via {'AFC' if use_afc_media else 'mobilebackup2'})")
            prepared = PreparedBackup(root=backup_root, manifest_password="",
                                      master=False, media_src=media_src)
            if needs_posterboard and is_encrypted:
                log_warn("Encrypted backup cannot yield a readable PosterBoard DB — "
                         "falling back to a separate backup")
                return prepared, False
            return prepared, _register_pb_db(backup_root)

        cache_enabled = (not force_standard_media and self.pref_manager.use_backup_cache
                         and not os.environ.get("GOLDENNUGGET_NO_BACKUP_CACHE"))

        async with lockdown_session(udid) as lc:
            if needs_posterboard and await is_backup_encrypted(lc):
                from src.exceptions.nugget_exception import PosterBoardBackupEncryptionError
                raise PosterBoardBackupEncryptionError(
                    'PosterBoard changes need extraction of an encrypted backup, which this build does not support. '
                    'No backup or injection was started. Repeating the backup cannot fix this. '
                    'Leave PosterBoard changes out of this apply; do not disable backup encryption to bypass this check.')
            if not cache_enabled:
                log_info("Protective backup cache is an experimental feature and is "
                         "off — running a fresh live protective backup instead")
                return await _live_backup(lc)

            # --- EXPERIMENTAL cache path ---
            use_afc_media = not force_standard_media and afc_media_enabled(self.pref_manager.use_afc_media)
            encrypted = await is_backup_encrypted(lc)
            self._known_backup_encryption = encrypted
            manifest_password = ""
            if encrypted:
                if prompt_password is None:
                    log_info("No password prompt available — bypassing the protective backup cache")
                    return await _live_backup(lc)
                update_label(QCoreApplication.tr("Backup encryption is enabled. Enter your backup password to use the fast cached backup:"))
                password = prompt_password(
                    QCoreApplication.tr("Backup Encryption Password"),
                    QCoreApplication.tr("Enter your iTunes/Finder backup password (used locally to prepare the cached backup):"))
                if not password:
                    log_info("No backup password provided — bypassing the protective backup cache")
                    return await _live_backup(lc)
                manifest_password = password
                self._backup_password = password  # reuse it for the Phase 3 restore prompt
            from src.restore.protective import ProtectiveBackupCache
            cache = ProtectiveBackupCache(udid, product_version=self.get_current_device_version(),
                                          encrypted=encrypted)
            cache.locate()
            update_label(QCoreApplication.tr("Refreshing current device settings and backup..."))
            master_root = await cache.refresh(
                lc, progress_callback=self._backup_progress(update_label, str(cache.master_root)),
                include_photos=True, include_posterboard=needs_posterboard,
                include_keychain=encrypted,
                include_afc_media=use_afc_media)

            media_src = str(cache.media_dir) if use_afc_media else ""
            prepared = PreparedBackup(root=master_root, manifest_password=manifest_password,
                                      master=True, view_root=str(cache.view_root),
                                      media_src=media_src)
            if needs_posterboard and encrypted:
                log_warn("Encrypted cache cannot yield a readable PosterBoard DB — "
                         "falling back to a separate backup")
                return prepared, False
            # The cache path above always refreshes the master (with the
            # PosterBoard container when wallpapers are pending), so the fresh
            # master is always a valid source for the PosterBoard DB.
            return prepared, _register_pb_db(master_root)

    async def refresh_backup_cache(self, update_label=lambda x: None) -> str:
        """Force a refresh of the backup cache master for the current device.

        Runs the same incremental master refresh + AFC media diff as an apply
        would, without applying any tweaks. Used by the pre-apply summary's
        "Update Cache" action so the user can freshen the cache (and from
        which date it will be reused) before confirming. Raises NuggetException
        when there is no device or the cache is disabled.
        """
        udid = self.get_current_device_udid()
        if not udid:
            raise NuggetException("No device selected.")
        cache_enabled = (self.pref_manager.use_backup_cache
                         and not os.environ.get("GOLDENNUGGET_NO_BACKUP_CACHE"))
        if not cache_enabled:
            raise NuggetException(
                "The backup cache is disabled. Enable 'Use Fast Backup Cache "
                "(Experimental)' in Settings → Backup first.")

        from src.restore.protective import (
            ProtectiveBackupCache, is_backup_encrypted)
        use_afc_media = afc_media_enabled(self.pref_manager.use_afc_media)
        async with lockdown_session(udid) as lc:
            encrypted = await is_backup_encrypted(lc)
            cache = ProtectiveBackupCache(udid,
                                          product_version=self.get_current_device_version(),
                                          encrypted=encrypted)
            update_label(QCoreApplication.tr("Updating backup cache..."))
            master_root = await cache.refresh(
                lc, progress_callback=self._backup_progress(update_label, str(cache.master_root)),
                include_photos=True, include_posterboard=False,
                include_keychain=encrypted,
                include_afc_media=use_afc_media)
            log_info(f"Backup cache refreshed for {udid}")
        return master_root

    async def _backup_posterboard_database(self, update_label=lambda x: None, force: bool = False):
        """Fetch the device's PosterBoard sqlite database before applying wallpapers.

        The database (PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3) holds the
        user's current wallpapers. A fresh copy is pulled from the device every
        time a tendie is about to be applied (``force=True``) so the config
        manager always builds on top of the current on-device state. Previously
        fetched copies are only reused when the database is genuinely needed and
        a fresh one isn't required (``force=False``).

        Uses a targeted PosterBoard-only backup
        (``targeted_posterboard_database_backup`` in ``src/restore/posterboard_backup.py``):
        only the PosterBoard container is pulled off the device and everything
        else the device uploads is drained mid-stream, so no full backup is
        ever written. A disk-space failure stops the apply with the original
        destination/action message. Any fetch failure aborts before restore;
        continuing could use a stale database or mask the actual error.
        """
        tweaks = _selection_store(self)
        udid = self.get_current_device_udid()
        if not udid:
            raise NuggetException("Connect and select a device before fetching the PosterBoard database.")
        # already backed up for this device and no fresh copy required -> reuse it
        if not force and PreferenceManager.has_pbconfig_data(udid):
            return
        pb = tweaks[TweakID.PosterBoard]
        if (len(pb.tendies) == 0 and pb.videoFile is None
                and len(tweaks[TweakID.Templates].templates) == 0):
            # no wallpapers being added, nothing to back up
            return

        update_label(QCoreApplication.tr("Fetching PosterBoard database..."))
        from src.restore.posterboard_backup import targeted_posterboard_database_backup
        try:
            db_result = await targeted_posterboard_database_backup(
                udid, update_label, self._backup_progress(update_label))
            if not db_result or not os.path.exists(db_result[0]):
                raise NuggetException("The PosterBoard database file doesn't exist!")
            db_file_path, structure_version = db_result
            update_label(QCoreApplication.tr("Saving PosterBoard database..."))
            if not pb.config_manager.update_database_file(
                    db_file_path, udid, structure_version=structure_version):
                raise NuggetException("The PosterBoard database is not of the correct format!")
            pb.config_manager.update_for_saved_database(udid)
            update_label(QCoreApplication.tr("PosterBoard database backed up successfully."))
        except BackupDiskSpaceError:
            # Do not replace the actionable storage error with the later
            # misleading "PosterBoard database file not selected" error.
            raise
        except Exception as e:
            log_error(f"Failed to back up PosterBoard database: {e}\n{traceback.format_exc()}")
            print(f"Failed to back up PosterBoard database: {e}")
            print(traceback.format_exc())
            if _is_device_locked_error(e):
                raise NuggetException(QCoreApplication.tr(
                    "Could not fetch the PosterBoard database because the device is locked. "
                    "Unlock it, keep it awake, and try again."), detailed_text=str(e)) from e
            raise

    async def _apply_tweak_pass(self, update_label=lambda x: None, templates: list = None, prepared_backup_root=None, prompt_password=None, prompt_choice=None, skip_protective_backup: bool = False):
        """Generate all tweak files and restore them to the device in one pass.

        Returns (alert, files_to_restore) so the caller can surface the result
        and keep the file list for error reporting.
        """
        tweaks = _selection_store(self)
        if templates is None:
            templates = tweaks[TweakID.Templates].templates
        from src.controllers.tweak_compiler import CompilationContext, compile_tweaks
        context = CompilationContext(
            store=tweaks, version=self.get_current_device_version(),
            model=self.get_current_device_model(), templates=templates,
            force_pb_refresh=getattr(self.pref_manager, "auto_refresh_posterboard", True),
            prepare_setup=self.add_skip_setup, concat_file=self.concat_file,
            add_community_files=self._add_community_files, update_label=update_label,
            udid=self.get_current_device_udid())
        artifacts = await compile_tweaks(
            context, HotLoad(self.pref_manager.settings), self._disable_unavailable_controls(update_label))
        self._last_community_writes = artifacts.community_writes
        files_to_restore = artifacts.files
        try:
            # Check if backup encryption is enabled and handle it
            backup_password = ""
            if Version(self.get_current_device_version()) >= Version("27.0"):
                # Phase 0's protective backup already established the
                # encryption state (and may have captured a password). Reusing
                # it avoids a whole extra lockdown session on every apply; only
                # when Phase 0 did not run (raw sparse / nothing to prepare)
                # do we pay for a real check here.
                known = self._known_backup_encryption
                if known is None:
                    async with lockdown_session(self.get_current_device_udid()) as check_ld:
                        try:
                            async with Mobilebackup2Service(check_ld) as mb:
                                is_encrypted = await mb.get_will_encrypt()
                        except Exception as e:
                            if isinstance(e, NuggetException):
                                raise
                            log_warn(f"Failed to check backup encryption status: {e}")
                            is_encrypted = False
                else:
                    is_encrypted = known
                if is_encrypted:
                    if self.pref_manager.use_encrypted_backup:
                        # reuse the password entered for the cached backup, if any
                        backup_password = self._get_backup_password()
                        if backup_password:
                            log_info("Using existing backup encryption with provided password")
                            update_label(QCoreApplication.tr("Password accepted. Proceeding with encrypted restore..."))
                        else:
                            # User wants to keep encryption - ask for password to use it
                            update_label(QCoreApplication.tr("Backup encryption is enabled. We'll use it for the restore."))
                            update_label(QCoreApplication.tr("Please enter your iTunes/Finder backup password:"))
                            if prompt_password is None:
                                raise NuggetException(QCoreApplication.tr("Backup password is required for encrypted restore. Please provide the password or disable encryption in iTunes/Finder."))
                            password = prompt_password(
                                QCoreApplication.tr("Backup Encryption Password"),
                                QCoreApplication.tr("Enter your iTunes/Finder backup password (required for encrypted restore):"))
                            if password:
                                backup_password = password
                                log_info("Using existing backup encryption with provided password")
                                update_label(QCoreApplication.tr("Password accepted. Proceeding with encrypted restore..."))
                            else:
                                raise NuggetException(QCoreApplication.tr("Backup password is required for encrypted restore. Please provide the password or disable encryption in iTunes/Finder."))
                    else:
                        # User doesn't want encryption - show friendly error
                        raise NuggetException(QCoreApplication.tr(
                            "Backup encryption is enabled on your iPhone.\n\n"
                            "GoldenNugget needs to temporarily disable it to apply tweaks safely.\n\n"
                            "Please choose one:\n"
                            "1. Disable encryption on your iPhone: Settings → General → Transfer or Reset iPhone → Backup Password → Turn Off\n"
                            "2. Or enable \"Use Encrypted Backups (Experimental)\" in GoldenNugget Settings → enter your backup password when prompted.\n\n"
                            "Tip: Option 1 is simpler if you don't know your backup password."
                        ))

            # restore to the device
            # include_keychain only when backup encryption is active — iOS rejects
            # keychain entries in an unencrypted backup, and the keychain is what
            # preserves Apple Watch pairing / iMessage identity across the wipe.
            final_alert = await self.start_restore(
                files_to_restore, update_label, backup_password=backup_password,
                prepared_backup_root=prepared_backup_root,
                skip_protective_backup=skip_protective_backup,
                include_keychain=bool(backup_password),
                prompt_choice=prompt_choice,
                supervised=self.pref_manager.supervised,
                organization_name=self.pref_manager.organization_name)
            return final_alert, files_to_restore
        finally:
            artifacts.close()

    def _add_community_files(self, plists: dict, files: dict,
                             files_to_restore: list[FileToRestore], is_ios27: bool):
        """Add community tweak writes that no built-in tweak already covers."""
        taken = {(item.domain, item.restore_path) for item in files_to_restore}
        writes = [(path, plistlib.dumps(values), owner) for path, (values, owner) in plists.items()]
        writes += [(path, data, owner) for path, (data, owner) in files.items()]
        for path, contents, owner in writes:
            rel_path, domain = self.get_domain_for_path(path)
            if (domain, rel_path) in taken:
                raise NuggetException(QCoreApplication.tr(
                    "A template tries to replace {0}, which GoldenNugget already writes.").format(path))
            self.concat_file(contents=contents, path=path, files_to_restore=files_to_restore,
                             owner=owner, group=owner)
            app_pref = managed_pref_target(path) if is_ios27 and path in plists else None
            if app_pref and f"{HOME_PREFIX}{app_pref}" not in plists and f"{HOME_PREFIX}{app_pref}" not in files:
                self.concat_file(contents=contents, path=f"{HOME_PREFIX}{app_pref}",
                                 files_to_restore=files_to_restore, owner=501, group=501)

    ## RESETTING TWEAKS
    def reset_tweaks(self, reset_pages: list[Page], settings: QSettings, update_label=lambda x: None, show_alert=lambda x: None, prompt_choice=None):
        return asyncio.run(self._reset_tweaks(reset_pages, settings, update_label, show_alert, prompt_choice))
    async def _reset_tweaks(self, reset_pages: list[Page], settings: QSettings, update_label=lambda x: None, show_alert=lambda x: None, prompt_choice=None):
        final_alert = None
        files_to_restore = []
        try:
            self._raise_if_unsupported()
            # create the restore file list
            files_to_restore: list[FileToRestore] = []
            udid = self.get_current_device_udid()
            if not udid:
                raise NuggetException(QCoreApplication.tr("No device connected."))
            dev_version = self.get_current_device_version()
            files_to_null: list[str] = []
            community_leftover: list[str] = []
            uses_domains = False
            from src.controllers.apply_preview import load_preview
            from src.controllers.default_reset import preference_reset_plan
            recorded = load_preview(udid, dev_version)
            reset_plan = preference_reset_plan(recorded, reset_pages)
            recorded = recorded or {}
            for location, contents in reset_plan.items():
                self.concat_file(contents, location.value, files_to_restore,
                                 owner=0 if location == FileLocation.disabledDaemons else 501,
                                 group=0 if location == FileLocation.disabledDaemons else 501)
                if Version(dev_version) >= Version('27.0'):
                    mirror = managed_pref_target(location.value)
                    if mirror:
                        self.concat_file(contents, f'{HOME_PREFIX}{mirror}', files_to_restore)

            # plain if-chains, not match: the page set is a long, stable list
            # and a flat chain keeps the diff readable when pages are added
            for page in reset_pages:
                if page == Page.StatusBar:
                    ## STATUS BAR
                    dev_version = self.get_current_device_version()
                    if dev_version and Version(dev_version) >= Version("27.0"):
                        # iOS 27: SpringBoard reads the carrier name from
                        # StatusBarOverrides.archive. Writing a valid archive
                        # with no cellular entries is the reset -- SpringBoard
                        # decodes it as "no overrides" and unlinks the file
                        # itself, which brings the stock carrier names back.
                        # The old SpeakeasyNewStatusBar FeatureFlags write is
                        # gone: a restore cannot write that plist on iOS 27
                        # anyway, and poking /var/preferences risks tripping
                        # Security Recovery.
                        self.concat_file(
                            contents=build_reset_archive(),
                            path=FileLocation.statusBarOverridesArchive.value,
                            files_to_restore=files_to_restore
                        )
                        uses_domains = True
                    else:
                        # iOS 26 and below: the tweak writes a classic binary
                        # statusBarOverrides file. Reset it to a fresh (all-
                        # default) override struct so the status bar returns to
                        # stock — the apply path reads the same file, so an
                        # untouched zeroed file makes every override "off".
                        fresh = StatusBarTweak()
                        files_to_restore.append(FileToRestore(
                            contents=fresh.setter.get_data(),
                            restore_path="/Library/SpringBoard/statusBarOverrides",
                            domain="HomeDomain"
                        ))
                elif page == Page.Springboard:
                    pass
                elif page == Page.Daemons:
                    pass
                elif page == Page.Templates:
                    ## COMMUNITY TWEAKS FROM TEMPLATES
                    from src.tweaks.posterboard.community_tweaks import load_record, reset_plan as community_reset_plan
                    to_empty, community_leftover = community_reset_plan(load_record(udid))
                    files_to_null.extend(path for path in to_empty if path not in files_to_null)
                elif page == Page.InternalOptions:
                    pass
                elif page == Page.LiquidGlass:
                    pass
                else:
                    raise NuggetException(
                        f'No verified rollback is available for {page.name}. No reset was started.')

            if files_to_null:
                raise NuggetException(
                    'Preference reset needs a verified pre-tweak baseline. '
                    'Clearing whole preference files would also erase unrelated settings. '
                    'No reset was started; existing backups are unchanged.')

            if not files_to_restore:
                raise NuggetException('There is no verified reset payload. No device restore was started.')

            await self.add_skip_setup(files_to_restore, uses_domains)

            prepared_root = None
            if reset_plan:
                prepared_root, _ = await self._prepare_protective_backup(update_label)

            # restore to the device
            final_alert = await self.start_restore(files_to_restore, update_label,
                                                   prepared_backup_root=prepared_root,
                                                   prompt_choice=prompt_choice)
            # Invalidate selection history after the supported targeted reset.
            from src.restore.lastapply import clear_lastapply
            udid = self.get_current_device_udid()
            if udid:
                clear_lastapply(udid)
                from src.controllers.apply_preview import write_preview
                from src.controllers.default_reset import remaining_reset_entries
                write_preview(udid, dev_version, {
                    'entries': remaining_reset_entries(recorded, reset_pages)})
                if Page.Templates in reset_pages:
                    from src.tweaks.posterboard.community_tweaks import clear_record
                    clear_record(udid)
            if community_leftover:
                update_label(QCoreApplication.tr(
                    "Not reset, because GoldenNugget has no copy of what was there before: {0}").format(
                        ", ".join(community_leftover)))
            update_label(QCoreApplication.tr("Success!"))
            if Page.InternalOptions in reset_pages and 'SiriAI' in recorded:
                final_alert = ApplyAlertMessage(
                    'Recorded preference and daemon overrides were reset. Siri AI eligibility overrides were not changed; use Reset Siri AI Overrides separately. PosterKit and imported wallpaper changes are not included in this reset.',
                    title='Defaults restored', icon=QMessageBox.Information)
            return True
        except ApplyCancelledError:
            raise
        except Exception as e:
            final_alert = show_apply_error(e, update_label, files_list=files_to_restore)
            return False
        finally:
            if final_alert is not None:
                show_alert(final_alert)
