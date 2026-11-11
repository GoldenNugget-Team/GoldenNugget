from enum import Enum

# Daemon controls remain user-selectable; keep this empty for compatibility
# with the shared tweak loader's protected-key interface.
DANGEROUS_KEYS = frozenset()

class Daemon(Enum):
    thermalmonitord = ["com.apple.thermalmonitord"]
    OTA = [
        "com.apple.mobile.softwareupdated",
        "com.apple.OTATaskingAgent",
        "com.apple.softwareupdateservicesd",
        "com.apple.mobile.NRDUpdated"
    ]
    UsageTrackingAgent = ["com.apple.UsageTrackingAgent"]
    GameCenter = ["com.apple.gamed"]
    CrashReports = [
        "com.apple.ReportCrash",
        "com.apple.ReportCrash.Jetsam",
        "com.apple.ReportMemoryException",
        "com.apple.OTACrashCopier",
        "com.apple.aslmanager",
        "com.apple.coresymbolicationd",
        "com.apple.crash_mover",
        "com.apple.crashreportcopymobile",
        "com.apple.DumpBasebandCrash",
        "com.apple.DumpPanic",
        "com.apple.logd",
        "com.apple.logd.admin",
        "com.apple.logd.events",
        "com.apple.logd.watchdog",
        "com.apple.logd_helper",
        "com.apple.logd_reporter",
        "com.apple.logd_reporter.report_statistics",
        "com.apple.system.logger",
        "com.apple.hangreporter",
        "com.apple.hangtracerd",
        "com.apple.spindump",
        "com.apple.tailspind",
        "com.apple.syslogd",
        "com.apple.signpost.signpost_reporter",
        "com.apple.pluginkit.pkreporter",
        "com.apple.ProxiedCrashCopier",
        "com.apple.ProxiedCrashCopier.ProxyingDevice",
        "com.apple.ReportSystemMemory"
    ]
    Diagnostics = [
        "com.apple.diagnosticd",
        "com.apple.diagnosticextensionsd",
        "com.apple.diagnosticservicesd",
        "com.apple.diagnosticspushd",
        "com.apple.symptomsd-diag",
        "com.apple.sysdiagnose",
        "com.apple.sysdiagnose.darwinos",
        "com.apple.sysdiagnose_helper"
    ]
    ATWAKEUP = ["com.apple.atc.atwakeup"]
    Tips = ["com.apple.tipsd"]
    VPN = ["com.apple.racoon"]
    Location = ["com.apple.locationd"]
    ChineseLAN = [
        "com.apple.wapic",
        "com.apple.wifi.wapic"
    ]
    HealthKit = ["com.apple.healthd"]
    AirPrint = ["com.apple.printd"]
    AssistiveTouch = ["com.apple.assistivetouchd"]
    iCloud = ["com.apple.itunescloudd"]
    InternetTethering = ["com.apple.MobileInternetSharing"]
    PassBook = ["com.apple.passd"]
    Spotlight = [
        "com.apple.searchd",
        "com.apple.corespotlightservice",
        "com.apple.spotlightknowledged",
        "com.apple.spotlightknowledged.updater",
        "com.apple.spotlight.IndexAgent"
    ]
    VoiceControl = [
        "com.apple.assistant_service",
        "com.apple.assistantd",
        "com.apple.voiced"
    ]
    FollowUp = ["com.apple.followupd"]
    # --- Safe additions (from MiniVoidyy/GoldenNugget-) grouped by function.
    # Only daemons whose disable is safe and not already removed/disabled by iOS.
    AppleAds = [
        "com.apple.promotedcontentd",
        "com.apple.adprivacyd",
        "com.apple.adservicesd"
    ]
    News = ["com.apple.newsd"]
    FamilySharing = [
        "com.apple.familycircled",
        "com.apple.familynotificationd"
    ]
    VideoSubscriptions = ["com.apple.videosubscriptionsd"]
    WebBookmarks = ["com.apple.webbookmarksd"]
    Feedback = ["com.apple.feedbackd"]
    WifiLogging = ["com.apple.wifilogd"]
    Maps = ["com.apple.geod"]
    SafariSuggestions = ["com.apple.parsecd"]
    Shazam = ["com.apple.shazamd"]
    SettingsStats = ["com.apple.settings-statsd"]
    Reminders = ["com.apple.reminderd"]
    AirPlay = ["com.apple.airplay"]
    GameKitService = ["com.apple.gamekitservice"]
    Sidecar = ["com.apple.sidecarcore"]
    SpeechRecognition = ["com.apple.speechrecognition"]
    MockLocation = ["com.apple.mocksynclocationd"]
    # --- Safe analytics/telemetry additions (from MiniVoidyy/GoldenNugget-) ---
    # Telemetry/analytics daemons ONLY. Nothing boot-critical, no core
    # wireless/cellular/auth services. These mirror the fork's curated
    # "Recommended" analytics set, whose disable is confirmed safe.
    WifiAnalytics = ["com.apple.wifianalyticsd"]
    AnalyticsHelper = [
        "com.apple.analyticsd",
        "com.apple.analyticsd.admin",
        "com.apple.analyticsd.events"
    ]
    AudioAnalytics = ["com.apple.audioanalyticsd"]
    EcosystemAnalytics = ["com.apple.ecosystemanalyticsd"]
    CallAnalytics = ["com.apple.rtcreportingd"]
    CoreDuet = ["com.apple.coreduetd"]
    Insight = ["com.apple.insightd"]
    Metrics = ["com.apple.metricsd"]
    MediaExperience = ["com.apple.mediaremoted"]
    Symptomsd = ["com.apple.symptomsd", "com.apple.symptomsd-app"]
    StatisticalDiagnostic = ["com.apple.StatisticalDiagnosticService"]
    WirelessDiagnostics = ["com.apple.wirelessdiagnostics"]
    DuetHeuristic = [
        "com.apple.DuetHeuristic-BM",
        "com.apple.DuetHeuristic-BM.Baseband"
    ]
    DuetExpert = ["com.apple.duetexpertd"]
    Triald = ["com.apple.triald"]
    Sociald = ["com.apple.sociald"]


