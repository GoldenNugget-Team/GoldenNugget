import struct
from enum import Enum

from .status_bar_c.status_setter import ffi


class StatusBarItem(Enum):
    TimeStatusBarItem = 0
    DateStatusBarItem = 1
    QuietModeStatusBarItem = 2
    AirplaneModeStatusBarItem = 3
    CellularSignalStrengthStatusBarItem = 4
    SecondaryCellularSignalStrengthStatusBarItem = 5
    CellularServiceStatusBarItem = 6
    SecondaryCellularServiceStatusBarItem = 7
    # 8
    CellularDataNetworkStatusBarItem = 9
    SecondaryCellularDataNetworkStatusBarItem = 10
    # 11
    MainBatteryStatusBarItem = 12
    ProminentlyShowBatteryDetailStatusBarItem = 13
    # 14
    # 15
    BluetoothStatusBarItem = 16
    TTYStatusBarItem = 17
    AlarmStatusBarItem = 18
    # 19
    # 20
    LocationStatusBarItem = 21
    RotationLockStatusBarItem = 22
    CameraUseStatusBarItem = 23
    AirPlayStatusBarItem = 24
    AssistantStatusBarItem = 25
    CarPlayStatusBarItem = 26
    StudentStatusBarItem = 27
    MicrophoneUseStatusBarItem = 28
    VPNStatusBarItem = 29
    # 30
    PhonePickupStatusBarItem = 31
    # 32
    # 33
    # 34
    # 35
    # 36
    # 37
    # 38
    # 39
    LiquidDetectionStatusBarItem = 40
    VoiceControlStatusBarItem = 41
    # 42
    # 43
    Extra1StatusBarItem = 44
    # 45

# Bitfield layout of `StatusBarRawData` and `StatusBarOverrideData` as produced
# by clang/gcc (the Apple-compatible layout the device expects). MSVC lays
# bitfields out differently, so cffi cannot be used to serialize on Windows —
# this fixed table is the cross-platform source of truth instead.
#
# Table rows:
#   ("bool46",  ...) -> _Bool[46] array, one byte per element
#   ("str<N>",  ...) -> char array, raw bytes
#   ("int"/"uint")   -> 32-bit little-endian integer
#   ("double", ...)  -> 64-bit little-endian IEEE-754
#   ("bit", off, bit, w) -> bitfield: absolute bit = off*8 + bit, width w

_STRING_LEN = {
    "str64": 64,
    "str256": 256,
    "str100": 100,
    "str200": 200,
    "str1024": 1024,
    "str150": 150,
}

_RAW_LAYOUT = [
    ("itemIsEnabled", "bool46", 0, 0, 0),
    ("timeString", "str64", 46, 0, 0),
    ("shortTimeString", "str64", 110, 0, 0),
    ("dateString", "str256", 174, 0, 0),
    ("GSMSignalStrengthRaw", "int", 432, 0, 0),
    ("secondaryGSMSignalStrengthRaw", "int", 436, 0, 0),
    ("GSMSignalStrengthBars", "int", 440, 0, 0),
    ("secondaryGSMSignalStrengthBars", "int", 444, 0, 0),
    ("serviceString", "str100", 448, 0, 0),
    ("secondaryServiceString", "str100", 548, 0, 0),
    ("serviceCrossfadeString", "str100", 648, 0, 0),
    ("secondaryServiceCrossfadeString", "str100", 748, 0, 0),
    ("serviceImages", "str200", 848, 0, 0),
    ("operatorDirectory", "str1024", 1048, 0, 0),
    ("serviceContentType", "uint", 2072, 0, 0),
    ("secondaryServiceContentType", "uint", 2076, 0, 0),
    ("cellLowDataModeActive", "bit", 2080, 0, 1),
    ("secondaryCellLowDataModeActive", "bit", 2080, 1, 1),
    ("wifiSignalStrengthRaw", "int", 2084, 0, 0),
    ("wifiSignalStrengthBars", "int", 2088, 0, 0),
    ("wifiLowDataModeActive", "bit", 2092, 0, 1),
    ("dataNetworkType", "uint", 2096, 0, 0),
    ("secondaryDataNetworkType", "uint", 2100, 0, 0),
    ("batteryCapacity", "int", 2104, 0, 0),
    ("batteryState", "uint", 2108, 0, 0),
    ("batteryDetailString", "str150", 2112, 0, 0),
    ("bluetoothBatteryCapacity", "int", 2264, 0, 0),
    ("thermalColor", "int", 2268, 0, 0),
    ("thermalSunlightMode", "bit", 2272, 0, 1),
    ("slowActivity", "bit", 2272, 1, 1),
    ("syncActivity", "bit", 2272, 2, 1),
    ("activityDisplayId", "str256", 2273, 0, 0),
    ("bluetoothConnected", "bit", 2528, 8, 1),
    ("displayRawGSMSignal", "bit", 2528, 9, 1),
    ("displayRawWifiSignal", "bit", 2528, 10, 1),
    ("locationIconType", "bit", 2528, 11, 1),
    ("voiceControlIconType", "bit", 2528, 12, 2),
    ("quietModeInactive", "bit", 2528, 14, 1),
    ("tetheringConnectionCount", "uint", 2532, 0, 0),
    ("batterySaverModeActive", "bit", 2536, 0, 1),
    ("deviceIsRTL", "bit", 2536, 1, 1),
    ("lock", "bit", 2536, 2, 1),
    ("breadcrumbTitle", "str256", 2537, 0, 0),
    ("breadcrumbSecondaryTitle", "str256", 2793, 0, 0),
    ("personName", "str100", 3049, 0, 0),
    ("electronicTollCollectionAvailable", "bit", 3148, 8, 1),
    ("radarAvailable", "bit", 3148, 9, 1),
    ("wifiLinkWarning", "bit", 3148, 10, 1),
    ("wifiSearching", "bit", 3148, 11, 1),
    ("backgroundActivityDisplayStartDate", "double", 3152, 0, 0),
    ("shouldShowEmergencyOnlyStatus", "bit", 3160, 0, 1),
    ("secondaryCellularConfigured", "bit", 3160, 1, 1),
    ("primaryServiceBadgeString", "str100", 3161, 0, 0),
    ("secondaryServiceBadgeString", "str100", 3261, 0, 0),
    ("quietModeImage", "str256", 3361, 0, 0),
    ("quietModeName", "str256", 3617, 0, 0),
    ("extra1", "bit", 3872, 8, 1),
]

