"""Display groups for the registry-backed tweak pages."""

from src.tweaks.registry import Kind, Section

SPRINGBOARD_GROUPS = {
    "Animation & Motion": (
        "DisableControlSymbolAnimations",
        "SBDisableIconParallax", "SBDisableIconFlyInAnimation", "SBDisableParallaxOnPageControl",
        "SBAppIconForceTouchAnimationDurationMultiplier", "SBQuickActionAnimationDuration",
        "SBAppIconForceTouchEnableUIPreviewInteractionAnimations",
    ),
    "iPad Dock": (
        "SBAppLibraryInDockEnabled", "SBRecentsEnabled",
    ),
    "Widget Migration": (
        "SBShouldAddDefaultWidgetsToHomeScreen",
        "SBShouldUpgradeEnableWidgetSuggestions",
        "SBShouldResetDefaultTodayList",
        "SBShouldResetStackForDefaultTodayList",
    ),
    "Always-On Display": (
        "SBAlwaysOnTapToInteract",
        "SBAlwaysOnSwipeToUnlock",
        "SBAndromedaDebugColors",
        "SBUseAlwaysOnBrightnessCurve",
        "SBEnforceOverallAPLLimit",

    ),
    "StandBy": (
        "AMBumpToWakeEnabled",
        "AMAmbientIgnoreBatteryCharging", "AMAlwaysUpdateIconModelOnAmbientWidgetLayoutChange",
    ),
    "Lock Screen": (
        "SBHideNotifications",
        "SBCoverSheetForceWakeToMaps",
        "LockScreenFootnote", "SBDontLockAfterCrash", "SBHideACPower",
        "SBShowSupervisionTextOnLockScreen", "SBMinimumLockscreenIdleTime",
        "SBShowAuthenticationEngineeringUI", "SBCoverSheetPlayerTimeout",
        "SBCoverSheetProportionalAdaptiveTime",
    ),
    "Home Screen & Navigation": (
        "SBFolderViewSuppressSetCurrentPage",
        "SBHomeShouldShowLibraryEducationView",
        "SBNeverBreadcrumb", "SBAlwaysShowSystemApertureInSnapshots", "HideDICompletely",
         "UseFloatingTabBar",
        "KeyboardShouldSplitInDefaultContext",
        "KeyboardShouldSplitInSplitPreferringContext",
        "UIKeyboardPersistentSplitProgress",
        "UIKeyboardPersistentSplitLock",
        "SBHideSearchAffordance", "SBHomeScreenShowsSearchButton", "SBDisableLiveIcons", "SBMaxIconListCount",
        "SBSuppressAppShortcutTruncation",
    ),
    "Power & Alerts": (
        "SBDontDimOrLockOnAC", "SBHideLowPowerAlerts", "SBSuppressNoSimAlert",
    ),
    "Sharing & Accessories": (
        "WatchOSCompatibility", "AirDropDisableTimeLimit", "AirplaySupport",
    ),
    "Widgets": (
        "SBShouldShowWidgetIntroductionPage",
        "SBHideReportWidgetStackRotationQuickAction",
        "SBIgnoreMinimumRequiredSDKVersionForWidgets", "SBNotificationCenterUseDuet",
        "SBBatteryWidgetAlwaysAvailable", "SBAlwaysAllowLongLookGesture",

        "SBWidgetLogging",
    ),
    "Lock Screen Camera": (
        "SBCoverSheetUseDefaultsValuesForCameraPrewarm", "SBCoverSheetPrewarmCameraOnSwipe",
        "SBCoverSheetPrelaunchCameraOnSwipe", "SBCoverSheetPrewarmCameraOnButtonTouch",
        "SBCoverSheetPrelaunchCameraOnButtonTouch", "SBCoverSheetCameraPrewarmThreshold",
        "SBCoverSheetCameraPrelaunchThreshold",
    ),
    "Windows & Multitasking": (
        "SBMenuBarDemoMode",
        "SBTrackpadSwitcherGesturesEnabled",
        "SBPIPInitiallyUsesMinimumPreferredContentSize",
        "SBDismissControlCenterElsewhereOnPresentation",
    ),
    "Dynamic Island Rendering": (


        "SBAlwaysShowSystemApertureOnClonedDisplays", "SBEnableSystemApertureStateCollection",
    ),
    "Stage Manager": (
        "SBChamoisWindowingEnabled", "SBChamoisHideDockExternal", "SBChamoisHideStripsExternal",
        "SBShowQuickNoteFingerGestureRecognizer",
        "SBHomeSidebarIsPinned",
        "SBShouldShowSplitPeekEducation",
        "SBShouldShowSlideOverPeekEducation",
        "SBChamoisHideStrips", "SBChamoisHideDock",
        "SBFlexibleWindowingManualStageCreationShouldRestorePreviousOpenWindows",
        "SBShouldInsertDownloadFileStackIconToFloatingDock", "SBWantsManyForegroundWindows",
        "SBForceMedusaAdoption",
    ),
    "Camera Control": (
        "SBDisableCaptureButton", "SBCaptureButtonAssociatedAppBundleIdentifier",
        "SBCaptureButtonAllowLaunchIfUnobstructionOccursWhileButtonDown",
        "SBCaptureButtonAllowLaunchIfUnobstructionOccursPromptlyAfterButtonUp",
        "SBCameraShutterButtonShouldUsePocketDetection", "SBCameraShutterButtonLongPressTimeout",
        "SBCameraShutterButtonLongPressCancellationTimeout",
        "SBSimulateCaptureButtonUsingActionButton", "SBDisablePreLaunchCaptureButtonSuppression",
        "SBCaptureButtonDisableWakeWhenDim", "SBCaptureButtonDisableStationaryDetection",
        "SBCaptureButtonDisableDirectLaunchAfterUnsuppress", "SBCaptureButtonEnableCameraPose",
    ),
    "App Behavior": (
        "SBForceAllPhoneAppsToBeResizableOnPad", "SBForceAllPhoneAppsToBeResizableOnResizableDisplays", "SBPhoneInitiatedAppResizeWidth", "SBPhoneInitiatedAppResizeHeight", "NavigationBarBackButtonShowsContextMenu",
        "SBIgnoreSBUsesNetwork", "SBBundleIdentifierToForceHomeAffordanceInset",
    ),
    "Picture in Picture Diagnostics": (
        "SBPIPVisualizeKeyboardFrame", "SBPIPVisualizePositionRegions",
    ),
    "Rotation & Display": (
        "SBScreenLongevityDimInterval",
        "SBBacklightLevel2",
        "SBExternalDisplayContentsScaleAndDontFileRadars",
         "SBMainDisplayDarkeningPercentage",
    ),
    "Status Indicators": (
        "SBSuppressScreenSharingStatusBarOverridePreferenceKey", "SBCarPlayShowOptimalCellData",
        "SBShowRSSI", "SBShowThermalWarning", "SBShowStatusBarOverridesForRecording",
    ),
    "Notification Experiments": (
         "SBNotificationVisibleIdleTimer",
    ),
    "Diagnostics": (
        "SBEnableExtraBacklightLogging",
        "SBDisableAutomaticMallocStackLogging",
        "SBSystemGestureLogging",
        "SBStatusBarishLogOptions",
        "SBSwitcherBottomEdgeGestureSwipeCount",
    ),
    "Risky Experiments": (
        "SBDisableHomeButton", "SBDisableProximity",
        "SBShouldLaunchWithMallocStackLogging",
        "SBDisableIdleSleep",
        "SBDisableHomeButtonDoublePress",
        "SBIgnoreCaptureApplicationLaunchMonitor",
        "SBWidgetSnapshottingEnabled", "SBDisableAsyncRenderingSurfaceRetention",
        "SBEnableDynamicJetsamLimits", "SBKillableInAppSwitcher", "SBBackgroundNethermostWindows",
        "SBHijackSpotlightButtonActionForPrototyping", "SBPostModernRotationForciblyEnabled",
        "SBCoverSheetDisableDeviceMotionEffectPerformanceOptimizations",
        "SBAlwaysAllowDefaultAction",
    ),
}

