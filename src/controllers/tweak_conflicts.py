"""Offline checks for contradictory plist selections, not a device safety audit."""
import hashlib
import plistlib
from copy import deepcopy
from dataclasses import dataclass

from src.tweaks.candidate_preferences import InstalledAppSuggestionsBlacklist
from src.tweaks.registry import SPECS_BY_ID
from src.tweaks.store import ChangeBus
from src.tweaks.tweak_classes import (
    AdvancedPlistTweak,
    BasicPlistTweak,
    NullifyFileTweak,
)
from src.tweaks.tweak_names import TweakID
from src.utils.i18n import QT_TRANSLATE_NOOP, QCoreApplication


def _payload_digests(payload):
    """``{key: sha1(serialized value)}`` for one tweak payload.

    Comparing two writers used to re-serialize both sides of every shared key,
    for every pair sharing a file — quadratic work on a value that never
    changes during the comparison. The digests are computed once per payload.
    """
    return {key: hashlib.sha1(plistlib.dumps(value, sort_keys=True)).digest()
            for key, value in payload.items()}


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
    Wallpaper/template generators and device-dependent app-list writers are
    never invoked. Preview writers run on copies so review cannot consume state.
    """
    writers = {}
    conflicts = []
    for tid, tweak in selections.items():
        if not tweak.enabled:
            continue
        if isinstance(tweak, InstalledAppSuggestionsBlacklist):
            continue
        if isinstance(tweak, NullifyFileTweak):
            payload = None
        elif isinstance(tweak, BasicPlistTweak):
            preview = deepcopy(tweak, {id(tweak._change_bus): ChangeBus()})
            payload = preview.apply_tweak({}).get(tweak.file_location)
            if payload is None:
                continue
        else:
            continue
        location = tweak.file_location
        digests = _payload_digests(payload) if payload is not None else None
        for old_id, old, old_digests in writers.get(location, []):
            reason = None
            if payload is None or old is None:
                if payload != old:
                    reason = QT_TRANSLATE_NOOP("TweakConflicts", "One tweak clears a preferences file used by the other.")
            elif any(old_digests[key] != digests[key] for key in old.keys() & payload.keys()):
                reason = QT_TRANSLATE_NOOP("TweakConflicts", "They write different values to the same setting.")
            elif isinstance(tweak, AdvancedPlistTweak) and old.keys() - payload.keys():
                reason = QT_TRANSLATE_NOOP("TweakConflicts", "The later tweak replaces settings written by the earlier one.")
            if reason:
                conflicts.append(TweakConflict(old_id, tid, reason))
        writers.setdefault(location, []).append((tid, payload, digests))

    rtl, ltr = (selections.get(tid) for tid in (TweakID.RTL, TweakID.LTR))
    if all(tweak is not None and tweak.enabled and tweak.value for tweak in (rtl, ltr)):
        conflicts.append(TweakConflict(TweakID.RTL, TweakID.LTR, QT_TRANSLATE_NOOP(
            "TweakConflicts", "Both layout directions are forced at the same time. Select only one.")))
    for spec in SPECS_BY_ID.values():
        if spec.exclusive_with is None or spec.id.value >= spec.exclusive_with.value:
            continue
        pair = (selections.get(spec.id), selections.get(spec.exclusive_with))
        if all(tweak is not None and tweak.enabled for tweak in pair):
            conflicts.append(TweakConflict(spec.id, spec.exclusive_with, QT_TRANSLATE_NOOP(
                "TweakConflicts", "Select only one Dynamic Island GPU fill experiment.")))
    return conflicts


def current_conflicts(manager):
    from src.controllers.hotload import HotLoad
    from src.tweaks.store import selection_store
    from src.tweaks.tweak_loader import load_daemons, load_plist_tweaks
    from src.tweaks.tweaks import tweaks
    tweaks = selection_store(manager, tweaks)
    load_plist_tweaks()
    load_daemons()
    hotload = HotLoad(manager.pref_manager.settings)
    context = dict(device_version=manager.get_current_device_version(),
                   device_model=manager.get_current_device_model())
    hidden = hotload.hidden_tweak_names(**context)
    return find_conflicts({tid: tweak for tid, tweak in tweaks.items()
                           if tid.name not in hidden and hotload.rule_for(tid, **context) is None})
