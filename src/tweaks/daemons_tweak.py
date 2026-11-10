from enum import Enum

# Daemon controls remain user-selectable; keep this empty for compatibility
# with the shared tweak loader's protected-key interface.
DANGEROUS_KEYS = frozenset()

class Daemon(Enum):
    appinstallationmetricsd = ['com.apple.AppInstallationMetrics']
    geoanalyticsd = ['com.apple.geoanalyticsd']
    hangtelemetryd = ['com.apple.hangtelemetryd']
    fitnessintelligenced = ['com.apple.fitnessintelligenced']
    icloudsubscriptionoptimizerd = ['com.apple.icloudsubscriptionoptimizerd']
    gamepolicyd = ['com.apple.gamepolicyd']
    batteryintelligenced = ['com.apple.batteryintelligenced']
    anomalydetectiond = ['com.apple.anomalydetectiond']
    callintelligenced = ['com.apple.callintelligenced']
    appmanagedfeaturesd = ['com.apple.appmanagedfeaturesd']
    appprotectiond = ['com.apple.appprotectiond']
    iconservicesagent = ['com.apple.iconservices.iconservicesagent']
    biomesyncd = ['com.apple.biomesyncd']
    eligibilityd = ['com.apple.eligibilityd']
    mlhostd = ['com.apple.mlhostd']
    inboxupdaterd = ['com.apple.inboxupdaterd']
    visioncompaniond = ['com.apple.visioncompaniond']
    icloudmailagent = ['com.apple.icloudmailagent']
    attributionkitd = ['com.apple.attributionkitd']
    wirelessinsightsd = ['com.apple.wirelessinsightsd']
    axauditd = ['com.apple.accessibility.axAuditDaemon.deviceservice']
    bookdatastored = ['com.apple.bookdatastored']
    bookassetd = ['com.apple.bookassetd']
    calaccessd = ['com.apple.calaccessd']
    callhistoryd = ['com.apple.callhistoryd']
    chronod = ['com.apple.chronod']
    cloudphotod = ['com.apple.cloudphotod']
    donotdisturbd = ['com.apple.donotdisturbd']
    photoanalysisd = ['com.apple.photoanalysisd']
    stickersd = ['com.apple.stickersd']
    storekitd = ['com.apple.storekitd']
    appstorecomponentsd = ['com.apple.appstorecomponentsd']
    avatarsd = ['com.apple.avatarsd']
    medialibraryd = ['com.apple.medialibraryd']
    mediaartworkd = ['com.apple.mediaartworkd']
    liveactivitiesd = ['com.apple.liveactivitiesd']
    contactsd = ['com.apple.contactsd']
    postersyncd = ['com.apple.contacts.postersyncd']
    fileproviderd = ['com.apple.FileProvider']
    axremoted = ['com.apple.accessibility.axremoted']
    motiontrackingd = ['com.apple.accessibility.motiontrackingd']
    biomed = ['com.apple.biomed']
    ckdiscretionaryd = ['com.apple.ckdiscretionaryd']
    dataaccessd = ['com.apple.dataaccess.dataaccessd']
    exchangesyncd = ['com.apple.exchangesyncd']
    eyedropperd = ['com.apple.uikit.eyedropperd']
    fontservicesd = ['com.apple.fontservicesd']
    homeenergyd = ['com.apple.homeenergyd']
    homeeventsd = ['com.apple.homeeventsd']
    jetpackassetd = ['com.apple.jetpackassetd']
    mstreamd = ['com.apple.mediastream.mstreamd']
    pointeruid = ['com.apple.PointerUI.pointeruid']
    previewsd = ['com.apple.dt.previewsd']
    replicatord = ['com.apple.replicatord']
    contentlinkingd = ['com.apple.synapse.contentlinkingd']
    cloudtelemetryd = ['com.apple.cloudtelemetryd']
    filederivatived = ['com.apple.filederivatived']
    shazameventsd = ['com.apple.shazameventsd']
    visualintelligenced = ['com.apple.visualintelligenced']
    agentstored = ['com.apple.GenerativeFunctions.agentstored']
    cksharingmanagementd = ['com.apple.cksharingmanagementd']
    messagesescrowd = ['com.apple.messagesescrowd']
    imageplaygroundd = ['com.apple.imageplaygroundd']
    callverificationd = ['com.apple.callverificationd']
    cameraispd = ['com.apple.cameraispd']
    clocksyncd = ['com.apple.clocksyncd']
    dbtelemetryd = ['com.apple.libsqlite3.dbtelemetryd']
    diagnosticscheckupd = ['com.apple.diagnosticscheckupd']
    fpassetmanagerd = ['com.apple.fpassetmanagerd']
    hybridsearchd = ['com.apple.hybridsearchd']
    riskdatad = ['com.apple.riskdatad']
    sharereportingd = ['com.apple.sharereportingd']
    symptomsd_darwin = ['com.apple.symptomsd-darwin']
    inputanalyticsd = ['com.apple.inputanalyticsd']
    metrickitd = ['com.apple.metrickitd']
    photosfaced = ['com.apple.photosface']
    sportsd = ['com.apple.sportsd']
    wifivelocityd = ['com.apple.wifivelocityd']
    textunderstandingd = ['com.apple.textunderstandingd']
    proactiveeventtrackerd = ['com.apple.proactiveeventtrackerd']
    locationpushd = ['com.apple.locationpushd']
    modelmanagerd = ['com.apple.modelmanagerd']
    gamesaved = ['com.apple.gamesaved']
    syncdefaultsd = ['com.apple.syncdefaultsd']
    securityuploadd = ['com.apple.securityuploadd']
    watchlistd = ['com.apple.watchlistd']
    swiftuitraced = ['com.apple.swiftuitracingsupport.xpc']
    soundanalysisd = ['com.apple.soundanalysisd']
    powerdatad = ['com.apple.powerdatad']
    facemetricsd = ['com.apple.facemetricsd']
    contactsdonationagent = ['com.apple.contacts.donation-agent']
    voicebankingd = ['com.apple.voicebankingd']
    voicememod = ['com.apple.voicememod']
    amsondevicestoraged = ['com.apple.amsondevicestoraged']
    intelligencetasksd = ['com.apple.intelligencetasksd']
    accessoryupdaterd = ['com.apple.accessoryupdaterd']
    deferredmediad = ['com.apple.deferredmediad']
    mediaplaybackd = ['com.apple.mediaplaybackd']
    mediasetupd = ['com.apple.mediasetupd']
    enhancedloggingd = ['com.apple.enhancedloggingd']
    betaenrollmentd = ['com.apple.betaenrollmentd']
    remoteappintentsd = ['com.apple.remoteappintentsd']
    safetyalertsd = ['com.apple.safetyalertsd']
    relatived = ['com.apple.relatived']
    naturallanguaged = ['com.apple.naturallanguaged']
    textcontextd = ['com.apple.textcontextd']
    ospredictiond = ['com.apple.ospredictiond']
    locationaccessstored = ['com.apple.locationaccessstored']
    powerexperienced = ['com.apple.powerexperienced']
    powerexceptionsd = ['com.apple.powerexceptionsd']
    proximitycontrold = ['com.apple.proximitycontrold']
    webkit_adattributiond = ['com.apple.webkit.adattributiond']
    privacyaccountingd = ['com.apple.privacyaccountingd']
    parsec_fbf = ['com.apple.parsec-fbf']
    sensorkitd = ['com.apple.sensorkitd']
    activitysharingd = ['com.apple.activitysharingd']
    activityawardsd = ['com.apple.activityawardsd']
    maps_geocorrectiond = ['com.apple.Maps.geocorrectiond']
    maps_pushdaemon = ['com.apple.Maps.mapspushd']
    safarifetcherd = ['com.apple.safarifetcherd']
    safari_historyd = ['com.apple.Safari.History']
    safari_safebrowsing = ['com.apple.Safari.SafeBrowsing.Service']
    webkit_webpushd = ['com.apple.webkit.webpushd']
    textcomposerd = ['com.apple.textcomposerd']
    speechmodeltrainingd = ['com.apple.speechmodeltrainingd']
    reversetemplated = ['com.apple.reversetemplated']
    featureaccessd = ['com.apple.featureaccessd']
    cloudsettingssyncagent = ['com.apple.cloudsettingssyncagent']
    recentsd = ['com.apple.recentsd']
    keychainsharingmessagingd = ['com.apple.keychainsharingmessagingd']
    assetcachelocatorservice = ['com.apple.AssetCacheLocatorService']
    watchconnectivityd = ['com.apple.wcd']
    announced = ['com.apple.announced']
    barcodesupport_notification = ['com.apple.BarcodeSupport.BarcodeNotificationService']
    photos_imageconversionservice = ['com.apple.photos.ImageConversionService']
    photos_videoconversionservice = ['com.apple.photos.VideoConversionService']
    quicklook_thumbnailsagent = ['com.apple.quicklook.ThumbnailsAgent']
    healtheventsd = ['com.apple.healtheventsd']
    webinspectord = ['com.apple.webinspectord']
    abdatabasedoctor = ['com.apple.ABDatabaseDoctor']
    asktod = ['com.apple.asktod']
    progressd = ['com.apple.progressd']
    storagedatad = ['com.apple.storagedatad']
    tzlinkd = ['com.apple.tzlinkd']
    businessservicesd = ['com.apple.businessservicesd']
    carkitd = ['com.apple.carkitd']
    useractivityd = ['com.apple.coreservices.useractivityd']
    maps_destinationd = ['com.apple.maps.destinationd']
    nanobackupd = ['com.apple.nanobackupd']
    passcodenagd = ['com.apple.managedconfiguration.passcodenagd']
    safetycheckd = ['com.apple.safetycheckd']
    hearingaid_heard = ['com.apple.accessibility.heard']
    cmfsyncagent = ['com.apple.cmfsyncagent']

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