INTERNAL_GROUPS = {
    "Layout & Appearance": (
        "SBBuildNumber", "RTL", "LTR", "SBIconVisibility", "DisableSecondsHand",
        "BKHideAppleLogoOnLaunch",
    ),
    "Search & Clipboard": (
        "DisableSearchingWebsites", "PlaySoundOnPaste", "AnnounceAllPastes",
    ),
    "Touch & Feedback": ("BKDigitizerVisualizeTouches", "EnableWakeGestureHaptic"),
    "App & Accessory Diagnostics": (
        "iMessageDiagnosticsEnabled", "IDSDiagnosticsEnabled", "VCDiagnosticsEnabled",
        "AccessoryDeveloperEnabled", "ShowButtonHints", "AppStoreDebug", "NotesDebugMode",
    ),
}


BOTTOM_TWEAK_CATEGORIES = (
    "Glass Adjustments", "Floating Views", "Focus Highlights", "Layered Icons", "Icon Depth & Motion",
)


def _catalog_category(spec):
    name = spec.id.name
    if spec.section == Section.POSTERBOARD:
        return 'PosterKit Archives' if name=='PosterKitOverrides' else 'Wallpaper Feature Flags' if spec.kind==Kind.POSTER_FLAG else 'Wallpaper Dictionaries'
    if spec.section == Section.SPRINGBOARD:
        return next((title for title, names in SPRINGBOARD_GROUPS.items() if name in names),
                    "Other System Options")
    if spec.section == Section.INTERNAL:
        if spec.id.name in ('DisableCollectionViewPrefetching', 'TableViewCellPrefetchingModeResearch'):
            return 'Experimental Performance'
        if spec.id.name in ('SpotlightMetricsWritingResearch',
                            'ICloudBackgroundTaskSchedulingResearch',
                            'DASFairSchedulingQueueResearch'):
            return 'Research Leads'
        return next((title for title, names in INTERNAL_GROUPS.items() if name in names),
                    "Other Internal Options")
    if name.startswith("FloatingContentView"):
        return "Floating Views"
    if name.startswith("FocusSpecular"):
        return "Focus Highlights"
    if name.startswith("NewStackedImage"):
        return "Layered Icons"
    if name.startswith("StackedImageContainer"):
        return "Icon Depth & Motion"
    if spec.kind == Kind.NUMBER:
        return "Glass Adjustments"
    if name.startswith("Calistoga"):
        return "Glass Materials"
    if name in ("GlassVisualDebug", "GlassVisualWarnings",
                "BlurFillExperiment"):
        return "Glass Diagnostics"
    if name.startswith(("DisableSpecular", "DisableOuter", "DisableSolariumHDR",
                        "DisableWidget", "DisableDock", "DisableFolder", "Exclude")):
        return "Reflections & Shadows"
    return "Glass Appearance"


