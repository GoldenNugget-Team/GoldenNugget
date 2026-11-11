#!/usr/bin/env python3
"""Build InternalOptions.batter from the registry's Internal Options section.

Provenance of every tweak in the output (nothing here is guessed):

  A. ``src/tweaks/registry.py`` ``Section.INTERNAL`` specs - the same
     authoritative key table GoldenNugget's own Internal Options page is
     built from (id, title, plist location, key, value, version gate,
     warnings). The template mirrors it one-to-one through the shared
     ``spec_to_tweak`` / ``spec_description`` helpers of
     tools/build_community_batters.py, so a community switch and the
     built-in tweak always agree on path, key and polarity.

  B. Every write lands in ``/var/Managed Preferences/`` (the global
     domain plus the per-app domains: App Store, Notes, backboardd,
     CoreMotion, Pasteboard). That is the low-risk overlay the app itself
     rewrites on every apply; no whole-file replacement, no system folder.

Deliberately NOT included, and why:

  * ``SiriAI`` / ``ResetSiriAIOverrides`` - they sit in the same registry
    section, but their factory is ``SiriAITweak``
    (src/tweaks/siri_ai.py), not a plist tweak: the payload is an opaque
    NSKeyedArchiver (``EligibilityOverrideData``), delivered with a
    SHA-256 integrity check and a protective-backup gate
    (``require_protective_delivery``). Turning either into a batter would
    mean writing ``{"SiriAI": true}`` as a *plist merge* into
    ``eligibility_overrides.data`` - corrupting the archive, silently
    dropping the hash check and the protective-delivery requirement, and
    landing in a HIGH-risk system container
    (``/var/containers/Data/SystemGroup/``). Those two stay in the app's
    Internal Options page, where the guards live.

The template is built with GoldenNugget-TemplateBuilder's own model and
rules, then validated with GoldenNugget's real loader by
tools/verify_community_batters.py (which globs community-batters/).
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.environ.get("GOLDENNUGGET_TEMPLATEBUILDER", os.path.join(REPO, "..", "GoldenNugget-TemplateBuilder"))
OUT_DIR = os.path.join(REPO, "community-batters")

sys.path.insert(0, REPO)
sys.path.insert(0, BUILDER)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from batter_builder import batter as batter_io  # noqa: E402
from batter_builder import rules  # noqa: E402
from batter_builder.model import Template  # noqa: E402
from build_community_batters import AUTHOR, spec_to_tweak  # noqa: E402

from src.tweaks.registry import SPECS, Section  # noqa: E402

# Archive-delivered eligibility overrides with their own guarded class; see
# the module docstring for why a plist write cannot carry them.
EXCLUDED_IDS = {"SiriAI", "ResetSiriAIOverrides"}

# Floor shared with SpringBoard.batter: these keys predate iOS 17 and the
# restore pipeline only supports 17.0+ anyway.
MIN_VERSION = "17.0"


def build() -> Template:
    tweaks = [spec_to_tweak(spec) for spec in SPECS
              if spec.section == Section.INTERNAL and not spec.disabled
              and spec.key and spec.id.name not in EXCLUDED_IDS]
    return Template(
        title="Internal Options",
        author=AUTHOR,
        description=(
            "GoldenNugget's own Internal Options switches as a community "
            "template: status bar build number, forced layout direction, "
            "hidden Home Screen icons, per-app test settings (Messages, "
            "FaceTime, SharePlay, Accessories, App Store, Notes), touch "
            "visualization, paste sounds and more. Keys come from "
            "GoldenNugget's tweak registry (section 'Internal Options'); "
            "every write lands in Managed Preferences, so each switch is "
            "the same sparse overlay the built-in tweaks use. The Siri AI "
            "eligibility overrides share that page but are deliberately "
            "not here: they deliver a SHA-256-verified NSKeyedArchiver "
            "through a protective backup, which a plist write cannot do."
        ),
        min_version=MIN_VERSION,
        tags=["internal", "debug", "preferences"],
        tweaks=tweaks,
    )


def main() -> int:
    template = build()
    issues = rules.validate(template)
    errors = rules.errors(issues)
    if errors:
        for issue in errors:
            print(f"ERROR {issue}")
        return 1
    for issue in issues:
        print(f"warn  {issue}")

    ids = [t.id for t in template.tweaks]
    assert len(ids) == len(set(ids)), "duplicate tweak ids"

    out = os.path.join(OUT_DIR, "InternalOptions.batter")
    batter_io.save(template, out)
    print(f"written: {out}  ({len(template.tweaks)} tweaks)")
    for t in template.tweaks:
        keys = sorted({k for w in t.writes for k in w.values})
        print(f"  {t.id:28s} {','.join(keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
