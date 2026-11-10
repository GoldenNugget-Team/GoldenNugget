"""Additional opt-in plist controls extending the canonical tweak registry."""

from typing import Optional

from src.utils.i18n import QT_TRANSLATE_NOOP

from .basic_plist_locations import FileLocation
from .registry import Kind, Section, TweakSpec
from .tweak_names import TweakID


def _t(
    id_: TweakID,
    section: Section,
    title: str,
    location: Optional[FileLocation],
    key: str,
    description: str = "",
    **kwargs,
) -> TweakSpec:
    # QT_TRANSLATE_NOOP marks the title for pyside6-lupdate; the actual
    # translation happens at render time (translators are not installed yet
    # when this module is imported).
    return TweakSpec(
        id=id_,
        section=section,
        title=QT_TRANSLATE_NOOP("Nugget", title),
        description=QT_TRANSLATE_NOOP("Nugget", description) if description else None,
        location=location,
        key=key,
        **kwargs,
    )




def _experimental_domain_boolean(location, key, on_value=True, off_value=False):
    from .tweak_classes import ExperimentalBooleanPlistTweak

    return ExperimentalBooleanPlistTweak(location, key, on_value, off_value)


def _glass_legibility():
    from .tweak_classes import GlassLegibilityTweak

    return GlassLegibilityTweak()


def _tri_state_boolean(location, key):
    from .tweak_classes import TriStateBooleanPlistTweak

    return TriStateBooleanPlistTweak(location, key)


def _candidate_headphone_limit():
    from .candidate_preferences import NestedNumericPreference

    return NestedNumericPreference(
        FileLocation.celestialPreferencesHomeDomain,
        "volumeLimits",
        "Headphone",
        1.0,
        0.0,
        1.0,
    )


def _candidate_watchdog_timeout():
    from .candidate_preferences import NestedNumericPreference

    return NestedNumericPreference(
        FileLocation.springboardPreferencesHomeDomain,
        "FBLaunchWatchdogExceptions",
        "com.apple.Spotlight",
        60,
        1,
        600,
        integral=True,
    )


def _candidate_tracker_dates():
    from .candidate_preferences import DiagnosticTrackerDates

    return DiagnosticTrackerDates()


def _all_app_suggestions_blacklist():
    from .candidate_preferences import InstalledAppSuggestionsBlacklist

    return InstalledAppSuggestionsBlacklist()


def _mail_search_receiver():
    from .candidate_preferences import MailSearchReceiverPreference

    return MailSearchReceiverPreference()


def _mail_search_task_date():
    from .candidate_preferences import MailSearchTaskBaseDate

    return MailSearchTaskBaseDate()


def _research_swiftui_global_default(member, key, title, description):
    from .tweak_classes import TriStateBooleanPlistTweak

    warning = (
        "This reader uses standardUserDefaults. The global defaults domain is a "
        "fallback behind each app’s own settings, so app-specific values can override "
        "this request. GoldenNugget stages the key in .GlobalPreferences.plist through "
        "restore; device acceptance and behavior are unverified. No battery, memory, "
        "or performance benefit is established. The value may alter app behavior. "
        "Not Used omits a future write but does not remove a prior override."
    )
    return _t(
        member,
        Section.INTERNAL,
        title,
        FileLocation.globalPreferencesHomeDomain,
        key,
        value=None,
        min_version="27.2",
        experimental=True,
        description=description,
        warning=warning,
        factory=lambda: TriStateBooleanPlistTweak(
            FileLocation.globalPreferencesHomeDomain, key
        ),
    )


def _research_swiftui_unverified_global_default(
    member, key, title, description, warning
):
    from .tweak_classes import TriStateBooleanPlistTweak

    return _t(
        member,
        Section.INTERNAL,
        title,
        FileLocation.globalPreferencesHomeDomain,
        key,
        value=None,
        min_version="27.2",
        experimental=True,
        description=description,
        warning=warning,
        factory=lambda: TriStateBooleanPlistTweak(
            FileLocation.globalPreferencesHomeDomain, key
        ),
    )


def _research_swiftui_suite_default(member, key, title, description):
    from .tweak_classes import TriStateBooleanPlistTweak

    warning = (
        "The reader uses the com.apple.SwiftUI defaults suite. GoldenNugget "
        "stages this key in the matching HomeDomain preference file; actual "
        "suite resolution, restore acceptance, and behavior are unverified. "
        "No battery, memory, or performance benefit is established. The value "
        "may alter visual behavior. Not Used omits a future write but does not "
        "remove a prior override."
    )
    return _t(
        member,
        Section.INTERNAL,
        title,
        FileLocation.swiftuiPreferencesHomeDomain,
        key,
        value=None,
        min_version="27.2",
        experimental=True,
        description=description,
        warning=warning,
        factory=lambda: TriStateBooleanPlistTweak(
            FileLocation.swiftuiPreferencesHomeDomain, key
        ),
    )


