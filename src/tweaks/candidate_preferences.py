import asyncio
from datetime import datetime

from .basic_plist_locations import FileLocation
from .tweak_classes import BasicPlistTweak, TriStateBooleanPlistTweak


class NestedNumericPreference(BasicPlistTweak):
    def __init__(self, location, key, child, value, minimum, maximum, *, integral=False):
        super().__init__(location, key, value=value)
        self.child = child
        self.minimum = minimum
        self.maximum = maximum
        self.integral = integral

    def set_value(self, value, toggle_enabled=True):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('This preference requires a number.')
        if not self.minimum <= value <= self.maximum or self.integral and int(value) != value:
            raise ValueError('The preference value is outside its allowed range.')
        super().set_value(int(value) if self.integral else float(value), toggle_enabled)

    def apply_tweak(self, other_tweaks):
        if self.enabled:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError('This preference requires a number.')
            if not self.minimum <= self.value <= self.maximum or self.integral and int(self.value) != self.value:
                raise ValueError('The preference value is outside its allowed range.')
            target = other_tweaks.setdefault(self.file_location, {}).setdefault(self.key, {})
            if not isinstance(target, dict):
                raise ValueError('The destination preference must be a dictionary.')
            target[self.child] = int(self.value) if self.integral else float(self.value)
        return other_tweaks


class DiagnosticTrackerDates(BasicPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.diagnosticExtensionTracker, 'com.apple.DiagnosticExtensions.extensionTracker')

    def apply_tweak(self, other_tweaks):
        if self.enabled:
            tracker = other_tweaks.setdefault(self.file_location, {}).setdefault(self.key, {})
            activity = tracker.setdefault('XPCActivity', {})
            activity.update(EarliestExpirationDate=datetime(4001, 1, 1),
                            XPCActivityScheduledDate=datetime(4001, 1, 1, 2))
        return other_tweaks


class InstalledAppSuggestionsBlacklist(BasicPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.suggestionsPreferencesHomeDomain, 'AppCanShowSiriSuggestionsBlacklist')
        self._bundle_ids = None

    def preference_reset_paths(self):
        return {self.file_location: ((self.key,),)}

    async def prepare_for_device(self, udid):
        self._bundle_ids = None
        if not self.enabled:
            return
        if not udid:
            raise ValueError('Select a connected device before collecting its apps.')
        from pymobiledevice3.services.installation_proxy import InstallationProxyService

        from src.devicemanagement.session import lockdown_session
        async def fetch():
            async with lockdown_session(udid) as lockdown:
                async with InstallationProxyService(lockdown=lockdown) as service:
                    return await service.get_apps(application_type='Any', calculate_sizes=False)
        apps = await asyncio.wait_for(fetch(), timeout=30)
        if not isinstance(apps, dict):
            raise ValueError('Could not read the selected device’s installed apps.')
        bundle_ids = sorted({key for key in apps if isinstance(key, str) and key and not any(char.isspace() for char in key)})
        if not bundle_ids:
            raise ValueError('No app bundle IDs were returned; the suggestions list was not written.')
        self._bundle_ids = bundle_ids

    def apply_tweak(self, other_tweaks):
        if self.enabled:
            if self._bundle_ids is None:
                raise ValueError('Collect the selected device’s installed apps before building this preference.')
            other_tweaks.setdefault(self.file_location, {})[self.key] = list(self._bundle_ids)
            self._bundle_ids = None
        return other_tweaks


class MailSearchReceiverPreference(TriStateBooleanPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.coreSpotlightUIPreferencesHomeDomain,
                         'CSReceiverBundleIdentifierState', on_value=False)

    def apply_tweak(self, other_tweaks):
        if self.enabled:
            states = other_tweaks.setdefault(self.file_location, {}).setdefault(self.key, {})
            states['com.apple.email.SearchIndexer'] = self.value
        return other_tweaks


class MailSearchTaskBaseDate(BasicPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.backgroundSystemTaskPreferencesHomeDomain, 'ActivityBaseDates')

    def apply_tweak(self, other_tweaks):
        if self.enabled:
            dates = other_tweaks.setdefault(self.file_location, {}).setdefault(self.key, {})
            dates['com.apple.email.searchIndexerBGTask'] = datetime(4001, 1, 1)
        return other_tweaks
