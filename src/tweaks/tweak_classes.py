from typing import Any, Optional, Callable
from .store import default_changes

from .basic_plist_locations import FileLocation

_legacy_unsubscribe = None

def suspend_tweak_notifications():
    return default_changes.suspend()

def subscribe_tweak_changes(callback):
    return default_changes.subscribe(callback)

def set_tweak_change_callback(callback: Optional[Callable[[], None]]):
    """Compatibility for single-subscriber callers; new code uses subscribe."""
    global _legacy_unsubscribe
    if _legacy_unsubscribe is not None:
        _legacy_unsubscribe()
    _legacy_unsubscribe = default_changes.subscribe(callback) if callback else None

def _notify_tweak_change():
    default_changes.notify()

class Tweak:
    def __init__(
            self,
            key: str,
            value: Any = 1,
            owner: int = 501, group: int = 501
        ):
        self.key = key
        self.value = value
        self.owner = owner
        self.group = group
        self.enabled = False
        self._change_bus = default_changes

    def set_enabled(self, value: bool):
        if self.enabled != value:
            self.enabled = value
            self._change_bus.notify()
    def set_value(self, new_value: Any, toggle_enabled: bool = True):
        self.value = new_value
        if toggle_enabled:
            self.enabled = True
        self._change_bus.notify()

    def apply_tweak(self):
        raise NotImplementedError
    
class NullifyFileTweak(Tweak):
    def __init__(
            self,
            file_location: FileLocation,
            owner: int = 501, group: int = 501
        ):
        super().__init__(key=None, value=None, owner=owner, group=group)
        self.file_location = file_location

    def apply_tweak(self, other_tweaks: dict):
        if self.enabled:
            other_tweaks[self.file_location] = b""
    

class BasicPlistTweak(Tweak):
    def __init__(
            self,
            file_location: FileLocation,
            key: str,
            value: Any = True,
            owner: int = 501, group: int = 501
        ):
        super().__init__(key=key, value=value, owner=owner, group=group)
        self.file_location = file_location

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        if self.file_location in other_tweaks:
            other_tweaks[self.file_location][self.key] = self.value
        else:
            other_tweaks[self.file_location] = {self.key: self.value}
        return other_tweaks


class WallpaperPreferencesTweak(BasicPlistTweak):
    def apply_tweak(self, other_tweaks):
        if not self.enabled:
            return other_tweaks
        from copy import deepcopy
        from math import isfinite
        value=deepcopy(self.value)
        for key in ('SBWallpaperHasVideoKey','SBWallpaperMagnifyEnabledKey',
                    'SBWallpaperPortraitKey','SBWallpaperSupportsCroppingKey',
                    'kSBProceduralWallpaperHomeUserSetKey'):
            old=value['none'][key]
            if type(old) not in (bool,int) or old not in (False,True):
                raise ValueError(f'Expected a boolean wallpaper field: {key}')
            value['none'][key]=bool(old)
        for key,lower,upper in (('SBWallpaperParallaxFactorKey',0,100),
                                ('SBWallpaperStillTimeInVideoKey',0,86400),
                                ('SBWallpaperZoomScaleKey',.01,100)):
            number=value['none'][key]
            if type(number) not in (int,float) or not isfinite(number) or not lower<=number<=upper:
                raise ValueError(f'Invalid numeric wallpaper field: {key}')
        other_tweaks.setdefault(self.file_location,{})[self.key]=value
        return other_tweaks


class ReversibleBooleanPlistTweak(BasicPlistTweak):
    """Write both states so disabling a previously applied key takes effect."""

    def __init__(self, file_location, key, *, integer_value=False, companion_keys=()):
        super().__init__(file_location, key, value=None)
        self.integer_value = integer_value
        self.companion_keys = tuple(companion_keys)

    def set_enabled(self, value: bool):
        value = bool(value)
        if self.enabled != value:
            self.value = value
        super().set_enabled(value)

    def apply_tweak(self, other_tweaks: dict, force_disabled: bool = False) -> dict:
        if not self.enabled and self.value is None and not force_disabled:
            return other_tweaks
        target = other_tweaks.get(self.file_location)
        if not isinstance(target, dict):
            target = {}
            other_tweaks[self.file_location] = target
        value = False if force_disabled else bool(self.enabled)
        for key in (self.key, *self.companion_keys):
            target[key] = int(value) if self.integer_value else value
        return other_tweaks

