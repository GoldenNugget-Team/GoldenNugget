#!/usr/bin/env python3
"""Build SpringBoard-27.1.batter from iOS 27.1 firmware findings.

Provenance of every tweak in the output (nothing here is guessed):

  A. iOS 27.1 (24A94401) simulator dyld shared cache, SpringBoardFoundation
     ``__cstring`` diff against iOS 27.0 (24A5380i / 24A434): 29 new keys,
     14 of them with a strict accessor pairing (``accessor \\0 key \\0`` in
     the bind table). Those 14 are live defaults keys by construction --
     the accessor is the property SpringBoardFoundation binds the key to.
     Tooling: tools/fw_accessor_pairs.py, output docs/data/pairs_27.1_sbf.txt.

  B. Two of the 15 "loose" 27.1 keys are live too, but the pairing heuristic
     missed them: SBAmbientDefaults emits its strings as a *key block* then
     an *accessor block*, not alternating. Dumping the pool around
     ``SBAmbientPresentationControllerMockIsCharging'' shows the three keys
     followed by ``qiChargingIdleTimerDuration'' /
     ``presentationControllerMockIsCharging'' /
     ``transientOverlayInteractiveDismissal'' -- each accessor is a literal
     substring of its key, so the pairing is unambiguous.

  C. Pre-existing keys (present in the 27.0 baseline as well) that the
     accessor pairing never resolved and no template ever shipped. They sit
     inside SpringBoardFoundation's defaults bind tables next to keys that
     ARE paired, which is what makes them shippable: the key is real, the
     on-device effect is not.

Not shippable, and why (see docs/data/fw_new_keys_27.1.md for the full list):
  * The SB-prefixed cluster around SBForceButterfly / SBPhoneRingLight /
    SBMotionEffects is interleaved with unprefixed names like
    ``ChamoisWindowingUI'' / ``ForceButterfly'' / ``WindowFlattening'' and
    their ``...LivingOn'' siblings -- that table is feature-flag domains,
    not defaults keys, and a restore cannot write FeatureFlags plists on
    iOS 27 anyway.
  * SBF-prefixed names (SBFDevicePoseProvider, SBFHingeSamples,
    SBFIEDynamicMarkPersistence, SBContinuousFoldController, ...) are ObjC
    class names -- the pool dump shows the matching ``.m'' literals and
    ivar type encodings next to them.
  * SBFDevicePoseLastKnownCMAngle / ...CMMagicPose and
    SBResizingCapabilityOverrideForApps / SBBundleIdentifiersToForce... are
    dictionary/array payloads, not toggles.
  * SBShowVictoria belongs to the com.apple.springboard.usage domain, not
    com.apple.springboard.
  * SBHomeIcon* keys are proven dead (storage moved to the PosterBoard
    poster configuration; SPRINGBOARD_TWEAK_CANDIDATES.md section 13).

The templates are built with GoldenNugget-TemplateBuilder's own model and
rules, then validated with GoldenNugget's real loader by
tools/verify_community_batters.py (which globs this directory).
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

AUTHOR = "Jason"

# SpringBoardFoundation defaults keys are read from com.apple.springboard.
SB_PLIST = "/var/Managed Preferences/mobile/com.apple.springboard.plist"

# (id, label, description, min_version, on-values)
# on-values: dict written when the switch is on; the off state writes the
# same keys with False. A slider spec carries a Control instead.
STRICT_27_1 = [
    ("SBHomeScreenShowsSearchButton", "Show Home Screen Search Button",
     "iOS 27.1 renamed the key behind the search pill: accessor "
     "showsHomeScreenSearchAffordance now binds to SBHomeScreenShowsSearch-"
     "Button, with the legacy name sitting unused beside it in the same "
     "table. On writes True (pill shown), off writes False (hidden) - the "
     "polarity the Tier-A device test measured for the legacy key. Only the "
     "new key is written; the legacy one is already covered by "
     "SBHideSearchAffordance in SpringBoard.batter. Firmware-verified, "
     "effect not tested.",
     "27.1", {"SBHomeScreenShowsSearchButton": True}),
    ("SBDebugHUD", "Debug HUD",
     "iOS 27.1 adds a whole new defaults class, SBDebugHUDDefaults (visible "
     "in the ObjC class table next to SBHomeScreenDefaults and friends); "
     "this is its master switch and shows an engineering HUD overlay. "
     "Firmware-verified; effect not tested.",
     "27.1", {"SBDebugHUD": True}),
    ("SBVisualizeTouchSuppression", "Visualize Touch Suppression",
     "Draws the regions where touches are suppressed (dim display and "
     "CoverSheet gestures) - a debug aid. Sits between "
     "SBShowNotificationsInAlwaysOn and the wallpaper keys in the bind "
     "table. Firmware-verified; effect not tested.",
     "27.1", {"SBVisualizeTouchSuppression": True}),
    ("SBRequireFreshTouch", "Require Fresh Touch (Cover Sheet)",
     "CoverSheet gestures must start from a new touch instead of reusing a "
     "tracked one (accessor freshTouchRequired, inside the SBCoverSheet* "
     "block of the bind table). Firmware-verified; effect not tested.",
     "27.1", {"SBRequireFreshTouch": True}),
    ("SBForceAllAppsToSupportLimitedResizing",
     "Force All Apps to Support Limited Resizing",
     "Treats every app as supporting limited resizing, bypassing per-app "
     "declarations (iPad windowing). Directly adjacent to "
     "SBBundleIdentifiersToForceSupportLimitedResizing in the same table. "
     "Firmware-verified; effect not tested.",
     "27.1", {"SBForceAllAppsToSupportLimitedResizing": True}),
    ("SBEnableDisplayDimTouchSuppressionForAllSurfaces",
     "Display Dim Touch Suppression (All Surfaces)",
     "Extends the dim-display touch suppression to every surface instead of "
     "the lock screen only. In the idle-timer block of the bind table, "
     "between SBNotificationVisibleIdleTimer and SBHasSeenACaseLatch-"
     "CoverOnce. Firmware-verified; effect not tested.",
     "27.1", {"SBEnableDisplayDimTouchSuppressionForAllSurfaces": True}),
    ("SBUseFallbackDisplayRegionBlankingRenderer",
     "Fallback Display Region Blanking Renderer",
     "Switches the System Aperture blanking renderer to its fallback path "
     "(SBSystemApertureDefaults block). Visual: the blacked-out regions "
     "behind the aperture. Firmware-verified; effect not tested.",
     "27.1", {"SBUseFallbackDisplayRegionBlankingRenderer": True}),
    ("SBShowHingeAngleHUD", "Show Hinge Angle HUD",
     "Shows a live hinge-angle HUD; part of the new SBDebugHUDDefaults "
     "(accessor showHingeAngleHUD). FOLDABLE DEVICES ONLY - inert on other "
     "hardware. Firmware-verified; effect not tested.",
     "27.1", {"SBShowHingeAngleHUD": True}),
    ("SBAlwaysSendHingeUpdates", "Always Send Hinge Updates",
     "Keeps sending hinge-angle updates even when no client is listening "
     "(SBMiscellaneousDefaults; the literal "
     "'-[SBMiscellaneousDefaults _bindAndRegisterDefaults]' sits right "
     "after the key in the pool). FOLDABLE DEVICES ONLY. Firmware-verified; "
     "effect not tested.",
     "27.1", {"SBAlwaysSendHingeUpdates": True}),
]

# SBAmbientDefaults emits a key block first and the accessor block after it,
# so the automated pairing marked these loose. The pool dump around
# SBAmbientPresentationControllerMockIsCharging shows all three accessors as
# literal substrings of their keys - the pairing is unambiguous.
AMBIENT_27_1 = [
    ("SBAmbientPresentationControllerMockIsCharging",
     "Mock Charging State (StandBy)",
     "iOS 27.1, SBAmbientDefaults. Fakes the charging state for StandBy "
     "testing. Its class emits keys before accessors, which is why the "
     "automated pairing reported it as loose; the accessor "
     "presentationControllerMockIsCharging is confirmed in the same pool. "
     "Firmware-verified; effect not tested.",
     "27.1", {"SBAmbientPresentationControllerMockIsCharging": True}),
    ("SBAmbientTransientOverlayInteractiveDismissal",
     "Ambient Overlay Interactive Dismissal",
     "iOS 27.1, SBAmbientDefaults. Lets the transient ambient overlay be "
     "dismissed interactively (accessor transientOverlayInteractive-"
     "Dismissal, same key-block/accessor-block emission). Firmware-"
     "verified; effect not tested.",
     "27.1", {"SBAmbientTransientOverlayInteractiveDismissal": True}),
]

# Present in the 27.0 baseline as well - real keys that no template ever
# shipped because the accessor pairing never resolved them.
PRE_EXISTING = [
    ("SBDisableAutoDim", "Disable Auto Dim",
     "Turns off the screen-longevity auto dimming. Inside the idle-timer "
     "defaults table (between SBCaptureApplicationDefaults state and "
     "SBMinimumLockscreenIdleTime) with the accessor disableAutoDim in the "
     "same region. Key exists since iOS 27.0; never shipped before. Effect "
     "not tested.",
     "27.0", {"SBDisableAutoDim": True}),
    ("SBEnableHomeScreenWallpaperDimming", "Home Screen Wallpaper Dimming",
     "Dims the wallpaper behind the Home Screen icon grid. In the "
     "SBHomeScreenDefaults table, right before the PosterBoard migration "
     "flag SBMigratedHomeScreenDefaultsTintToPosterBoard. Key exists since "
     "iOS 27.0; never shipped before. Effect not tested.",
     "27.0", {"SBEnableHomeScreenWallpaperDimming": True}),
    ("SBExternalDisplayMirroringEnabled", "External Display Mirroring",
     "Mirroring switch from the external-display defaults cluster "
     "(SBDisplayModeSettings, SBExternalDisplayArrangementEdge, "
     "SBNonInteractiveCompanionScenesEnabledForAll). Key exists since iOS "
     "27.0; never shipped before. Effect not tested.",
     "27.0", {"SBExternalDisplayMirroringEnabled": True}),
    ("SBSensitiveUIEnabled", "Sensitive UI",
     "Sensitive-UI protection flag in com.apple.springboard - the binary "
     "carries the migration log string 'SBSensitiveUIEnabled was %@', and "
     "the key sits next to com.apple.springboard domain literals. The "
     "default is probably already on, so any visible change appears when "
     "switched OFF. Key exists since iOS 27.0; never shipped before. Effect "
     "and direction not tested.",
     "27.0", {"SBSensitiveUIEnabled": True}),
]

# Slider: SBAmbientExtendedIdleTimer (strict, 27.1). Units and on-device
# default are unknown, so the bounds mirror the already-shipped sibling
# SBNotificationVisibleIdleTimer (0.1-3600, examined default 8).
IDLE_SLIDER = Control(type="slider", min=0.1, max=3600.0, step=0.1, default=8.0)


def switch_tweak(spec) -> Tweak:
    tid, label, desc, min_version, values = spec
    return Tweak(
        id=tid,
        label=label,
        description=desc,
        default=False,
        min_version=min_version,
        writes=[Write("plist", SB_PLIST, dict(values))],
        writes_off=[Write("plist", SB_PLIST, {k: False for k in values})],
    )


def slider_tweak() -> Tweak:
    return Tweak(
        id="SBAmbientExtendedIdleTimer",
        label="Ambient Extended Idle Timer",
        description="StandBy (ambient) idle-timer extension in seconds; "
                    "strict accessor pairing (ambientExtendedIdleTimer) in "
                    "the 27.1 bind table, next to "
                    "SBNotificationVisibleIdleTimer. Units unknown and no "
                    "examined default - the slider starts at the sibling "
                    "notification timer's 8s and spans 0.1-3600. "
                    "Firmware-verified key; value semantics not tested.",
        default=False,
        min_version="27.1",
        control=IDLE_SLIDER,
        writes=[Write("plist", SB_PLIST, {"SBAmbientExtendedIdleTimer": "$value"})],
    )


def build() -> Template:
    tweaks = [switch_tweak(s) for s in STRICT_27_1 + AMBIENT_27_1 + PRE_EXISTING]
    tweaks.append(slider_tweak())
    return Template(
        title="SpringBoard - iOS 27.1 Firmware Findings",
        author=AUTHOR,
        description=(
            "Keys extracted from the iOS 27.1 (24A94401) simulator dyld "
            "shared cache by diffing SpringBoardFoundation's defaults bind "
            "table against iOS 27.0, plus pre-existing table keys the "
            "accessor pairing had missed. Every key is firmware-verified "
            "(it lives in SpringBoardFoundation's own bind table); none has "
            "been tested on a device. Full evidence and the excluded-key "
            "reasoning: docs/data/fw_new_keys_27.1.md."
        ),
        min_version="27.0",
        tags=["springboard", "firmware", "27.1"],
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

    out = os.path.join(OUT_DIR, "SpringBoard-27.1.batter")
    batter_io.save(template, out)
    print(f"written: {out}  ({len(template.tweaks)} tweaks)")
    for t in template.tweaks:
        keys = sorted({k for w in t.writes for k in w.values})
        print(f"  {t.id:45s} {','.join(keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
