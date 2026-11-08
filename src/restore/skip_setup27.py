from __future__ import annotations

# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "cryptography",
    "cryptography.hazmat.primitives.serialization",
    "pymobiledevice3.ca",
    "pymobiledevice3.lockdown",
    "src.devicemanagement.session",
    "pymobiledevice3.services.mobile_config",
)

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from pymobiledevice3.ca import create_keybag_file
from pymobiledevice3.exceptions import ConnectionTerminatedError
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.services.mobile_config import MobileConfigService

from src.devicemanagement.progress_status import OperationStatus
from src.devicemanagement.session import lockdown_session
from src.exceptions.device_errors import is_device_lock_required_error
from src.exceptions.nugget_exception import NuggetException

# Canonical list of setup panes to mark as skipped. This is the single source of
# truth for every skip-setup path:
#   - the standalone CLI (skip_setup.py)
#   - the iOS 27 Phase-4 sweep (skip_all_setup27 below)
#   - the iOS 26 cloud-config path (device_manager.add_skip_setup)
# It is the union of the curated iOS 27 list and the older iOS 26 list so no pane
# is lost on either OS (an identifier that is unknown to a given iOS is a no-op).
# Keep the list here and never fork a copy.
SKIP_ALL_PANES = [
    'Location',
    'Restore',
    'SIMSetup',
    'Android',
    'AppleID',
    'IntendedUser',
    'TOS',
    'Siri',
    'ScreenTime',
    'Diagnostics',
    'SoftwareUpdate',
    'Passcode',
    'Biometric',
    'Payment',
    'Zoom',
    'DisplayTone',
    'MessagingActivationUsingPhoneNumber',
    'HomeButtonSensitivity',
    'CloudStorage',
    'ScreenSaver',
    'TapToSetup',
    'Keyboard',
    'PreferredLanguage',
    'SpokenLanguage',
    'WatchMigration',
    'OnBoarding',
    'TVProviderSignIn',
    'TVHomeScreenSync',
    'Privacy',
    'TVRoom',
    'iMessageAndFaceTime',
    'AppStore',
    'Safety',
    'Multitasking',
    'ActionButton',
    'TermsOfAddress',
    'AccessibilityAppearance',
    'Welcome',
    'Appearance',
    'RestoreCompleted',
    'UpdateCompleted',
    'WiFi',
    'Display',
    'Tone',
    'LanguageAndLocale',
    'TouchID',
    'TrueToneDisplay',
    'FileVault',
    'iCloudStorage',
    'iCloudDiagnostics',
    'Registration',
    'DeviceToDeviceMigration',
    'UnlockWithWatch',
    'Accessibility',
    'All',
    'ExpressLanguage',
    'Language',
    'N/A',
    'Region',
    'Avatar',
    'DeviceProtection',
    'Key',
    'LockdownMode',
    'Wallpaper',
    'PrivacySubtitle',
    'SecuritySubtitle',
    'DataSubtitle',
    'AppleIDSubtitle',
    'AppearanceSubtitle',
    'PreferredLang',
    'OnboardingSubtitle',
    'AppleTVSubtitle',
    'Intelligence',
    'WebContentFiltering',
    'CameraButton',
    'AdditionalPrivacySettings',
    'EnableLockdownMode',
    'OSShowcase',
    'SafetyAndHandling',
    'Tips',
    'AgeBasedSafetySettings',
]

def skip_setup_panes() -> list:
    """Resolve the exact ``SkipSetup`` pane list: every pane is skipped,
    Apple ID sign-in included. Keeps ``SKIP_ALL_PANES`` as the canonical list.
    """
    return list(SKIP_ALL_PANES)


def build_cloud_config(existing: dict | None, supervised: bool = False,
                       organization_name: str = "") -> dict:
    """Build the cloud configuration dict (single source of truth).

    Used by both skip-setup deliveries so they produce byte-identical config:
      * iOS 27: ``skip_all_setup27`` pushes it natively with
        ``MobileConfigService.set_cloud_configuration`` (Phase 5).
      * iOS 26: ``device_manager.add_skip_setup`` embeds it into Phase 2's
        sparse restore as ``CloudConfigurationDetails.plist``.
    """
    cloud_config = dict(existing or {})
    cloud_config['SkipSetup'] = skip_setup_panes()
    cloud_config["AllowPairing"] = True
    cloud_config["ConfigurationWasApplied"] = True
    cloud_config["CloudConfigurationUIComplete"] = True
    cloud_config["IsSupervised"] = False
    cloud_config["ConfigurationSource"] = 0
    cloud_config["PostSetupProfileWasInstalled"] = True
    if supervised:
        cloud_config["IsSupervised"] = True
        # create/add the keybag
        if organization_name:
            with TemporaryDirectory() as temp_dir:
                keybag_file = Path(temp_dir) / 'keybag'
                create_keybag_file(keybag_file, organization_name)
                cer = x509.load_pem_x509_certificate(keybag_file.read_bytes())
                public_key = cer.public_bytes(Encoding.DER)
                # make sure the mdm is removable
                cloud_config["OrganizationName"] = organization_name
                cloud_config['OrganizationMagic'] = str(uuid4())
                cloud_config['IsMDMUnremovable'] = False
                cloud_config['SupervisorHostCertificates'] = [public_key]
        else:
            # remove keybag info
            if 'OrganizationMagic' in cloud_config:
                cloud_config.pop('OrganizationMagic')
            if 'SupervisorHostCertificates' in cloud_config:
                cloud_config.pop('SupervisorHostCertificates')
    return cloud_config


async def skip_all_setup27(ld: LockdownClient, udid: str | None = None,
                           supervised: bool = False,
                           organization_name: str = "", progress_callback=None):
    last_error = None
    attempt = 0
    fresh_session = False
    waiting_for_unlock = False
    while attempt < 6:
        try:
            if not fresh_session:
                async with MobileConfigService(lockdown=ld) as mcs:
                    cloud_config = build_cloud_config(
                        await mcs.get_cloud_configuration(),
                        supervised=supervised,
                        organization_name=organization_name)
                    await mcs.set_cloud_configuration(cloud_config)
            else:
                async with lockdown_session(udid, autopair=False) as fresh_ld:
                    async with MobileConfigService(lockdown=fresh_ld) as mcs:
                        cloud_config = build_cloud_config(
                            await mcs.get_cloud_configuration(),
                            supervised=supervised,
                            organization_name=organization_name)
                        await mcs.set_cloud_configuration(cloud_config)
            if waiting_for_unlock and progress_callback:
                progress_callback(OperationStatus("Device unlocked. Setup configuration completed.", "transfer_ready"))
            return
        except Exception as error:
            if is_device_lock_required_error(error):
                waiting_for_unlock = True
                fresh_session = bool(udid)
                if progress_callback:
                    progress_callback(OperationStatus(
                        "Your device is locked. Enter its passcode to finish Setup. Keeping the operation open while waiting for you to unlock it…",
                        "authentication"))
                await asyncio.sleep(3)
                continue
            if not isinstance(error, (ConnectionTerminatedError, ConnectionError, OSError, asyncio.TimeoutError)):
                raise
            last_error = error
            attempt += 1
            fresh_session = bool(udid)
            if attempt >= 6 or not udid:
                break
            await asyncio.sleep(min(2 + (attempt - 1) * 3, 15))
    raise NuggetException(
        "The restore completed, but the device disconnected while GoldenNugget "
        "was configuring Setup Assistant. Keep the device connected and retry "
        "the setup step after it finishes reconnecting. The protective backup "
        "is preserved.",
        detailed_text=f"MobileConfigService connection closed: {last_error!r}",
    ) from last_error
