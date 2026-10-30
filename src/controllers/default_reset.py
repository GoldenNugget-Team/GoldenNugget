from collections import defaultdict

from src.tweaks.basic_plist_locations import FileLocation
from src.tweaks.registry import SPECS, Section
from src.tweaks.tweak_classes import BasicPlistTweak, suspend_tweak_notifications
from src.tweaks.tweak_loader import _build_spec
from src.utils.pages import Page
from src.utils.preference_reset import PreferenceKeyReset

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


def preference_reset_plan(entries, pages):
    if entries is None:
        # No applied-selection record for this device/iOS version: nothing was
        # recorded to take keys out of, so the keyed preference reset is empty
        # (other reset targets are built straight from the tweak registry).
        return {}
    selected = {PAGE_SECTIONS[page] for page in pages if page in PAGE_SECTIONS}
    paths = defaultdict(set)
    specs = {spec.id.name: spec for spec in SPECS}
    for name, entry in entries.items():
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
        reset_paths = getattr(tweak, 'preference_reset_paths', None)
        if reset_paths is not None:
            for location, keys in reset_paths().items():
                paths[location].update(keys)
            continue
        with suspend_tweak_notifications():
            tweak.set_value(entry['value'])
            payloads = tweak.apply_tweak({})
        for location, values in payloads.items():
            if location == FileLocation.featureflags:
                for domain, flags in values.items():
                    paths[location].update((domain, flag, field)
                                           for flag, fields in flags.items() for field in fields)
            else:
                paths[location].update(_leaf_paths(values))
    return {location: PreferenceKeyReset(keys) for location, keys in paths.items()}