SPECS = (
    _t(
        TweakID.BGAppKillDemo,
        Section.INTERNAL,
        "Fast App Termination (BGAppKillDemo)",
        FileLocation.dasdAppResumePreferencesHomeDomain,
        "BGAppKillDemo",
        factory=lambda: _tri_state_boolean(
            FileLocation.dasdAppResumePreferencesHomeDomain, "BGAppKillDemo"
        ),
        experimental=True,
        min_version="13.0",
        description="Disables apps from remaining suspended in the background (aggressive termination). Can reduce background activity but may increase launch times.",
        warning="Older behavior; may not apply on modern iOS. Turning this on forces faster app termination and can break background tasks/continuity.",
    ),
    _t(
        TweakID.SpotlightMetricsWriting,
        Section.INTERNAL,
        "Spotlight Metrics Writing",
        FileLocation.spotlightKnowledgePreferencesHomeDomain,
        "metricsWriting",
        factory=lambda: _tri_state_boolean(
            FileLocation.spotlightKnowledgePreferencesHomeDomain, "metricsWriting"
        ),
        experimental=True,
        description="Disables Spotlight knowledge metrics writing to reduce background indexing/logging overhead.",
        warning="Unverified on iOS 27; disabling metrics may affect Spotlight tuning/telemetry only.",
    ),
    _t(
        TweakID.ICloudBackgroundTaskScheduling,
        Section.INTERNAL,
        "iCloud Background Task Scheduling",
        FileLocation.itunesclouddPreferencesHomeDomain,
        "ICBackgroundTaskScheduler",
        factory=lambda: _tri_state_boolean(
            FileLocation.itunesclouddPreferencesHomeDomain, "ICBackgroundTaskScheduler"
        ),
        experimental=True,
        description="Controls iCloud background task scheduling. Research target only.",
        warning="Complex structure; behavior unverified on modern iOS.",
    ),
    _t(
        TweakID.DASDisableFairSchedulingQueue,
        Section.INTERNAL,
        "DAS Fair Scheduling Queue",
        FileLocation.dasFairSchedulingPreferencesHomeDomain,
        "priorityQueue",
        factory=lambda: _tri_state_boolean(
            FileLocation.dasFairSchedulingPreferencesHomeDomain, "priorityQueue"
        ),
        experimental=True,
        description="DAS fair scheduling queue - research target.",
        warning="May be live scheduler state; not safe/verified to modify.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIPersistentLazyStackCache,
        "com.apple.SwiftUI.PersistentLazyStackCache",
        "SwiftUI Persistent Lazy Stack Cache (Global Defaults)",
        "Sets the traced Boolean reader through the global defaults fallback. Cache memory and recomputation tradeoffs are unknown.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIHitTestingCache,
        "com.apple.SwiftUI.HitTestingCache",
        "SwiftUI Hit-Testing Cache (Global Defaults)",
        "Sets the traced Boolean reader through the global defaults fallback. Hit-testing behavior and workload effects are unknown.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIDisableAsyncRendering,
        "com.apple.SwiftUI.DisableAsyncRendering",
        "Disable SwiftUI Async Rendering (Global Defaults)",
        "Sets the traced rendering Boolean through the global defaults fallback. Enabling the key requests disabling async rendering and may worsen responsiveness.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIGestureContainers,
        "com.apple.SwiftUI.GestureContainers",
        "SwiftUI Gesture Containers (Global Defaults)",
        "Sets the traced gesture-feature Boolean through the global defaults fallback. Gesture behavior changes are unknown.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIUniversalGestureRelationships,
        "com.apple.SwiftUI.UniversalGestureRelationships",
        "SwiftUI Universal Gesture Relationships (Global Defaults)",
        "Sets the traced gesture-feature Boolean through the global defaults fallback. Gesture precedence and behavior changes are unknown.",
    ),
    _research_swiftui_global_default(
        TweakID.SwiftUIDisableRemoteEffects,
        "com.apple.SwiftUI.DisableRemoteEffects",
        "Disable SwiftUI Remote Effects (Global Defaults)",
        "Sets the traced Boolean graph-input feature through the global defaults fallback. Which effects it disables and any resource impact are unknown.",
    ),
    _research_swiftui_unverified_global_default(
        TweakID.SwiftUIEnableUnifiedLayoutResearch,
        "com.apple.SwiftUI.EnableUnifiedLayout",
        "SwiftUI Unified Layout (Experimental)",
        "Research lead: the key appears in the iOS 27.2 RC SwiftUICore and UIKitCore binaries; a public reimplementation reports a standard-defaults reader. Apple reader behavior and performance effects are unverified.",
        "The standard-defaults reader is reported by a third-party reimplementation, not verified in Apple device code. GoldenNugget stages this key in .GlobalPreferences.plist as a fallback; app-specific values can override it. Restore acceptance, default behavior, layout effects, and any battery, memory, or performance impact are unknown. It may change layout behavior. Use only for isolated testing; Not Used omits future writes but does not remove a prior override.",
    ),
    _research_swiftui_suite_default(
        TweakID.SwiftUINewScrollEdgeEffectTag,
        "NewScrollEdgeEffectTag",
        "SwiftUI Scroll Edge Effect Tag",
        "Sets the traced SwiftUI-suite Boolean. The effect appears presentation-related; resource impact is unknown.",
    ),
    _t(
        TweakID.DisableMailSearchReceiver,
        Section.SPRINGBOARD,
        "Disable Mail Search Indexer Receiver",
        FileLocation.coreSpotlightUIPreferencesHomeDomain,
        "CSReceiverBundleIdentifierState",
        factory=_mail_search_receiver,
        experimental=True,
        description="Writes false for com.apple.email.SearchIndexer inside CSReceiverBundleIdentifierState. Disabled writes true; Not Used leaves it alone. This may affect Mail search; current iOS behavior is unverified.",
    ),
    _t(
        TweakID.DeferMailSearchTaskBaseDate,
        Section.SPRINGBOARD,
        "Defer Mail Search Task Base Date",
        FileLocation.backgroundSystemTaskPreferencesHomeDomain,
        "ActivityBaseDates",
        factory=_mail_search_task_date,
        experimental=True,
        warning="This writes scheduler bookkeeping and may affect Mail search. A future base date is not a verified way to disable the task; iOS may ignore, recalculate, or replace it.",
        description="Sets the stored base date for com.apple.email.searchIndexerBGTask to January 1, 4001 UTC. This is not confirmed to stop indexing. Turning this off stops writing it and does not restore the previous date.",
    ),
    _t(
        TweakID.AllowScreenShot,
        Section.SPRINGBOARD,
        "Allow Screenshots and Screen Recording",
        FileLocation.applicationAccess,
        "allowScreenShot",
        factory=lambda: _tri_state_boolean(
            FileLocation.applicationAccess, "allowScreenShot"
        ),
        experimental=True,
        description="Enabled requests permission to capture the screen; Disabled requests blocking screenshots and screen recording. Existing managed restrictions can still take precedence. Restore behavior is unverified.",
    ),
    _t(
        TweakID.CanExceedEUVolumeLimit,
        Section.SPRINGBOARD,
        "Allow Exceeding the EU Volume Limit",
        FileLocation.celestialPreferencesHomeDomain,
        "canExceedEUVolumeLimit",
        factory=lambda: _tri_state_boolean(
            FileLocation.celestialPreferencesHomeDomain, "canExceedEUVolumeLimit"
        ),
        experimental=True,
        warning="This historical preference may permit louder headphone output. Support on current iOS is unverified.",
        description="Historical headphone-volume permission. It does not guarantee that current audio services accept the override.",
    ),
    _t(
        TweakID.HeadphoneVolumeLimit,
        Section.SPRINGBOARD,
        "Headphone Volume Limit Value",
        FileLocation.celestialPreferencesHomeDomain,
        "volumeLimits",
        kind=Kind.NUMBER,
        value=1.0,
        min_value=0.0,
        max_value=1.0,
        step=0.01,
        factory=_candidate_headphone_limit,
        experimental=True,
        description="Stores the historical Headphone value inside volumeLimits (0–1). Current behavior and its relationship to audible volume are unverified.",
    ),
    _t(
        TweakID.ReindexAttemptsWithoutProgress,
        Section.SPRINGBOARD,
        "Calendar Reindex Retry Counter",
        FileLocation.mobilecalPreferencesHomeDomain,
        "ReindexAttemptsWithoutProgress",
        kind=Kind.NUMBER,
        value=0,
        min_value=0,
        max_value=999,
        experimental=True,
        description="Sets Calendar’s stored count of reindex attempts without progress. This is a bookkeeping counter, not a switch to disable indexing; current behavior is unverified.",
    ),
    _t(
        TweakID.AVTUIGlobalPreferencesFlushStickersCache,
        Section.SPRINGBOARD,
        "Request Avatar Sticker Cache Flush",
        FileLocation.avatarPreferencesHomeDomain,
        "AVTUIGlobalPreferencesFlushStickersCache",
        factory=lambda: _tri_state_boolean(
            FileLocation.avatarPreferencesHomeDomain,
            "AVTUIGlobalPreferencesFlushStickersCache",
        ),
        experimental=True,
        description="Requests avatar sticker-cache invalidation. The reader and current effect are unverified; rebuilding the cache can add work rather than save battery.",
    ),
    _t(
        TweakID.AVTAvatarUIFlushThumbnailCache,
        Section.SPRINGBOARD,
        "Request Avatar Thumbnail Cache Flush",
        FileLocation.avatarPreferencesHomeDomain,
        "AVTAvatarUIFlushThumbnailCache",
        factory=lambda: _tri_state_boolean(
            FileLocation.avatarPreferencesHomeDomain, "AVTAvatarUIFlushThumbnailCache"
        ),
        experimental=True,
        description="Requests avatar thumbnail-cache invalidation. Current behavior is unverified, and thumbnails may need to be generated again.",
    ),
    _t(
        TweakID.BlockAllAppSiriSuggestions,
        Section.SPRINGBOARD,
        "Block Siri Suggestions for All Installed Apps",
        FileLocation.suggestionsPreferencesHomeDomain,
        "AppCanShowSiriSuggestionsBlacklist",
        factory=_all_app_suggestions_blacklist,
        experimental=True,
        warning="Apply will replace this preference’s app list with apps reported by the selected device. iOS support is unverified. Turning this control off stops future writes; it does not restore an older list.",
        description="During Apply, fetches all app bundle IDs reported by the selected device and writes them to the suggestions blacklist. Newly installed apps require another Apply. This does not disable Siri itself.",
    ),
    _t(
        TweakID.ShowSystemServicesLocationIcon,
        Section.SPRINGBOARD,
        "Show System Services Location Icon",
        FileLocation.locationStatusBarPreferencesHomeDomain,
        "ShowSystemServices",
        factory=lambda: _tri_state_boolean(
            FileLocation.locationStatusBarPreferencesHomeDomain, "ShowSystemServices"
        ),
        experimental=True,
        description="Requests the location status-bar indicator for system services. Current preference ownership and effect are unverified; this does not stop location services.",
    ),
    _t(
        TweakID.SpotlightLaunchWatchdogTimeout,
        Section.SPRINGBOARD,
        "Spotlight Launch Watchdog Value",
        FileLocation.springboardPreferencesHomeDomain,
        "FBLaunchWatchdogExceptions",
        kind=Kind.NUMBER,
        value=60,
        min_value=1,
        max_value=600,
        factory=_candidate_watchdog_timeout,
        experimental=True,
        warning="Reducing this watchdog allowance may cause Spotlight to be terminated during slow launches. This is not a confirmed performance improvement.",
        description="Writes com.apple.Spotlight inside FBLaunchWatchdogExceptions. Default proposed override: 60. Units and current reader behavior remain unverified.",
    ),
    _t(
        TweakID.AppAndAccessoryAnalyticsAllowedRemoval,
        Section.SPRINGBOARD,
        "App and Accessory Analytics Removal Flag",
        FileLocation.preferencesHomeDomain,
        "isAppAndAccessoryAnalyticsAllowedRemoval",
        factory=lambda: _tri_state_boolean(
            FileLocation.preferencesHomeDomain,
            "isAppAndAccessoryAnalyticsAllowedRemoval",
        ),
        experimental=True,
        description="Stores an internal analytics-removal flag. Its name does not establish that analytics collection is disabled; current effect is unverified.",
    ),
    _t(
        TweakID.LogAllIOErrors,
        Section.SPRINGBOARD,
        "Log All Messaging I/O Errors",
        FileLocation.imdPersistencePreferencesHomeDomain,
        "LogAllIOErrors",
        factory=lambda: _tri_state_boolean(
            FileLocation.imdPersistencePreferencesHomeDomain, "LogAllIOErrors"
        ),
        experimental=True,
        description="Requests detailed I/O error logging by the messaging persistence agent. Extra logging may increase disk work. Current effect is unverified.",
    ),
    _t(
        TweakID.DeferDiagnosticExtensionTracker,
        Section.SPRINGBOARD,
        "Diagnostic Tracker Dates: Year 4001",
        FileLocation.diagnosticExtensionTracker,
        "com.apple.DiagnosticExtensions.extensionTracker",
        factory=_candidate_tracker_dates,
        experimental=True,
        warning="This changes stored scheduler bookkeeping dates. The system may overwrite or ignore them; it is not a verified way to disable diagnostics.",
        description="Sets EarliestExpirationDate and XPCActivityScheduledDate under the tracker’s XPCActivity dictionary to January 1, 4001 (00:00 and 02:00 UTC). Restore acceptance and scheduling effects are unverified.",
    ),
    _t(
        TweakID.SPUISearchFirstTimeShowCount,
        Section.SPRINGBOARD,
        "Spotlight First-Time Display Counter",
        FileLocation.spotlightUIPreferencesHomeDomain,
        "SPUISearchFirstTimeShowCount",
        kind=Kind.NUMBER,
        value=0,
        min_value=0,
        max_value=999,
        experimental=True,
        description="Sets Spotlight’s stored first-time display count. Resetting it may show introductory UI again; current behavior is unverified.",
    ),
    _t(
        TweakID.PersonalizedAdsDefaulted,
        Section.SPRINGBOARD,
        "Personalized Ads Default Marker",
        FileLocation.adPlatformsPreferencesHomeDomain,
        "personalizedAdsDefaulted",
        factory=lambda: _tri_state_boolean(
            FileLocation.adPlatformsPreferencesHomeDomain, "personalizedAdsDefaulted"
        ),
        experimental=True,
        description="Changes the stored marker for a defaulted personalized-ads choice. This is not a confirmed advertising opt-out and does not promise to hide consent prompts.",
    ),
    _t(
        TweakID.UseAppstoredUpdates2,
        Section.SPRINGBOARD,
        "Alternate App Store Update Path",
        FileLocation.itunesstoredPreferencesHomeDomain,
        "UseAppstoredUpdates2",
        factory=lambda: _tri_state_boolean(
            FileLocation.itunesstoredPreferencesHomeDomain, "UseAppstoredUpdates2"
        ),
        experimental=True,
        description="Selects the candidate AppstoredUpdates2 update path. Current support is unverified; this does not disable app updates or guarantee faster downloads.",
    ),
    _t(
        TweakID.UIViewGlassLegibilitySetting,
        Section.LIQUID_GLASS,
        "Glass Legibility Appearance",
        FileLocation.uikitPreferencesHomeDomain,
        "UIViewGlassLegibilitySetting",
        factory=_glass_legibility,
        kind=Kind.NUMBER,
        value=0,
        min_value=0,
        max_value=1,
        step=1,
        min_version="26.4",
        max_version="26.99",
        experimental=True,
        description="Selects the glass appearance branch: 0 is the default and 1 uses the alternate, more opaque appearance. Apply 0 to return to the default.",
        warning="Visibly verified in an iOS 26.4 simulator, not through a phone restore. This changes glass appearance; it does not remove glass. Unavailable on iOS 27 because the inspected standard getter returns 0. Disabling the control does not undo an earlier apply.",
    ),
    _t(
        TweakID.PrototypeSettingsEnabled,
        Section.INTERNAL,
        "Prototype Settings",
        FileLocation.prototypeToolsPreferencesHomeDomain,
        "PrototypeSettingsEnabled",
        factory=lambda: _tri_state_boolean(
            FileLocation.prototypeToolsPreferencesHomeDomain, "PrototypeSettingsEnabled"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests PrototypeTools settings. Retail iOS may ignore this.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.ActivePrototypingEnabled,
        Section.INTERNAL,
        "Active Prototyping",
        FileLocation.prototypeToolsPreferencesHomeDomain,
        "ActivePrototypingEnabled",
        factory=lambda: _tri_state_boolean(
            FileLocation.prototypeToolsPreferencesHomeDomain, "ActivePrototypingEnabled"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests active prototyping. Retail iOS may ignore this.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.ClearPrototypeCachesForMigration,
        Section.INTERNAL,
        "Clear Prototype Caches During Migration",
        FileLocation.prototypeToolsPreferencesHomeDomain,
        "ClearPrototypeCachesForMigration",
        factory=lambda: _tri_state_boolean(
            FileLocation.prototypeToolsPreferencesHomeDomain,
            "ClearPrototypeCachesForMigration",
        ),
        min_version="26.0",
        experimental=True,
        description="Requests prototype-cache clearing during migration.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.DisableLiveActivities,
        Section.SPRINGBOARD,
        "Stop Widget Live Activity Handling",
        FileLocation.chronodPreferencesHomeDomain,
        "DisableLiveActivities",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "DisableLiveActivities"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests suppression of ChronoServices Live Activity handling. This is not a global Dynamic Island switch.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.disableAnimations,
        Section.SPRINGBOARD,
        "Stop Widget Animations",
        FileLocation.chronodPreferencesHomeDomain,
        "disableAnimations",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "disableAnimations"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests suppression of ChronoServices animations.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.DisableSnapshots,
        Section.SPRINGBOARD,
        "Stop Widget Snapshots",
        FileLocation.chronodPreferencesHomeDomain,
        "DisableSnapshots",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "DisableSnapshots"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests suppression of widget snapshots. Widgets may stop updating or appear blank.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.DisableTimelines,
        Section.SPRINGBOARD,
        "Stop Widget Timelines",
        FileLocation.chronodPreferencesHomeDomain,
        "DisableTimelines",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "DisableTimelines"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests suppression of widget timelines. Widgets may stop updating.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.DisablePlaceholders,
        Section.SPRINGBOARD,
        "Stop Widget Placeholders",
        FileLocation.chronodPreferencesHomeDomain,
        "DisablePlaceholders",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "DisablePlaceholders"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests suppression of placeholder rendering. Widgets may appear blank while loading.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.LayerSnapshotter_USE_CAML,
        Section.SPRINGBOARD,
        "Alternate Widget Snapshot Format",
        FileLocation.chronodPreferencesHomeDomain,
        "LayerSnapshotter_USE_CAML",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "LayerSnapshotter_USE_CAML"
        ),
        min_version="26.0",
        experimental=True,
        description="Selects an alternate widget snapshotting path. Its visible effect is unverified.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.DelayRendererStartup,
        Section.SPRINGBOARD,
        "Delay Widget Renderer Startup",
        FileLocation.chronodPreferencesHomeDomain,
        "DelayRendererStartup",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "DelayRendererStartup"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests delayed widget renderer initialization.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.showInternalWidgets,
        Section.SPRINGBOARD,
        "Show Internal Widgets",
        FileLocation.chronodPreferencesHomeDomain,
        "showInternalWidgets",
        factory=lambda: _tri_state_boolean(
            FileLocation.chronodPreferencesHomeDomain, "showInternalWidgets"
        ),
        min_version="26.0",
        experimental=True,
        description="Requests internal widget visibility. Retail iOS may ignore this.",
        warning="Reader traced on iOS 26.4.1; key present in inspected 26.0 and 27.0.1 binaries. Device delivery, retail restrictions and effects are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassGroupEnabled,
        Section.LIQUID_GLASS,
        "SwiftUI Glass Groups",
        FileLocation.uikitPreferencesHomeDomain,
        "SwiftUIGlassGroupEnabled",
        factory=lambda: _tri_state_boolean(
            FileLocation.uikitPreferencesHomeDomain, "SwiftUIGlassGroupEnabled"
        ),
        min_version="27.0",
        experimental=True,
        description="Controls UIKit integration for SwiftUI glass groups. Does not disable all Liquid Glass.",
        warning="Reader traced on iOS 27.0.1. Device delivery and visible effect are unverified.",
    ),
    _t(
        TweakID.SBComingFromUserPowerDown,
        Section.SPRINGBOARD,
        "Clear Startup After Power-Off Marker",
        FileLocation.springboard,
        "SBComingFromUserPowerDown",
        value=False,
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.springboard, "SBComingFromUserPowerDown", False, True
        ),
        description="Writes SBComingFromUserPowerDown as false when enabled, clearing the historical startup-after-power-off marker. Turning this toggle off writes true. It does not power off or restart the device, or skip setup. Its effect on iOS 18, 26 and 27 is unverified.",
        experimental=True,
    ),
    _t(
        TweakID.UseAlternateGlassColorMatrix,
        Section.LIQUID_GLASS,
        "Alternate Widget Glass Colors",
        FileLocation.chronodPreferencesHomeDomain,
        "UseAlternateGlassColorMatrix",
        min_version="26.0",
        experimental=True,
        description="Selects alternate widget glass color processing. Its visible effect is unverified.",
        warning="Preference traced on iOS 26.4.1. Device delivery, internal-UI restrictions and behavior on other versions are unverified.",
    ),
    _t(
        TweakID.EmulateFallbackTreatment,
        Section.LIQUID_GLASS,
        "Widget Fallback Appearance",
        FileLocation.chronodPreferencesHomeDomain,
        "EmulateFallbackTreatment",
        min_version="26.0",
        experimental=True,
        description="Requests fallback widget styling. Does not guarantee removal of widget glass.",
        warning="Preference traced on iOS 26.4.1. Device delivery, internal-UI restrictions and behavior on other versions are unverified.",
    ),
    _t(
        TweakID.ForceCARendering,
        Section.LIQUID_GLASS,
        "Alternate Widget Rendering",
        FileLocation.chronodPreferencesHomeDomain,
        "ForceCARendering",
        min_version="26.0",
        experimental=True,
        description="Requests an alternate widget rendering path. Visual and performance effects are unverified.",
        warning="Preference traced on iOS 26.4.1. Device delivery, internal-UI restrictions and behavior on other versions are unverified.",
    ),
    _t(
        TweakID.SolariumUseHDRGainMultiply,
        Section.LIQUID_GLASS,
        "Glass HDR Gain Multiplication",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumUseHDRGainMultiply",
        min_version="26.0",
        experimental=True,
        description="Controls an HDR brightness calculation. Its visible effect is unverified."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SolariumEnableKeyboardExteriorEffects,
        Section.LIQUID_GLASS,
        "Outer Keyboard Glass Effects",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumEnableKeyboardExteriorEffects",
        min_version="26.0",
        experimental=True,
        description="Controls outer keyboard effects. Does not guarantee removal of all keyboard glass."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SolariumEnableDockExteriorEffects,
        Section.LIQUID_GLASS,
        "Outer Dock Glass Effects",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumEnableDockExteriorEffects",
        min_version="26.0",
        experimental=True,
        description="Controls outer dock effects. Does not guarantee removal of all dock glass."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SolariumEnableReducedShadowVibrancy,
        Section.LIQUID_GLASS,
        "Reduced Glass Shadow Vibrancy",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumEnableReducedShadowVibrancy",
        min_version="26.0",
        experimental=True,
        description="Controls reduced shadow vibrancy. Its visible effect is unverified."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SolariumForceDarkShadow,
        Section.LIQUID_GLASS,
        "Dark Glass Shadows",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumForceDarkShadow",
        min_version="26.0",
        experimental=True,
        description="Requests darker glass shadows. Its visible effect is unverified."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SolariumDisableFocusForegroundEffects,
        Section.LIQUID_GLASS,
        "Suppress Foreground Focus Effects",
        FileLocation.swiftuiPreferencesHomeDomain,
        "SolariumDisableFocusForegroundEffects",
        min_version="26.0",
        experimental=True,
        description="Requests suppression of foreground focus effects. The affected surfaces are unverified."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassAppearanceAdjustments,
        Section.LIQUID_GLASS,
        "Custom Glass Appearance",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassAppearance.Enabled",
        min_version="26.0",
        experimental=True,
        description="Enables the glass appearance adjustments below. Disabling this restores normal adjustments; it does not disable Liquid Glass."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassTransitionAdjustments,
        Section.LIQUID_GLASS,
        "Custom Glass Transitions",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.Enabled",
        min_version="26.0",
        experimental=True,
        description="Enables the glass transition adjustments below. Disabling this restores normal adjustments; it does not disable Liquid Glass."
        + " Reader traced on iOS 26.0; device delivery and behavior on iOS 27 are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassBlurRadius,
        Section.LIQUID_GLASS,
        "Glass Blur Radius",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassAppearance.BlurRadius",
        kind=Kind.NUMBER,
        value=10.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Appearance enabled. Zero uses the default blur radius, rather than removing blur."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassAppearanceScale,
        Section.LIQUID_GLASS,
        "Glass Appearance Scale",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassAppearance.Scale",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Appearance enabled. Zero keeps the built-in scale."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassSpringDuration,
        Section.LIQUID_GLASS,
        "Glass Transition Spring Duration",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.SpringDuration",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Transitions enabled and a nonzero bounce. Zero keeps the built-in spring."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassSpringBounce,
        Section.LIQUID_GLASS,
        "Glass Transition Spring Bounce",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.SpringBounce",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Transitions enabled and a nonzero duration. Zero keeps the built-in spring."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassDelayFactor,
        Section.LIQUID_GLASS,
        "Glass Transition Delay Factor",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.DelayFactor",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Transitions enabled. Zero keeps the built-in delay factor."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassMinDelay,
        Section.LIQUID_GLASS,
        "Glass Transition Minimum Delay",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.MinDelay",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Transitions enabled. Zero keeps the built-in minimum delay."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SwiftUIGlassMaxDelay,
        Section.LIQUID_GLASS,
        "Glass Transition Maximum Delay",
        FileLocation.swiftuiPreferencesHomeDomain,
        "com.apple.SwiftUI.GlassTransition.MaxDelay",
        kind=Kind.NUMBER,
        value=0.0,
        min_value=0,
        max_value=999,
        step=0.01,
        min_version="26.0",
        experimental=True,
        description="Requires Custom Glass Transitions enabled. Zero keeps the built-in maximum delay."
        + " Reader traced on iOS 26.0; device delivery, accepted range and iOS 27 behavior are unverified.",
    ),
    _t(
        TweakID.SBDisableAutoDim,
        Section.SPRINGBOARD,
        "Disable Dimming Before Auto-Lock",
        FileLocation.springboard,
        "SBDisableAutoDim",
        min_version="26.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.springboard, "SBDisableAutoDim"
        ),
        description="Requests that the screen stay at its current brightness until Auto-Lock, instead of dimming first. This does not disable Auto-Lock or change its timeout.",
        experimental=True,
        warning="The preference exists in the inspected iOS 26 and 27 code, but restore delivery and visible behavior have not been verified.",
    ),
    _t(
        TweakID.SBDontLockEver,
        Section.SPRINGBOARD,
        "Prevent Device Locking",
        FileLocation.springboard,
        "SBDontLockEver",
        min_version="27.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.springboard, "SBDontLockEver"
        ),
        description="Requests that the device stay unlocked. If honored, automatic locking and the lock button will no longer lock it. Power-off should remain available through the normal button combination for your model. This does not unlock an already locked device.",
        experimental=True,
        warning="May prevent locking with the side button. Restore delivery and behavior are not verified on iOS 27.",
    ),
    _t(
        TweakID.HWKeyboardCapsLockRomanSwitch,
        Section.SPRINGBOARD,
        "Switch Languages with Caps Lock",
        FileLocation.keyboardPreferencesHomeDomain,
        "HWKeyboardCapsLockRomanSwitch",
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.keyboardPreferencesHomeDomain, "HWKeyboardCapsLockRomanSwitch"
        ),
        description="Use Caps Lock on a physical keyboard to switch between Latin and non-Latin input.",
        warning="Requires a physical keyboard and suitable input languages. Delivery and behavior through GoldenNugget are unverified.",
    ),
    _t(
        TweakID.GesturesEnabled,
        Section.SPRINGBOARD,
        "Enable Key Flicks",
        FileLocation.keyboardPreferencesHomeDomain,
        "GesturesEnabled",
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.keyboardPreferencesHomeDomain, "GesturesEnabled"
        ),
        description="Requests flicking down on iPad keyboard keys to type alternate characters.",
        warning="Intended for supported iPad keyboards. Delivery through GoldenNugget and support on other devices are unverified.",
    ),
    _t(
        TweakID.RivenKeyboard,
        Section.SPRINGBOARD,
        "Split Keyboard",
        FileLocation.keyboardPreferencesHomeDomain,
        "RivenKeyboard",
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.keyboardPreferencesHomeDomain, "RivenKeyboard"
        ),
        description="Requests the split keyboard option on supported iPads.",
        warning="Does not establish split keyboard support on unsupported devices. Delivery and behavior through GoldenNugget are unverified.",
    ),
    _t(
        TweakID.SplitHWRKeyboardEnabled,
        Section.SPRINGBOARD,
        "Split Handwriting Keyboard",
        FileLocation.keyboardPreferencesHomeDomain,
        "SplitHWRKeyboardEnabled",
        min_version="27.0",
        experimental=True,
        factory=lambda: _experimental_domain_boolean(
            FileLocation.keyboardPreferencesHomeDomain, "SplitHWRKeyboardEnabled"
        ),
        description="Requests split handwriting-keyboard behavior.",
        warning="A matching reader exists in iOS 27.0.1, but its preference domain, Boolean type, delivery and effect remain unverified. "
        "Uses the candidate ordinary keyboard preferences path. This does not establish support for the regular split keyboard.",
    ),
    _t(
        TweakID.KeyboardContinuousPathEnabled,
        Section.SPRINGBOARD,
        "Slide to Type",
        FileLocation.keyboardContinuousPath,
        "KeyboardContinuousPathEnabled",
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.keyboardContinuousPath, "KeyboardContinuousPathEnabled"
        ),
        description="Requests typing words by sliding your finger between keyboard letters.",
        warning="Requires a supported keyboard and language. Delivery and behavior through GoldenNugget are unverified.",
    ),
    _t(
        TweakID.LogFileStorageCount,
        Section.SPRINGBOARD,
        "Location Log Files to Keep",
        FileLocation.locationPreferencesHomeDomain,
        "LogFileStorageCount",
        value=6,
        kind=Kind.NUMBER,
        min_value=-1,
        max_value=8,
        step=1,
        min_version="26.0",
        description="Location diagnostic logs to retain: -1 keeps all, 0 keeps none, and 1–8 keeps that many files.",
        warning="Delivery and behavior through GoldenNugget are unverified. This setting controls log retention, not general device cache.",
    ),
    _t(
        TweakID.HarvestTraceOnDiskOnly,
        Section.SPRINGBOARD,
        "Trace Location Harvest to Disk",
        FileLocation.locationPreferencesHomeDomain,
        "HarvestTraceOnDiskOnly",
        value=1,
        min_version="26.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.locationPreferencesHomeDomain, "HarvestTraceOnDiskOnly", 1, 0
        ),
        description="Requests writing location-harvest diagnostic traces to disk.",
        warning="The Settings label identifies a diagnostic option; its exact behavior and delivery through GoldenNugget are unverified.",
    ),
    _t(
        TweakID.SBEnableAlwaysOn,
        Section.SPRINGBOARD,
        "Enable Always-On Display",
        FileLocation.springboardPreferencesHomeDomain,
        "SBEnableAlwaysOn",
        min_version="18.0",
        factory=lambda: _experimental_domain_boolean(
            FileLocation.springboardPreferencesHomeDomain, "SBEnableAlwaysOn"
        ),
        description="Requests keeping a dimmed Lock Screen visible while the device is locked.",
        warning="Delivery and behavior through GoldenNugget are unverified. This preference does not establish Always-On Display support on incompatible hardware.",
    ),
    _t(
        TweakID.SBBottomLeftCornerGestureTouchTypes,
        Section.SPRINGBOARD,
        "Bottom-Left Corner Gesture",
        FileLocation.springboard,
        "SBBottomLeftCornerGestureTouchTypes",
        value=0,
        kind=Kind.NUMBER,
        min_value=0,
        max_value=3,
        ipad_only=True,
        description="Configure bottom-left corner swipe: 0=Off, 1=Screenshot, 2=Quick Note, 3=Both.",
    ),
    _t(
        TweakID.SBBottomRightCornerGestureTouchTypes,
        Section.SPRINGBOARD,
        "Bottom-Right Corner Gesture",
        FileLocation.springboard,
        "SBBottomRightCornerGestureTouchTypes",
        value=0,
        kind=Kind.NUMBER,
        min_value=0,
        max_value=3,
        ipad_only=True,
        description="Configure bottom-right corner swipe: 0=Off, 1=Screenshot, 2=Quick Note, 3=Both.",
    ),
    _t(
        TweakID.SBGestureRequiresEducationCorner,
        Section.SPRINGBOARD,
        "Bypass Corner Gesture Tutorial",
        FileLocation.springboard,
        "SBGestureRequiresEducation-Corner",
        value=0,
        kind=Kind.NUMBER,
        min_value=0,
        max_value=1,
        ipad_only=True,
        description="Disables the first-time onboarding prompt for corner gestures.",
    ),
    _t(
        TweakID.SmartInvertSystemUI,
        Section.INTERNAL,
        "Smart Invert System UI Process",
        FileLocation.accessibility,
        "AXSSystemUIProcessAppSmartInvertEnabledPreference",
        value=True,
        kind=Kind.SWITCH,
        description="Forces Smart Invert on system UI background processes and sheets.",
    ),
)
