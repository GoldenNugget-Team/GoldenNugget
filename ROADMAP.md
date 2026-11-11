# Roadmap

What has already shipped, and what is next. This is a plan, not a promise.

9.3 through 9.7.6 are already released. The notes below cover 9.6 and later, taken from the release notes.

## Already shipped (9.3 – 9.7.6)

### 9.6

9.6.0:

- Home screen: preset manager, apply preview, operation history, session log viewer
- Tweak favorites, settings search, search in the tweak and daemon lists
- Russian UI translations
- Safety: conflicting-tweak warnings, validation of imported presets, a rollback preset, warnings for unsafe device setups
- Applying: a time estimate before applying, operation results stay on screen
- Faster startup thanks to lazy imports of heavy modules
- PosterBoard reworked, converter improved
- Interface: a "no device connected" placeholder, polished navigation, language choice saved before restart
- Python 3.15 compatibility fixed

9.6.2, the last 9.6 update, added a community presets page, packaged the macOS build as a universal2 DMG, fixed the status bar, and fixed issues #58 and #59.

### 9.7

9.7.0 added a community catalog for presets and `.batter` templates, with community tweaks (switches, sliders, text fields, and choices), catalog update indicators, and download size and SHA-256 checks. Those tweaks show up in the apply summary, the risk assessment, and the Reset dialog. New tweaks: Disable Icon Shimmer (iOS 26.4+) and experimental Disable Icon Glass Outline and SpringBoard RSSI indicator. Legacy wallpaper conversion runs only on iOS 27 and newer. First-run interface selection (Sidebar or Modern) came back, with English screenshots instead of the old preview SVGs. Media-cache verification checks every recorded file and its size, and an apply no longer reports success when tweak delivery or media restoration is incomplete.

### 9.7.2

`.batter` templates moved to a separate Templates page, with its own sidebar entry, home tile, and Import action. PosterBoard keeps Tendies and Video. Siri AI overrides are available on all iPhones running iOS 27.0, and are still experimental: only iPhone 16 Pro, build 24A437, was verified upstream. HotLoad `badNews` rules open a mandatory update window at startup, including from cached rules, that cannot be skipped, and the app stays blocked until it is restarted with an unaffected build. Catalog presets and templates can be marked "Not tested on a device."

### 9.7.4

The desktop app can install the mobile version onto the phone. The packaged app ships as GoldenNugget. Preference tweaks whose file had no backup baseline are delivered as new files instead of aborting the apply. Fixes include issues #80 and #81, Calendar Access timers stopping on close, removal of retired feature-flag writers, OTA daemon delivery separated from the MobileAsset preference, and nested preferences kept on reset.

### 9.7.5

Mobile Helper was simplified, and pairing moved from a lockdown record to remote pairing.

### 9.7.6

Critical bug fixes, including issue #87, plus a fix for PNG icons not rendering in the compiled build.

## Unreleased (in main)

- iOS 27 backup fail-safe: an apply does not start unless the selective backup finished and was verified, and the previous backup is kept until the restore finishes. In main, awaiting release and on-device verification.

## Next

- Verify the iOS 27 flow on a real device.
- Mark iOS 27 features as verified or experimental.
