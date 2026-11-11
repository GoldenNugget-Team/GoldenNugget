#!/usr/bin/env python3
"""Build community .batter templates for the Liquid Glass and SpringBoard tweaks.

Every tweak in the output is traceable to one of these sources:

  A. ``src/tweaks/registry.py`` — GoldenNugget's own tweak definitions
     (id, title, plist location, key, value, kind, version range, warnings).
     This is the authoritative key table; the .batter mirrors it one-to-one.
  B. Upstream leminlimez/Nugget ``tweak_loader.py`` — the original
     "Disable Liquid Glass" tweak: ``com.apple.SwiftUI.DisableSolarium``
     written to ``.GlobalPreferences`` (system-wide SwiftUI opt-out).
  C. Git history — the Feature Flags page removed in 3b2bc17
     ("[QOL] remove Feature Flags feature completely", a feature cleanup,
     not a bug fix). The flag structure is reconstructed from
     ``3b2bc17~1:src/tweaks/tweak_loader.py``. iOS 26.0-26.1 only: a restore
     cannot write FeatureFlags plists on iOS 27, and /var/preferences is a
     high-risk system folder.
  D. ``docs/data/effective_key_value_pairs.md`` — ``UIViewGlassTintAmount``
     (com.apple.UIKit, 0..1, 0.5 = stock) is the only Liquid Glass key with a
     complete measured response curve. It was reverted in cf9d2d9 with no
     stated reason; the forensics in
     ``docs/data/glass_tint_amount_revert_forensics.md`` rule out every bug
     hypothesis, and the original author is this repo's owner.
  E. ``docs/SPRINGBOARD_TWEAK_CANDIDATES.md`` Tier B — keys SpringBoard
     itself writes into the device backup (key is real; on-device effect
     unverified).
  F. Community reports — per-app ``com.apple.SwiftUI.DisableSolarium``
     (defaults write com.apple.<app> ...), the "Solid Glass" style opt-out.

Deliberately NOT included (see the module docstring of the generated
templates and the commit history for the reasons):
  * ``SBHideDockBackground`` / ``SBDockAlpha`` — they only ever existed in
    documentation.md's illustrative example; no upstream or registry basis.
  * The 264 Tier-C SpringBoard candidates — 3.1% live-verified hit rate;
    shipping unverified toggles is worse than shipping none.
  * ``SBHomeIcon*`` — proven dead: storage moved to the PosterBoard poster
    configuration (SPRINGBOARD_TWEAK_CANDIDATES.md section 13).
  * The dangerous keys listed in section 7 of that report.
  * Enum-only entries never wired to a spec (dockCornerRadius, ...).

The templates are built with GoldenNugget-TemplateBuilder's own model, rules
and archive modules, then validated with GoldenNugget's real loader
(``community_tweaks.parse_tweaks``) before they are written.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.environ.get("GOLDENNUGGET_TEMPLATEBUILDER", os.path.join(REPO, "..", "GoldenNugget-TemplateBuilder"))
OUT_DIR = os.path.join(REPO, "community-batters")

sys.path.insert(0, REPO)
sys.path.insert(0, BUILDER)

from batter_builder import batter as batter_io  # noqa: E402
from batter_builder import rules  # noqa: E402
from batter_builder.model import Control, Template, Tweak, Write  # noqa: E402

from src.tweaks.basic_plist_locations import FileLocation  # noqa: E402
from src.tweaks.registry import SPECS, SPECS_BY_ID, Kind, Section  # noqa: E402

AUTHOR = "Jason"

# --- shared constants -------------------------------------------------------

GP = FileLocation.globalPreferences
SB = FileLocation.springboard
UIKIT = FileLocation.uikit
FF_PATH = "/var/preferences/FeatureFlags/Global.plist"

# Feature Flags structure, verbatim from 3b2bc17~1:src/tweaks/tweak_loader.py
# (FeatureFlagTweak, inverted=True: switch on -> flag false).
SOLARIUM_FF_ON = {
    "SwiftUI": {"Solarium": False},
    "IconServices": {"EnhancedGlass": False, "SolariumCornerRadius": False},
    "DocumentCamera": {"CaptureLiquidGlass": False},
    "Photos": {"SolariumGridMagicPocket": False},
    "AppleMediaServices": {"Solarium": False},
    "Sharing": {"ShareSheetSolarium": False},
    "Mail": {"SolariumSearch": False},
}
SOLARIUM_FF_OFF = {cat: {flag: True for flag in flags}
                   for cat, flags in SOLARIUM_FF_ON.items()}

# SpringBoard-category flags: the Solarium HUD flag from the same removed
# page plus the lock-screen flags (ClockAnim / Lockscreen, not inverted:
# switch on -> flag true). One tweak, one top-level category, so it can never
# clobber the Solarium categories above when both are enabled.
SPRINGBOARD_FF_ON = {
    "SolariumElasticHUD": False,
    "SwiftUITimeAnimation": True,
    "AutobahnQuickSwitchTransition": True,
    "SlipSwitch": True,
    "PosterEditorKashida": True,
}
SPRINGBOARD_FF_OFF = {
    "SolariumElasticHUD": True,
    "SwiftUITimeAnimation": False,
    "AutobahnQuickSwitchTransition": False,
    "SlipSwitch": False,
    "PosterEditorKashida": False,
}

# Per-app SwiftUI opt-out (community "Solid Glass" style), F above.
PER_APP_SOLARIUM = [
    ("com.apple.clock", "Clock"),
    ("com.apple.Music", "Music"),
    ("com.apple.AppStore", "App Store"),
    ("com.apple.weather", "Weather"),
    ("com.apple.mobilenotes", "Notes"),
    ("com.apple.Home", "Home"),
]

# Tier B device-backup keys not present in the registry (E above).
TIER_B_EXTRAS = [
    ("SBMedusaMultitaskingEnabled", "iPad Multitasking Switch", True,
     "Present in the device backup (SpringBoard writes it itself), so the key "
     "is real; the visible effect is unverified. Examined device value: true."),
    ("SBFlexibleWindowingAutomaticStageCreationEnabledExternal",
     "Auto Stage on External Display", True,
     "Present in the device backup (SpringBoard writes it itself), so the key "
     "is real; the visible effect is unverified. Examined device value: false."),
]

# Keys dropped from the registry by 8e91241's refresh (no breakage on record).
REFRESH_DROPPED = [
    ("com.apple.SwiftUI.GlassContainerLogging", "Glass Container Logging",
     "Debug logging for the glass container (com.apple.SwiftUI UserDefaults "
     "key). Writes log output; no visual effect."),
    ("SolariumLiveTuning", "Solarium Live Tuning",
     "Enables the Solarium live tuning switch - real-time glass parameter "
     "changes. Effect unverified."),
]


# --- helpers ----------------------------------------------------------------

# Registry ids longer than the 64-character limit the loader enforces.
# Shortened deterministically; the plist key (and therefore the effect) is
# untouched.
ID_ALIASES = {
    "SBCaptureButtonAllowLaunchIfUnobstructionOccursPromptlyAfterButtonUp":
        "SBCaptureButtonAllowLaunchIfUnobstructionAfterButtonUp",
    "SBFlexibleWindowingManualStageCreationShouldRestorePreviousOpenWindows":
        "SBFlexibleWindowingManualStageRestorePreviousWindows",
}

# Registry specs the app itself marks unavailable (no accepted value range or
# no verified consumer). A slider cannot express min == max, and guessing a
# range would be worse than leaving them out.
EXCLUDED_UNAVAILABLE = {
    "SBStatusBarishLogOptions",
    "SBExternalDisplayContentsScaleAndDontFileRadars",
    "SBMainDisplayDarkeningPercentage",
}


def spec_description(spec) -> str:
    """Registry description plus the gating / risk notes the app shows."""
    parts = []
    if spec.iphone_only:
        parts.append("iPhone only.")
    if spec.ipad_only:
        parts.append("iPad only.")
    if spec.requires_dynamic_island:
        parts.append("Requires Dynamic Island.")
    if spec.requires_camera_control:
        parts.append("Requires Camera Control.")
    if spec.requires_action_button:
        parts.append("Requires the Action Button.")
    if spec.requires_home_button:
        parts.append("Requires a Home button.")
    if spec.requires_always_on:
        parts.append("Requires an Always-On Display.")
    if spec.bundle_identifier:
        parts.append("Enter an app bundle identifier.")
    if spec.experimental:
        parts.append("Experimental: not verified on a real device.")
    if spec.warning:
        parts.append(spec.warning)
    if spec.unavailable_reason:
        parts.append("Unavailable: " + spec.unavailable_reason)
    if spec.requires:
        names = []
        for needed in spec.requires:
            other = SPECS_BY_ID.get(needed)
            names.append(other.title if other else needed.name)
        parts.append("Also enable: " + ", ".join(names) + ".")
    if spec.description:
        parts.append(spec.description)
    if not spec.location.value.startswith("/var/Managed Preferences/"):
        parts.append("Writes outside Managed Preferences: the whole file is "
                     "replaced, so the iPhone's own copy of it is lost.")
    text = " ".join(parts)
    if len(text) > 500:  # the loader refuses longer descriptions
        text = text[:497] + "..."
    return text


def spec_to_tweak(spec) -> Tweak:
    """One registry spec -> one switch tweak (plus slider/text control)."""
    tweak = Tweak(
        id=ID_ALIASES.get(spec.id.name, spec.id.name),
        label=spec.title,
        description=spec_description(spec),
        default=False,
        min_version=spec.min_version or "",
        max_version=spec.max_version or "",
    )
    path = spec.location.value
    if spec.kind == Kind.SWITCH:
        on_value = spec.value if isinstance(spec.value, bool) else True
        tweak.writes = [Write("plist", path, {spec.key: on_value})]
        tweak.writes_off = [Write("plist", path, {spec.key: not on_value})]
    elif spec.kind == Kind.NUMBER:
        tweak.control = Control("slider", default=spec.value,
                                min=spec.min_value, max=spec.max_value,
                                step=spec.step)
        tweak.writes = [Write("plist", path, {spec.key: "$value"})]
        if spec.reset_value is not None:
            # The registry's documented "remove this setting" value.
            tweak.writes_off = [Write("plist", path, {spec.key: spec.reset_value})]
    elif spec.kind == Kind.TEXT:
        default = spec.value if isinstance(spec.value, str) else ""
        tweak.control = Control("text", default=default, max_length=200)
        tweak.writes = [Write("plist", path, {spec.key: "$value"})]
        tweak.writes_off = [Write("plist", path, {spec.key: ""})]
    else:  # pragma: no cover - the registry has no other kinds
        raise ValueError(f"unhandled kind {spec.kind} for {spec.id}")
    return tweak


def make_tweak(id_, label, description, writes, writes_off=None, *,
               min_version="", max_version="", control=None, default=False):
    return Tweak(id=id_, label=label, description=description, default=default,
                 min_version=min_version, max_version=max_version,
                 control=control,
                 writes=[Write("plist", path, values) for path, values in writes],
                 writes_off=[Write("plist", path, values)
                             for path, values in (writes_off or [])])


def glass_tint_tweak() -> Tweak:
    """UIViewGlassTintAmount, restored from cf9d2d9^ (source D)."""
    return make_tweak(
        "GlassTintAmount", "Liquid Glass Tint Amount",
        "System-wide Liquid Glass tint amount, 0 to 1. 0.0 = More Clear, "
        "0.5 = Default (the stock appearance), 1.0 = More Tinted - the same "
        "number Settings > Display & Brightness > Liquid Glass drives. The "
        "visible work happens between 0.5 and 0.75. Also writes "
        "UIViewGlassEverEditedInSettings, matching what Settings itself does. "
        "Verified on-device with a full 8-point response curve; restored from "
        "git history after an unexplained revert.",
        [(UIKIT.value, {"UIViewGlassTintAmount": "$value",
                        "UIViewGlassEverEditedInSettings": True})],
        min_version="27.0",
        control=Control("slider", default=0.5, min=0.0, max=1.0, step=0.05),
    )


def disable_solarium_tweak() -> Tweak:
    """com.apple.SwiftUI.DisableSolarium in .GlobalPreferences (source B)."""
    return make_tweak(
        "DisableSolarium", "Disable Liquid Glass (SwiftUI)",
        "The original Nugget's system-wide Liquid Glass switch: writes "
        "com.apple.SwiftUI.DisableSolarium to the global domain, asking "
        "SwiftUI to fall back to the pre-glass rendering path. Community "
        "reports say it stopped working on some 26.1 builds; if it does "
        "nothing on your device, turn it off and apply to put the key back. "
        "Per-app variants are in LiquidGlass-Advanced.batter.",
        [(GP.value, {"com.apple.SwiftUI.DisableSolarium": True})],
        writes_off=[(GP.value, {"com.apple.SwiftUI.DisableSolarium": False})],
        min_version="26.0",
    )


def solarium_ff_tweak() -> Tweak:
    """Feature Flags method for disabling Liquid Glass (source C)."""
    return make_tweak(
        "DisableSolariumFeatureFlags",
        "Disable Liquid Glass (Feature Flags)",
        "iOS 26.0-26.1 only. Writes the Solarium feature flags off in "
        "/var/preferences/FeatureFlags/Global.plist: SwiftUI, IconServices, "
        "DocumentCamera, Photos, AppleMediaServices, Sharing and Mail. This "
        "is the method the original Nugget shipped on its Feature Flags page. "
        "HIGH RISK: /var/preferences is a system folder, the whole file is "
        "replaced, and a restore cannot write it on iOS 27 at all - do not "
        "apply this on iOS 27.",
        [(FF_PATH, SOLARIUM_FF_ON)],
        writes_off=[(FF_PATH, SOLARIUM_FF_OFF)],
        min_version="26.0", max_version="26.99",
    )


def springboard_ff_tweak() -> Tweak:
    """SpringBoard-category feature flags (source C)."""
    return make_tweak(
        "SpringBoardFeatureFlags", "Lock Screen Flags (Feature Flags)",
        "iOS 26.0-26.1 only. Writes the SpringBoard category of "
        "/var/preferences/FeatureFlags/Global.plist: SolariumElasticHUD off, "
        "plus SwiftUITimeAnimation (lock screen clock animation), "
        "AutobahnQuickSwitchTransition, SlipSwitch and PosterEditorKashida "
        "(lock screen page duplication) on. HIGH RISK: /var/preferences is a "
        "system folder, the whole file is replaced, and a restore cannot "
        "write it on iOS 27 at all - do not apply this on iOS 27.",
        [(FF_PATH, {"SpringBoard": SPRINGBOARD_FF_ON})],
        writes_off=[(FF_PATH, {"SpringBoard": SPRINGBOARD_FF_OFF})],
        min_version="26.0", max_version="26.99",
    )


def per_app_tweaks():
    out = []
    for bundle, name in PER_APP_SOLARIUM:
        path = f"/var/Managed Preferences/mobile/{bundle}.plist"
        out.append(make_tweak(
            f"DisableSolarium.{bundle}", f"Disable Liquid Glass in {name}",
            f"Writes com.apple.SwiftUI.DisableSolarium to the {name} app's own "
            "preferences, the per-app form of the community 'Solid Glass' "
            "opt-out (defaults write com.apple.<app> ...). Community-reported; "
            "some 26.1 builds ignore it. Turning the switch off and applying "
            "puts the key back.",
            [(path, {"com.apple.SwiftUI.DisableSolarium": True})],
            writes_off=[(path, {"com.apple.SwiftUI.DisableSolarium": False})],
            min_version="26.0",
        ))
    return out


def refresh_dropped_tweaks():
    return [make_tweak(
        "dropped." + key.replace(".", "_"), label, description,
        [(GP.value, {key: True})],
        writes_off=[(GP.value, {key: False})],
        min_version="27.0",
    ) for key, label, description in REFRESH_DROPPED]


def watchos_tweak() -> Tweak:
    """The registry's WatchOSCompatibility keys (AdvancedPlistTweak).

    Same keys, same file, same whole-file semantics as the built-in; the
    description says so, because /var/mobile is not Managed Preferences.
    """
    values = {
        "IOS_PAIRING_EOL_MIN_PAIRING_COMPATIBILITY_VERSION_CHIPIDS": "",
        "maxPairingCompatibilityVersion": 37,
        "lastRestoreIdentifier": "CD97EEB8-BCD2-486B-BC13-C384E6B916C4",
        "minPairingCompatibilityVersionWithChipID": 1,
        "lastRestoreIdentifier_state": 0,
        "AdvertisingIdentifierSeed": "85E70251-1960-4DA0-A321-B68AC118FAB5",
        "minPairingCompatibilityVersion": 1,
    }
    return make_tweak(
        "WatchOSCompatibility", "Relax Apple Watch Version Check",
        "Pair an Apple Watch running a different watchOS version. Writes the "
        "fixed key set GoldenNugget's built-in tweak writes to "
        "/var/mobile/Library/Preferences/com.apple.NanoRegistry.plist. That "
        "file is replaced whole, so only enable this when you actually pair "
        "a Watch; turning the switch off and applying rewrites the same key "
        "set, it does not restore a previous file.",
        [(FileLocation.nanoregistry.value, values)],
    )


def tier_b_tweaks():
    out = []
    for key, label, value, note in TIER_B_EXTRAS:
        out.append(make_tweak(
            key, label, note,
            [(SB.value, {key: value})],
            writes_off=[(SB.value, {key: not value})],
        ))
    return out


# --- assembly ---------------------------------------------------------------

def lg_specs():
    return [s for s in SPECS
            if s.section == Section.LIQUID_GLASS and not s.disabled]


def sb_specs():
    return [s for s in SPECS
            if s.section == Section.SPRINGBOARD and not s.disabled]


def build_templates():
    lg_core, lg_adv = [], []
    for spec in lg_specs():
        (lg_adv if spec.key.startswith("UISolarium") else lg_core).append(spec_to_tweak(spec))
    lg_core.append(disable_solarium_tweak())
    lg_core.append(glass_tint_tweak())
    lg_core.append(solarium_ff_tweak())
    lg_adv.extend(refresh_dropped_tweaks())
    lg_adv.extend(per_app_tweaks())

    sb_core, sb_exp = [], []
    for spec in sb_specs():
        if spec.key == "" and spec.id.name != "WatchOSCompatibility":
            continue  # AdvancedPlistTweak with no single key
        if spec.id.name in EXCLUDED_UNAVAILABLE:
            continue  # the app itself marks these unavailable
        if spec.id.name == "WatchOSCompatibility":
            sb_core.append(watchos_tweak())
            continue
        (sb_exp if spec.experimental else sb_core).append(spec_to_tweak(spec))
    sb_core.extend(tier_b_tweaks())
    sb_core.append(springboard_ff_tweak())

    templates = [
        Template(
            title="Liquid Glass",
            author=AUTHOR,
            description=(
                "Every Liquid Glass (Solarium) tweak GoldenNugget knows, as "
                "community switches: glass appearance, reflections, shadows, "
                "icon style, the SwiftUI opt-out and the iOS 26 Feature Flags "
                "method. Keys come from GoldenNugget's own tweak registry; "
                "writes go to Managed Preferences unless a tweak says "
                "otherwise. Experimental entries are marked in their "
                "description - test one at a time."
            ),
            min_version="26.0",
            tags=["liquid glass", "solarium", "ios 26", "ios 27"],
            tweaks=lg_core,
        ),
        Template(
            title="Liquid Glass - Advanced",
            author=AUTHOR,
            description=(
                "The numeric Liquid Glass debug family: UISolarium floating "
                "panels, focus highlights and stacked-icon motion, plus the "
                "per-app com.apple.SwiftUI.DisableSolarium opt-out. Every "
                "value type here was inferred from the key table, not "
                "verified on a device - change one number at a time."
            ),
            min_version="26.0",
            tags=["liquid glass", "solarium", "advanced", "debug"],
            tweaks=lg_adv,
        ),
        Template(
            title="SpringBoard",
            author=AUTHOR,
            description=(
                "The proven SpringBoard tweaks: lock screen, power, "
                "navigation, Dynamic Island, keyboard and the device-backup "
                "verified keys, plus the iOS 26 lock screen Feature Flags. "
                "Keys come from GoldenNugget's own tweak registry."
            ),
            min_version="17.0",
            tags=["springboard", "home screen", "lock screen"],
            tweaks=sb_core,
        ),
    ]
    for index in range(0, len(sb_exp), 58):
        chunk = sb_exp[index:index + 58]
        part = "" if len(sb_exp) <= 58 else f" (part {index // 58 + 1})"
        templates.append(Template(
            title=f"SpringBoard - Experimental{part}",
            author=AUTHOR,
            description=(
                "The experimental SpringBoard registry: hidden switches whose "
                "preference reader or on-device effect is not verified. Each "
                "description carries the registry's own warning. Apply one at "
                "a time and keep a usable backup."
            ),
            min_version="26.0",
            tags=["springboard", "experimental"],
            tweaks=chunk,
        ))
    return templates


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    templates = build_templates()
    ok = True
    for template in templates:
        issues = rules.validate(template)
        errors = rules.errors(issues)
        warnings = [i for i in issues if i.level == rules.WARNING]
        print(f"\n=== {template.title}: {len(template.tweaks)} tweaks, "
              f"{len(errors)} errors, {len(warnings)} warnings ===")
        for issue in errors:
            ok = False
            print(f"  ERROR  {issue.where}: {issue.text}")
        for issue in warnings:
            print(f"  warn   {issue.where}: {issue.text}")
        if not errors:
            stem = {"Liquid Glass": "LiquidGlass",
                    "Liquid Glass - Advanced": "LiquidGlass-Advanced",
                    "SpringBoard": "SpringBoard"}.get(template.title)
            if stem is None:  # experimental parts
                stem = "SpringBoard-Experimental"
                if "part 2" in template.title:
                    stem += "-2"
            path = os.path.join(OUT_DIR, stem + ".batter")
            batter_io.save(template, path)
            print(f"  saved  {path} ({os.path.getsize(path)} bytes)")
    print("\nALL OK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