# Preserve the old shortcut's scope for recovery of already-applied presets.
# Issue #58 reports missed-call notifications failing with this set + Spotlight.
# This is a recovery scope, not proof that any one member caused the failure.
NOTIFICATION_RECOVERY_DAEMONS = (
    Daemon.Spotlight,
    Daemon.Diagnostics, Daemon.UsageTrackingAgent,
    Daemon.AppleAds, Daemon.FollowUp, Daemon.Feedback, Daemon.Shazam,
    Daemon.SettingsStats, Daemon.WifiAnalytics, Daemon.AnalyticsHelper,
    Daemon.AudioAnalytics, Daemon.EcosystemAnalytics,
    Daemon.CallAnalytics, Daemon.CoreDuet, Daemon.Insight, Daemon.Metrics,
    Daemon.MediaExperience, Daemon.Symptomsd, Daemon.StatisticalDiagnostic,
    Daemon.WirelessDiagnostics, Daemon.DuetHeuristic, Daemon.DuetExpert,
    Daemon.Triald, Daemon.Sociald,
)

# Keep shared system services out of the one-tap analytics shortcut. Their
# individual controls remain available, but disabling them is not telemetry-only.
RECOMMENDED_ANALYTICS = [
    Daemon.Diagnostics, Daemon.UsageTrackingAgent,
    Daemon.AppleAds, Daemon.Feedback,
    Daemon.SettingsStats, Daemon.WifiAnalytics, Daemon.AnalyticsHelper,
    Daemon.AudioAnalytics, Daemon.EcosystemAnalytics,
    Daemon.Insight, Daemon.Metrics, Daemon.StatisticalDiagnostic,
    Daemon.WirelessDiagnostics,
]

# Interface-visible daemons: the switches on the Daemons page plus the
# one-tap Recommended set. Any enum member without a visible control is
# excluded from stored presets and the apply pass.
INTERFACE_DAEMONS: frozenset["Daemon"] = frozenset({
    # main "Disable" section (src/gui/ios/daemons.py)
    Daemon.thermalmonitord, Daemon.OTA, Daemon.UsageTrackingAgent,
    Daemon.GameCenter, Daemon.ATWAKEUP, Daemon.Tips, Daemon.VPN,
    Daemon.ChineseLAN, Daemon.HealthKit, Daemon.AirPrint,
    Daemon.AssistiveTouch, Daemon.iCloud, Daemon.InternetTethering,
    Daemon.PassBook, Daemon.Spotlight,
    Daemon.VoiceControl, Daemon.FollowUp, Daemon.Location,
    Daemon.News, Daemon.FamilySharing, Daemon.VideoSubscriptions,
    Daemon.WebBookmarks,
    Daemon.WifiLogging, Daemon.Maps, Daemon.SafariSuggestions,
    Daemon.Reminders, Daemon.AirPlay, Daemon.GameKitService,
    Daemon.Sidecar, Daemon.SpeechRecognition,
    Daemon.MockLocation,
    # analytics / telemetry section
    Daemon.CrashReports, Daemon.WifiAnalytics, Daemon.AnalyticsHelper, Daemon.CallAnalytics,
    Daemon.AudioAnalytics, Daemon.EcosystemAnalytics,
    Daemon.CoreDuet, Daemon.Insight, Daemon.Metrics, Daemon.MediaExperience,
    Daemon.Symptomsd, Daemon.StatisticalDiagnostic, Daemon.WirelessDiagnostics,
    Daemon.DuetHeuristic, Daemon.DuetExpert, Daemon.Triald,
    Daemon.Sociald,
} | set(RECOMMENDED_ANALYTICS) | set(NOTIFICATION_RECOVERY_DAEMONS))

# Interface-visible daemon keys: everything a user can toggle in the UI.
# Any key outside this set is stripped from presets / the apply pass.
INTERFACE_KEYS = frozenset(k for d in INTERFACE_DAEMONS for k in d.value)
