"""Offline checks for contradictory plist selections, not a device safety audit."""
from dataclasses import dataclass
import plistlib

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP

from src.tweaks.registry import SPECS_BY_ID
from src.tweaks.tweak_classes import BasicPlistTweak, AdvancedPlistTweak, NullifyFileTweak
from src.tweaks.tweak_names import TweakID


@dataclass(frozen=True)
class TweakConflict:
    first: TweakID
    second: TweakID
    reason: str

    def description(self):
        def title(tid):
            spec = SPECS_BY_ID.get(tid)
            return QCoreApplication.translate("Nugget", spec.title if spec else tid.name)
        return QCoreApplication.translate("TweakConflicts", "{0} + {1}: {2}").format(
            title(self.first), title(self.second),
            QCoreApplication.translate("TweakConflicts", self.reason))


def find_conflicts(selections):
    """Compare only enabled plist writers, preserving their apply order.

    Basic/companion writers merge keys; advanced writers replace the whole
    dictionary. Their apply methods operate on fresh local dictionaries only.
    Wallpaper/template generators and device operations are never invoked.
    """
    writers = {}
    conflicts = []
    for tid, tweak in selections.items():
        if not tweak.enabled:
            continue
        if isinstance(tweak, NullifyFileTweak):
            payload = None
        elif isinstance(tweak, BasicPlistTweak):
            payload = tweak.apply_tweak({})[tweak.file_location]
        else:
            continue
        location = tweak.file_location
        for old_id, old in writers.get(location, []):
            reason = None
            if payload is None or old is None:
                if payload != old:
                    reason = QT_TRANSLATE_NOOP("TweakConflicts", "One tweak clears a preferences file used by the other.")
            elif any(plistlib.dumps(old[key], sort_keys=True) != plistlib.dumps(payload[key], sort_keys=True)
                     for key in old.keys() & payload.keys()):
                reason = QT_TRANSLATE_NOOP("TweakConflicts", "They write different values to the same setting.")
            elif isinstance(tweak, AdvancedPlistTweak) and old.keys() - payload.keys():
                reason = QT_TRANSLATE_NOOP("TweakConflicts", "The later tweak replaces settings written by the earlier one.")
            if reason:
                conflicts.append(TweakConflict(old_id, tid, reason))
        writers.setdefault(location, []).append((tid, payload))

    rtl, ltr = (selections.get(tid) for tid in (TweakID.RTL, TweakID.LTR))
    if all(tweak is not None and tweak.enabled and tweak.value for tweak in (rtl, ltr)):
        conflicts.append(TweakConflict(TweakID.RTL, TweakID.LTR, QT_TRANSLATE_NOOP(
            "TweakConflicts", "Both layout directions are forced at the same time. Select only one.")))
    return conflicts


def current_conflicts(manager):
    from src.controllers.hotload import HotLoad
    from src.tweaks.tweak_loader import load_plist_tweaks, load_daemons
    from src.tweaks.tweaks import tweaks
    load_plist_tweaks()
    load_daemons()
    hotload = HotLoad(manager.pref_manager.settings)
    context = dict(device_version=manager.get_current_device_version(),
                   device_model=manager.get_current_device_model())
    hidden = hotload.hidden_tweak_names(**context)
    return find_conflicts({tid: tweak for tid, tweak in tweaks.items()
                           if tid.name not in hidden and hotload.rule_for(tid, **context) is None})