ADDITIONAL_DAEMONS = (
    Daemon.appinstallationmetricsd,
    Daemon.geoanalyticsd,
    Daemon.hangtelemetryd,
    Daemon.fitnessintelligenced,
    Daemon.icloudsubscriptionoptimizerd,
    Daemon.gamepolicyd,
    Daemon.batteryintelligenced,
    Daemon.anomalydetectiond,
    Daemon.callintelligenced,
    Daemon.appmanagedfeaturesd,
    Daemon.appprotectiond,
    Daemon.iconservicesagent,
    Daemon.biomesyncd,
    Daemon.eligibilityd,
    Daemon.mlhostd,
    Daemon.inboxupdaterd,
    Daemon.visioncompaniond,
    Daemon.icloudmailagent,
    Daemon.attributionkitd,
    Daemon.wirelessinsightsd,
    Daemon.axauditd,
    Daemon.bookdatastored,
    Daemon.bookassetd,
    Daemon.calaccessd,
    Daemon.callhistoryd,
    Daemon.chronod,
    Daemon.cloudphotod,
    Daemon.donotdisturbd,
    Daemon.photoanalysisd,
    Daemon.stickersd,
    Daemon.storekitd,
    Daemon.appstorecomponentsd,
    Daemon.avatarsd,
    Daemon.medialibraryd,
    Daemon.mediaartworkd,
    Daemon.liveactivitiesd,
    Daemon.contactsd,
    Daemon.postersyncd,
    Daemon.fileproviderd,
    Daemon.axremoted,
    Daemon.motiontrackingd,
    Daemon.biomed,
    Daemon.ckdiscretionaryd,
    Daemon.dataaccessd,
    Daemon.exchangesyncd,
    Daemon.eyedropperd,
    Daemon.fontservicesd,
    Daemon.homeenergyd,
    Daemon.homeeventsd,
    Daemon.jetpackassetd,
    Daemon.mstreamd,
    Daemon.pointeruid,
    Daemon.previewsd,
    Daemon.replicatord,
    Daemon.contentlinkingd,
    Daemon.cloudtelemetryd,
    Daemon.filederivatived,
    Daemon.shazameventsd,
    Daemon.visualintelligenced,
    Daemon.agentstored,
    Daemon.cksharingmanagementd,
    Daemon.messagesescrowd,
    Daemon.imageplaygroundd,
    Daemon.callverificationd,
    Daemon.cameraispd,
    Daemon.clocksyncd,
    Daemon.dbtelemetryd,
    Daemon.diagnosticscheckupd,
    Daemon.fpassetmanagerd,
    Daemon.hybridsearchd,
    Daemon.riskdatad,
    Daemon.sharereportingd,
    Daemon.symptomsd_darwin,
    Daemon.inputanalyticsd,
    Daemon.metrickitd,
    Daemon.photosfaced,
    Daemon.sportsd,
    Daemon.wifivelocityd,
    Daemon.textunderstandingd,
    Daemon.proactiveeventtrackerd,
    Daemon.locationpushd,
    Daemon.modelmanagerd,
    Daemon.gamesaved,
    Daemon.syncdefaultsd,
    Daemon.securityuploadd,
    Daemon.watchlistd,
    Daemon.swiftuitraced,
    Daemon.soundanalysisd,
    Daemon.powerdatad,
    Daemon.facemetricsd,
    Daemon.contactsdonationagent,
    Daemon.voicebankingd,
    Daemon.voicememod,
    Daemon.amsondevicestoraged,
    Daemon.intelligencetasksd,
    Daemon.accessoryupdaterd,
    Daemon.deferredmediad,
    Daemon.mediaplaybackd,
    Daemon.mediasetupd,
    Daemon.enhancedloggingd,
    Daemon.betaenrollmentd,
    Daemon.remoteappintentsd,
    Daemon.safetyalertsd,
    Daemon.relatived,
    Daemon.naturallanguaged,
    Daemon.textcontextd,
    Daemon.ospredictiond,
    Daemon.locationaccessstored,
    Daemon.powerexperienced,
    Daemon.powerexceptionsd,
    Daemon.proximitycontrold,
    Daemon.webkit_adattributiond,
    Daemon.privacyaccountingd,
    Daemon.parsec_fbf,
    Daemon.sensorkitd,
    Daemon.activitysharingd,
    Daemon.activityawardsd,
    Daemon.maps_geocorrectiond,
    Daemon.maps_pushdaemon,
    Daemon.safarifetcherd,
    Daemon.safari_historyd,
    Daemon.safari_safebrowsing,
    Daemon.webkit_webpushd,
    Daemon.textcomposerd,
    Daemon.speechmodeltrainingd,
    Daemon.reversetemplated,
    Daemon.featureaccessd,
    Daemon.cloudsettingssyncagent,
    Daemon.recentsd,
    Daemon.keychainsharingmessagingd,
    Daemon.assetcachelocatorservice,
    Daemon.watchconnectivityd,
    Daemon.announced,
    Daemon.barcodesupport_notification,
    Daemon.photos_imageconversionservice,
    Daemon.photos_videoconversionservice,
    Daemon.quicklook_thumbnailsagent,
    Daemon.healtheventsd,
    Daemon.webinspectord,
    Daemon.abdatabasedoctor,
    Daemon.asktod,
    Daemon.progressd,
    Daemon.storagedatad,
    Daemon.tzlinkd,
    Daemon.businessservicesd,
    Daemon.carkitd,
    Daemon.useractivityd,
    Daemon.maps_destinationd,
    Daemon.nanobackupd,
    Daemon.passcodenagd,
    Daemon.safetycheckd,
    Daemon.hearingaid_heard,
    Daemon.cmfsyncagent,
)
INTERFACE_DAEMONS |= frozenset(ADDITIONAL_DAEMONS)

# Interface-visible daemon keys: everything a user can toggle in the UI.
# Any key outside this set is stripped from presets / the apply pass.
INTERFACE_KEYS = frozenset(k for d in INTERFACE_DAEMONS for k in d.value)
