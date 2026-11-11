from .basic_plist_locations import FileLocation
from .daemons_tweak import DANGEROUS_KEYS, INTERFACE_KEYS
from .registry import LOCAL_ONLY_IDS, SPECS, Kind, Section
from .tweak_classes import (
    AdvancedPlistTweak,
    BasicPlistTweak,
    DaemonPlistTweak,
    NullifyFileTweak,
)
from .tweaks import TweakID, tweaks


def _build_spec(spec):
    if spec.kind == Kind.POSTER_ARCHIVE:
        from .posterboard.device_overrides import PosterKitOverrides
        return PosterKitOverrides()
    if spec.kind == Kind.WALLPAPER:
        from copy import deepcopy

        from .tweak_classes import WallpaperPreferencesTweak
        return WallpaperPreferencesTweak(spec.location,spec.key,value=deepcopy(spec.value))
    if spec.factory is not None:
        return spec.factory()
    if spec.id in LOCAL_ONLY_IDS and spec.section==Section.LIQUID_GLASS and spec.kind==Kind.SWITCH and type(spec.value) in (bool,int) and spec.value in (0,1):
        from .tweak_classes import TriStateBooleanPlistTweak
        return TriStateBooleanPlistTweak(spec.location,spec.key,spec.value)
    return BasicPlistTweak(spec.location, spec.key, value=spec.value)


def load_plist_tweaks():
    """Register every registry-defined tweak that isn't loaded yet (idempotent).

    Specs marked ``disabled`` are cut off entirely: they are never registered,
    so they neither render nor apply.
    """
    tweaks.update({spec.id: _build_spec(spec) for spec in SPECS
                   if spec.id not in tweaks and not spec.disabled})


def load_daemons():
    if TweakID.Daemons in tweaks:
        return
    # Daemons start empty; each interface toggle adds its own keys. Only
    # interface-visible keys (INTERFACE_KEYS) survive filtering, so unrelated
    # or hidden daemons can never leak into the apply pass or a stored preset.
    defaults = {}
    tweaks.update({
        TweakID.Daemons: DaemonPlistTweak(
            FileLocation.disabledDaemons,
            defaults,
            owner=0, group=0,
            never_enable=DANGEROUS_KEYS,
            allowed_keys=INTERFACE_KEYS,
        ),
        TweakID.ClearScreenTimeAgentPlist: NullifyFileTweak(FileLocation.screentime),
    })