_OVERRIDE_BITFIELDS = [
    ("overrideTimeString", 44, 16), ("overrideDateString", 44, 17),
    ("overrideGSMSignalStrengthRaw", 44, 18), ("overrideSecondaryGSMSignalStrengthRaw", 44, 19),
    ("overrideGSMSignalStrengthBars", 44, 20), ("overrideSecondaryGSMSignalStrengthBars", 44, 21),
    ("overrideServiceString", 44, 22), ("overrideSecondaryServiceString", 44, 23),
    ("overrideServiceImages", 44, 24), ("overrideOperatorDirectory", 44, 26),
    ("overrideServiceContentType", 44, 27), ("overrideSecondaryServiceContentType", 44, 28),
    ("overrideWifiSignalStrengthRaw", 44, 29), ("overrideWifiSignalStrengthBars", 44, 30),
    ("overrideDataNetworkType", 44, 31),
    ("overrideSecondaryDataNetworkType", 48, 0), ("disallowsCellularDataNetworkTypes", 48, 1),
    ("overrideBatteryCapacity", 48, 2), ("overrideBatteryState", 48, 3),
    ("overrideBatteryDetailString", 48, 4), ("overrideBluetoothBatteryCapacity", 48, 5),
    ("overrideThermalColor", 48, 6), ("overrideSlowActivity", 48, 7),
    ("overrideActivityDisplayId", 48, 8), ("overrideBluetoothConnected", 48, 9),
    ("overrideBreadcrumb", 48, 10),
    ("overrideDisplayRawGSMSignal", 56, 0), ("overrideDisplayRawWifiSignal", 56, 1),
    ("overridePersonName", 56, 2), ("overrideWifiLinkWarning", 56, 3),
    ("overrideSecondaryCellularConfigured", 56, 4),
    ("overridePrimaryServiceBadgeString", 56, 5), ("overrideSecondaryServiceBadgeString", 56, 6),
    ("overrideQuietModeImage", 56, 7), ("overrideQuietModeName", 56, 8),
    ("overrideExtra1", 56, 9),
]


def _serialize_raw(data) -> bytes:
    buf = bytearray(3880)
    for name, kind, off, bit, _ in _RAW_LAYOUT:
        if kind == "bool46":
            for i in range(46):
                buf[off + i] = 1 if data.itemIsEnabled[i] else 0
        elif kind.startswith("str"):
            n = _STRING_LEN[kind]
            buf[off:off + n] = bytes(ffi.buffer(getattr(data, name)))
        elif kind in ("int", "uint"):
            struct.pack_into("<I" if kind == "uint" else "<i", buf, off, int(getattr(data, name)))
        elif kind == "double":
            struct.pack_into("<d", buf, off, float(getattr(data, name)))
        elif kind == "bit":
            val = int(getattr(data, name))
            if val:
                bpos, sh = divmod(off * 8 + bit, 8)
                buf[bpos] |= (val << sh) & 0xFF
    return bytes(buf)


def _serialize_override(overrides) -> bytes:
    buf = bytearray(3944)
    for i in range(46):
        buf[i] = 1 if overrides.overrideItemIsEnabled[i] else 0
    for name, off, bit in _OVERRIDE_BITFIELDS:
        val = int(getattr(overrides, name))
        if val:
            bpos, sh = divmod(off * 8 + bit, 8)
            buf[bpos] |= (val << sh) & 0xFF
    struct.pack_into("<I", buf, 52, int(overrides.overrideLock))
    buf[64:64 + 3880] = _serialize_raw(overrides.values)
    return bytes(buf)


class Setter:
    def __init__(self):
        self.current_overrides = ffi.new("StatusBarOverrideData *")
        self.silly_mode = False

    def apply_changes(self, new_overrides):
        self.current_overrides = new_overrides
    def get_overrides(self):
        return self.current_overrides

    def get_overrides_with_silly_mode(self):
        """Return the overrides struct, copying it when silly mode is on and
        turning every non-overridden status bar item on. The caller's original
        struct is never mutated.
        """
        if not self.silly_mode:
            return self.current_overrides
        # create a copy so that it doesn't change the original data
        overrides = ffi.new("StatusBarOverrideData *")
        # since it doesn't contain pointers, can just copy directly
        ffi.memmove(overrides, self.current_overrides, ffi.sizeof(self.current_overrides))
        # now turn on everything funny
        for i in range(46):
            if overrides.overrideItemIsEnabled[i] == 1:
                # don't change setting
                continue
            overrides.overrideItemIsEnabled[i] = 1
            overrides.values.itemIsEnabled[i] = 1
        return overrides

    def get_data(self) -> bytes:
        overrides = self.get_overrides_with_silly_mode()
        return _serialize_override(overrides)