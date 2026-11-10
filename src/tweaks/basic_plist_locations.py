from enum import Enum


class FileLocation(Enum):
    # Feature Flags
    featureflags = "/var/preferences/FeatureFlags/Global.plist"

    ota = "/var/Managed Preferences/mobile/com.apple.MobileAsset.plist"
    
    # SpringBoard Options
    springboard = "/var/Managed Preferences/mobile/com.apple.springboard.plist"
    springboardPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.springboard.plist"
    footnote = "/var/containers/Shared/SystemGroup/systemgroup.com.apple.configurationprofiles/Library/ConfigurationProfiles/SharedDeviceConfiguration.plist"
    airdrop = "/var/Managed Preferences/mobile/com.apple.sharingd.plist"
    nanoregistry = "/var/mobile/Library/Preferences/com.apple.NanoRegistry.plist"

    chronod = "/var/Managed Preferences/mobile/com.apple.chronod.plist"
    ambient = "/var/Managed Preferences/mobile/com.apple.ambient.plist"

    # Status Bar
    # iOS 27+: SpringBoard unarchives the carrier name from this file.
    # iOS 26 and below used the classic struct at
    # /var/mobile/Library/SpringBoard/statusBarOverrides instead.
    statusBarOverridesArchive = "/var/mobile/Library/SpringBoard/StatusBarOverrides.archive"

    accessibility = "/var/Managed Preferences/mobile/com.apple.Accessibility.plist"
    
    # Internal Options
    siriAIOverrides = "/var/containers/Data/SystemGroup/com.apple.eligibilityd/Library/Caches/NeverRestore/eligibility_overrides.data"
    globalPreferences = "/var/Managed Preferences/mobile/.GlobalPreferences.plist"
    globalPreferencesHomeDomain = "/var/mobile/Library/Preferences/.GlobalPreferences.plist"
    appStore = "/var/Managed Preferences/mobile/com.apple.AppStore.plist"
    backboardd = "/var/Managed Preferences/mobile/com.apple.backboardd.plist"
    coreMotion = "/var/Managed Preferences/mobile/com.apple.CoreMotion.plist"
    pasteboard = "/var/Managed Preferences/mobile/com.apple.Pasteboard.plist"
    notes = "/var/Managed Preferences/mobile/com.apple.mobilenotes.plist"
    keyboardPreferences = "/var/Managed Preferences/mobile/com.apple.keyboard.preferences.plist"
    uikit = "/var/Managed Preferences/mobile/com.apple.UIKit.plist"
    swiftui = "/var/Managed Preferences/mobile/com.apple.SwiftUI.plist"

    # Daemons
    disabledDaemons = "/var/db/com.apple.xpc.launchd/disabled.plist"
    screentime = "/var/mobile/Library/Preferences/com.apple.ScreenTimeAgent.plist"

    userActivityPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.coreservices.useractivityd.plist"
    mobileSMSPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.MobileSMS.plist"
    mobilePhonePreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.mobilephone.plist"
    safariPreferencesAppDomain = "AppDomain-com.apple.mobilesafari/Library/Preferences/com.apple.mobilesafari.plist"
    madridPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.madrid.plist"
    sharingPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.Sharing.plist"
    chronodPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.chronod.plist"
    prototypeToolsPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.PrototypeTools.plist"
    uikitPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.UIKit.plist"
    uikitInternalPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.UIKit.InternalPreferences.plist"
    carrierBundleOverlay = "/var/mobile/Library/Carrier Bundles/Overlay"
    keyboardPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.keyboard.preferences.plist"
    keyboardSettingsHomeDomain = "/var/mobile/Library/Preferences/com.apple.keyboard.plist"
    keyboardContinuousPath = "/var/mobile/Library/Preferences/com.apple.keyboard.ContinuousPath.plist"
    locationPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.locationd.plist"
    swiftuiPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.SwiftUI.plist"
    accessibilityPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.Accessibility.plist"
    applicationAccess = "/var/Managed Preferences/mobile/com.apple.applicationaccess.plist"
    celestialPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.celestial.plist"
    mobilecalPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.mobilecal.plist"
    apsPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.apsd.plist"
    avatarPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.AvatarUI.Staryu.plist"
    suggestionsPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.suggestions.plist"
    locationStatusBarPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.locationd.StatusBarIconManager.plist"
    preferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.Preferences.plist"
    imdPersistencePreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.imdpersistence.IMDPersistenceAgent.plist"
    diagnosticExtensionTracker = "/var/mobile/Library/Preferences/com.apple.DiagnosticExtensions.extensionTracker.plist"
    spotlightUIPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.spotlightui.plist"
    adPlatformsPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.AdPlatforms.plist"
    itunesstoredPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.itunesstored.plist"
    coreSpotlightUIPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.corespotlightui.plist"
    backgroundSystemTaskPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.bg.system.task.plist"
    dasdAppResumePreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.dasd.appResume.plist"
    spotlightKnowledgePreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.spotlightknowledged.pipeline.plist"
    itunesclouddPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.itunescloudd.plist"
    dasFairSchedulingPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.das.fairscheduling.plist"
    duetActivitySchedulerPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.duetactivityscheduler.plist"
    dasdActivityDurationTrackerPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.dasd.activityDurationTracker.plist"
    powerlogPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.powerlog.plist"
    photoanalysisdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.photoanalysisd.plist"
    activityawardsdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.activityawardsd.plist"
    apsdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.apsd.plist"
    analyticsdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.analyticsd.plist"
    osanalyticsPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.osanalytics.plist"
    duetExpertdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.duetexpertd.plist"
    coreduetdPreferencesHomeDomain = "/var/mobile/Library/Preferences/com.apple.coreduetd.plist"

    # Accessibility
    # Managed so the single key is merged on top of the user's own AX prefs
    # instead of replacing com.apple.Accessibility wholesale.
