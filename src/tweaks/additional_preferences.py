"""Additional opt-in preference controls; upstream definitions remain authoritative."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.utils.i18n import QT_TRANSLATE_NOOP, QCoreApplication

from .basic_plist_locations import FileLocation
from .registry import Kind, Section, TweakSpec, _t
from .tweak_classes import HandoffPreferenceTweak
from .tweak_names import TweakID


def _experimental_domain_boolean(location, key, on_value=True, off_value=False):
    from .tweak_classes import ExperimentalBooleanPlistTweak

    return ExperimentalBooleanPlistTweak(location, key, on_value, off_value)


def _duo_limited_resizing():
    from .candidate_preferences import DuoLimitedResizingApp

    return DuoLimitedResizingApp()


def _keyboard_image_caching():
    from .tweak_classes import TriStateBooleanPlistTweak

    return TriStateBooleanPlistTweak(
        FileLocation.keyboardSettingsHomeDomain,
        "KeyboardCachingDisabled",
        on_value=False,
    )


def _system_setting(location, key, requested):
    from .tweak_classes import TriStateBooleanPlistTweak

    return TriStateBooleanPlistTweak(location, key, on_value=requested)


SPECS = (
    _t(
        TweakID.DuoLimitedResizingApp,
        Section.SPRINGBOARD,
        "Duo: Enlarge a Legacy App",
        FileLocation.springboardPreferencesHomeDomain,
        "SBBundleIdentifiersToForceSupportLimitedResizing",
        value="",
        kind=Kind.TEXT,
        bundle_identifier=True,
        min_version="27.1",
        supported_models=("iPhone19,4",),
        iphone_only=True,
        experimental=True,
        factory=_duo_limited_resizing,
        description="Requests limited resizing for one app without editing its IPA. Enter its bundle identifier. A side strip may remain.",
        warning="Verified only in the iOS 27.1 Duo simulator. Physical-device restore acceptance and effect are unverified. Replaces the limited-resizing app list with this one app; an empty value writes an empty list. Disabling leaves the device unchanged. Restore defaults removes the override, not any previous custom list. Does not apply the SDK stamp or Discord edge fix.",
    ),
    _t(
        TweakID.UIKitC2LowRefreshRateEnabled,
        Section.INTERNAL,
        "Allow Low-Refresh-Rate Animations",
        FileLocation.uikitInternalPreferencesHomeDomain,
        "C2LowRefreshRateEnabled",
        value=True,
        min_version="27.0",
        experimental=True,
        factory=lambda: _experimental_domain_boolean(
            FileLocation.uikitInternalPreferencesHomeDomain,
            "C2LowRefreshRateEnabled",
            True,
            False,
        ),
        description="Requests allowing eligible UIKit animations to use a lower refresh rate. Battery and performance effects are unknown.",
        warning="UIKitCore contains this preference reader on iOS 27.0, but the plist delivery path and override behavior are unverified. Applying it may change animation smoothness; battery savings are not established.",
    ),
    _t(
        TweakID.KeyboardImageCaching,
        Section.INTERNAL,
        "Keyboard Image Caching",
        FileLocation.keyboardSettingsHomeDomain,
        "KeyboardCachingDisabled",
        value=False,
        min_version="27.1",
        max_version="27.99",
        experimental=True,
        factory=_keyboard_image_caching,
        description="Enabled permits keyboard image caching; Disabled requests turning it off. Not Used leaves the preference untouched.",
        warning="Domain and Boolean consumer traced in iOS 27.1 Simulator 24A94425. The key also appears in retained iOS 27.2 firmware, but physical-device restore delivery and visible effects are unverified. Caching may already be enabled by default, so enabling this may change nothing. Disabling caching may worsen responsiveness. Restart affected apps or the device after an accepted write. An unreadable or missing backup baseline blocks applying; no empty baseline is substituted. Not Used does not undo an earlier write; Restore defaults removes the override rather than restoring a prior custom value.",
    ),
    *(
        _t(
            member,
            Section.INTERNAL,
            title,
            location,
            key,
            value=requested,
            min_version="27.0",
            max_version="27.99.99",
            experimental=True,
            factory=lambda location=location, key=key, requested=requested: (
                _system_setting(location, key, requested)
            ),
            description=description,
            warning="Preference reader and setter traced in Apple iOS 26.4 (23E254a) and iOS 27.0 (24A434) Simulator binaries. "
            "Uses a numeric 0/1 preference. Delivery is restricted to iOS 27 current-baseline merging; "
            "iOS 26 sparse writes could replace unrelated preferences and are not supported. "
            "Physical-device restore delivery and visible effects are not verified. Restart the device after applying. "
            "Not Used omits future writes; it does not undo an earlier apply. "
            "Missing or unreadable current preference baselines still block applying safely.",
        )
        for member, title, location, key, requested, description in (
            (
                TweakID.SystemReduceMotion,
                "System Settings: Reduce Motion",
                FileLocation.accessibilityPreferencesHomeDomain,
                "ReduceMotionEnabled",
                1,
                "Controls global Reduce Motion. Enabled requests On; Disabled requests Off.",
            ),
            (
                TweakID.SystemReduceTransparency,
                "System Settings: Reduce Transparency",
                FileLocation.accessibilityPreferencesHomeDomain,
                "EnhancedBackgroundContrastEnabled",
                1,
                "Controls global Reduce Transparency using the actual iOS EnhancedBackgroundContrastEnabled preference.",
            ),
            (
                TweakID.SystemAutoplayAnimatedImages,
                "System Settings: Stop Animated Image Autoplay",
                FileLocation.accessibilityPreferencesHomeDomain,
                "ReduceMotionAutoplayAnimatedImagesEnabled",
                0,
                "Enabled requests Auto-Play Animated Images Off. Disabled requests On.",
            ),
            (
                TweakID.SystemAutoplayMessageEffects,
                "System Settings: Stop Message Effect Autoplay",
                FileLocation.accessibilityPreferencesHomeDomain,
                "ReduceMotionAutoplayMessagesEffectsEnabled",
                0,
                "Enabled requests Auto-Play Message Effects Off. Disabled requests On.",
            ),
            (
                TweakID.SystemAttentionAware,
                "System Settings: Disable Attention Aware Features",
                FileLocation.accessibilityPreferencesHomeDomain,
                "AXSAttentionAwarenessFeatures",
                0,
                "Requests Attention Aware Features Off. This is not the separate Require Attention for Face ID setting.",
            ),
            (
                TweakID.SystemLiveSpeech,
                "System Settings: Disable Live Speech",
                FileLocation.accessibilityPreferencesHomeDomain,
                "LiveSpeechEnabled",
                0,
                "Requests Live Speech Off without deleting voices or changing Personal Voice sharing.",
            ),
            (
                TweakID.HomeScreenReduceMotion,
                "System Settings: Home Screen Motion Exception",
                FileLocation.springboardPreferencesHomeDomain,
                "ReduceMotionEnabled",
                0,
                "Enabled requests the SpringBoard/Home Screen per-app Reduce Motion override Off, without changing global Reduce Motion. "
                "Does not replace the Settings app list of registered per-app overrides.",
            ),
        )
    ),
    _t(
        TweakID.SystemRCSBusinessMessages,
        Section.INTERNAL,
        "System Settings: Disable RCS Business Messages",
        FileLocation.madridPreferencesHomeDomain,
        "RCSForBusinessEnabled",
        value=False,
        min_version="27.0",
        max_version="27.99.99",
        experimental=True,
        factory=lambda: _system_setting(
            FileLocation.madridPreferencesHomeDomain, "RCSForBusinessEnabled", False
        ),
        description="Enabled requests RCS business messages Off; Disabled requests On. Does not disable every Business Updates or Messages feature.",
        warning="MessagesSettingsUI BusinessSettingsHelper setter traced in iOS 26.4 (23E254a) and 27.0 (24A434): "
        "NSNumber numberWithBool -> CFPreferencesSetAppValue in com.apple.madrid, followed by synchronization and notification. "
        "Physical-device restore acceptance and effect are unverified. Restart after applying. "
        "Delivery is restricted to iOS 27 current-baseline merging; iOS 26 sparse writes are not supported. "
        "A readable current backup baseline is required. Not Used omits future writes and does not undo an earlier apply.",
    ),
    _t(
        TweakID.SystemSiriSharingSuggestions,
        Section.INTERNAL,
        "System Settings: Disable Siri Sharing Suggestions",
        FileLocation.sharingPreferencesHomeDomain,
        "SharingPeopleSuggestionsDisabled",
        value=True,
        min_version="27.0",
        max_version="27.99.99",
        experimental=True,
        factory=lambda: _system_setting(
            FileLocation.sharingPreferencesHomeDomain,
            "SharingPeopleSuggestionsDisabled",
            True,
        ),
        description="Enabled requests Siri suggestions when sharing Off. Disabled requests On. Does not disable search or Home Screen suggestions.",
        warning="iOS 27.0 (24A434) SiriSettings SuggestionsProvider setShowWhenSharingEnabled traced: "
        "NSUserDefaults suite com.apple.Sharing, setBool:forKey: SharingPeopleSuggestionsDisabled with the logical value inverted. "
        "iOS 26 writer not verified. Physical-device restore delivery and effect are unverified. "
        "Restart after applying. Current readable backup baseline required. Not Used does not undo an earlier apply.",
    ),
    _t(
        TweakID.SystemMessageSummarization,
        Section.INTERNAL,
        "System Settings: Disable Message Summarization",
        FileLocation.mobileSMSPreferencesHomeDomain,
        "messageSummarizationEnabled",
        value=False,
        min_version="27.0",
        max_version="27.99.99",
        experimental=True,
        requires_apple_intelligence=True,
        factory=lambda: _system_setting(
            FileLocation.mobileSMSPreferencesHomeDomain,
            "messageSummarizationEnabled",
            False,
        ),
        description="Requests Summarize Messages Off. Does not enable Apple Intelligence or change notification summaries.",
        warning="iOS 27.0 IMGenerativeModelsAvailabilityProvider setter traced through IMSetDomainValueForKey to "
        "CFPreferencesSetAppValue, using com.apple.MobileSMS and an NSNumber Boolean. Reader uses the same domain "
        "and key. This exact HomeDomain plist exists in an older iPhone16,2 / 27.0.1 (24A446) backup, but "
        "physical-device write acceptance and visible effect are unverified. A readable current baseline is "
        "required. Not Used omits future writes; it does not undo an earlier apply.",
    ),
    *tuple(
        _t(
            member,
            Section.INTERNAL,
            title,
            FileLocation.userActivityPreferencesHomeDomain,
            key,
            value=False,
            min_version="27.0",
            max_version="27.99.99",
            experimental=True,
            factory=HandoffPreferenceTweak,
            description="Writes the supplied Handoff preference candidate as a Boolean. Not a verified Settings replacement.",
            warning="User-supplied candidate; current iOS reader and writer are unverified. "
            "Requires a readable current preference baseline and iOS 27 merged delivery. "
            "The value may be ignored or overwritten. Not Used omits future writes, not an earlier override. "
            "May affect Continuity features; no battery savings have been measured.",
        )
        for member, title, key in (
            (
                TweakID.HandoffAdvertisingCandidate,
                "Disable Handoff",
                "ActivityAdvertisingAllowed",
            ),
        )
    ),
    *(
        _t(
            TweakID.SystemLockScreenMessaging,
            Section.INTERNAL,
            "System Settings: Disable Reply with Message While Locked",
            FileLocation.mobilePhonePreferencesHomeDomain,
            "LockScreenMessaging",
            value=False,
            min_version="27.0",
            max_version="27.99.99",
            experimental=True,
            factory=lambda: _system_setting(
                FileLocation.mobilePhonePreferencesHomeDomain,
                "LockScreenMessaging",
                False,
            ),
            description="Experimental request to disable replying with a message while locked.",
            warning="Key, Boolean type and domain come from an iOS 18.6 Settings declaration. "
            "iOS 26/27 reader, writer, restore acceptance and effect are unverified. "
            "Requires iOS 27 current-baseline merging. No authentication bypass. "
            "Not Used omits future writes; it does not undo an earlier override.",
        ),
    ),
)