class ExperimentalBooleanPlistTweak(ReversibleBooleanPlistTweak):
    """Leave untouched keys alone; persist explicit off selections for rollback."""

    def __init__(self, location, key, on_value, off_value):
        super().__init__(location, key)
        self.on_value = on_value
        self.off_value = off_value
        self.value = None

    def set_enabled(self, value: bool):
        value = bool(value)
        if self.enabled != value:
            self.value = self.on_value if value else self.off_value
        super().set_enabled(value)

    def apply_tweak(self, other_tweaks: dict, force_disabled: bool = False) -> dict:
        if not self.enabled and self.value is None:
            return other_tweaks
        value = self.on_value if self.enabled and not force_disabled else self.off_value
        other_tweaks.setdefault(self.file_location, {})[self.key] = value
        return other_tweaks


class DynamicIslandBorderWriteTest(ExperimentalBooleanPlistTweak):
    VALUES = {
        "keyLineEnabled": False,
        "activityKeyLineColorEnabled": False,
        "keyLineAlpha": 0.0,
        "keyLineThickness": 0.0,
        "backgroundBlurEnabled": False,
        "elementShadowEnabled": False,
        "sensorShadowVisible": False,
    }

    def __init__(self):
        super().__init__(FileLocation.springboard, "keyLineEnabled", True, False)

    def apply_tweak(self, other_tweaks: dict, force_disabled: bool = False) -> dict:
        if not self.enabled and self.value is None:
            return other_tweaks
        target = other_tweaks.setdefault(self.file_location, {})
        if self.enabled and not force_disabled:
            target.update(self.VALUES)
        else:
            for key in self.VALUES:
                target.pop(key, None)
        return other_tweaks


class ResettableNumericPreferenceTweak(BasicPlistTweak):
    """Use -1 to remove an optional numeric key from the replacement plist."""

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        target = other_tweaks.setdefault(self.file_location, {})
        if self.value == -1:
            target.pop(self.key, None)
        else:
            target[self.key] = float(self.value)
        return other_tweaks


class OptionalBundlePreferenceTweak(BasicPlistTweak):
    """An empty app identifier removes the key from the generated preference file."""

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        target = other_tweaks.setdefault(self.file_location, {})
        if self.value:
            target[self.key] = self.value
        else:
            target.pop(self.key, None)
        return other_tweaks

    
class CompanionKeyTweak(BasicPlistTweak):
    """A plist tweak that writes companion keys alongside its main key.

    Some settings only take effect once the system can see that a human
    changed them (e.g. ``UIViewGlassEverEditedInSettings`` marks the Liquid
    Glass tint amount as deliberately chosen; without it iOS treats the
    amount as never set and applies its own default). Those keys are not
    user-facing toggles, so they ride along with the real one.

    Merging matches ``BasicPlistTweak``, so several tweaks can keep sharing
    one plist (both this one and ``UseFloatingTabBar`` target the UIKit
    Managed Preferences file).
    """
    def __init__(
            self,
            file_location: FileLocation,
            key: str,
            value: Any = True,
            companion_keys: Optional[dict] = None,
            owner: int = 501, group: int = 501
        ):
        super().__init__(file_location=file_location, key=key, value=value,
                         owner=owner, group=group)
        self.companion_keys = dict(companion_keys or {})

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        target = other_tweaks.get(self.file_location)
        if not isinstance(target, dict):
            target = {}
            other_tweaks[self.file_location] = target
        target[self.key] = self.value
        target.update(self.companion_keys)
        return other_tweaks

