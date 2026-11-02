"""Single source of truth for the plist-based tweaks.

Every tweak's definition (id, section, title, plist location, key, default
value, UI kind) lives here exactly once. ``tweak_loader`` builds the runtime
instances from these specs and the iOS tweaks page renders its rows from
them — adding a tweak means adding one entry here.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.utils.i18n import QT_TRANSLATE_NOOP

from .basic_plist_locations import FileLocation
from .tweak_names import TweakID


class Section(Enum):
    POSTERBOARD = "PosterBoard"
    LIQUID_GLASS = "Liquid Glass"
    SPRINGBOARD = "SpringBoard"
    INTERNAL = "Internal Options"


class Kind(Enum):
    POSTER_ARCHIVE = "poster_archive"
    WALLPAPER = "wallpaper"
    POSTER_FLAG = "poster_flag"
    SWITCH = "switch"   # boolean toggle
    TEXT = "text"       # free-form text value
    NUMBER = "number"   # numeric value


# Feature (page) key each registry Section belongs to. Feeds HotLoad's
# FEATURE_TWEAKS so every registry tweak automatically joins its feature;
# the Sidebar uses the same keys to know which page owns a section.
SECTION_FEATURES: dict[Section, str] = {
    Section.POSTERBOARD: "PosterBoard",
    Section.LIQUID_GLASS: "Liquid Glass",
    Section.SPRINGBOARD: "Springboard",
    Section.INTERNAL: "Internal",
}


@dataclass(frozen=True)
class TweakSpec:
    id: TweakID
    section: Section
    title: str
    location: FileLocation
    key: str
    value: any = True          # value written when the tweak is enabled
    kind: Kind = Kind.SWITCH
    min_value: float = 0       # NUMBER kind only
    max_value: float = 999     # NUMBER kind only
    reset_value: Optional[float] = None
    step: float = 1.0          # NUMBER kind only; not integral = decimal input
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    iphone_only: bool = False
    ipad_only: bool = False
    requires_dynamic_island: bool = False
    requires_camera_control: bool = False
    requires_action_button: bool = False
    requires_home_button: bool = False
    requires_always_on: bool = False
    bundle_identifier: bool = False
    unavailable_reason: Optional[str] = None
    show_when_unavailable: bool = False
    factory: Optional[Callable[[], object]] = None  # overrides BasicPlistTweak
    description: Optional[str] = None  # detailed "what it does" tooltip
    experimental: bool = False
    warning: Optional[str] = None
    requires: tuple[TweakID, ...] = ()
    exclusive_with: Optional[TweakID] = None
    disabled: bool = False  # True = tweak is cut off: never loaded, never applied, never rendered
    supported_models: tuple[str, ...] = ()
    requires_apple_intelligence: bool = False


def _t(id_: TweakID, section: Section, title: str, location: FileLocation,
       key: str, description: str = "", **kwargs) -> TweakSpec:
    # QT_TRANSLATE_NOOP marks the title for pyside6-lupdate; the actual
    # translation happens at render time (translators are not installed yet
    # when this module is imported).
    return TweakSpec(id=id_, section=section,
                     title=QT_TRANSLATE_NOOP("Nugget", title),
                     description=QT_TRANSLATE_NOOP("Nugget", description) if description else None,
                     location=location, key=key, **kwargs)


def _watchos_compatibility():
    from .tweak_classes import AdvancedPlistTweak
    return AdvancedPlistTweak(
        FileLocation.nanoregistry,
        keyValues={
            "IOS_PAIRING_EOL_MIN_PAIRING_COMPATIBILITY_VERSION_CHIPIDS": "",
            "maxPairingCompatibilityVersion": 37,
            "lastRestoreIdentifier": "CD97EEB8-BCD2-486B-BC13-C384E6B916C4",  # not sure if this is needed
            "minPairingCompatibilityVersionWithChipID": 1,
            "lastRestoreIdentifier_state": 0,
            "AdvertisingIdentifierSeed": "85E70251-1960-4DA0-A321-B68AC118FAB5",  # this prolly isn't needed either
            "minPairingCompatibilityVersion": 1
        })


def _sb_experiment(member, title, on_value, off_value, description, **kwargs):
    from .tweak_classes import ExperimentalBooleanPlistTweak
    return _t(member, Section.SPRINGBOARD, title,
              FileLocation.springboard, member.name, value=on_value,
              factory=lambda: ExperimentalBooleanPlistTweak(
                  FileLocation.springboard, member.name, on_value, off_value),
              description=description,
              min_version="26.1", experimental=True, **kwargs)


def _experimental_domain_boolean(location, key, on_value=True, off_value=False):
    from .tweak_classes import ExperimentalBooleanPlistTweak
    return ExperimentalBooleanPlistTweak(location, key, on_value, off_value)


def _resettable_number(member, value):
    from .tweak_classes import ResettableNumericPreferenceTweak
    return ResettableNumericPreferenceTweak(FileLocation.springboard, member.name, value=value)


def _bundle_preference(member):
    from .tweak_classes import OptionalBundlePreferenceTweak
    return OptionalBundlePreferenceTweak(FileLocation.springboard, member.name, value="")


def _usol(member: TweakID, title: str, kind: Kind = Kind.SWITCH, value=True, *,
          min_value: float = 0, max_value: float = 999, step: float = 1.0,
          description: str = "") -> TweakSpec:
    """UISolarium* debug / stacked-icon-motion tweak (.GlobalPreferences, iOS 27).

    The plist key is derived from the TweakID name (``UISolarium`` + name), so
    the enum member and the written key can never drift apart.
    """
    return _t(member, Section.LIQUID_GLASS, title, GP,
              "UISolarium" + member.name,
              description=description, kind=kind, value=value,
              min_value=min_value, max_value=max_value, step=step,
              min_version="27.0")


def _reversible_bool(location, key, *, integer_value=False):
    from .tweak_classes import ReversibleBooleanPlistTweak
    return ReversibleBooleanPlistTweak(location, key, integer_value=integer_value)


GP = FileLocation.globalPreferences

def _icon_outline_experiment():
    from .tweak_classes import ExperimentalBooleanPlistTweak
    return ExperimentalBooleanPlistTweak(GP, "SBDisableIconOutline", True, False)


def _siri_ai(action):
    from .siri_ai import SiriAITweak
    return SiriAITweak(action)


SPECS: tuple[TweakSpec, ...] = (
    _t(TweakID.PosterKitOverrides, Section.POSTERBOARD, 'PosterKit Wallpaper Settings',
       FileLocation.springboardPreferencesHomeDomain, 'PosterKitOverrides', value={},
       kind=Kind.POSTER_ARCHIVE, experimental=True, min_version='27.0',
       description='Edits selected fields in existing device wallpaper archives. Applies to all matching configurations. Experimental; not all styles honor every field.'),
    *(_t(member, Section.POSTERBOARD, title, FileLocation.springboardPreferencesHomeDomain,
         member.name, value={'none': {
             'SBWallpaperHasVideoKey': False, 'SBWallpaperMagnifyEnabledKey': False,
             'SBWallpaperParallaxFactorKey': 1, 'SBWallpaperPortraitKey': True,
             'SBWallpaperStillTimeInVideoKey': 0, 'SBWallpaperSupportsCroppingKey': False,
             'SBWallpaperZoomScaleKey': 1, 'kSBProceduralWallpaperHomeUserSetKey': False,
         }}, kind=Kind.WALLPAPER, experimental=True,
         description='Writes the selected wallpaper dictionary to SpringBoard preferences. Current iOS behavior is unverified.')
      for member,title in ((TweakID.SBHomeScreenWallpapers,'Home Screen Wallpaper Preferences'),
                           (TweakID.SBLockScreenWallpapers,'Lock Screen Wallpaper Preferences'))),
    # AXSettings key observed in iOS 27.0.1 (24A446). Managed delivery still
    # needs device validation; leave the user's setting alone until selected.
    _t(TweakID.LimitDisplayRefreshRate, Section.INTERNAL, 'Limit Frame Rate to 60 FPS',
       FileLocation.accessibility, 'LimitDisplayRefreshRate',
       'Limits the maximum display frame rate to 60 fps on ProMotion displays. Has no effect on displays already limited to 60 Hz.',
       min_version='27.0', experimental=True,
       factory=lambda: _experimental_domain_boolean(
           FileLocation.accessibility, 'LimitDisplayRefreshRate'),
       warning='Experimental: applying this setting has not been verified on a device. Turn off and apply to remove the requested frame-rate limit.'),
    _t(TweakID.SiriAI, Section.INTERNAL, 'Siri AI (Ineligible Regions)',
       FileLocation.siriAIOverrides, 'SiriAI',
       'Siri AI override in regions where it unsupported',
       min_version='27.0', iphone_only=False,
       experimental=False, requires_apple_intelligence=True,
       factory=lambda: _siri_ai('enable'), exclusive_with=TweakID.ResetSiriAIOverrides,
       warning='Requires an unencrypted protective backup and a reboot. Set Siri language to English (US), then complete consent in Settings. This replaces ALL existing eligibility overrides. Other builds are untested. Turning this switch off does not undo an applied override; use Reset Siri AI Overrides and apply.'),
    _t(TweakID.ResetSiriAIOverrides, Section.INTERNAL, 'Reset Siri AI Overrides',
       FileLocation.siriAIOverrides, 'ResetSiriAIOverrides',
       'Writes a valid empty eligibility override archive. This clears ALL eligibility overrides, including overrides installed by other tools.',
       min_version='27.0', max_version='27.99.99', iphone_only=True,
       experimental=True,
       factory=lambda: _siri_ai('reset'), exclusive_with=TweakID.SiriAI,
       warning='This clears ALL eligibility overrides, not just Siri AI. It cannot recover a previous override map. Requires an unencrypted protective backup; apply and reboot.'),
    _sb_experiment(TweakID.SBChamoisWindowingEnabled, 'iPad Window Mode', True, False,
                   "Enables Apple's hidden iPad window-management mode.", ipad_only=True),
    _sb_experiment(TweakID.SBChamoisHideDockExternal, 'Hide Dock on External Display', True, False,
                   'Hides the Dock on a screen connected to your iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBChamoisHideStripsExternal, 'Hide Recent Windows on External Display', True, False,
                   'Hides the recent-window list on a screen connected to your iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBDisableCaptureButton, 'Disable Camera Control', True, False,
                   'Stops the Camera Control button from responding.', requires_camera_control=True),
    _sb_experiment(TweakID.SBDisableProximity, 'Keep Screen On Near Your Face', True, False,
                   'Stops the screen turning off near your face during calls.'),
    _sb_experiment(TweakID.SBSuppressScreenSharingStatusBarOverridePreferenceKey, 'Hide Screen Sharing Indicator', True, False,
                   'Hides the special status indicator while sharing your screen.'),
    _sb_experiment(TweakID.SBCarPlayShowOptimalCellData, 'Show CarPlay Network Indicator', True, False,
                   'Shows a hidden cellular-data indicator in CarPlay.'),
    _sb_experiment(TweakID.SBDisableHomeButton, 'Disable Home Button', True, False,
                   'Stops the physical Home button responding.', requires_home_button=True),
    _sb_experiment(TweakID.SBForceAllPhoneAppsToBeResizableOnPad, 'Resize iPhone Apps on iPad', True, False,
                   'Lets iPhone-only apps resize on iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBForceAllPhoneAppsToBeResizableOnResizableDisplays, 'Resize iPhone Apps on Other Displays', True, False,
                   'Resize iPhone apps on iPad displays.', ipad_only=True),
    _t(TweakID.SBScreenLongevityDimInterval, Section.SPRINGBOARD, 'Screen Dimming Interval',
       FileLocation.springboard, 'SBScreenLongevityDimInterval', kind=Kind.NUMBER, value=60.0,
       min_value=-1, max_value=86400, step=1, reset_value=-1,
       min_version="27.0", experimental=True,
       factory=lambda: _resettable_number(TweakID.SBScreenLongevityDimInterval, 60.0),
       description='Hidden dimming interval; time units unknown. Enter -1 to remove.',
       warning='The effect and safe values are unknown. Test this alone. Enter -1 and apply to remove this setting.'),
    _t(TweakID.SBPhoneInitiatedAppResizeWidth, Section.SPRINGBOARD, 'iPhone App Window Width',
       FileLocation.springboard, 'SBPhoneInitiatedAppResizeWidth', kind=Kind.NUMBER, value=390.0,
       min_value=-1, max_value=4096, step=1, reset_value=-1,
       min_version="27.0", experimental=True, ipad_only=True,
       factory=lambda: _resettable_number(TweakID.SBPhoneInitiatedAppResizeWidth, 390.0),
       description='Window width for iPhone apps on iPad. Enter -1 to remove.',
       warning='Working window sizes are unknown and apps may display incorrectly. Enter -1 and apply to remove this setting.'),
    _t(TweakID.SBPhoneInitiatedAppResizeHeight, Section.SPRINGBOARD, 'iPhone App Window Height',
       FileLocation.springboard, 'SBPhoneInitiatedAppResizeHeight', kind=Kind.NUMBER, value=844.0,
       min_value=-1, max_value=4096, step=1, reset_value=-1,
       min_version="27.0", experimental=True, ipad_only=True,
       factory=lambda: _resettable_number(TweakID.SBPhoneInitiatedAppResizeHeight, 844.0),
       description='Window height for iPhone apps on iPad. Enter -1 to remove.',
       warning='Working window sizes are unknown and apps may display incorrectly. Enter -1 and apply to remove this setting.'),
    _t(TweakID.SBCaptureButtonAssociatedAppBundleIdentifier, Section.SPRINGBOARD, 'Camera Control App',
       FileLocation.springboard, 'SBCaptureButtonAssociatedAppBundleIdentifier', kind=Kind.TEXT, value="",
       factory=lambda: _bundle_preference(TweakID.SBCaptureButtonAssociatedAppBundleIdentifier),
       min_version="27.0", experimental=True, bundle_identifier=True,
       requires_camera_control=True,
       description='App to open with Camera Control. Enter an app ID; clear it to undo.',
       warning='An unsupported app ID may stop this button working. Clear the field and apply to remove this setting.'),
    _t(TweakID.DisableControlSymbolAnimations, Section.SPRINGBOARD, 'Stop Button Icon Animations', FileLocation.uikit,
       'DisableControlSymbolAnimations', value=True, min_version="27.0", experimental=True,
       factory=lambda: _experimental_domain_boolean(FileLocation.uikit, 'DisableControlSymbolAnimations', True, False),
       description='Stops small icon animations inside buttons.'),
    _t(TweakID.NavigationBarBackButtonShowsContextMenu, Section.SPRINGBOARD, 'Hide Back Button History', FileLocation.uikit,
       'NavigationBarBackButtonShowsContextMenu', value=False, min_version="27.0", experimental=True,
       factory=lambda: _experimental_domain_boolean(FileLocation.uikit, 'NavigationBarBackButtonShowsContextMenu', False, True),
       description="Hides the history menu shown when holding an app's Back button."),

    _t(TweakID.SBAppIconForceTouchAnimationDurationMultiplier, Section.SPRINGBOARD,
       'App Menu Animation Speed', FileLocation.springboard,
       "SBAppIconForceTouchAnimationDurationMultiplier", kind=Kind.NUMBER, value=0.5,
       min_value=-1, max_value=10, step=0.01, reset_value=-1, min_version="26.0", experimental=True,
       factory=lambda: _resettable_number(TweakID.SBAppIconForceTouchAnimationDurationMultiplier, 0.5),
       description='Speed of the menu opened by holding an app icon. Enter -1 to remove.',
       warning='This older setting may be ignored on your system version. Test it alone. Enter -1 and apply to remove it.'),
    _t(TweakID.SBQuickActionAnimationDuration, Section.SPRINGBOARD,
       'App Shortcut Animation Time', FileLocation.springboard,
       "SBQuickActionAnimationDuration", kind=Kind.NUMBER, value=0.1,
       min_value=-1, max_value=10, step=0.01, reset_value=-1, min_version="26.0", experimental=True,
       factory=lambda: _resettable_number(TweakID.SBQuickActionAnimationDuration, 0.1),
       description='Time used for app shortcut animations; units unconfirmed. Enter -1 to remove.',
       warning='This older setting may be ignored on your system version. The example number is not a proven working value. Enter -1 and apply to remove it.'),
    _t(TweakID.SBAppIconForceTouchEnableUIPreviewInteractionAnimations, Section.SPRINGBOARD,
       'Stop App Preview Animations', FileLocation.springboard,
       "SBAppIconForceTouchEnableUIPreviewInteractionAnimations", value=False,
       factory=lambda: _experimental_domain_boolean(FileLocation.springboard,
           "SBAppIconForceTouchEnableUIPreviewInteractionAnimations", False, True),
       min_version="26.0", experimental=True,
       description='Stops animations used when previewing an app from its icon.',
       warning='This older setting may do nothing. It does not stop every animation. Turn off and apply to reverse the request.'),
    _t(TweakID.DisableIconGlassOutline, Section.LIQUID_GLASS,
       'Hide Glass Icon Outlines', GP, "SBDisableIconOutline",
       factory=lambda: _icon_outline_experiment(),
       min_version="26.0", experimental=True,
       description='Hides outlines around glass icons.',
       warning='This guessed setting may do nothing. It does not remove all Liquid Glass effects.'),
    _t(TweakID.SBBacklightLevel2, Section.SPRINGBOARD, 'Screen Brightness',
       FileLocation.springboard, 'SBBacklightLevel2', kind=Kind.NUMBER, value=0.5,
       min_value=-1, max_value=1, step=0.01, reset_value=-1, min_version="26.1", experimental=True,
       factory=lambda: _resettable_number(TweakID.SBBacklightLevel2, 0.5),
       description='Brightness value from 0 to 1; not a guaranteed percentage. Enter -1 to remove.',
       warning='The screen may become very dim, especially at 0. The system may ignore or replace this value. Enter -1 and apply to remove it.'),


    _sb_experiment(TweakID.SBAppLibraryInDockEnabled, 'Hide App Library in Dock', False, True,
                   'Hides the App Library shortcut in the iPad Dock.', ipad_only=True),
    _sb_experiment(TweakID.SBRecentsEnabled, 'Hide Recent Apps in Dock', False, True,
                   'Hides recent or suggested apps in the iPad Dock.', ipad_only=True),

    _sb_experiment(TweakID.SBAlwaysOnTapToInteract, 'Tap Always-On Display to Interact', True, False,
                   'Allows touch interaction while Always-On Display is active.', requires_always_on=True),
    _sb_experiment(TweakID.SBAlwaysOnSwipeToUnlock, 'Disable Always-On Unlock Swipe', False, True,
                   'Stops swiping to unlock from Always-On Display.', requires_always_on=True),
    _sb_experiment(TweakID.SBAndromedaDebugColors, 'Show Always-On Clock Test Colors', True, False,
                   'Shows test colors on the Always-On Lock Screen clock.', requires_always_on=True),
    _sb_experiment(TweakID.SBUseAlwaysOnBrightnessCurve, 'Change Always-On Brightness Behavior', False, True,
                   'Stops the usual Always-On brightness adjustment.', requires_always_on=True, warning='The Always-On screen may look different or use more battery.'),
    _sb_experiment(TweakID.SBEnforceOverallAPLLimit, 'Remove Always-On Image Brightness Limit', False, True,
                   'Removes a hidden limit on the overall brightness of the Always-On image.', requires_always_on=True, warning='This may change screen brightness or increase battery use. Test it alone and restore defaults afterward.'),
    _sb_experiment(TweakID.SBShouldAddDefaultWidgetsToHomeScreen, 'Stop Adding Default Widgets', False, True,
                   'Stops default widgets being added during setup or an upgrade.', warning='This affects setup or upgrades. Removing this setting cannot bring back a widget layout that has already changed.'),
    _sb_experiment(TweakID.SBShouldUpgradeEnableWidgetSuggestions, 'Skip Widget Suggestion Setup', False, True,
                   'Skips a widget-suggestion setup step during upgrades.', warning='This affects setup or upgrades. Removing this setting cannot bring back a widget layout that has already changed.'),
    _sb_experiment(TweakID.SBShouldResetDefaultTodayList, 'Keep Today View Widget List', False, True,
                   'Prevents a setup or upgrade step from resetting the Today View widget list.', warning='This affects setup or upgrades. Removing this setting cannot bring back a widget layout that has already changed.'),
    _sb_experiment(TweakID.SBShouldResetStackForDefaultTodayList, 'Keep Today View Widget Stack', False, True,
                   'Prevents a setup or upgrade step from resetting the Today View widget stack.', warning='This affects setup or upgrades. Removing this setting cannot bring back a widget layout that has already changed.'),
    _sb_experiment(TweakID.SBCaptureButtonAllowLaunchIfUnobstructionOccursWhileButtonDown, 'Open Camera When Button Is Uncovered', True, False,
                   'Opens Camera when an obstruction clears while Camera Control is held.', requires_camera_control=True),
    _sb_experiment(TweakID.SBCaptureButtonAllowLaunchIfUnobstructionOccursPromptlyAfterButtonUp, 'Open Camera After Button Is Released', True, False,
                   'Opens Camera if an obstruction clears shortly after releasing Camera Control.', requires_camera_control=True),
    _sb_experiment(TweakID.SBEnableExtraBacklightLogging, 'Record Extra Brightness Logs', True, False,
                   'Saves more brightness troubleshooting logs.'),
    _sb_experiment(TweakID.SBShouldLaunchWithMallocStackLogging, 'Record Interface Memory Use', True, False,
                   'Record detailed memory-use logs when the system interface starts.', warning='Detailed memory logs can slow down the interface and use extra memory and storage. This is for troubleshooting, not making the device faster.', exclusive_with=TweakID.SBDisableAutomaticMallocStackLogging),
    _sb_experiment(TweakID.SBDisableAutomaticMallocStackLogging, 'Stop Automatic Memory Logs', True, False,
                   'Stops automatic detailed memory-use logs.', exclusive_with=TweakID.SBShouldLaunchWithMallocStackLogging),
    _sb_experiment(TweakID.SBDisableIdleSleep, 'Disable Hidden Idle Sleep', True, False,
                   'Changes a hidden sleep setting, not the normal Auto-Lock timeout.', warning='The device may stay awake longer, get warmer or use more battery. Test this alone.'),
    _sb_experiment(TweakID.SBSystemGestureLogging, 'Record Gesture Logs', True, False,
                   'Saves troubleshooting logs for system gestures, such as swiping between apps.'),
    _t(TweakID.AMBumpToWakeEnabled, Section.SPRINGBOARD, 'Stop StandBy Waking from Movement',
       FileLocation.ambient, 'AMBumpToWakeEnabled', value=False, min_version="26.1", experimental=True, iphone_only=True,
       factory=lambda: _experimental_domain_boolean(FileLocation.ambient, 'AMBumpToWakeEnabled', False, True),
       description='Stops StandBy waking when the device is bumped.'),
    _t(TweakID.SBMenuBarDemoMode, Section.SPRINGBOARD, 'iPad Menu Bar Demo Commands',
       FileLocation.springboard, 'SBMenuBarDemoMode', kind=Kind.NUMBER, value=0, min_value=0, max_value=2,
       experimental=True, min_version="26.1", ipad_only=True,
       description='0: Off. 1: Show after searching Help for sbdemo. 2: Always show. iPad menu bar required.',
       warning='Demo commands can save or change app-window layouts. Set 0 and apply to hide the commands. This does not undo layouts changed through that menu.'),
    _t(TweakID.SBStatusBarishLogOptions, Section.SPRINGBOARD, 'Status Bar Logs',
       FileLocation.springboard, 'SBStatusBarishLogOptions', kind=Kind.NUMBER, value=0, min_value=0, max_value=0,
       experimental=True, min_version="26.1", requires_always_on=False,
       unavailable_reason="Accepted values and reset behavior not established.", description='Unavailable: valid setting numbers are unknown.'),

    _sb_experiment(TweakID.SBTrackpadSwitcherGesturesEnabled, 'Disable Trackpad App Switching', False, True,
                   'Stops trackpad gestures that open the App Switcher.', ipad_only=True),
    _sb_experiment(TweakID.SBDisableHomeButtonDoublePress, 'Disable Home Button Double-Press', True, False,
                   'Stops double-pressing the Home button from opening the App Switcher.',
                   requires_home_button=True, warning='Double-pressing Home may stop opening the App Switcher. Turn off and apply to reverse this request.'),
    _t(TweakID.AMAmbientIgnoreBatteryCharging, Section.SPRINGBOARD, 'StandBy Without Charging',
       FileLocation.ambient, 'AMAmbientIgnoreBatteryCharging', value=True, experimental=True, min_version="26.1", iphone_only=True,
       factory=lambda: _experimental_domain_boolean(FileLocation.ambient, 'AMAmbientIgnoreBatteryCharging'),
       description='Skips one StandBy charging check.'),
    _t(TweakID.AMAlwaysUpdateIconModelOnAmbientWidgetLayoutChange, Section.SPRINGBOARD, 'Rebuild StandBy Widgets After Changes',
       FileLocation.ambient, 'AMAlwaysUpdateIconModelOnAmbientWidgetLayoutChange', value=True, experimental=True, min_version="26.1", iphone_only=True,
       factory=lambda: _experimental_domain_boolean(FileLocation.ambient, 'AMAlwaysUpdateIconModelOnAmbientWidgetLayoutChange'),
       description='Rebuild StandBy widget layouts when they change.'),

    _sb_experiment(TweakID.SBHideNotifications, 'Hide Lock Screen Notifications', True, False,
                   'Hides notifications on the Lock Screen.', warning='Lock Screen notifications may disappear. Turn off and apply to reverse this request.'),
    _sb_experiment(TweakID.SBShowQuickNoteFingerGestureRecognizer, 'Enable Quick Note Finger Gesture', True, False,
                   'Enables a finger gesture for Quick Note on iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBCoverSheetForceWakeToMaps, 'Maps on Lock Screen Wake', True, False,
                   'When or how Maps appears is unknown.', warning='This may change what appears when the device wakes. The exact effect is unknown.'),
    _sb_experiment(TweakID.SBFolderViewSuppressSetCurrentPage, 'Change Folder Page Selection', True, False,
                   'Blocks a hidden folder-page update. The visible effect is unconfirmed.', warning='This may stop you switching pages inside Home Screen folders normally.'),
    _sb_experiment(TweakID.SBHomeSidebarIsPinned, 'Keep iPad Home Sidebar Open', True, False,
                   'Keeps the hidden iPad Home Screen sidebar open.', ipad_only=True),
    _sb_experiment(TweakID.SBIgnoreCaptureApplicationLaunchMonitor, 'Skip Camera App Launch Check', True, False,
                   'Skips a hidden camera-app launch check.', warning='Camera may stop opening correctly. The effect on your system version is unconfirmed.'),
    _sb_experiment(TweakID.SBShouldShowSplitPeekEducation, 'Hide Split View Tips', False, True,
                   'Hides the introductory instructions for Split View on iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBShouldShowSlideOverPeekEducation, 'Hide Slide Over Tips', False, True,
                   'Hides the introductory instructions for Slide Over on iPad.', ipad_only=True),
    _sb_experiment(TweakID.SBHomeShouldShowLibraryEducationView, 'Hide App Library Tips', False, True,
                   'Hides the introductory instructions for App Library.'),
    _sb_experiment(TweakID.SBShouldShowWidgetIntroductionPage, 'Hide Widget Introduction', False, True,
                   'Hides the introductory page for widgets.'),
    _t(TweakID.SBExternalDisplayContentsScaleAndDontFileRadars, Section.SPRINGBOARD, 'External Display Size',
       FileLocation.springboard, 'SBExternalDisplayContentsScaleAndDontFileRadars', kind=Kind.NUMBER,
       value=0.0, min_value=0, max_value=0, experimental=True, min_version="26.1",
       unavailable_reason='iOS 27 preference binding and accepted range not established.',
       description='Unavailable: supported values and behavior are unknown.'),

    _sb_experiment(TweakID.SBDisableLiveIcons, 'Stop Live App Icons', True, False,
                   'Stops moving or updating app icons, such as the live Clock icon.'),
    _sb_experiment(TweakID.SBDisableIconFlyInAnimation, 'Stop Icons Flying In', True, False,
                   'Stops the Home Screen icons flying into place after unlocking.'),
    _sb_experiment(TweakID.SBDisableParallaxOnPageControl, 'Stop Page Dots Moving with Tilt', True, True,
                   'Stops the Home Screen page dots shifting as you tilt the device.'),
    _sb_experiment(TweakID.SBHideReportWidgetStackRotationQuickAction, 'Hide Widget Rotation Report Option', True, False,
                   'Hides the widget-stack menu option for reporting rotation problems.'),
    _sb_experiment(TweakID.SBWidgetSnapshottingEnabled, 'Stop Saving Widget Images', False, True,
                   'Stops the system saving widget preview images.',
                   warning='Widgets may appear blank, outdated or drawn incorrectly.'),
    _sb_experiment(TweakID.SBCoverSheetPrewarmCameraOnSwipe, 'Stop Preparing Camera During Swipe', False, True,
                   'Stops Camera getting ready during a Lock Screen swipe.',
                   requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _sb_experiment(TweakID.SBCoverSheetPrelaunchCameraOnSwipe, 'Stop Starting Camera During Swipe', False, True,
                   'Stops Camera starting early during a Lock Screen swipe.',
                   requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _sb_experiment(TweakID.SBCoverSheetPrewarmCameraOnButtonTouch, 'Stop Preparing Camera on Touch', False, True,
                   'Stops Camera getting ready when touching its Lock Screen button.',
                   requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _sb_experiment(TweakID.SBCoverSheetPrelaunchCameraOnButtonTouch, 'Stop Starting Camera on Touch', False, True,
                   'Stops Camera starting early when touching its Lock Screen button.',
                   requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _sb_experiment(TweakID.SBSuppressNoSimAlert, 'Hide No SIM Alerts', True, False,
                   'Hides pop-up alerts about a missing SIM card.'),
    _sb_experiment(TweakID.SBIgnoreMinimumRequiredSDKVersionForWidgets, 'Skip Widget Compatibility Check', True, False,
                   'Skips a widget software-version check.'),
    _sb_experiment(TweakID.SBPIPInitiallyUsesMinimumPreferredContentSize, 'Start Floating Videos Smaller', True, False,
                   'Opens Picture in Picture videos at their smallest preferred size.'),
    _sb_experiment(TweakID.SBDisableAsyncRenderingSurfaceRetention, 'Release Temporary Screen Images', True, False,
                   'Changes how temporary screen images are kept. No speed or memory benefit is confirmed.',
                   warning='The screen may draw incorrectly or the interface may become unstable. No speed or memory improvement is confirmed.'),
    _sb_experiment(TweakID.SBEnableDynamicJetsamLimits, 'Stop Automatic Interface Memory Limits', False, True,
                   'Stops the system adjusting memory limits for the Home Screen and Lock Screen.',
                   warning="Changing the system interface's memory limits may cause crashes or repeated restarts. Keep a usable backup."),
    _sb_experiment(TweakID.SBKillableInAppSwitcher, 'Allow Closing the System Interface', True, False,
                   'Allows closing the Home Screen interface from the App Switcher. Can cause restarts.',
                   warning='Closing the system interface may restart it. Repeated restarts or an unusable screen are possible; recovery may require restoring the device.'),
    _sb_experiment(TweakID.SBChamoisHideStrips, 'Hide Stage Manager Recent Windows', True, False,
                   'Hides the recent-window list in Stage Manager on iPad.',
                   ipad_only=True),
    _sb_experiment(TweakID.SBChamoisHideDock, 'Hide Stage Manager Dock', True, False,
                   'Hides the Dock while using Stage Manager on iPad.',
                   ipad_only=True),
    _sb_experiment(TweakID.SBBackgroundNethermostWindows, 'Windows Behind Other Windows', True, True,
                   'Changes background-window handling. Already on by default; visible effects are unconfirmed.',
                   ipad_only=True, warning='This may interrupt apps or change how iPad windows stay active. The exact effect is unknown.'),
    _sb_experiment(TweakID.SBFlexibleWindowingManualStageCreationShouldRestorePreviousOpenWindows, 'Stop Reopening Previous Stage Windows', False, True,
                   'Stops old windows reopening when you manually create a Stage Manager workspace.',
                   ipad_only=True),
    _sb_experiment(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm, 'Enable Lock Screen Camera Tests', True, False,
                   'Allows the camera preparation settings in this section to be used.',
                   warning='Camera may open more slowly or respond differently to gestures. Test one camera setting at a time.'),
    _t(TweakID.SBMaxIconListCount, Section.SPRINGBOARD, 'Home Screen Page Limit',
       FileLocation.springboard, 'SBMaxIconListCount',
       description='Hidden icon-page limit; how numbers affect pages is unknown. Examined default: 0.',
       experimental=True, kind=Kind.NUMBER, value=0, min_value=0, max_value=100, step=1.0, min_version="26.1", warning='Home Screen pages or icons may disappear. Set 0 to request the default found in the examined software.'),
    _t(TweakID.SBCoverSheetCameraPrewarmThreshold, Section.SPRINGBOARD, 'Camera Preparation Swipe Threshold',
       FileLocation.springboard, 'SBCoverSheetCameraPrewarmThreshold',
       description='When Camera gets ready during a Lock Screen swipe. Units unknown; default: 0.05.',
       experimental=True, kind=Kind.NUMBER, value=0.05, min_value=0, max_value=1, step=0.01, min_version="26.1", requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _t(TweakID.SBCoverSheetCameraPrelaunchThreshold, Section.SPRINGBOARD, 'Camera Startup Swipe Threshold',
       FileLocation.springboard, 'SBCoverSheetCameraPrelaunchThreshold',
       description='When Camera starts during a Lock Screen swipe. Units unknown; default: 0.05.',
       experimental=True, kind=Kind.NUMBER, value=0.05, min_value=0, max_value=1, step=0.01, min_version="26.1", requires=(TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm,)),
    _t(TweakID.SBCoverSheetPlayerTimeout, Section.SPRINGBOARD, 'Lock Screen Music Player Timeout',
       FileLocation.springboard, 'SBCoverSheetPlayerTimeout',
       description='Hidden music-player timeout. Units unknown; examined default: -1.',
       experimental=True, kind=Kind.NUMBER, value=-1.0, min_value=-1, max_value=3600, step=0.1, min_version="26.1"),

    _sb_experiment(TweakID.SBSuppressAppShortcutTruncation, 'Show Full App Shortcut Names', True, False,
                   'Shows full names in app-icon menus instead of shortening them.'),
    _sb_experiment(TweakID.SBShouldInsertDownloadFileStackIconToFloatingDock, 'Stop Adding Downloads to Dock', False, True,
                   'Stops the Downloads stack being added automatically to the iPad Dock.',
                   ipad_only=True),
    _sb_experiment(TweakID.SBCoverSheetProportionalAdaptiveTime, 'Change Lock Screen Clock Sizing', True, False,
                   'Changes a hidden clock-sizing option. The visible effect is unconfirmed.'),
    _sb_experiment(TweakID.SBNotificationCenterUseDuet, 'Stop Activity-Based Notification Suggestions', False, True,
                   'Stops notification suggestions based on your activity.'),
    _sb_experiment(TweakID.SBBatteryWidgetAlwaysAvailable, 'Always Offer Batteries Widget', True, False,
                   'Makes the Batteries widget available more often.'),
    _sb_experiment(TweakID.SBAlwaysAllowLongLookGesture, 'Allow More Notification Press Actions', True, False,
                   'Relaxes checks for opening a notification by pressing it. Does not bypass the passcode.'),
    _sb_experiment(TweakID.SBWantsManyForegroundWindows, 'Allow More Active iPad Windows', True, True,
                   'Requests more active windows. Already on by default; no higher limit is guaranteed.',
                   ipad_only=True, warning='App behavior, memory use and the number of active windows may change. No higher window limit is guaranteed.'),
    _sb_experiment(TweakID.SBCameraShutterButtonShouldUsePocketDetection, 'Check Pocket Before Opening Camera', True, False,
                   'Check whether the device is in a pocket before responding to Camera Control.',
                   requires_camera_control=True),
    _sb_experiment(TweakID.SBDismissControlCenterElsewhereOnPresentation, 'Close Control Center on Other Screens', True, True,
                   'Close Control Center on other displays when opening it here.'),
    _t(TweakID.SBCameraShutterButtonLongPressTimeout, Section.SPRINGBOARD, 'Camera Control Hold Time',
       FileLocation.springboard, 'SBCameraShutterButtonLongPressTimeout',
       description='Time before a hold is recognized. Units unconfirmed; examined default: 0.25.',
       experimental=True, kind=Kind.NUMBER, value=0.25, min_value=0.01, max_value=10,
       step=0.01, min_version="26.1", requires_camera_control=True,
       warning='Camera Control may stop responding reliably. Record your current value before changing it.'),
    _t(TweakID.SBCameraShutterButtonLongPressCancellationTimeout, Section.SPRINGBOARD, 'Camera Control Hold Cancel Time',
       FileLocation.springboard, 'SBCameraShutterButtonLongPressCancellationTimeout',
       description='Time limit for cancelling a hold. Units unconfirmed; examined default: 2.',
       experimental=True, kind=Kind.NUMBER, value=2.0, min_value=0.01, max_value=30,
       step=0.01, min_version="26.1", requires_camera_control=True,
       warning='Camera Control may stop responding reliably. Record your current value before changing it.'),

    _sb_experiment(TweakID.SBForceMedusaAdoption, 'Multitasking in More iPad Apps', True, False,
                   'Allows multitasking in apps that do not normally support it.',
                   ipad_only=True, warning='Apps may display incorrectly or have broken window controls. Test one app at a time.'),
    _sb_experiment(TweakID.SBIgnoreSBUsesNetwork, 'Ignore App Network-Use Declaration', True, False,
                   "Ignore an app's hidden network-use declaration."),
    _sb_experiment(TweakID.SBWidgetLogging, 'Record Widget Logs', True, False,
                   'Saves extra troubleshooting logs for widgets.'),
    _sb_experiment(TweakID.SBHijackSpotlightButtonActionForPrototyping, 'Change Search Button Action', True, False,
                   "Replaces normal Search with Apple's test action. The replacement action is unknown.",
                   warning='The Search button may stop working normally. Its replacement action is unknown.'),
    _sb_experiment(TweakID.SBPIPVisualizeKeyboardFrame, 'Show Floating Video Keyboard Guides', True, False,
                   'Draw guides around the keyboard area used to position Picture in Picture videos.'),
    _sb_experiment(TweakID.SBPIPVisualizePositionRegions, 'Show Floating Video Placement Guides', True, False,
                   'Shows where Picture in Picture videos are allowed to sit.'),
    _sb_experiment(TweakID.SBPostModernRotationForciblyEnabled, 'Alternate Screen Rotation', True, False,
                   'Uses a different system method for rotating the interface.',
                   warning='The screen may rotate incorrectly, apps may display badly or the interface may become unstable.'),
    _sb_experiment(TweakID.SBCoverSheetDisableDeviceMotionEffectPerformanceOptimizations, 'Disable Lock Screen Motion Shortcuts', True, False,
                   'Stops time-saving steps used to draw Lock Screen motion effects.',
                   warning='Lock Screen movement may stutter or use more power. No speed improvement is confirmed.'),
    _sb_experiment(TweakID.SBAlwaysShowSystemApertureOnClonedDisplays, 'Show Dynamic Island on Mirrored Screens', True, False,
                   'Includes Dynamic Island when mirroring the display.',
                   requires_dynamic_island=True),
    _sb_experiment(TweakID.SBEnableSystemApertureStateCollection, 'Stop Dynamic Island Status Recording', False, True,
                   'Stops hidden status recording for Dynamic Island.',
                   requires_dynamic_island=True),
    _sb_experiment(TweakID.SBShowRSSI, 'Show Cellular Signal Reading', True, False,
                   'Shows a signal-strength reading in the status bar.',
                   iphone_only=True),
    _sb_experiment(TweakID.SBShowThermalWarning, 'Apple Temperature Test Indicator', True, False,
                   "Only available on Apple's internal test devices in the examined software."),
    _sb_experiment(TweakID.SBShowStatusBarOverridesForRecording, 'Show Recording Status Indicators', True, False,
                   'Enables recording-related status bar changes.'),
    _sb_experiment(TweakID.SBAlwaysAllowDefaultAction, 'Relax Notification Action Checks', True, False,
                   "Relaxes hidden checks before running a notification's main action.",
                   warning='Notification actions may behave differently. Do not assume this removes passcode or other security checks.'),
    _sb_experiment(TweakID.SBSimulateCaptureButtonUsingActionButton, 'Use Action Button as Camera Control', True, False,
                   'Makes the Action Button act like Camera Control.',
                   requires_action_button=True, warning="This may replace the Action Button's current action. Camera Control features may still be unavailable."),
    _sb_experiment(TweakID.SBDisablePreLaunchCaptureButtonSuppression, 'Skip Camera Control Startup Block', True, False,
                   'Skips a hidden step that blocks Camera Control from launching an app.',
                   requires_camera_control=True),
    _sb_experiment(TweakID.SBCaptureButtonDisableWakeWhenDim, 'Stop Camera Control Waking Screen', True, False,
                   'Stops Camera Control waking a dimmed screen.',
                   requires_camera_control=True),
    _sb_experiment(TweakID.SBCaptureButtonDisableStationaryDetection, 'Ignore Movement for Camera Control', True, False,
                   'Stops checking whether the device is still when using Camera Control.',
                   requires_camera_control=True),
    _sb_experiment(TweakID.SBCaptureButtonDisableDirectLaunchAfterUnsuppress, 'Stop Camera Opening After a Block Clears', True, False,
                   'Stops direct camera launch when a Camera Control block is lifted.',
                   requires_camera_control=True),
    _sb_experiment(TweakID.SBCaptureButtonEnableCameraPose, 'Camera Position Detection', True, False,
                   'Its visible effect is unknown.',
                   requires_camera_control=True),
    _t(TweakID.SBBundleIdentifierToForceHomeAffordanceInset, Section.SPRINGBOARD, 'App with Extra Home Indicator Space',
       FileLocation.springboard, 'SBBundleIdentifierToForceHomeAffordanceInset', kind=Kind.TEXT, value="",
       factory=lambda: _bundle_preference(TweakID.SBBundleIdentifierToForceHomeAffordanceInset),
       description='Adds bottom-indicator space in one app. Enter its app ID; clear to undo.',
       experimental=True, bundle_identifier=True, min_version="26.1",
       warning="Use an installed app's ID. An unsupported ID may disrupt this part of the screen. Clear the field and apply to remove it."),
    _t(TweakID.SBSwitcherBottomEdgeGestureSwipeCount, Section.SPRINGBOARD, 'App Switcher Swipe Counter',
       FileLocation.springboard, 'SBSwitcherBottomEdgeGestureSwipeCount', kind=Kind.NUMBER, value=0,
       min_value=0, max_value=1000000, step=1.0, min_version="26.1",
       description='Changes the saved count of App Switcher swipes, not how many swipes you need to make.', experimental=True),
    _t(TweakID.SBNotificationVisibleIdleTimer, Section.SPRINGBOARD, 'Notification On-Screen Timer',
       FileLocation.springboard, 'SBNotificationVisibleIdleTimer', kind=Kind.NUMBER, value=8.0,
       min_value=0.1, max_value=3600, step=0.1, min_version="26.1",
       description='Hidden timer for visible notifications. Units unknown; examined default: 8.', experimental=True),
    _t(TweakID.SBMainDisplayDarkeningPercentage, Section.SPRINGBOARD, 'Screen Darkening',
       FileLocation.springboard, 'SBMainDisplayDarkeningPercentage', kind=Kind.NUMBER, value=0.0,
       min_value=0, max_value=0, step=0.01, min_version="26.1",
       description='Unavailable: safe values and visible behavior are unknown.', experimental=True, unavailable_reason="Accepted range and active consumer not verified."),

    # --- Liquid Glass ---
    _t(TweakID.SolariumEnableHomeScreenExteriorEffects, Section.LIQUID_GLASS,
       'Outer Home Screen Glass Effects', GP,
       "SolariumEnableHomeScreenExteriorEffects",
       factory=lambda: _reversible_bool(GP, "SolariumEnableHomeScreenExteriorEffects"),
       min_version="26.0",
       description='Visible effect and correct setting location are unconfirmed.'),
    _t(TweakID.SolariumNoBlurReducedFrost, Section.LIQUID_GLASS,
       'Less-Frosted Glass Without Blur', GP, "SolariumNoBlurReducedFrost",
       factory=lambda: _reversible_bool(GP, "SolariumNoBlurReducedFrost"),
       min_version="26.0",
       description='Visible effect and correct setting location are unconfirmed.'),
    _t(TweakID.ReduceHighlightingEffectsEnabled, Section.LIQUID_GLASS,
       'Reduce Bright Highlights', FileLocation.accessibility,
       "ReduceHighlightingEffectsEnabled", value=1,
       factory=lambda: _reversible_bool(FileLocation.accessibility,
                                      "ReduceHighlightingEffectsEnabled", integer_value=True),
       min_version="27.0",
       description='Reduces bright flashes and highlights when interacting with the interface.'),
    _t(TweakID.ForceSolariumFallback, Section.LIQUID_GLASS, 'Older Glass Drawing Method', GP, "SolariumForceFallback",
       description='Uses an older glass drawing method, not necessarily the pre-glass appearance.',
       min_version="26.0", max_version="26.99"),
    _t(TweakID.IgnoreSolariumLinkedOnCheck, Section.LIQUID_GLASS, 'Glass in Older Apps', GP, "com.apple.SwiftUI.IgnoreSolariumLinkedOnCheck",
       description='Skips the check for whether an app was built for the new glass design.',
       min_version="26.0"),
    _t(TweakID.ForceSolariumIntelligence, Section.LIQUID_GLASS, 'Hidden Glass Option', GP, "SolariumForceIntelligence",
       description='Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.ForceEnhancedSpeculars, Section.LIQUID_GLASS, 'Stronger Glass Reflections', GP, "SolariumForceEnhancedSpeculars",
       description='Strengthens light reflections on glass surfaces.',
       min_version="27.0"),
    _t(TweakID.UISolariumFallback, Section.LIQUID_GLASS, 'Alternate Glass Drawing Method', GP, "UISolariumForceFallback",
       description='Uses an alternate glass drawing method, not necessarily the pre-glass appearance.',
       min_version="27.0"),
    _t(TweakID.IgnoreSolariumHardwareCheck, Section.LIQUID_GLASS, 'Glass Without Hardware Check', GP, "com.apple.SwiftUI.IgnoreSolariumHardwareCheck",
       description='Skips a glass hardware check.',
       min_version="27.0"),
    _t(TweakID.IgnoreSolariumOptOut, Section.LIQUID_GLASS, 'Glass in Apps That Avoid It', GP, "com.apple.SwiftUI.IgnoreSolariumOptOut",
       description='Uses glass in apps that opted out.',
       min_version="27.0"),
    _t(TweakID.DisallowGlassButtons, Section.LIQUID_GLASS, 'Removing Glass from Buttons', GP, "SBDisallowGlassButtons",
       description='Removes the glass appearance from buttons.',
       min_version="27.0"),
    _t(TweakID.DisallowGlassLockScreen, Section.LIQUID_GLASS, 'Removing Lock Screen Glass',
       FileLocation.springboard, "SBDisallowGlassLockScreen",
       factory=lambda: _experimental_domain_boolean(FileLocation.springboard, "SBDisallowGlassLockScreen"),
       experimental=True, min_version="27.0",
       description='Limits glass effects on the Lock Screen.'),
    _t(TweakID.DisableSpecularEverywhere, Section.LIQUID_GLASS, 'Remove Glass Highlights', GP, "SBDisableSpecularEverywhere",
       description='Removes shiny light highlights from glass surfaces.',
       min_version="27.0"),
    _t(TweakID.NoLiquidClock, Section.LIQUID_GLASS, 'Remove Lock Screen Clock Glass', GP, "SBDisallowGlassTime",
       description='Removes the glass appearance from the Lock Screen clock.',
       min_version="26.0"),
    _t(TweakID.NoLiquidDock, Section.LIQUID_GLASS, 'Remove Dock Glass', GP, "SBDisableGlassDock",
       description='Removes the glass appearance from the Home Screen Dock.',
       min_version="26.0"),
    _t(TweakID.DisableSpecularMotion, Section.LIQUID_GLASS, 'Stop Glass Reflections Moving', GP, "SBDisableSpecularEverywhereUsingLSSAssertion",
       description='Keeps glass reflections still as the device moves.',
       min_version="26.0"),
    _t(TweakID.DisableOuterRefraction, Section.LIQUID_GLASS, 'Reduce Glass Edge Distortion', GP, "SolariumDisableOuterRefraction",
       description='Reduces the bending of the background around glass edges.',
       min_version="26.0"),
    _t(TweakID.DisableSolariumHDR, Section.LIQUID_GLASS, 'Limit Extra-Bright Glass Effects', GP, "SolariumAllowHDR", value=False,
       description='Stops glass effects using extra-bright display colors.',
       min_version="26.0"),
    # Home Screen glass family. These sit in the same accessor/key table as the
    # SB* keys above — the one SpringBoard itself persists into
    # com.apple.springboard — and SpringBoard reads them through the standard
    # defaults search chain, so NSGlobalDomain (GP) reaches them too.
    _t(TweakID.DisableWidgetSpecular, Section.LIQUID_GLASS, 'Remove Widget Shine',
       GP, "SBDisableWidgetSpecular",
       description='Removes shiny highlights from widgets.',
       min_version="26.0"),
    _t(TweakID.DisableDockSpecular, Section.LIQUID_GLASS, 'Remove Dock Shine',
       GP, "SBDisableDockSpecular",
       description='Removes shiny highlights from the Dock.',
       min_version="26.0"),
    _t(TweakID.DisableFolderSpecular, Section.LIQUID_GLASS, 'Remove Folder Shine',
       GP, "SBDisableFolderSpecular",
       description='Removes shiny highlights from Home Screen folders.',
       min_version="26.0"),
    _t(TweakID.ExcludeClearGlassShadows, Section.LIQUID_GLASS, 'Remove Clear Glass Shadows',
       GP, "SBExcludeAllClearGlassShadows",
       description='Removes shadows around clear glass surfaces.',
       min_version="26.0"),
    _t(TweakID.ExcludeDockShadow, Section.LIQUID_GLASS, 'Remove Dock Shadow',
       GP, "SBExcludeDockShadow",
       description='Removes the shadow beneath the Dock.',
       min_version="26.0"),
    _t(TweakID.ExcludeSearchShadow, Section.LIQUID_GLASS, 'Remove Search Button Shadow',
       GP, "SBExcludeSearchShadow",
       description='Removes the shadow beneath the Home Screen Search button.',
       min_version="26.0"),
    _t(TweakID.UseFlatIconsEverywhere, Section.LIQUID_GLASS, 'Use Flat App Icons',
       GP, "SBUseFlatIconsEverywhere",
       description='Uses flat-looking Home Screen icons instead of layered ones.',
       min_version="26.0"),

    # --- Tier 3: SwiftUI / UIKit debug switches (UserDefaults -> GP) ---
    _t(TweakID.FlexiGlassMacOS, Section.LIQUID_GLASS,
       'Mac-Style Glass', GP,
       "com.apple.SwiftUI.FlexiGlassMacOS",
       description='Mac-specific glass option. Effect on iPhone and iPad unknown.',
       min_version="27.0"),
    _t(TweakID.FlexiGlassMacOSPointer, Section.LIQUID_GLASS,
       'Mac-Style Pointer Glass', GP,
       "com.apple.SwiftUI.FlexiGlassMacOSPointer",
       description='Mac-specific pointer glass option. Effect on iPhone and iPad unknown.',
       min_version="27.0"),
    _t(TweakID.InvisibilitySuppressesGlass, Section.LIQUID_GLASS,
       'Stop Glass in Hidden Views', GP,
       "com.apple.UIKit.InvisibilitySuppressesGlass",
       description='Stops hidden parts of an app adding glass effects.',
       min_version="27.0"),
    _t(TweakID.EnableGlassEffectBridgeLayers, Section.LIQUID_GLASS,
       'Combined Glass Layers', GP,
       "EnableGlassEffectBridgeLayers",
       description='Changes a hidden glass-layer option. Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.EnableGaussianGlassEffectBridgeLayers, Section.LIQUID_GLASS,
       'Combined Glass Blur', GP,
       "EnableGaussianGlassEffectBridgeLayers",
       description='Changes a hidden glass-blur option. Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.UnifiedSystemBackgroundColorsEnabled, Section.LIQUID_GLASS,
       'Matching Background Colors', GP,
       "UnifiedSystemBackgroundColorsEnabled",
       description='Makes system background colors more consistent.',
       min_version="27.0"),
    _t(TweakID.UnaryGlassContainerEnabled, Section.LIQUID_GLASS,
       'Single Glass Container', GP,
       "UnaryGlassContainerEnabled",
       description='Changes a hidden glass grouping option. Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.EnableSolariumCompactChrome, Section.LIQUID_GLASS,
       'Smaller Glass Controls', GP,
       "EnableSolariumCompactChrome",
       description='Uses the compact size for glass controls.',
       min_version="27.0"),
    _t(TweakID.DisableSolariumCompactChrome, Section.LIQUID_GLASS,
       'Standard-Size Glass Controls', GP,
       "DisableSolariumCompactChrome",
       description='Uses the normal size instead of compact glass controls.',
       min_version="27.0"),

    # --- Tier 4: DesignLibrary glass recipes (GP) ---
    _t(TweakID.SolariumIncreasedDiffusion, Section.LIQUID_GLASS,
       'Softer Glass Backgrounds', GP, "SolariumIncreasedDiffusion",
       description='Spread background light more evenly through glass.',
       min_version="27.0"),
    _t(TweakID.SolariumUseDisplayAngle, Section.LIQUID_GLASS,
       'Tilt-Based Glass Lighting', GP, "SolariumUseDisplayAngle",
       description='Changes glass lighting with the screen angle.',
       min_version="27.0"),
    _t(TweakID.SolariumTintMask, Section.LIQUID_GLASS,
       'Glass Tint Layer', GP, "SolariumTintMask",
       description='Changes a hidden tint layer. Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.SolariumBackgroundFilter, Section.LIQUID_GLASS,
       'Glass Background Filter', GP, "SolariumBackgroundFilter",
       description='Changes a hidden background filter. Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.SolariumHighlightWhite, Section.LIQUID_GLASS,
       'Glass Highlight Brightness', GP, "SolariumHighlightWhite",
       value=1.0, kind=Kind.NUMBER, min_value=0.0, max_value=1.0, step=0.05,
       description='Brightness of glass highlights.',
       min_version="27.0"),
    _t(TweakID.SolariumHierarchicalStyle, Section.LIQUID_GLASS,
       'Glass Style Number', GP, "SolariumHierarchicalStyle",
       value=1, kind=Kind.NUMBER, min_value=0, max_value=10, step=1,
       description='What each style number does is unknown.',
       min_version="27.0"),
    _t(TweakID.GlassHierarchicalStyle, Section.LIQUID_GLASS,
       'Alternate Glass Style Number', GP, "GlassHierarchicalStyle",
       value=1, kind=Kind.NUMBER, min_value=0, max_value=10, step=1,
       description='What each style number does is unknown.',
       min_version="27.0"),
    _t(TweakID.GlassVisualDebug, Section.LIQUID_GLASS,
       'Show Glass Test Overlay', GP, "GlassVisualDebug",
       description='Shows a troubleshooting overlay for glass effects.',
       min_version="27.0"),
    _t(TweakID.GlassVisualWarnings, Section.LIQUID_GLASS,
       'Show Glass Drawing Warnings', GP, "GlassVisualWarnings",
       description='Shows on-screen warnings about problems drawing glass.',
       min_version="27.0"),
    _t(TweakID.BlurFillExperiment, Section.LIQUID_GLASS,
       'Glass Blur Fill', GP, "blurFillExperiment",
       description='Its visible effect is unknown.',
       min_version="27.0"),
    _t(TweakID.AdaptiveGlassHysteresisDarkRange, Section.LIQUID_GLASS,
       'Dark Mode Glass Thresholds', GP,
       "AdaptiveGlassHysteresisDarkRangeArray",
       value="", kind=Kind.TEXT,
       unavailable_reason='Numeric array format and accepted thresholds are not verified. Free-form text must not be applied.',
       description='Unavailable: the numeric array format and valid thresholds need verification.',
       min_version="27.0"),
    _t(TweakID.AdaptiveGlassHysteresisLightRange, Section.LIQUID_GLASS,
       'Light Mode Glass Thresholds', GP,
       "AdaptiveGlassHysteresisLightRangeArray",
       value="", kind=Kind.TEXT,
       unavailable_reason='Numeric array format and accepted thresholds are not verified. Free-form text must not be applied.',
       description='Unavailable: the numeric array format and valid thresholds need verification.',
       min_version="27.0"),
    _t(TweakID.CalistogaLargeRefraction, Section.LIQUID_GLASS,
       'Stronger Background Distortion', GP, "CalistogaLargeRefraction",
       description='Makes the background bend more through glass.',
       min_version="27.0"),
    _t(TweakID.CalistogaRegularClearer, Section.LIQUID_GLASS,
       'Clearer Glass', GP, "CalistogaRegularClearer",
       description='Makes glass backgrounds clearer.',
       min_version="27.0"),
    _t(TweakID.CalistogaBackdropMarginIncludesBlur, Section.LIQUID_GLASS,
       'Blur Around Glass Edges', GP,
       "CalistogaBackdropMarginIncludesBlur",
       description='Includes blur when calculating the space around glass backgrounds.',
       min_version="27.0"),
    _t(TweakID.CalistogaAllowLumaTracking, Section.LIQUID_GLASS,
       'Glass That Adapts to Brightness', GP, "CalistogaAllowLumaTracking",
       description='Changes glass with the brightness of the background behind it.',
       min_version="27.0"),
    _t(TweakID.CalistogaSidebarAccentOpacity, Section.LIQUID_GLASS,
       'Sidebar Color Strength', GP, "CalistogaSidebarAccentOpacity",
       value=1.0, kind=Kind.NUMBER, min_value=0.0, max_value=1.0, step=0.05,
       description='Strength of the sidebar tint.',
       min_version="27.0"),
    _t(TweakID.CalistogaPerceptualBackdropScale, Section.LIQUID_GLASS,
       'Glass Background Scale', GP,
       "CalistogaPerceptualBackdropScale",
       value=1.0, kind=Kind.NUMBER, min_value=0.0, max_value=2.0, step=0.05,
       description='Size setting used for glass backgrounds.',
       min_version="27.0"),
    _t(TweakID.CalistogaKeyboardGlass, Section.LIQUID_GLASS,
       'Keyboard Glass Effects', GP, "CalistogaKeyboardGlass",
       description='Enables glass effects on the keyboard.',
       min_version="27.0"),
    _t(TweakID.CalistogaCameraGlass, Section.LIQUID_GLASS,
       'Camera Control Glass Effects', GP, "CalistogaCameraGlass",
       description='Enables glass effects on camera controls.',
       min_version="27.0"),

    # --- Tier 5: UISolarium* floating content / stacked icon motion ---
    # Floating content view
    _usol(TweakID.FloatingContentViewSpecularHighlightOpacity,
          'Floating Panel Shine Strength',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How strong shiny highlights look on floating panels.'),
    _usol(TweakID.FloatingContentViewUnfocusedBorderOpacity,
          'Inactive Panel Border Strength',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How visible the border looks on an inactive floating panel.'),
    _usol(TweakID.FloatingContentViewUnfocusedBorderWidth,
          'Inactive Panel Border Width',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=20.0, step=0.5,
          description='How thick the border looks on an inactive floating panel.'),
    _usol(TweakID.FloatingContentViewEnableBackgroundFills,
          'Floating Panel Backgrounds',
          description='Drawing a background inside floating panels.'),
    _usol(TweakID.FloatingContentViewDebugBackgroundFills,
          'Floating Panel Test Backgrounds',
          description='Special troubleshooting backgrounds inside floating panels.'),
    _usol(TweakID.FloatingContentViewPunchoutShadow,
          'Floating Panel Cutout Shadow',
          description='A cutout-style shadow around floating panels.'),
    _usol(TweakID.FloatingContentViewModifyTransformMode,
          'Floating Panel Movement Mode',
          Kind.NUMBER, value=1, min_value=0, max_value=10, step=1,
          description='How floating panels move and tilt.'),
    _usol(TweakID.FloatingContentViewOverrideRotationX,
          'Floating Panel Forward/Back Tilt',
          Kind.NUMBER, value=0.0, min_value=-90.0, max_value=90.0, step=1.0,
          description='The forward and backward tilt for floating panels.'),
    _usol(TweakID.FloatingContentViewOverrideRotationY,
          'Floating Panel Side-to-Side Tilt',
          Kind.NUMBER, value=0.0, min_value=-90.0, max_value=90.0, step=1.0,
          description='The side-to-side tilt for floating panels.'),
    _usol(TweakID.FloatingContentViewOverrideTranslationX,
          'Floating Panel Left/Right Position',
          Kind.NUMBER, value=0.0, min_value=-1000.0, max_value=1000.0, step=1.0,
          description='The left and right position for floating panels.'),
    _usol(TweakID.FloatingContentViewOverrideTranslationY,
          'Floating Panel Up/Down Position',
          Kind.NUMBER, value=0.0, min_value=-1000.0, max_value=1000.0, step=1.0,
          description='The up and down position for floating panels.'),
    _usol(TweakID.FloatingContentViewModifyRotationStrength,
          'Floating Panel Tilt Strength',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How much floating panels tilt.'),
    _usol(TweakID.FloatingContentViewModifyTranslationStrength,
          'Floating Panel Movement Strength',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How far floating panels move.'),
    # Focus specular highlight
    _usol(TweakID.FocusSpecularHighlightMaxSize,
          'Selection Shine Maximum Size',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='The largest shiny highlight on a selected item.'),
    _usol(TweakID.FocusSpecularHighlightScaleFactor,
          'Selection Shine Size',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=2.0, step=0.05,
          description='The size of shiny highlights on selected items.'),
    _usol(TweakID.FocusSpecularHighlightSensitivity,
          'Selection Shine Response',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How readily shiny highlights respond to selecting an item.'),
    _usol(TweakID.FocusSpecularHighlightNormalizedPositionX,
          'Selection Shine Left/Right Position',
          Kind.NUMBER, value=0.5, min_value=0.0, max_value=1.0, step=0.05,
          description="The horizontal position of a selected item's shiny highlight."),
    _usol(TweakID.FocusSpecularHighlightNormalizedPositionY,
          'Selection Shine Up/Down Position',
          Kind.NUMBER, value=0.5, min_value=0.0, max_value=1.0, step=0.05,
          description="The vertical position of a selected item's shiny highlight."),
    # New stacked image (3D parallax) family
    _usol(TweakID.NewStackedImageRenderingEnabled,
          'Draw 3D Layered Images',
          description='A drawing method for pictures made from multiple layers.'),
    _usol(TweakID.NewStackedImageFiltersEnabled,
          'Layered Image Filters',
          description='Visual filters for pictures made from multiple layers.'),
    _usol(TweakID.NewStackedImage3DTransformsEnabled,
          'Layered Image 3D Movement',
          description='Tilting and moving layered pictures in 3D.'),
    _usol(TweakID.NewStackedImage3DTransformedGlassLayer,
          'Layered Image Moving Glass',
          description='A glass layer that moves with layered pictures.'),
    _usol(TweakID.NewStackedImageSpecularEnabled,
          'Layered Image Shine',
          description='Shiny highlights on layered pictures.'),
    _usol(TweakID.NewStackedImageSpecularOpacity,
          'Layered Image Shine Strength',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How visible shiny highlights look on layered pictures.'),
    _usol(TweakID.NewStackedImageRadiosityEnabled,
          'Layered Image Reflected Colors',
          description='Colors reflected between layers of a picture.'),
    _usol(TweakID.NewStackedImageForceAdjustMotionForSize,
          'Match Layered Image Movement to Size',
          description="Changing a layered picture's movement based on its size."),
    _usol(TweakID.NewStackedImageForceDefaultScaleSizeIncrease,
          'Enlarge Layered Images',
          description='Making layered pictures larger by default.'),
    _usol(TweakID.NewStackedImageInnerParallaxScale,
          'Movement Between Image Layers',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How much parts of a layered picture move relative to each other.'),
    _usol(TweakID.NewStackedImageAsymmetricScale,
          'Uneven Layered Image Scaling',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='Scaling different parts of a layered picture by different amounts.'),
    _usol(TweakID.NewStackedImageProgressiveScale,
          'Scaling Across Image Layers',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How picture size changes across successive layers.'),
    _usol(TweakID.NewStackedImageAdditionalTranslation,
          'Extra Layered Image Movement',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=100.0, step=1.0,
          description='Extra movement of layered pictures.'),
    _usol(TweakID.NewStackedImageFocusedAdditionalScaleAmount,
          'Enlarge Selected Layered Images',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=2.0, step=0.05,
          description='Extra enlargement when a layered picture is selected.'),
    # Stacked image container defaults and modifiers
    _usol(TweakID.StackedImageContainerDefaultMaxDepth,
          'Maximum Space Between Image Layers',
          Kind.NUMBER, value=20.0, min_value=0.0, max_value=100.0, step=1.0,
          description='The apparent depth between layers of a picture.'),
    _usol(TweakID.StackedImageContainerDefaultRotationX,
          'Layered Image Forward/Back Tilt',
          Kind.NUMBER, value=0.0, min_value=-90.0, max_value=90.0, step=1.0,
          description='The forward and backward tilt of layered pictures.'),
    _usol(TweakID.StackedImageContainerDefaultRotationY,
          'Layered Image Side-to-Side Tilt',
          Kind.NUMBER, value=0.0, min_value=-90.0, max_value=90.0, step=1.0,
          description='The side-to-side tilt of layered pictures.'),
    _usol(TweakID.StackedImageContainerDefaultTranslationX,
          'Layered Image Left/Right Position',
          Kind.NUMBER, value=0.0, min_value=-1000.0, max_value=1000.0, step=1.0,
          description='The left and right position of layered pictures.'),
    _usol(TweakID.StackedImageContainerDefaultTranslationY,
          'Layered Image Up/Down Position',
          Kind.NUMBER, value=0.0, min_value=-1000.0, max_value=1000.0, step=1.0,
          description='The up and down position of layered pictures.'),
    _usol(TweakID.StackedImageContainerModifyMaxDepthStrength,
          'Image Layer Depth Strength',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How strongly the depth between picture layers is applied.'),
    _usol(TweakID.StackedImageContainerModifyRotationStrength,
          'Layered Image Tilt Strength',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How much layered pictures tilt.'),
    _usol(TweakID.StackedImageContainerModifyTranslationStrength,
          'Layered Image Movement Strength',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='How far layered pictures move.'),
    _usol(TweakID.StackedImageContainerModifyInnerParallaxScaleStrength,
          'Relative Image Layer Movement',
          Kind.NUMBER, value=1.0, min_value=0.0, max_value=1.0, step=0.05,
          description='The strength of movement between parts of a layered picture.'),
    _usol(TweakID.StackedImageContainerModifyTransformMinWidth,
          'Layered Image Movement Minimum Width',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1000.0, step=1.0,
          description='The minimum width at which layered-picture movement is applied.'),
    _usol(TweakID.StackedImageContainerModifyTransformMaxWidth,
          'Layered Image Movement Maximum Width',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1000.0, step=1.0,
          description='The maximum width at which layered-picture movement is applied.'),
    _usol(TweakID.StackedImageContainerModifyTransformMinHeight,
          'Layered Image Movement Minimum Height',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1000.0, step=1.0,
          description='The minimum height at which layered-picture movement is applied.'),
    _usol(TweakID.StackedImageContainerModifyTransformMaxHeight,
          'Layered Image Movement Maximum Height',
          Kind.NUMBER, value=0.0, min_value=0.0, max_value=1000.0, step=1.0,
          description='The maximum height at which layered-picture movement is applied.'),

    # --- SpringBoard ---
    _t(TweakID.LockScreenFootnote, Section.SPRINGBOARD, 'Lock Screen Message',
       FileLocation.footnote, "LockScreenFootnote", value="", kind=Kind.TEXT,
       description='Adds a short message to the Lock Screen.'),
    _t(TweakID.WatchOSCompatibility, Section.SPRINGBOARD, 'Relax Apple Watch Version Check',
       FileLocation.nanoregistry, "", factory=_watchos_compatibility, ipad_only=False,
       description='Pair an Apple Watch running a different watchOS version.'),
    _t(TweakID.AirDropDisableTimeLimit, Section.SPRINGBOARD, 'Keep AirDrop Open to Everyone',
       FileLocation.airdrop, "OverrideTimeLimitEveryoneMode",
       description="Removes the usual time limit for AirDrop's Everyone setting."),
    _t(TweakID.SBDontLockAfterCrash, Section.SPRINGBOARD, 'Stay Unlocked After Interface Restart',
       FileLocation.springboard, "SBDontLockAfterCrash",
       description='Avoids locking after the system interface restarts.'),
    _t(TweakID.SBDontDimOrLockOnAC, Section.SPRINGBOARD, 'Keep Screen Awake While Charging',
       FileLocation.springboard, "SBDontDimOrLockOnAC",
       description='Prevents automatic dimming and locking while connected to power, .'),
    _t(TweakID.SBHideLowPowerAlerts, Section.SPRINGBOARD, 'Hide Low Battery Alerts',
       FileLocation.springboard, "SBHideLowPowerAlerts",
       description='Hides low-battery pop-up alerts, .'),
    _t(TweakID.SBHideACPower, Section.SPRINGBOARD, 'Hide Lock Screen Charging Indicator',
       FileLocation.springboard, "SBHideACPower",
       description='Hides the charging indicator on the Lock Screen.'),
    _t(TweakID.SBNeverBreadcrumb, Section.SPRINGBOARD, 'Hide Return-to-App Shortcut',
       FileLocation.springboard, "SBNeverBreadcrumb",
       description='Hides the status bar shortcut that returns to the previous app, .'),
    _t(TweakID.SBShowSupervisionTextOnLockScreen, Section.SPRINGBOARD, 'Show Device Management Message',
       FileLocation.springboard, "SBShowSupervisionTextOnLockScreen",
       description='Shows the device-management message on the Lock Screen when available.'),
    _t(TweakID.AirplaySupport, Section.SPRINGBOARD, 'Stage Manager over AirPlay',
       FileLocation.springboard, "SBExtendedDisplayOverrideSupportForAirPlayAndDontFileRadars",
       description='Enables Stage Manager on a wireless AirPlay display, where supported.'),
    _t(TweakID.SBMinimumLockscreenIdleTime, Section.SPRINGBOARD, 'Lock Screen Auto-Lock Time',
       FileLocation.springboard, "SBMinimumLockscreenIdleTime", value=5, kind=Kind.NUMBER,
       min_value=0, max_value=600,
       description='Changes the Lock Screen idle timeout .'),
    _t(TweakID.SBAlwaysShowSystemApertureInSnapshots, Section.SPRINGBOARD, 'Show Dynamic Island in Screenshots',
       FileLocation.springboard, "SBAlwaysShowSystemApertureInSnapshots", min_version="17.4", iphone_only=True, requires_dynamic_island=True,
       description='Includes Dynamic Island in screenshots.'),
    _t(TweakID.HideDICompletely, Section.SPRINGBOARD, 'Disable Dynamic Island',
       FileLocation.springboard, "SBSuppressDynamicIslandCompletely", factory=lambda: _reversible_bool(FileLocation.springboard, "SBSuppressDynamicIslandCompletely"),
       min_version="17.4", iphone_only=True, requires_dynamic_island=True,
       description='Hides Dynamic Island content. The black background can remain on iOS 27.'),
    _t(TweakID.SBShowAuthenticationEngineeringUI, Section.SPRINGBOARD, 'Show Lock Screen Unlock Test Indicator',
       FileLocation.springboard, "SBShowAuthenticationEngineeringUI",
       description="Shows Apple's unlock test indicator."),
    _t(TweakID.KeyboardShouldSplitInDefaultContext, Section.SPRINGBOARD, 'Prefer Split Keyboard',
       FileLocation.keyboardPreferences, "KeyboardShouldSplitInDefaultContext", min_version="27.0",
       factory=lambda: _experimental_domain_boolean(FileLocation.keyboardPreferences, "KeyboardShouldSplitInDefaultContext"),
       description='Requests a split keyboard in the default context.'),
    _t(TweakID.KeyboardShouldSplitInSplitPreferringContext, Section.SPRINGBOARD, 'Prefer Split Keyboard in Split-Preferring Contexts',
       FileLocation.keyboardPreferences, "KeyboardShouldSplitInSplitPreferringContext", min_version="27.0",
       factory=lambda: _experimental_domain_boolean(FileLocation.keyboardPreferences, "KeyboardShouldSplitInSplitPreferringContext"),
       description='Requests a split keyboard in split-preferring contexts.'),
    _t(TweakID.UIKeyboardPersistentSplitProgress, Section.SPRINGBOARD, 'Save Split Keyboard State',
       FileLocation.keyboardPreferences, "UIKeyboardPersistentSplitProgress", min_version="27.0",
       factory=lambda: _experimental_domain_boolean(FileLocation.keyboardPreferences, "UIKeyboardPersistentSplitProgress"),
       description='Sets the saved keyboard state to split.'),
    _t(TweakID.UIKeyboardPersistentSplitLock, Section.SPRINGBOARD, 'Save Split Keyboard Lock',
       FileLocation.keyboardPreferences, "UIKeyboardPersistentSplitLock", min_version="27.0",
       factory=lambda: _experimental_domain_boolean(FileLocation.keyboardPreferences, "UIKeyboardPersistentSplitLock"),
       description='Sets the saved split keyboard lock state.'),
    _t(TweakID.UseFloatingTabBar, Section.SPRINGBOARD, 'Use Fixed iPad Tab Bar',
       FileLocation.uikit, "UseFloatingTabBar", value=False, ipad_only=True,
       description='Replaces the floating iPad tab bar with a fixed one in apps.'),
    _t(TweakID.SBDisableIconParallax, Section.SPRINGBOARD, 'Stop Icons Moving with Tilt',
       FileLocation.springboard, "SBDisableParallax",
       description='Stops Home Screen icons shifting as you tilt the device, .'),
    _t(TweakID.SBHideSearchAffordance, Section.SPRINGBOARD, 'Hide Home Screen Search Button',
       FileLocation.springboard, "SBHomeScreenShowsSearchAffordance", value=False,
       max_version='27.0.99',
       description='Hides the Search button below Home Screen icons on versions before iOS 27.1.'),
    # Replacement key reported for iOS 27.1; no Duo-only hardware restriction
    # has been established. Keep the old ID for existing presets on older OSes.
    _t(TweakID.SBHomeScreenShowsSearchButton, Section.SPRINGBOARD,
       'Hide Home Screen Search Button (iOS 27.1+)',
       FileLocation.springboard, 'SBHomeScreenShowsSearchButton', value=False,
       min_version='27.1', experimental=True,
       factory=lambda: _experimental_domain_boolean(
           FileLocation.springboard, 'SBHomeScreenShowsSearchButton', False, True),
       description='Hides the Search button below Home Screen icons using the replacement iOS 27.1 setting.',
       warning='Reported for iOS 27.1; not yet verified on a device. Turn off and apply to show the Search button again.'),

    # --- Internal Options ---
    _t(TweakID.SBBuildNumber, Section.INTERNAL, 'Show System Build in Status Bar', GP, "UIStatusBarShowBuildVersion",
       description="Shows the device's software build number in the status bar."),
    _t(TweakID.RTL, Section.INTERNAL, 'Use Right-to-Left Layout', GP, "NSForceRightToLeftWritingDirection",
       description='Uses a right-to-left layout for the system interface.'),
    _t(TweakID.LTR, Section.INTERNAL, 'Use Left-to-Right Layout', GP, "NSForceLeftToRightWritingDirection",
       description='Uses a left-to-right layout for the system interface.'),
    _t(TweakID.SBIconVisibility, Section.INTERNAL, 'Show Hidden Home Screen Icons', GP, "SBIconVisibility",
       description='Shows hidden app icons.'),
    _t(TweakID.iMessageDiagnosticsEnabled, Section.INTERNAL, 'Show Messages Test Settings', GP, "iMessageDiagnosticsEnabled",
       description='Shows extra troubleshooting settings for Messages.'),
    _t(TweakID.IDSDiagnosticsEnabled, Section.INTERNAL, 'Show Cross-Device Test Settings', GP, "IDSDiagnosticsEnabled",
       description='Shows extra troubleshooting settings for features shared between Apple devices.'),
    _t(TweakID.VCDiagnosticsEnabled, Section.INTERNAL, 'Show FaceTime Test Settings', GP, "VCDiagnosticsEnabled",
       description='Shows extra troubleshooting settings for FaceTime.'),
    _t(TweakID.AccessoryDeveloperEnabled, Section.INTERNAL, 'Show Accessory Test Settings', GP, "AccessoryDeveloperEnabled",
       description='Shows development settings for connected accessories.'),
    _t(TweakID.DisableSecondsHand, Section.INTERNAL, 'Hide Clock Icon Second Hand', GP, "SBDisableClockIconSecondsHand",
       description='Hides the moving second hand on the Clock app icon.'),
    _t(TweakID.DisableSearchingWebsites, Section.INTERNAL, 'Stop Website Results in Search', GP, "SBSearchDisabledDomains",
       description='Stops the configured website search source appearing in system search.'),
    _t(TweakID.ShowButtonHints, Section.INTERNAL, 'Show Button Hints in Screenshots', GP, "SBHardwareButtonHintDropletsAlwaysVisibleInSnapshots",
       description='Includes hardware-button hints in screenshots.'),
    _t(TweakID.AppStoreDebug, Section.INTERNAL, 'Enable App Store Test Gesture', FileLocation.appStore, "debugGestureEnabled",
       description="Enables the App Store's hidden test gesture."),
    _t(TweakID.NotesDebugMode, Section.INTERNAL, 'Show Notes Test Settings', FileLocation.notes, "DebugModeEnabled",
       description='Shows extra troubleshooting controls in Notes.'),
    _t(TweakID.BKDigitizerVisualizeTouches, Section.INTERNAL, 'Show Touch Points', FileLocation.backboardd, "BKDigitizerVisualizeTouches",
       description='Mark where you touch the screen and display touch troubleshooting information.'),
    _t(TweakID.BKHideAppleLogoOnLaunch, Section.INTERNAL, 'Hide Logo During Interface Restart', FileLocation.backboardd, "BKHideAppleLogoOnLaunch",
       description='Hides the Apple logo while the system interface restarts.'),
    _t(TweakID.EnableWakeGestureHaptic, Section.INTERNAL, 'Vibrate When Raise to Wake Activates', FileLocation.coreMotion, "EnableWakeGestureHaptic",
       description='Gives a short vibration when Raise to Wake turns on the screen.'),
    _t(TweakID.PlaySoundOnPaste, Section.INTERNAL, 'Play a Paste Sound', FileLocation.pasteboard, "PlaySoundOnPaste",
       description='Plays a sound when pasting copied content.'),
    _t(TweakID.AnnounceAllPastes, Section.INTERNAL, 'Show More Paste Notices', FileLocation.pasteboard, "AnnounceAllPastes",
       description='Shows extra notices when the system accesses copied content.'),
    _t(TweakID.DisableCollectionViewPrefetching, Section.INTERNAL,
       'Disable Collection View Prefetching', FileLocation.uikitPreferencesHomeDomain,
       'CollectionViewCellPrefetchingMode', value=-2, min_version='27.0', experimental=True,
       description='Requests disabling collection-view cell prefetching using the reported internal UIKit preference.',
       warning='Reader and integer -2 are user-reported for iOS 27.0, not independently verified here. Retail restore delivery and visible effects are unverified. May worsen scrolling or loading; battery and performance gains are not established. Disabling omits future writes and does not remove an applied override.'),
    _t(TweakID.DisableSwiftUIScrollPrefetch, Section.INTERNAL,
       'Disable SwiftUI Scroll Prefetching', FileLocation.swiftuiPreferencesHomeDomain,
       'EnableScrollPrefetch', value=False, min_version='27.2', experimental=True,
       factory=lambda: _experimental_domain_boolean(
           FileLocation.swiftuiPreferencesHomeDomain, 'EnableScrollPrefetch', False, True),
       description='Requests disabling SwiftUI scroll prefetching. This may increase loading or scrolling delays.',
       warning="The Boolean reader is traced in iOS 27.2 RC, but device delivery, accepted overrides and visible effects are unverified. Battery or performance gains are not established. Turning this off writes true for the key; that may not restore the device's prior value."),
    _t(TweakID.TableViewCellPrefetchingModeResearch, Section.INTERNAL,
       'Disable Table View Prefetching', FileLocation.uikitPreferencesHomeDomain,
       'TableViewCellPrefetchingMode', value=-1, min_version='27.0', experimental=True,
       description='Requests disabling table-view cell prefetching using the reported internal UIKit preference.',
       warning='Reader, shared UIKit suite and integer -1 are user-reported for iOS 27.0, not independently verified here. Retail restore delivery and visible effects are unverified. May worsen scrolling or loading; battery and performance gains are not established. Disabling omits future writes and does not remove an applied override.'),
)


MANAGED_PREF_PREFIX = "/var/Managed Preferences/"
HOME_PREFIX = "/var/mobile/"


def managed_pref_target(path: str) -> Optional[str]:
    """HomeDomain path of the app plist a managed-preference file mirrors into.

    ``/var/Managed Preferences/mobile/com.apple.springboard.plist`` ->
    ``Library/Preferences/com.apple.springboard.plist``. Returns None for any
    other location.
    """
    if not path.startswith(MANAGED_PREF_PREFIX):
        return None
    name = path[len(MANAGED_PREF_PREFIX):]
    if name.startswith("mobile/"):
        name = name[len("mobile/"):]
    if not name.endswith(".plist"):
        return None
    return f"Library/Preferences/{name}"


def managed_pref_app_plists() -> frozenset:
    """HomeDomain-relative app plists that carry the managed-preference tweaks.

    mcxd copies every managed preference into the target app's own cfprefs
    domain on disk, so a managed-pref tweak lives in TWO places: the
    ``/var/Managed Preferences`` file Nugget owns, and the app plist where the
    merged value stays behind as an ordinary preference once the managed
    entry is gone. Anything that must not resurrect a tweak — the protective
    backup keep-set (Phase 3 restores it after the sparse reset) or the reset
    itself — derives its exclusion list from here, so adding a
    managed-pref target to the registry is enough.
    """
    out = {managed_pref_target(FileLocation.ota.value)}
    for spec in SPECS:
        if spec.location is None:
            continue
        target = managed_pref_target(spec.location.value)
        if target is not None:
            out.add(target)
    return frozenset(out)
LOCAL_ONLY_IDS: frozenset = frozenset()

SPECS_BY_SECTION: dict[Section, list[TweakSpec]] = {
    section: [s for s in SPECS if s.section == section and not s.disabled]
    for section in Section
}

SPECS_BY_ID: dict[TweakID, TweakSpec] = {
    spec.id: spec for spec in SPECS if not spec.disabled
}