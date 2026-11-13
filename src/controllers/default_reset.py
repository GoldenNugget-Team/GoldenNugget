import plistlib
from collections import defaultdict

from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.registry import SPECS, Section
from src.tweaks.tweak_classes import (
    AdvancedPlistTweak,
    BasicPlistTweak,
    suspend_tweak_notifications,
)
from src.tweaks.tweak_loader import _build_spec
from src.utils.pages import Page
from src.utils.preference_reset import PreferenceKeyReset, PreferenceNullify

_EMPTY_PLIST = plistlib.dumps({})

PAGE_SECTIONS = {Page.Springboard: Section.SPRINGBOARD,
                 Page.InternalOptions: Section.INTERNAL,
                 Page.LiquidGlass: Section.LIQUID_GLASS}


def _leaf_paths(values, prefix=()):
    for key, value in values.items():
        path = prefix + (key,)
        if isinstance(value, dict) and value and '$archiver' not in value:
            yield from _leaf_paths(value, path)
        else:
            yield path


def remaining_reset_entries(entries, pages):
    sections = {PAGE_SECTIONS[page] for page in pages if page in PAGE_SECTIONS}
    specs = {spec.id.name: spec for spec in SPECS}
    return {name: entry for name, entry in entries.items()
            if not ((name.startswith('Daemons/') and Page.Daemons in pages)
                    or (name.startswith('StatusBar') and Page.StatusBar in pages)
                    or (name in specs and specs[name].section in sections
                        and isinstance(_build_spec(specs[name]), BasicPlistTweak)))}


def _spec_reset_paths(tweak, value=True, tolerate_value_error=False):
    """Key paths a keyed reset removes for one registry spec's tweak."""
    reset_paths = getattr(tweak, 'preference_reset_paths', None)
    if reset_paths is not None:
        return {location: set(keys) for location, keys in reset_paths().items()}
    if isinstance(tweak, AdvancedPlistTweak):
        # The multi-key tweaks' value IS the key map; a reset removes its
        # keys (apply would deliver them filtered the same way).
        return {tweak.file_location: set(tweak._filter_keys(dict(tweak.value)))}
    try:
        with suspend_tweak_notifications():
            tweak.set_value(value)
            payloads = tweak.apply_tweak({})
    except ValueError:
        if tolerate_value_error:
            # Numeric/string tweaks only carry a validated value: an
            # unrecorded one was never applied, so it has nothing to reset.
            return {}
        raise
    paths = defaultdict(set)
    for location, values in payloads.items():
        if location == FileLocation.featureflags:
            for domain, flags in values.items():
                paths[location].update((domain, flag, field)
                                       for flag, fields in flags.items()
                                       for field in fields)
        else:
            paths[location].update(_leaf_paths(values))
    return paths


def preference_reset_plan(entries, pages):
    """Reset payloads for the selected sections.

    The set of locations is the union of the applied-selection record (the
    exact tweaks the last successful apply carried, plus dynamic sets like
    daemons) and the tweak registry's static entries for the selected
    sections: a tweak applied before records existed — or whose record an
    earlier reset consumed — is still covered. Preference files are reset by
    writing a valid empty plist (never zero bytes): the device falls back to
    its defaults, and no backup baseline is needed, so the reset works even
    for a file that never entered a backup. FeatureFlags/Global.plist and the
    launchd disabled.plist stay keyed removals — wiping those files whole
    would also undo flags and disabled services GoldenNugget does not own.
    """
    recorded = entries if isinstance(entries, dict) else {}
    selected = {PAGE_SECTIONS[page] for page in pages if page in PAGE_SECTIONS}
    paths = defaultdict(set)
    specs = {spec.id.name: spec for spec in SPECS}
    for name, entry in recorded.items():
        if name.startswith('Daemons/'):
            if Page.Daemons in pages:
                paths[FileLocation.disabledDaemons].add((name[len('Daemons/'):],))
            continue
        spec = specs.get(name)
        if spec is None or spec.section not in selected:
            continue
        tweak = _build_spec(spec)
        if not isinstance(tweak, BasicPlistTweak):
            # Eligibility archives and PosterKit have separate reset mechanisms.
            continue
        for location, keys in _spec_reset_paths(tweak, entry['value']).items():
            paths[location].update(keys)
    for spec in SPECS:
        if spec.section not in selected or spec.id.name in recorded:
            continue
        tweak = _build_spec(spec)
        if not isinstance(tweak, BasicPlistTweak):
            continue
        for location, keys in _spec_reset_paths(tweak, tolerate_value_error=True).items():
            paths[location].update(keys)
    return {
        location: PreferenceNullify(_EMPTY_PLIST)
        if location not in (FileLocation.featureflags, FileLocation.disabledDaemons)
        else PreferenceKeyReset(keys)
        for location, keys in paths.items()
    }
