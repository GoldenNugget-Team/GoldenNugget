"""Display text for opt-in additional daemon controls."""

ADDITIONAL_DAEMON_CONTROLS = {
    "appinstallationmetricsd": (
        "Disable App Installation Reports",
        "Stops reports about app installations.",
    ),
    "geoanalyticsd": (
        "Disable Location Reports",
        "Stops location-related usage reports.",
    ),
    "hangtelemetryd": (
        "Disable App Freeze Reports",
        "Stops collecting reports about apps that freeze or stop responding.",
    ),
    "fitnessintelligenced": (
        "Disable Fitness Insights",
        "Stops personalized activity insights updating.",
    ),
    "icloudsubscriptionoptimizerd": (
        "Disable iCloud Subscription Helper",
        "Stops an iCloud subscription helper.",
    ),
    "gamepolicyd": (
        "Disable Game Performance Management",
        "May change Game Mode and game performance.",
    ),
    "batteryintelligenced": (
        "Disable Battery Analysis",
        "Stops background battery analysis.",
    ),
    "anomalydetectiond": (
        "Disable Unusual-Event Detection",
        "Stops a hidden event-detection service.",
    ),
    "callintelligenced": (
        "Disable Smart Calling Features",
        "Stops calling features that use this service.",
    ),
    "appmanagedfeaturesd": (
        "Disable Managed App Features",
        "Interrupts checks for apps managed by an organization or administrator.",
    ),
    "appprotectiond": (
        "Disable App Protection Helper",
        "Stops an app-protection service.",
    ),
    "iconservicesagent": (
        "Disable App Icons",
        "Can remove icons from the Home Screen, App Library and Dock.",
    ),
    "biomesyncd": (
        "Disable Activity Data Sync",
        "Stops sharing activity data used by suggestions between devices.",
    ),
    "eligibilityd": (
        "Disable Feature Availability Checks",
        "Interrupts checks for which features your device can use.",
    ),
    "mlhostd": (
        "Disable Background AI Tasks",
        "Stops features that need this service's background AI tasks.",
    ),
    "inboxupdaterd": (
        "Disable Inbox Updater",
        "The effect of stopping this service is unknown.",
    ),
    "visioncompaniond": (
        "Disable Vision Companion Helper",
        "Interrupts companion-device features.",
    ),
    "icloudmailagent": (
        "Disable iCloud Mail Helper",
        "Stops background iCloud Mail tasks from completing.",
    ),
    "attributionkitd": (
        "Disable Ad Download Measurement",
        "Stops measuring which ads lead to app downloads.",
    ),
    "wirelessinsightsd": (
        "Disable Wireless Connection Reports",
        "Stops collecting wireless connection information for troubleshooting.",
    ),
    "axauditd": (
        "Disable Accessibility Inspection",
        "Stops accessibility checks used by app inspection and development tools.",
    ),
    "bookdatastored": (
        "Disable Books Library Data",
        "Interrupts access to book library information and updates.",
    ),
    "bookassetd": ("Disable Book Downloads", "Stops books downloading or opening."),
    "calaccessd": (
        "Disable Calendar Data Service",
        "Stops calendars being read, changed or synced.",
    ),
    "callhistoryd": (
        "Disable Recent Call History",
        "Stops recent calls being saved or synced between devices.",
    ),
    "chronod": (
        "Disable Widget Refreshing",
        "Stops widgets refreshing in the background.",
    ),
    "cloudphotod": (
        "Disable iCloud Photos Sync",
        "Stops photos and videos uploading to or downloading from iCloud.",
    ),
    "donotdisturbd": (
        "Disable Focus Mode",
        "Stops Focus controls opening, schedules running or modes changing.",
    ),
    "photoanalysisd": (
        "Disable Photo Content Analysis",
        "Experimental: requests stopping the PhotoAnalysis service, including its photoLibraryOnBatteryTasks activity (scheduled every 8 hours and not marked external-power-only in the inspected iOS 27.2 policy). The schedule does not prove actual execution or battery cost. People recognition, photo search, Memories and other Photos analysis may stop. Device disable behavior and battery savings are unverified.",
    ),
    "stickersd": (
        "Disable Sticker Service",
        "Interrupts sticker creation or make stickers unavailable in apps.",
    ),
    "storekitd": (
        "Disable In-App Purchases",
        "Interrupts purchases and subscription checks inside apps.",
    ),
    "appstorecomponentsd": (
        "Disable App Store Helpers",
        "Interrupts App Store content or features that use its helper services.",
    ),
    "avatarsd": (
        "Disable Memoji Service",
        "Stops Memoji being created, changed or made available to apps.",
    ),
    "medialibraryd": (
        "Disable Media Library Service",
        "Stops apps reading or updating music and other media library information.",
    ),
    "mediaartworkd": (
        "Disable Album Cover Downloads",
        "Stops album covers and other media artwork loading or updating.",
    ),
    "liveactivitiesd": (
        "Disable Live Activity Updates",
        "Stops Live Activities updating on the Lock Screen and Dynamic Island.",
    ),
    "contactsd": (
        "Disable Contacts Service",
        "Stops contacts being read, edited or synced.",
    ),
    "postersyncd": (
        "Disable Contact Poster Sync",
        "Stops contact photos and posters syncing between devices.",
    ),
    "fileproviderd": (
        "Disable Cloud File Access",
        "Stops cloud documents appearing, downloading or opening in Files and other apps.",
    ),
    "axremoted": (
        "Disable Remote Accessibility Control",
        "Interrupts accessibility features that control another device.",
    ),
    "motiontrackingd": (
        "Disable Accessibility Motion Tracking",
        "Interrupts accessibility features that use this service's movement tracking.",
    ),
    "biomed": (
        "Disable Activity-Based Suggestions Data",
        "Stops processing activity data used by system suggestions.",
    ),
    "ckdiscretionaryd": (
        "Disable Background iCloud Task Scheduling",
        "May delay or stop background iCloud database syncing for apps.",
    ),
    "dataaccessd": (
        "Disable Account Data Sync",
        "Stops Mail, Contacts and Calendar syncing data for accounts that use this service.",
    ),
    "exchangesyncd": (
        "Disable Exchange Account Sync",
        "Stops mail, contacts and calendars syncing for Exchange accounts.",
    ),
    "eyedropperd": (
        "Disable Screen Color Picker",
        "Stops the color picker sampling colors from the screen.",
    ),
    "fontservicesd": (
        "Disable Font Loading Service",
        "Interrupts font loading or cause text to display incorrectly.",
    ),
    "homeenergyd": (
        "Disable Home Energy Updates",
        "Stops energy-related features in Home updating.",
    ),
    "homeeventsd": (
        "Disable Home Event Helper",
        "Interrupts smart-home features that use this helper.",
    ),
    "jetpackassetd": (
        "Disable Jetpack Content Helper",
        "Stops a hidden content-download helper.",
    ),
    "mstreamd": (
        "Disable Photo Stream Helper",
        "Interrupts photo-stream features that still use this service.",
    ),
    "pointeruid": (
        "Disable Mouse and Trackpad Pointer",
        "Stops the on-screen mouse or trackpad pointer working.",
    ),
    "previewsd": (
        "Disable App Design Previews",
        "Stops development tools previewing an app's interface on the connected device.",
    ),
    "replicatord": ("Disable Data Copy Helper", "Stops a hidden data-copy service."),
    "contentlinkingd": (
        "Disable Related Content Links",
        "Stops links and suggestions based on related content.",
    ),
    "cloudtelemetryd": (
        "Disable iCloud Diagnostic Reports",
        "Stops collecting troubleshooting reports about cloud services.",
    ),
    "filederivatived": (
        "Disable File Preview Copy Generation",
        "Stops apps creating alternate versions of files they need.",
    ),
    "shazameventsd": (
        "Disable Music Recognition History Updates",
        "Stops recognized-song events being processed and added to history.",
    ),
    "visualintelligenced": (
        "Disable Visual Intelligence",
        "Stops features that understand images or what the camera sees.",
    ),
    "agentstored": (
        "Disable AI Task Storage Helper",
        "Interrupts AI tasks that use this storage helper.",
    ),
    "cksharingmanagementd": (
        "Disable Shared iCloud App Data",
        "Interrupts shared app data and invitations that use iCloud databases.",
    ),
    "messagesescrowd": (
        "Disable Messages Recovery Helper",
        "Stops a Messages recovery-related helper.",
    ),
    "imageplaygroundd": (
        "Disable Image Playground",
        "Stops Image Playground generating images.",
    ),
    "callverificationd": (
        "Disable Call Verification Helper",
        "Interrupts call-verification features.",
    ),
    "cameraispd": (
        "Disable Camera Image Processing",
        "Stops the camera taking photos or video.",
    ),
    "clocksyncd": (
        "Disable Device Clock Sync Helper",
        "Stops a low-level clock-sync helper.",
    ),
    "dbtelemetryd": (
        "Disable Database Error Reports",
        "Stops collecting database troubleshooting reports.",
    ),
    "diagnosticscheckupd": (
        "Disable Diagnostic Checkups",
        "Stops system troubleshooting checks that use this service.",
    ),
    "fpassetmanagerd": (
        "Disable Cloud File Download Helper",
        "Stops cloud documents downloading through file-provider apps.",
    ),
    "hybridsearchd": (
        "Disable Combined Search Helper",
        "May leave results missing in features that use this search service.",
    ),
    "riskdatad": (
        "Disable Risk Assessment Helper",
        "Stops a hidden risk-checking service.",
    ),
    "sharereportingd": (
        "Disable Sharing Report Helper",
        "Stops Apple's sharing-report service.",
    ),
    "symptomsd_darwin": (
        "Disable System Health Reports",
        "May reduce troubleshooting information about system problems.",
    ),
    "inputanalyticsd": (
        "Disable Input Usage Reports",
        "Stops collecting troubleshooting reports about user input.",
    ),
    "metrickitd": (
        "Disable App Performance Reports",
        "Stops apps receiving reports about crashes, freezes, memory use and performance.",
    ),
    "photosfaced": ("Disable Photos Face Helper", "Stops the Photos Face helper."),
    "sportsd": (
        "Disable Sports Updates",
        "Stops scores and other sports information updating.",
    ),
    "wifivelocityd": (
        "Disable Wi-Fi Troubleshooting Helper",
        "Stops Wi-Fi troubleshooting data being collected.",
    ),
    "textunderstandingd": (
        "Disable Text Understanding",
        "Interrupts system features that interpret the meaning of text.",
    ),
    "proactiveeventtrackerd": (
        "Disable Activity-Based Event Suggestions",
        "Stops event suggestions based on your activity updating.",
    ),
    "locationpushd": (
        "Disable Remote Location Update Helper",
        "Stops features that request location updates remotely.",
    ),
    "modelmanagerd": (
        "Disable AI Model Loading",
        "Stops AI features loading or updating the files they need.",
    ),
    "gamesaved": (
        "Disable Game Save Helper",
        "Stops games saving progress or syncing saves.",
    ),
    "syncdefaultsd": (
        "Disable Settings Sync",
        "Stops app or system settings syncing between devices.",
    ),
    "securityuploadd": (
        "Disable Security Report Uploads",
        "Stops uploading security-related troubleshooting reports.",
    ),
    "watchlistd": ("Disable TV Watchlist Updates", "Stops TV watchlists updating."),
    "swiftuitraced": (
        "Disable App Interface Tracing",
        "Stops interface troubleshooting traces used by development tools.",
    ),
    "soundanalysisd": (
        "Disable Sound Recognition Service",
        "Stops features that identify or analyze sounds.",
    ),
    "powerdatad": (
        "Disable Power Use Reports",
        "Stops collecting battery and power-use troubleshooting data.",
    ),
    "facemetricsd": (
        "Disable Face Metrics Helper",
        "The effect of stopping this service is unknown.",
    ),
    "contactsdonationagent": (
        "Disable Contact Suggestions Data",
        "Stops contact information being shared with system suggestion features.",
    ),
    "voicebankingd": (
        "Disable Personal Voice Processing",
        "Stops Personal Voice creating or processing a saved voice.",
    ),
    "voicememod": (
        "Disable Voice Memos Background Tasks",
        "Stops Voice Memos managing recordings or syncing them.",
    ),
    "amsondevicestoraged": (
        "Disable Apple Media Storage Helper",
        "Interrupts locally stored data used by Apple media and store features.",
    ),
    "intelligencetasksd": (
        "Disable Background Intelligence Tasks",
        "Stops AI features completing background work or updating results.",
    ),
    "accessoryupdaterd": (
        "Disable Accessory Software Updates",
        "Stops accessories receiving software updates.",
    ),
    "deferredmediad": (
        "Disable Photo and Video Finishing",
        "May leave captured photos or videos without their final background processing.",
    ),
    "mediaplaybackd": (
        "Disable Media Playback Helper",
        "Stops audio or video playing in apps that depend on this service.",
    ),
    "mediasetupd": (
        "Disable Media Setup Helper",
        "Stops a hidden media-setup service.",
    ),
    "enhancedloggingd": (
        "Disable Extra System Logs",
        "Stops additional system troubleshooting logs.",
    ),
    "betaenrollmentd": (
        "Disable Beta Update Enrollment",
        "Stops the device joining a beta software update program.",
    ),
    "remoteappintentsd": (
        "Disable App Actions Across Devices",
        "Stops app actions running between devices.",
    ),
    "safetyalertsd": (
        "Disable Safety Alert Helper",
        "May prevent safety alerts that depend on this service.",
    ),
    "relatived": (
        "Disable Relative Service",
        "The effect of stopping this service is unknown.",
    ),
    "naturallanguaged": (
        "Disable System Text Analysis",
        "Interrupts text features that analyze language or meaning.",
    ),
    "textcontextd": (
        "Disable Context-Aware Text Help",
        "Interrupts text assistance that uses nearby words or context.",
    ),
    "ospredictiond": (
        "Disable Battery Predictions",
        "Stops battery and charging predictions updating.",
    ),
    "locationaccessstored": (
        "Disable Location Access History",
        "Stops location-access records used by privacy reporting being saved.",
    ),
    "powerexperienced": (
        "Disable Power Mode Management",
        "Interrupts power modes and battery-related system behavior.",
    ),
    "powerexceptionsd": (
        "Disable Power Limit Exception Helper",
        "Interrupts system checks for tasks exceeding power limits.",
    ),
    "proximitycontrold": (
        "Disable Nearby Device Controls",
        "Interrupts interactions and controls between nearby devices.",
    ),
    "webkit_adattributiond": (
        "Disable WebKit Ad Attribution",
        "Stops WebKit measuring ad clicks and conversion events in Safari and web views.",
    ),
    "privacyaccountingd": (
        "Disable Privacy Accounting Service",
        "Stops background tracking of app sensor, camera, and microphone usage.",
    ),
    "parsec_fbf": (
        "Disable Parsec Feedback Telemetry",
        "Stops CoreParsec uploading search and Siri feedback logs.",
    ),
    "sensorkitd": (
        "Disable SensorKit Research Service",
        "Stops SensorKit collecting sensor research and study data.",
    ),
    "activitysharingd": (
        "Disable Activity Sharing Sync",
        "Stops Fitness activity and workout sharing with friends.",
    ),
    "activityawardsd": (
        "Disable Fitness Awards Service",
        "Stops calculating and generating Fitness badges and award notifications.",
    ),
    "maps_geocorrectiond": (
        "Disable Maps Geo Correction",
        "Stops Maps submitting correction logs and map feedback.",
    ),
    "maps_pushdaemon": (
        "Disable Maps Push Daemon",
        "Stops push updates and notifications for Apple Maps.",
    ),
    "safarifetcherd": (
        "Disable Safari Background Fetcher",
        "Stops Safari pre-fetching Reading List articles and web pages in the background.",
    ),
    "safari_historyd": (
        "Disable Safari History Indexing",
        "Stops background indexing and maintenance of Safari browsing history.",
    ),
    "safari_safebrowsing": (
        "Disable Safari Safe Browsing Service",
        "Stops Safari verifying suspicious websites against Apple anti-phishing service.",
    ),
    "webkit_webpushd": (
        "Disable Web Push Notifications",
        "Stops Safari and web apps from receiving background web push notifications.",
    ),
    "textcomposerd": (
        "Disable Text Composer Service",
        "Stops background text proofreading and composition tools in Apple Intelligence.",
    ),
    "speechmodeltrainingd": (
        "Disable Speech Model Training",
        "Stops background training and fine-tuning of personal speech recognition models.",
    ),
    "reversetemplated": (
        "Disable Suggestions Template Extraction",
        "Stops extracting events, flight details, and reservation suggestions from messages.",
    ),
    "featureaccessd": (
        "Disable Feature Entitlements Service",
        "Disrupts cloud subscription and feature entitlement checks.",
    ),
    "cloudsettingssyncagent": (
        "Disable Cloud Settings Sync",
        "Stops syncing system settings across iCloud devices.",
    ),
    "recentsd": (
        "Disable Recent Contacts History",
        "Stops CoreRecents logging recent contacts, recipients, and message history.",
    ),
    "keychainsharingmessagingd": (
        "Disable Keychain Group Sharing Sync",
        "Stops background communication for shared iCloud Keychain password groups.",
    ),
    "assetcachelocatorservice": (
        "Disable Content Caching Discovery",
        "Stops searching local network for macOS Content Caching servers.",
    ),
    "watchconnectivityd": (
        "Disable Watch Connectivity Daemon",
        "Stops background WatchConnectivity communication and data transfers with Apple Watch.",
    ),
    "announced": (
        "Disable Announce Notifications",
        "Stops Siri announcing notifications through AirPods and HomePod.",
    ),
    "barcodesupport_notification": (
        "Disable Barcode Notification Service",
        "Stops automatic QR code and barcode banner notifications from camera detections.",
    ),
    "photos_imageconversionservice": (
        "Disable Photo Conversion Service",
        "Stops background image transcoding and media format conversion.",
    ),
    "photos_videoconversionservice": (
        "Disable Video Conversion Service",
        "Stops background video transcoding and media format conversion.",
    ),
    "quicklook_thumbnailsagent": (
        "Disable Thumbnail Generation Service",
        "Stops generating QuickLook preview thumbnails for documents and media.",
    ),
    "healtheventsd": (
        "Disable Health Events Daemon",
        "Stops background health event detection and alert evaluations.",
    ),
    "webinspectord": (
        "Disable Remote Web Inspector",
        "Stops remote WebKit inspection and debugging connections from Safari on Mac.",
    ),
    "abdatabasedoctor": (
        "Disable Address Book Doctor",
        "Stops periodic database optimization and checkup on local contacts.",
    ),
    "asktod": (
        "Disable Ask To Buy Daemon",
        "Stops background handling of Ask To Buy notifications and family approvals.",
    ),
    "progressd": (
        "Disable ClassKit Progress Daemon",
        "Stops ClassKit tracking and syncing school and assignment progress.",
    ),
    "storagedatad": (
        "Disable Storage Breakdown Service",
        "Stops background calculation of app storage and disk category breakdowns.",
    ),
    "tzlinkd": (
        "Disable Time Zone Database Linker",
        "Stops background updates and linking of system timezone data.",
    ),
    "businessservicesd": (
        "Disable Apple Business Chat Service",
        "Stops background sync of business icons and business messaging profiles.",
    ),
    "carkitd": (
        "Disable CarPlay Daemon",
        "Disrupts wireless and wired Apple CarPlay connection handling.",
    ),
    "useractivityd": (
        "Disable Handoff & Universal Clipboard",
        "Stops Handoff activity broadcasting and Universal Clipboard sync between devices.",
    ),
    "maps_destinationd": (
        "Disable Maps Suggested Destinations",
        "Stops proactive destination predictions and suggested commute alerts.",
    ),
    "nanobackupd": (
        "Disable Apple Watch Backup Service",
        "Stops background backups of paired Apple Watches.",
    ),
    "passcodenagd": (
        "Disable Passcode Policy Nag Daemon",
        "Stops periodic notifications prompting you to change or update passcodes.",
    ),
    "safetycheckd": (
        "Disable Safety Check Daemon",
        "Stops background reviews and auditing of shared permissions and devices.",
    ),
    "hearingaid_heard": (
        "Disable Hearing Devices Daemon",
        "Stops background audio routing and connection to MFi hearing aids.",
    ),
    "cmfsyncagent": (
        "Disable Blocked Contacts Sync",
        "Stops syncing blocked phone numbers and message spam filters across devices.",
    ),
}
