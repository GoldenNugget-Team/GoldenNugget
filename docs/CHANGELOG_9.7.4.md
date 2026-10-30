# GoldenNugget Desktop 9.7.4

## GoldenNugget Mobile

The companion app for the iPhone can now be installed from the desktop
(Settings → Device → **GoldenNugget Mobile Helper**, plus a **GoldenNugget
Mobile** row on the home screen right under the feature tiles):

- One flow signs in with the Apple ID (GrandSlam auth with 2FA) and runs the
  free-provisioning dance, re-signs the GoldenNugget app for the device's team
  and installs it — powered by the new in-repo Rust engine **`gn-sideload`**
  (`tools/sideload-engine/`, built on `isideload`). No sideload tool to install
  by hand; Windows is supported (usbmuxd from Apple Devices/iTunes).
- The engine is driven as a QProcess over its stdout line protocol
  (`PROTOCOL` / `PROGRESS` / `STAGE` / `PROMPT …` / `RESULT`), so the dialog can
  open a modal for every prompt (2FA code choices, team and certificate
  selection) and stream progress. The Apple ID password rides
  `--password-stdin` — it never lands in the process list or on disk, and
  signing state persists in the platform keyring.
- After the install, the dialog vends the **pairing file** to the phone so
  GoldenNugget Mobile can talk to the desktop over the shared mobile device
  pairing record (delivered as UTF-8 XML plist into
  `Documents/pairingfile.mobiledevicepairing`, offered as a save-to-disk
  fallback when the app is not installed yet).
- Free-account limits are spelled out in the dialog (3 active apps, 2 certs,
  7-day profiles, Developer Mode on iOS 16+).
- A one-shot *"Did you know?"* pop-up mentions the mobile version when a phone
  connects — shown once per session, not during an apply/restore, and it can be
  dismissed permanently.

## Build & Security

- The frozen app now **bundles the `gn-sideload` engine on all platforms**:
  `compile.py` `--add-binary`s it into the PyInstaller bundle root, and every
  CI job builds the engine up front (Rust toolchain + cargo caches) and
  verifies it actually landed inside the packaged app.
- **Universal2 macOS builds require a universal engine** — `compile.py` refuses
  to proceed with a single-arch slice or none, the same failure style as the
  portable libusb check; `tools/build_sideload_engine.sh universal2`
  cross-compiles both darwin targets and `lipo`-merges them, and CI re-checks
  the bundled binary covers x86_64 AND arm64.
- **Dependabot security alerts on the `zip` crate cleared** (0 open): the
  critical zip-cloaking arbitrary-file-overwrite (GHSA-m665-v7pm-7grj /
  CVE-2026-115905) plus four advisories are fixed in `zip` 9.x, so the engine
  builds isideload from the one-line patch branch
  `GoldenNugget-Team/isideload@zip-9.1-security` until upstream releases it
  (PR nab138/isideload#31 tracks the same change upstream).
- The build script pins the rustup toolchain's bin ahead of PATH, so a
  MacPorts/Homebrew `rustc` earlier in PATH cannot shadow the rustup std for
  cross targets ("can't find crate for `core`").

## Fixes

- The home-screen mobile row opened its dialog through a `MainWindow` **call**
  (stored instance vs `window()` method) and crashed on the first click inside
  the overridden `mousePressEvent`; it now passes the stored instance.

### Also shipped in 9.7.3 (was released without changelog notes)

- Preference tweaks whose file had no backup baseline are delivered as new
  files instead of aborting the apply.
- Calendar Access timers stop on close and back off an already-destroyed
  timer instance.
- Retired feature-flag writers and saved selections removed; restore status
  navigation repaired; OTA daemon delivery decoupled from the MobileAsset
  preference; nested preferences preserved on reset.
- The packaged app ships as **GoldenNugget** instead of Nugget, and the
  experimental fast backup cache landed.

**Full Changelog**: https://github.com/GoldenNugget-Team/GoldenNugget/compare/9.7.2...9.7.4
