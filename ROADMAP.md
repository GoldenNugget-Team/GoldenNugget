# Roadmap

What has already shipped, and what is next. This is a plan, not a promise.

9.3 through 9.5.3 are already released. The notes below are the later releases in that range, taken from their release notes.

## Already shipped (9.3 – 9.7.6)

### 9.6

9.6.0 added a preset manager, an apply preview, operation history, and a session log viewer on the home screen. It also added tweak favorites, settings search, search in the tweak and daemon lists, Russian UI translations, conflicting-tweak warnings, validation of imported presets, a rollback preset, and warnings for unsafe device setups. Startup got faster by importing heavy modules lazily, a time estimate is shown before applying, and operation results stay on screen. PosterBoard was reworked, the converter was improved, and the interface gained a "no device connected" placeholder, polished navigation, and a language choice that is saved before restart. Python 3.15 compatibility was fixed.

9.6.2, the last 9.6 update, added a community presets page, packaged the macOS build as a universal2 DMG, fixed the status bar, and fixed issues #58 and #59.

### 9.7

9.7.0 added a community catalog for presets and `.batter` templates, with community tweaks (switches, sliders, text fields, and choices), catalog update indicators, and download size and SHA-256 checks. Those tweaks show up in the apply summary, the risk assessment, and the Reset dialog. New tweaks: Disable Icon Shimmer (iOS 26.4+) and experimental Disable Icon Glass Outline and SpringBoard RSSI indicator. Legacy wallpaper conversion runs only on iOS 27 and newer. First-run interface selection (Sidebar or Modern) came back, with English screenshots instead of the old preview SVGs. Media-cache verification checks every recorded file and its size, and an apply no longer reports success when tweak delivery or media restoration is incomplete.

### 9.7.4

The desktop app can install the mobile version onto the phone. The packaged app ships as GoldenNugget. Preference tweaks whose file had no backup baseline are delivered as new files instead of aborting the apply. Fixes include issues #80 and #81, Calendar Access timers stopping on close, removal of retired feature-flag writers, OTA daemon delivery separated from the MobileAsset preference, and nested preferences kept on reset.

### 9.7.5

Mobile Helper was simplified, and pairing moved from a lockdown record to remote pairing.

### 9.7.6

Critical bug fixes, including issue #87, plus a fix for PNG icons not rendering in the compiled build.

## Next

- Safety on iOS 27: never start an apply unless the selective backup completed and verified, and never overwrite the previous backup before restore finishes; mark iOS 27 features as verified or experimental.
- If the selective backup does not finish, the apply stops and says the device was not changed. The previous backup stays on this computer until that restore finishes.
