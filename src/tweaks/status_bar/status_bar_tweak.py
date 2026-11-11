from cffi import FFI

from src.utils.file_to_restore import FileToRestore

from ..tweak_classes import Tweak
from .status_setter import Setter, StatusBarItem
from .statusbar_archive import ARCHIVE_DOMAIN, ARCHIVE_PATH, build_archive

ffi = FFI()

class StatusBarTweak(Tweak):
    def __init__(self):
        super().__init__(key=None)
        self.setter = Setter()
    def _apply_changes(self, overrides) -> None:
        setter = self.setter
        setter.apply_changes(overrides)
        self._change_bus.notify()
        return None

    # iOS 27+: the classic binary statusBarOverrides file is no longer read and
    # the SpeakeasyNewStatusBar feature flag cannot be written by a restore, so
    # the carrier overrides are delivered as the StatusBarOverrides.archive
    # that SpringBoard unarchives itself. It lives in HomeDomain, the same
    # domain the classic path uses, so this is an ordinary restore file -- no
    # exploit.
    def apply_ios27_tweak(self, files_to_restore: list) -> None:
        """Stage StatusBarOverrides.archive (iOS 27+).

        The cellular entry carries the carrier name, its service badge and
        its signal-bar count and fixed network type. The classic
        time/date/battery/wifi overrides and the per-item show/hide toggles
        have no counterpart in the archive and are dropped, so the page hides
        them (see src/gui/ios/statusbar.py).
        """
        if not self.enabled:
            return
        primary = self.get_carrier_override() if self.is_carrier_overridden() else None
        secondary = self.get_secondary_carrier_override() if self.is_secondary_carrier_overridden() else None
        badge = self.get_primary_service_badge_override() if self.is_primary_service_badge_overridden() else None
        secondary_badge = self.get_secondary_service_badge_override() if self.is_secondary_service_badge_overridden() else None
        bars = self.get_gsm_signal_strength_bars_override() if self.is_gsm_signal_strength_bars_overridden() else None
        secondary_bars = self.get_secondary_gsm_signal_strength_bars_override() if self.is_secondary_gsm_signal_strength_bars_overridden() else None
        files_to_restore.append(FileToRestore(
            contents=build_archive(
                primary,
                secondary,
                badge,
                secondary_badge,
                bars,
                secondary_bars,
                primary_network_type=(self.get_data_network_type_override()
                    if self.is_data_network_type_overridden() else None),
                secondary_network_type=(self.get_secondary_data_network_type_override()
                    if self.is_secondary_data_network_type_overridden() else None),
            ),
            restore_path=ARCHIVE_PATH,
            domain=ARCHIVE_DOMAIN
        ))

    # iOS 26.x (pre-27): classic binary statusBarOverrides in HomeDomain.
    def apply_classic_tweak(self, files_to_restore: list) -> None:
        """Stage the classic binary status bar override file (iOS 26.x)."""
        if not self.enabled:
            return
        files_to_restore.append(FileToRestore(
            contents=self.setter.get_data(),
            restore_path="/Library/SpringBoard/statusBarOverrides",
            domain="HomeDomain"
        ))

    # --- generic helpers over the StatusBarOverrideData struct ---

    def _overrides(self):
        return self.setter.get_overrides()

    def _is_flag_overridden(self, flag: str) -> bool:
        return getattr(self._overrides(), flag) == 1

    def _get_str(self, field: str) -> str:
        return ffi.string(getattr(self._overrides().values, field)).decode()

    def _get_int(self, field: str) -> int:
        return getattr(self._overrides().values, field)

    @staticmethod
    def _bytes_fit(text: str, max_bytes: int) -> bytes:
        """UTF-8-encode *text* truncated to *max_bytes* on a whole character.

        The override struct fields are fixed byte arrays; slicing the str by
        characters can still encode past the field size (CJK ~3 bytes/char)
        and cffi then raises from inside the setter.
        """
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return encoded
        return encoded[:max_bytes].decode("utf-8", errors="ignore").encode("utf-8")

    def _set_flag(self, flag: str, field: str = None, value=None, max_len: int = None) -> None:
        overrides = self._overrides()
        setattr(overrides, flag, 1)
        if field is not None:
            data = value
            if max_len is not None:
                data = self._bytes_fit(value, max_len) if isinstance(value, str) else value[:max_len]
            setattr(overrides.values, field, data.encode() if isinstance(data, str) else data)
        self._apply_changes(overrides)

    def _unset_flag(self, flag: str) -> None:
        overrides = self._overrides()
        setattr(overrides, flag, 0)
        self._apply_changes(overrides)

    ### PRIMARY CARRIER
    # CELLULAR SERVICE
    def is_cellular_service_overridden(self) -> bool:
        return self.is_item_overridden(StatusBarItem.CellularServiceStatusBarItem)
    def get_cellular_service_override(self) -> bool:
        return self.get_item_override(StatusBarItem.CellularServiceStatusBarItem)
    def set_cellular_service(self, shown: bool) -> None:
        self.set_item_override(StatusBarItem.CellularServiceStatusBarItem, shown)
    def unset_cellular_service(self) -> None:
        self.unset_item_override(StatusBarItem.CellularServiceStatusBarItem)

    # SERVICE STRING
    def is_carrier_overridden(self) -> bool:
        return self._is_flag_overridden("overrideServiceString")
    def get_carrier_override(self) -> str:
        return self._get_str("serviceString")
    def set_carrier_override(self, text: str) -> None:
        overrides = self._overrides()
        truncated = self._bytes_fit(text, 100)
        overrides.values.serviceString = truncated
        overrides.values.serviceCrossfadeString = truncated
        self._set_flag("overrideServiceString")
    def unset_carrier_override(self) -> None:
        self._unset_flag("overrideServiceString")

    # SERVICE BADGE
    def is_primary_service_badge_overridden(self) -> bool:
        return self._is_flag_overridden("overridePrimaryServiceBadgeString")
    def get_primary_service_badge_override(self) -> str:
        return self._get_str("primaryServiceBadgeString")
    def set_primary_service_badge(self, text: str) -> None:
        self._set_flag("overridePrimaryServiceBadgeString", "primaryServiceBadgeString", text, max_len=100)
    def unset_primary_service_badge(self) -> None:
        self._unset_flag("overridePrimaryServiceBadgeString")

    # DATA NETWORK TYPE
    def is_data_network_type_overridden(self) -> bool:
        return self._is_flag_overridden("overrideDataNetworkType")
    def get_data_network_type_override(self) -> int:
        return self._get_int("dataNetworkType")
    def set_data_network_type(self, id: int) -> None:
        self._set_flag("overrideDataNetworkType", "dataNetworkType", id)
    def unset_data_network_type(self) -> None:
        self._unset_flag("overrideDataNetworkType")

    # GSM SIGNAL BARS
    def is_gsm_signal_strength_bars_overridden(self) -> bool:
        return self._is_flag_overridden("overrideGSMSignalStrengthBars")
    def get_gsm_signal_strength_bars_override(self) -> int:
        return self._get_int("GSMSignalStrengthBars")
    def set_gsm_signal_strength_bars(self, id: int) -> None:
        overrides = self._overrides()
        idx = StatusBarItem.CellularSignalStrengthStatusBarItem.value
        overrides.overrideItemIsEnabled[idx] = 1
        overrides.values.itemIsEnabled[idx] = 1
        self._set_flag("overrideGSMSignalStrengthBars", "GSMSignalStrengthBars", id)
    def unset_gsm_signal_strength_bars(self) -> None:
        overrides = self._overrides()
        overrides.overrideItemIsEnabled[StatusBarItem.CellularSignalStrengthStatusBarItem.value] = 0
        self._unset_flag("overrideGSMSignalStrengthBars")


    ### SECONDARY CARRIER
    # CELLULAR SERVICE
    def is_secondary_cellular_service_overridden(self) -> bool:
        return self.is_item_overridden(StatusBarItem.SecondaryCellularServiceStatusBarItem)
    def get_secondary_cellular_service_override(self) -> bool:
        return self.get_item_override(StatusBarItem.SecondaryCellularServiceStatusBarItem)
    def set_secondary_cellular_service(self, shown: bool) -> None:
        overrides = self._overrides()
        idx = StatusBarItem.SecondaryCellularServiceStatusBarItem.value
        overrides.overrideItemIsEnabled[idx] = 1
        overrides.values.itemIsEnabled[idx] = 1 if shown else 0
        overrides.overrideSecondaryCellularConfigured = 1
        overrides.values.secondaryCellularConfigured = 1 if shown else 0
        self._apply_changes(overrides)
    def unset_secondary_cellular_service(self) -> None:
        overrides = self._overrides()
        overrides.overrideItemIsEnabled[StatusBarItem.SecondaryCellularServiceStatusBarItem.value] = 0
        overrides.overrideSecondaryCellularConfigured = 0
        self._apply_changes(overrides)

    # SERVICE STRING
    def is_secondary_carrier_overridden(self) -> bool:
        return self._is_flag_overridden("overrideSecondaryServiceString")
    def get_secondary_carrier_override(self) -> str:
        return self._get_str("secondaryServiceString")
    def set_secondary_carrier_override(self, text: str) -> None:
        overrides = self._overrides()
        truncated = self._bytes_fit(text, 100)
        overrides.values.secondaryServiceString = truncated
        overrides.values.secondaryServiceCrossfadeString = truncated
        self._set_flag("overrideSecondaryServiceString")
    def unset_secondary_carrier_override(self) -> None:
        self._unset_flag("overrideSecondaryServiceString")

    # SERVICE BADGE
    def is_secondary_service_badge_overridden(self) -> bool:
        return self._is_flag_overridden("overrideSecondaryServiceBadgeString")
    def get_secondary_service_badge_override(self) -> str:
        return self._get_str("secondaryServiceBadgeString")
    def set_secondary_service_badge(self, text: str) -> None:
        self._set_flag("overrideSecondaryServiceBadgeString", "secondaryServiceBadgeString", text, max_len=100)
    def unset_secondary_service_badge(self) -> None:
        self._unset_flag("overrideSecondaryServiceBadgeString")

    # DATA NETWORK TYPE
    def is_secondary_data_network_type_overridden(self) -> bool:
        return self._is_flag_overridden("overrideSecondaryDataNetworkType")
    def get_secondary_data_network_type_override(self) -> int:
        return self._get_int("secondaryDataNetworkType")
    def set_secondary_data_network_type(self, id: int) -> None:
        self._set_flag("overrideSecondaryDataNetworkType", "secondaryDataNetworkType", id)
    def unset_secondary_data_network_type(self) -> None:
        self._unset_flag("overrideSecondaryDataNetworkType")

    # GSM SIGNAL BARS
    def is_secondary_gsm_signal_strength_bars_overridden(self) -> bool:
        return self._is_flag_overridden("overrideSecondaryGSMSignalStrengthBars")
    def get_secondary_gsm_signal_strength_bars_override(self) -> int:
        return self._get_int("secondaryGSMSignalStrengthBars")
    def set_secondary_gsm_signal_strength_bars(self, id: int) -> None:
        overrides = self._overrides()
        idx = StatusBarItem.SecondaryCellularSignalStrengthStatusBarItem.value
        overrides.overrideItemIsEnabled[idx] = 1
        overrides.values.itemIsEnabled[idx] = 1
        self._set_flag("overrideSecondaryGSMSignalStrengthBars", "secondaryGSMSignalStrengthBars", id)
    def unset_secondary_gsm_signal_strength_bars(self) -> None:
        overrides = self._overrides()
        overrides.overrideItemIsEnabled[StatusBarItem.SecondaryCellularSignalStrengthStatusBarItem.value] = 0
        self._unset_flag("overrideSecondaryGSMSignalStrengthBars")


    ### MISC TEXT INPUTS
    # TIME STRING
    def is_time_overridden(self) -> bool:
        return self._is_flag_overridden("overrideTimeString")
    def get_time_override(self) -> str:
        return self._get_str("timeString")
    def set_time(self, text: str) -> None:
        self._set_flag("overrideTimeString", "timeString", text, max_len=64)
    def unset_time(self) -> None:
        self._unset_flag("overrideTimeString")

    # DATE STRING
    def is_date_overridden(self) -> bool:
        return self._is_flag_overridden("overrideDateString")
    def get_date_override(self) -> str:
        return self._get_str("dateString")
    def set_date(self, text: str) -> None:
        self._set_flag("overrideDateString", "dateString", text, max_len=256)
    def unset_date(self) -> None:
        self._unset_flag("overrideDateString")

    # BREADCRUMB STRING
    def is_crumb_overridden(self) -> bool:
        return self._is_flag_overridden("overrideBreadcrumb")
    def get_crumb_override(self) -> str:
        text = self._get_str("breadcrumbTitle")
        if len(text) > 1:
            return text[:len(text) - 4]
        return ""
    def set_crumb(self, text: str) -> None:
        overrides = self._overrides()
        overrides.overrideBreadcrumb = 1
        new_crumb = self._bytes_fit(text + " ▶", 256) if text != "" else ""
        overrides.values.breadcrumbTitle = new_crumb.encode() if isinstance(new_crumb, str) else new_crumb
        self._apply_changes(overrides)
    def unset_crumb(self) -> None:
        overrides = self._overrides()
        overrides.overrideBreadcrumb = 0
        overrides.values.breadcrumbTitle = "".encode()
        self._apply_changes(overrides)

    # BATTERY DETAIL STRING
    def is_battery_detail_overridden(self) -> bool:
        return self._is_flag_overridden("overrideBatteryDetailString")
    def get_battery_detail_override(self) -> str:
        return self._get_str("batteryDetailString")
    def set_battery_detail(self, text: str) -> None:
        self._set_flag("overrideBatteryDetailString", "batteryDetailString", text, max_len=150)
    def unset_battery_detail(self) -> None:
        self._unset_flag("overrideBatteryDetailString")


    ## MISC SLIDER INPUTS
    # BATTERY CAPACITY
    def is_battery_capacity_overridden(self) -> bool:
        return self._is_flag_overridden("overrideBatteryCapacity")
    def get_battery_capacity_override(self) -> int:
        return self._get_int("batteryCapacity")
    def set_battery_capacity(self, id: int) -> None:
        self._set_flag("overrideBatteryCapacity", "batteryCapacity", id)
    def unset_battery_capacity(self) -> None:
        self._unset_flag("overrideBatteryCapacity")

    # WIFI SIGNAL STRENGTH
    def is_wifi_signal_strength_bars_overridden(self) -> bool:
        return self._is_flag_overridden("overrideWifiSignalStrengthBars")
    def get_wifi_signal_strength_bars_override(self) -> int:
        return self._get_int("wifiSignalStrengthBars")
    def set_wifi_signal_strength_bars(self, id: int) -> None:
        self._set_flag("overrideWifiSignalStrengthBars", "wifiSignalStrengthBars", id)
    def unset_wifi_signal_strength_bars(self) -> None:
        self._unset_flag("overrideWifiSignalStrengthBars")


    ## RAW SIGNAL STRENGTH TOGGLES
    # WIFI
    def is_raw_wifi_signal_shown(self) -> bool:
        return self._is_flag_overridden("overrideDisplayRawWifiSignal")
    def show_raw_wifi_signal(self, shown: bool) -> None:
        overrides = self._overrides()
        overrides.overrideDisplayRawWifiSignal = 1 if shown else 0
        if shown:
            overrides.values.displayRawWifiSignal = 1
        self._apply_changes(overrides)
    # GSM
    def is_raw_gsm_signal_shown(self) -> bool:
        return self._is_flag_overridden("overrideDisplayRawGSMSignal")
    def show_raw_gsm_signal(self, shown: bool) -> None:
        overrides = self._overrides()
        overrides.overrideDisplayRawGSMSignal = 1 if shown else 0
        if shown:
            overrides.values.displayRawGSMSignal = 1
        self._apply_changes(overrides)

    ## RADIO BUTTONS
    def is_item_overridden(self, item: StatusBarItem) -> bool:
        return self._overrides().overrideItemIsEnabled[item.value] == 1
    def get_item_override(self, item: StatusBarItem) -> bool:
        return self._overrides().values.itemIsEnabled[item.value] == 1
    def set_item_override(self, item: StatusBarItem, shown: bool) -> None:
        overrides = self._overrides()
        overrides.overrideItemIsEnabled[item.value] = 1
        overrides.values.itemIsEnabled[item.value] = 1 if shown else 0
        self._apply_changes(overrides)
    def unset_item_override(self, item: StatusBarItem) -> None:
        overrides = self._overrides()
        overrides.overrideItemIsEnabled[item.value] = 0
        self._apply_changes(overrides)


    def is_silly_mode_enabled(self) -> bool:
        return self.setter.silly_mode
    def toggle_silly_mode(self, value: bool) -> None:
        self.setter.silly_mode = value

    def count_overrides(self) -> int:
        """Number of currently-active overrides (drives the apply summary).

        Counts every ``override*`` flag set to 1 plus every enabled
        ``overrideItemIsEnabled`` entry. Approximate by design — a single
        user change can legitimately toggle more than one override field.
        """
        overrides = self._overrides()
        count = 0
        try:
            for i in range(len(overrides.overrideItemIsEnabled)):
                if overrides.overrideItemIsEnabled[i]:
                    count += 1
        except Exception:
            pass
        for name in dir(overrides):
            if not name.startswith("override") or name == "overrideItemIsEnabled":
                continue
            try:
                val = getattr(overrides, name)
            except Exception:
                continue
            if isinstance(val, int) and val:
                count += 1
        return count