_CATEGORY_MERGES = {
    "Dock Geometry Experiments": "Home Screen & Dock", "iPad Dock": "Home Screen & Dock",
    "Widget Migration": "Home Screen & Dock", "Widgets": "Home Screen & Dock",
    "Home Screen & Navigation": "Home Screen & Dock",
    "Always-On Display": "Lock Screen & Display", "StandBy": "Lock Screen & Display",
    "Lock Screen Date & Time": "Lock Screen & Display", "Lock Screen": "Lock Screen & Display",
    "Rotation & Display": "Lock Screen & Display", "Dynamic Island Rendering": "Lock Screen & Display",
    "Status Indicators": "Lock Screen & Display", "Notification Experiments": "Lock Screen & Display",
    "Camera Control": "Camera & Buttons", "Lock Screen Camera": "Camera & Buttons",
    "Touch & Feedback": "Camera & Buttons",
    "Windows & Multitasking": "Apps & Multitasking", "Stage Manager": "Apps & Multitasking",
    "App Behavior": "Apps & Multitasking", "Sharing & Accessories": "Connections",
    "Glass Appearance": "Glass & Appearance", "Glass Materials": "Glass & Appearance",
    "Glass Diagnostics": "Diagnostics", "App & Accessory Diagnostics": "Diagnostics",
    "Picture in Picture Diagnostics": "Diagnostics", "Power & Alerts": "Lock Screen & Display",
    "Layout & Appearance": "Home Screen & Dock",
}
TWEAK_CATEGORY_ORDER = (
    "Glass & Appearance", "Reflections & Shadows",
    "Home Screen & Dock", "Lock Screen & Display", "Animation & Motion", "Camera & Buttons", "Apps & Multitasking", "Connections",
    "Diagnostics", "Risky Experiments", *BOTTOM_TWEAK_CATEGORIES,
)


def tweak_category(spec):
    category = _catalog_category(spec)
    return _CATEGORY_MERGES.get(category, category)