class AdvancedPlistTweak(BasicPlistTweak):
    def __init__(
        self,
        file_location: FileLocation,
        keyValues: dict,
        owner: int = 501, group: int = 501,
        never_enable: Optional[set] = None,
        allowed_keys: Optional[set] = None
    ):
        super().__init__(file_location=file_location, key=None, value=keyValues, owner=owner, group=group)
        self.never_enable = set(never_enable or ())
        # If set, only keys in this set are ever applied / stored (interface-
        # visible daemons). Keys outside it are dropped, never written.
        self.allowed_keys = set(allowed_keys) if allowed_keys is not None else None

    def _filter_keys(self, values: dict) -> dict:
        """Drop keys that are hard-protected or not interface-visible."""
        out = {}
        for key, value in values.items():
            if key in self.never_enable:
                continue
            if self.allowed_keys is not None and key not in self.allowed_keys:
                continue
            out[key] = value
        return out

    def set_multiple_values(self, keys: list[str], value: Any):
        for key in keys:
            if value and value is not False and value is not None and key in self.never_enable:
                continue  # hard-protected: this key must never be enabled
            if self.allowed_keys is not None and key not in self.allowed_keys:
                continue  # not exposed in the UI: never introduce it
            self.value[key] = value
        self._change_bus.notify()

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        other_tweaks[self.file_location] = self._filter_keys(self.value)
        return other_tweaks


class DaemonPlistTweak(AdvancedPlistTweak):
    """Daemon selections only; unrelated preferences require separate edits."""


class TriStateBooleanPlistTweak(BasicPlistTweak):
    def __init__(self, file_location, key, on_value=True, *, owner=501, group=501):
        super().__init__(file_location, key, value=None, owner=owner, group=group)
        self.on_value = on_value
        self.off_value = not on_value if isinstance(on_value, bool) else 1 - on_value

    @property
    def state(self):
        return self.value == self.on_value if self.enabled else None

    def set_state(self, state, *, notify=True):
        if state is not None and type(state) is not bool:
            raise ValueError("A boolean preference state must be true, false, or unused.")
        self.enabled = state is not None
        self.value = None if state is None else self.on_value if state else self.off_value
        if notify:
            self._change_bus.notify()

    def set_enabled(self, value: bool):
        self.set_state(True if value else None)

    def set_value(self, new_value, toggle_enabled=True):
        if new_value is None:
            self.set_state(None)
            return
        if type(new_value) not in (bool, int) or new_value not in (0, 1):
            raise ValueError("A boolean preference requires true or false.")
        state = new_value == self.on_value
        if toggle_enabled:
            self.set_state(state)
        else:
            self.value = self.on_value if state else self.off_value
            self._change_bus.notify()

class ResearchOnlyTweak(Tweak):
    def __init__(self, key, reason):
        super().__init__(key=key, value=None)
        self.reason = reason

    def set_enabled(self, value):
        if value:
            raise ValueError(self.reason)
        super().set_enabled(False)

    def set_value(self, new_value, toggle_enabled=True):
        if new_value is not None or toggle_enabled:
            raise ValueError(self.reason)

    def apply_tweak(self, *args, **kwargs):
        raise ValueError(self.reason)

class GlassLegibilityTweak(BasicPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.uikitPreferencesHomeDomain, "UIViewGlassLegibilitySetting", value=0)

    def apply_tweak(self, other_tweaks: dict) -> dict:
        if not self.enabled:
            return other_tweaks
        if type(self.value) not in (int, float) or self.value not in (0, 1):
            raise ValueError("Glass legibility appearance must be 0 or 1.")
        other_tweaks.setdefault(self.file_location, {})[self.key] = int(self.value)
        return other_tweaks

class DisableDynamicIslandTweak(ReversibleBooleanPlistTweak):
    def __init__(self):
        super().__init__(FileLocation.springboard, "SBSuppressDynamicIslandCompletely",
                         companion_keys=("SBNeverRenderSystemApertureFillOnGPU",
                                         "SBSSystemApertureDisabled"))

    def apply_tweak(self, other_tweaks: dict, force_disabled: bool = False) -> dict:
        super().apply_tweak(other_tweaks, force_disabled)
        if 'SBSSystemApertureDisabled' not in other_tweaks.get(self.file_location, {}):
            return other_tweaks
        value = other_tweaks[self.file_location]["SBSSystemApertureDisabled"]
        other_tweaks.setdefault(FileLocation.springboardPreferencesHomeDomain, {})["SBSSystemApertureDisabled"] = value
        return other_tweaks
