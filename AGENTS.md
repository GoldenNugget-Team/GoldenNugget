# GoldenNugget Async Operations

> Full codebase documentation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

This document describes the background threads, async backup/restore operations, and error handling used in GoldenNugget.

## Color Theme System (src/gui/theme/)

**The app has one dark palette; only the accent is a user choice.**

- `colors.py` — frozen dataclass `ThemeColors` and the single palette
  **`DARK`** (named slots: `bg_primary`, `bg_secondary`, `bg_tertiary`,
  `bg_input`, `bg_elevated`, `text_primary`, `text_secondary`, `accent`,
  `divider`, `error`, `success`, `warning`, `border`, `scrollbar`,
  `surface_hover`, `danger_text`, ...). `ACCENT_PRESETS` holds the 8 accent
  choices (blue/purple/pink/red/orange/yellow/green/teal). There is no light
  palette and no `color_mode` setting any more.
- `theme_manager.py` — `ColorThemeManager` singleton (`instance()`):
  `colors` (the `ThemeColors`), `set_accent(name)`, `set_custom_accent(value)`,
  `c(slot)` (color accessor), `build_palette()` (QPalette for native widgets),
  `accent_hex()`, `accent_rgb()`. Persisted via QSettings (`accent_color`,
  `liquid/custom_accent`). Emits `theme_changed` (no payload) on any color
  change.
- `accent_name` is the stable user choice; `accent_hex()` / `accent_rgb()`
  return its actual color. Native QPalette roles are applied for active,
  inactive and disabled widgets on every change.
- The app does not follow the OS theme. `set_system_theme()` and
  `apply_system_theme()` do not exist. `apply_to_app()` instead PINS Qt's
  colour scheme to dark (`QStyleHints.setColorScheme`, Qt 6.8+) so native title
  bars and system dialogs never switch with the OS, and its
  `colorSchemeChanged` handler only re-asserts dark (only the live singleton
  answers). Always go through `apply_to_app()`, never a bare
  `app.setPalette(...)`.
- `styles.py` — `STYLES` dict of Qt stylesheet templates using `{slot}` named
  placeholders (literal braces are doubled `{{`/`}}`).
- `accent_picker.py` — `AccentPicker` widget: row of circular preset buttons,
  self-connects to `theme_changed` to repaint its selection border.
- `__init__.py` — exports the above plus `t(style_key) -> str`.

### Styling contract (IMPORTANT)

- `t(key)` is the **only** way widgets read theme colors; it renders the
  template with the current palette **internally** (`format_map`). Callers must
  use `widget.setStyleSheet(t("key"))` and **must NOT** call `.format_map()`
  again on top of `t(...)` (double-formatting breaks on the `{{` escapes).
- Any widget/page that draws theme colors implements `_retheme(self)` which
  re-applies all its stylesheets from `ColorThemeManager.instance().colors`.
  It is called by `MainWindow._on_color_theme_changed` for every `ios_pages`
  entry (line 224 of `src/gui/main_window.py`) AND by self-connections.
- Reused components in `src/gui/ios/components.py` call
  `_auto_retheme(self)` from their `__init__` (defined at module level),
  which connects `ColorThemeManager.instance().theme_changed` to their
  `_retheme` — authoritative, one connection per instance. Child widgets
  created before `_auto_retheme(self)` must be registered by hand or use
  the shared `IOSNavBar`/`IOSSwitch`/etc. components which self-connect.
- The whole-window stylesheet is `t("global")`, applied in
  `MainWindow._apply_global_stylesheet`; it sets `QLabel color` via the
  `QWidget { color: {text_primary} }` rule, so bare labels inside styled
  rows pick up the theme without their own `_retheme`.
- **Raised surfaces need an explicit transparent background.** A `QLabel` that
  carries its own stylesheet is a styled-background widget, so Qt fills it with
  the palette window color — invisible on `bg_secondary` cards, but a dark box
  on a lighter surface (e.g. the Home tiles on `bg_tertiary`). Always add
  `background-color: transparent;` to such label styles.
- **Icons bigger than their viewBox**: use
  `theme_pixmap(resource, color, size, dpr)` (scales the SVG *before* tinting, so
  11x11/16x16 sources stay crisp) instead of `theme_icon()`, which rasterizes at
  the intrinsic size and would be blurry. The Home feature tiles
  (`src/gui/ios/home.py`) are the reference use: large icons on seven
  feature tiles in a responsive grid, name + muted subtitle underneath,
  `_TileCard._retheme` → `t("home_tile")`.
- **One font everywhere**: the bundled `Inter` variable font is
  registered in `main_app.py` (`QFontDatabase.addApplicationFont` +
  `app.setFont`) and its family is pinned by the `global` template via the
  `{font_family}` placeholder (rendered from `FONT_FAMILY` —
  `"Inter Variable"` — in `src/gui/theme/styles.py`). The
  `QWidget { font-family: ... }` rule overrides any Designer-hardcoded
  family (e.g. `.AppleSystemUIFont`) while per-widget `font-size`/
  `font-weight` still win. Do not add new `font-family` declarations — a
  single source of truth. The font files ONLY live at `src/qt/fonts/`
  (`InterVariable.ttf` + `InterVariable-Italic.ttf`; they ship into the
  frozen app via `--add-data=src/qt:src/qt`).
- `src/qt/mainwindow_ui.py` is generated from Qt Designer — do not edit;
  theme the chrome via `_apply_global_stylesheet` instead.
- **The preset popup is a child widget, never a window.** `PresetPopup`
  (`src/gui/ios/preset_menu.py`) parents itself to the main window and draws
  over it with `raise_()`. Do **not** turn it into a top-level `Qt.Popup` or
  `Qt.Tool`: a Popup relies on Qt's implicit mouse/keyboard grab, which not
  every platform plugin provides (when the grab fails it is silently dismissed
  right after `show()`), and *any* top-level window gets its own decorations
  and taskbar entry — which looks like a stray window instead of a list growing
  out of the button. Click-away/Escape still need the app-level `_DismissOnOutsideClick`
  filter, which builds its hit rect with `popup.mapToGlobal(QPoint(0, 0))` +
  `popup.size()` (a child widget has no frame, so `frameGeometry()` is wrong).
  The filter holds the popup through a `weakref` and swallows `RuntimeError`, so
  a popup whose window was destroyed (or interpreter shutdown) can never leave a
  dangling target.
- **Position a child panel in parent coordinates, never global.** `move()` is
  parent-relative, so `_panel_pos()` maps the anchor with
  `anchor.mapTo(parent, ...)` and clamps against `parent.rect()`. Computing the
  spot from `mapToGlobal` and handing it to `move()` offsets the panel by the
  window's frame (title bar + border). The panel is right-aligned to the button
  with a 6px gap and **always opens downwards** — it never flips upwards. When
  the button sits too low for the whole list, `_fit_below_anchor()` pins the
  scroll area to `setFixedHeight(...)` and resizes the frame explicitly
  (`adjustSize()` is not enough: a `QScrollArea`'s `sizeHint()` keeps reporting
  the full content height, so a `setMaximumHeight` cap alone never shrinks the
  panel). `show_popup()` clears that fixed height again on every open, or the
  panel stays short after the window grows. The popup also installs an event
  filter on the parent and closes on Resize/Move/WindowStateChange, otherwise
  it detaches from the button.
- **Never animate `pos` on a top-level window.** Doing so makes Qt hide and
  re-place it (and for a popup, dismiss it). `PresetPopup` slides an inner
  `_body` widget instead, with `SLIDE_PX` of extra top margin reserved as the
  travel room; the fade is a `QPropertyAnimation` on a `QGraphicsOpacityEffect`
  (a plain `QWidget` has no `opacity` property). A close request is ignored
  until that fade-out finishes — guarded by `_allow_close`, or the recursive
  `close()` from `_finish_close` starts a second fade and the window never
  closes.
- **TEMP: Classic UI removed** — `src/qt/mainwindow.ui` is deleted (the
  generated `mainwindow_ui.py` stays committed and keeps working at runtime),
  the Settings "iOS-style Interface" switch is hidden, `ThemeManager.load_theme`
  always returns `IOS`. The first-launch `InterfacePickerDialog` now chooses
  **Sidebar / Modern** within the modern pages, by setting `ui/show_sidebar`;
  `ui/interface_choice_done` records completion independently of `ui/theme`
  (which is saved during window construction). Restore the legacy chrome when Classic comes back:
  recreate `mainwindow.ui`, unhide the switch in `settings.py`, revert
  `load_theme` to read `ui/theme`. Keep the first-run sidebar choice separate
  from the legacy chrome mode.
- Old `src/gui/ios/theme_manager.py` (`CLASSIC`/`IOS`) is layout-only
  (Classic vs iOS-style chrome) and stays untouched side-by-side.
- Theme UI lives in Settings → **Appearance** (`src/gui/ios/settings.py`):
  "Accent Color" selects the accent via `set_accent(...)`. There is no
  light/dark selector and no light palette at all.
- The app does **not** follow the OS colour scheme: `main_app.py` calls
  `ColorThemeManager.apply_to_app(app)`, which applies the dark palette and
  pins the Qt colour scheme to dark; accent changes re-run it.

## HotLoad Safety Rules (src/controllers/hotload.py)

Remote safety rules (cached from
`hotload_rules.json`) that warn on / block dangerous or broken tweaks, and can
hide whole broken features. Behaviours per rule `action`:
- (default) — **block**: a flagged tweak is never applied (`rule_for` matched
  in `device_manager._apply_tweak_pass`) and enabling it shows a warning
  (`confirm_flagged` in the iOS tweaks/daemons/preset pages).
- `"kill_app"` — **kill switch**: the app refuses to start (or shuts itself
  down) on matching setups (`main_app._hotload_kill_or_none`).
- `"badNews"` — **mandatory update**: shows an application-modal update dialog
  for matching setups, from cached rules at startup and after a rules refresh
  or device change. No Later button, Escape or window-close dismissal; opening
  the download leaves the app blocked until it is restarted with an unaffected
  version. Optional `version` names the available release and `reason` explains
  the requirement. Scope with `app_versions` or `max_app_version` so the updated
  build is not blocked. Honours `hotload_enabled` like the other actions.
- `"hide_feature"` (`feature` field) — **hide a whole feature page**: the
  feature's tweaks are never applied, removed from the iOS UI
  (`_hidden_sections` in `src/gui/ios/tweaks.py`), its Sidebar button and iOS
  home card are hidden (`_apply_hidden_feature_gating` in
  `src/gui/main_window.py`), and presets refuse to load it
  (`_hidden_tweak_names` stripping in `preset_manager._apply`, plus the
  "Hidden Features Skipped" warning in `src/gui/ios/settings.py`).
- `"disable_daemon"` (`daemons` field: Daemon enum member names and/or raw
  launchd keys) — **force-disable specific daemons** on matching setups: the
  keys are always injected into the disabled-daemons plist at apply time no
  matter the UI toggles or a loaded preset
  (`_apply_hotload_daemon_forcing` in `device_manager.py`, called from
  `_apply_changes`; the forced keys are added to the daemons tweak's
  `allowed_keys` so they bypass the `INTERFACE_KEYS` whitelist, since a rule
  may name a daemon with no UI switch), and the daemons page locks those
  switches ON with a "Daemon Locked by Safety Rules" warning
  (`src/gui/ios/daemons.py`).
- `"risk"` (`tweak`, `level`: `low`/`medium`/`high`, `reason`) — **warn only**:
  never blocks or hides anything (`rule_for` skips these rules). Matching
  notes (`risk_notes()`) join the pre-apply risk verdict
  (`src/controllers/risk_assessment.py`) when that tweak is selected.

Feature → tweak membership lives in `FEATURE_TWEAKS` (Liquid Glass, Springboard,
Internal, PosterBoard, Daemons, Status Bar, Templates). `hidden_features()` /
`hidden_tweak_names()` / `feature_for()` resolve what is hidden for a given
device/model/app. All gating honours the kill switch (`hotload_enabled` pref);
when off, nothing is hidden or blocked.

## Preset Popup (src/gui/ios/preset_menu.py)

Tapping *Manage* on the home-screen preset banner opens `PresetPopup` instead of
navigating to Settings. The module is deliberately split in two:

- **Actions** — `load_preset_flow`, `save_preset_flow`, `delete_preset_flow`,
  `export_preset_flow`, `partial_export_preset_flow`, `import_preset_flow`,
  plus `daemon_compat_warning` and `preset_subtitle`. Each takes a preset
  **name** (never a list row) and owns its confirm/safety dialogs, so the
  Settings page (`IOSSettingsPage`, which resolves the name off
  `preset_list` via `_selected_preset_name`/`_require_selection`) and the popup
  share one implementation and cannot drift.
- **The panel** — `PresetPopup` is deliberately minimal: a `_PresetRow` list
  (name + `model • iOS` + tags, ✓ on the active preset) with a single footer row
  holding nothing but **Delete, pinned to the far right** (behind a stretch). A
  single click *selects* a preset, a **double click applies it** (which restarts
  the app, so it must not be a single click). It scrolls at `MAX_VISIBLE_ROWS`.
  The full toolkit (save / import / export / partial export) lives only on the
  Settings page — do not add it back to the popup.
- `_PresetRow` declares its own `doubleClicked` signal and emits it from
  `mouseDoubleClickEvent`: `QAbstractButton` has no `doubleClicked` in the
  pinned Qt version.
- `PresetWidget._on_manage_pressed` falls back to `on_manage` when
  `ios_style` is False (the classic page still navigates) or when no window is
  available to own the popup.

## GoldenNugget Mobile Helper (src/devicemanagement/mobile_helper.py + src/gui/dialogs/mobile_helper_dialog.py)

Settings → Device → **"GoldenNugget Mobile Helper"** sideloads the on-device
port (`GoldenNugget-Team/GoldenNugget-mobile`, bundle id
`com.awesomenull.goldennugget`) onto the connected iPhone and delivers its
pairing record:

- Device logic (`mobile_helper.py`) is the only consumer allowed to pair with a
  device whose record is not known yet — everything still goes through
  `lockdown_session`. `read_pairing_record()` returns the record **the host
  already holds** (no re-pair), `pairing_record_xml()` dumps it as an
  **XML plist**: the mobile app's importer (`PairingRecord.accept`) only parses
  UTF-8 text plists — a binary plist is silently refused there.
- Delivery rides `HouseArrestService` (`VendDocuments`): the record must land
  exactly at `Documents/pairingfile.mobiledevicepairing` (`AppPaths.pairingFile`
  on the app side) — filename and location are contract, not convenience.
  `AppNotInstalledError` is translated into a save-to-disk fallback, same
  `save_pairing` flow used by the explicit "Save to Disk…" action (the manual
  AirDrop route when the app is not installed yet).
- IPA installation goes through `InstallationProxyService.install_from_local`
  on a background async-loop QThread (pattern of `FetchAppsThread`) for
  **already-signed** IPAs. Latest-release downloads ride QtNetwork
  (icon-pack downloader pattern), and the downloaded temp IPA is deleted only
  when the install has finished (`_pending_ipa_path`).
- **The Apple-ID sign-and-sideload engine is `gn-sideload`**
  (`tools/sideload-engine/`, built on the Rust crate `isideload` from
  nab138/iloader — NOT xtool, which does not run on Windows). One run does:
  GrandSlam Apple-ID login → 2FA → free-provisioning Developer Services dance
  → re-sign the IPA → install; "Sign in with Apple ID && Sideload" then pushes
  the pairing file automatically. The dialog drives it as a QProcess using its
  **line protocol** on stdout (`PROTOCOL n` / `PROGRESS` / `STAGE` /
  `PROMPT PASSWORD|2FA <json>|TEAM <json>|CERTS <json>` / `RESULT OK|ERROR`) —
  a prompt engine in `_pump_engine` opens a modal for every `PROMPT` line and
  writes the answer to stdin (2FA accepts `d`/`r`/`p<id>`; team is a 1-based
  index; certs a comma list). The password rides `--password-stdin` after the
  `PROMPT PASSWORD` handshake so it never lands in the process list; it lives
  in memory only and is sent to Apple alone.
- **Engine discovery** is `find_engine()` in `mobile_helper.py`: settings
  override `mobile_helper/engine_path` → PATH → bundled (PyInstaller root) →
  `<repo>/tools/sideload-engine/target/release/`. When absent, the dialog
  offers "Build Engine (cargo)" (runs `cargo build --release` in the engine
  dir, cwd = `tools/sideload-engine`) and "Locate engine binary…" (verified
  with a quick `--version` probe before the override is saved). The frozen
  app bundles the engine: `compile.py` `--add-binary`s it on all platforms
  (a Universal2 mac build REFUSES a single-arch engine;
  `tools/build_sideload_engine.sh universal2` lipo-merges both slices — the
  CI workflow runs it before compile.py and re-checks the bundled binary;
  the script pins the rustup toolchain's bin ahead of PATH, since a
  MacPorts/Homebrew `rustc` earlier in PATH carries no rustup std for cross
  targets). Signing state
  persists in the platform keyring (service `goldennugget`), team/certificate
  prompts only re-appear when Apple's answers reset. Windows needs usbmuxd
  served by Apple Devices/iTunes; limit the UI copy to the free-account
  constraints (3 active apps, 2 certs, 7-day profiles, Developer Mode on
  iOS 16+).
- The mobile app reads the pairing file **at launch** — the dialog tells the
  user to send it while the app is closed and reopen it afterwards.
- **Device quirks (both hit live in the field):**
  - the engine's free provisioning renames the bundle id at signing time to
    `com.awesomenull.goldennugget.<TEAM_ID>` (e.g. `…goldennugget.R56X75AKLF`);
    installation checks and house_arrest vends must match by PREFIX (`_match_mobile_app`
    in `mobile_helper.py`), an exact-equality lookup reports "not installed";
  - `VendDocuments` on this app serves a dead AFC root (every op fails with
    status 10) even when `Documents` exists — vend the WHOLE container
    (`VendContainer`) and write to `Documents/pairingfile.mobiledevicepairing`
    from the container root instead (`send_pairing_to_app`).

## Tweak Registry (src/tweaks/registry.py)

Single source of truth for every plist-based tweak: id, section, title,
plist location, key, default value, UI kind (switch/text/number).
- `tweak_loader.load_plist_tweaks()` builds the runtime instances from the
  registry (daemons stay hand-defined there).
- The iOS tweaks page (`src/gui/ios/tweaks.py`) renders its sections straight
  from `SPECS_BY_SECTION` — adding a tweak means adding one registry entry.
- Sections are **collapsible**: each is an `IOSCollapsibleSection`
  (`src/gui/ios/components.py`, header + `body_layout` the tweak cards are
  added to) whose collapsed state is persisted per section name in
  `tweaks_collapsed_sections` (comma-separated, `Settings("settings")`) so a
  rebuild (device change) or a restart restores it.
- Titles are marked with `QT_TRANSLATE_NOOP("Nugget", ...)` at
  definition time (so pyside6-lupdate sees them) and evaluated with
  `QCoreApplication.translate("Nugget", ...)` at render time in
  `src/gui/ios/tweaks.py`; keep `src/tweaks/registry.py` in the
  pyside6-lupdate file list so new strings reach the translators.
- Device compatibility (min iOS version, iPad/iPhone-only) is part of the
  spec (`min_version` / `iphone_only` / `ipad_only`);
  `src/gui/ios/compat.py` only evaluates it.

## Lockdown Sessions (src/devicemanagement/session.py)

`lockdown_session(serial)` is the one way to open a lockdown connection:
an async context manager that always closes safely (a rebooted device makes
`close()` raise ConnectionTerminatedError, which must never mask the real
result). Do not call `create_using_usbmux` directly in new code.

## Thread Workers (src/gui/thread_workers/)

### PBDBThread
**File**: `src/gui/thread_workers/pb_worker.py`
- **Purpose**: Generic background thread for backup-driven operations (PosterBoard database, etc.)
- **Signals**: `progress` (float), `infoLbl` (str), `alert` (object). There is **no declared `finished`** — callers use the inherited `QThread.finished`.
- Used by the PosterBoard "Fetch Database File" wizard (`PosterBoardDBWizard`)

## Apply / Reset Flow (src/devicemanagement/device_manager.py)

### `_apply_changes()`
Main entry point for applying tweaks. Order:
1. `_raise_if_unsupported()` — hard-block iOS < 26.2
2. `_prepare_protective_backup()` — Phase 0, **iOS 27+ only** (no Phase 0 on iOS 26): builds the protective backup that Phase 3 will restore. Default (cache OFF): a **live** `perform_protective_backup()` fresh every apply, **always carrying the PosterBoard container when wallpapers are pending** (`include_posterboard`) so the extracted DB is never stale. With the experimental cache ON: incremental refresh of the cached master; the "reuse as-is" fast path never applies when wallpapers are pending, so the extracted DB is still always fresh. Returns (PreparedBackup, posterboard_db_ok); (None, False) only when there is no UDID. It is a thin wrapper that ends in `_require_media_copy()` — when the AFC media channel carried the photos, the apply refuses to continue (device still intact) unless the media store is **verified** complete; see the AFC media store section below
3. PosterBoard DB delivery:
   - **iOS 26.x (no Phase 0):** a **targeted PosterBoard-only backup**
     (`targeted_posterboard_database_backup` in `src/restore/posterboard_backup.py`)
     pulls ONLY the `AppDomain-com.apple.PosterBoard` container — everything
     else the device uploads is drained mid-stream, never written to disk — and
     hands back a WAL-merged copy of the sqlite. This replaces the old "full
     Phase 0 as a delivery vehicle" and the legacy full-device fallback.
   - **iOS 27+:** the sqlite normally rides the Phase 0 backup; when it could
     not be read out of it (device rejected container inclusion / encrypted
     backup), the same targeted backup runs as the fallback and stores the
     extracted DB at `<AppData>/PosterBoard/<udid>.sqlite3`.
   - Both are skipped if `GOLDENNUGGET_SKIP_PB_BACKUP=1`.
4. `_apply_tweak_pass()` — generate all tweak files, handle backup encryption, then `start_restore(prepared_backup_root=...)`

### Protective Backup Cache (src/restore/protective_cache.py)
`ProtectiveBackupCache` keeps a per-device master copy of the protective
backup in the persistent app-data store
(`<AppData>/GoldenNugget/backup_cache/master/<udid>`):
- **Storage location is configurable** — Settings → Backup →
  "Backup/Cache Location" (`backup_storage_dir` in the `Settings("settings")`
  QSettings store; env override `GOLDENNUGGET_BACKUP_DIR` for headless tools
  like `restore_cache.py`). `src/restore/storage.py` is the single source of
  truth: `cache_base()` (backup_cache), `protective_base()` (live backup
  runs), `posterboard_dir()` and `legacy_backups_dir()` all derive from the
  same root so a small system drive (e.g. a 28 GB `C:`) can be relieved by
  pointing them at e.g. `D:\GoldenNugget\`. Unset → the historical
  `<AppData>/GoldenNugget/...` (backup_cache/protective) and
  `<AppData>/PosterBoard|Backups` locations, byte-for-byte. The recovery
  tools (`apply_worker.py`, `restore_cache.py`) also search the legacy
  AppData `backup_cache` as a read-only fallback when a custom location is
  set (migration/recovery of pre-existing caches).
- **EXPERIMENTAL, ON BY DEFAULT** — the cache engages unless the user turns
  off "Use Fast Backup Cache (Experimental)" in Settings
  (`pref.use_backup_cache`). Cache off → the classic live
  `perform_protective_backup()` / `_backup_posterboard_database()` path runs.
  Kill switch still hard-disables it:
  `GOLDENNUGGET_NO_BACKUP_CACHE=1`.
- **AFC media store** — the bulk photo trees (DCIM, PhotoStreamsData) ride a
  persistent per-device mirror at `<AppData>/GoldenNugget/backup_cache/media/<udid>`
  (`ProtectiveBackupCache.media_dir`, OUTSIDE `master_root` so working copies
  and the manifest prune never touch it), pulled over AFC by
  `backup_media_via_afc(diff=True)` — only objects that are new/changed on the
  device are pulled (size-compared; missing local files are pulled, extra local
  files are never deleted since the store is the only photo copy after a wipe).
  This is the same channel the LIVE path uses, so the media type is identical;
  `GOLDENNUGGET_NO_AFC_MEDIA=1` makes the cache carry photos on the
  mobilebackup2 rows instead.
- **AFC media completeness marker** (data-loss guard — a media store is NOT
  proven by having files in it). Because the store is the only copy of the
  photos between the wipe and Phase 5, "is the directory non-empty" was
  catastrophic: a cancelled/interrupted pull leaves a partial tree, and the
  prune then deleted the backup's own media rows. `backup_media_via_afc` now
  writes `.media_state.json` (`MEDIA_STATE_FILE`) into the store **only** after a
  pull that finished with zero failed files, recording the device-side
  `files`/`bytes`; it is removed before a pull starts and on ANY failure or
  cancellation (`except BaseException`, so a cancelled parallel task counts).
  Everything that could drop the media trees from the backup must gate on
  `media_store_verified(root)` (`src/restore/afc_media.py`) — marker present +
  `complete` + the tree still holds at least what the pull recorded (extra local
  files are fine, they are never deleted). Never reintroduce a
  `isdir() and any(iterdir())` / `os.listdir()` completeness test:
  - `DeviceManager._prepare_protective_backup` is a thin wrapper around
    `_build_protective_backup` and ends in `_require_media_copy(prepared)`,
    which raises `NuggetException` when a backup that excludes the media trees
    has no verified store — the apply stops while the device is still intact.
    The wrapper exists so none of the many return paths can bypass the gate.
  - the cache fast path's `media_ready` uses the marker too, so a partial store
    forces a refresh instead of being reused as-is.
  - `clean_backup_for_restore(exclude_afc_media_trees=media_store_verified(...))`
    keeps the media rows in the manifest when the store is unverified, so the
    restore fails loudly on a missing payload instead of losing the library.
  - Phase 5 and `apply_worker` push whatever store exists (that is the rescue
    path and `restore_cache.py` relies on it), but raise instead of reporting
    success when the store is missing/empty or any file failed to land.
  - `_pull_one` writes through `<file>.part` + `os.replace()` and validates the
    result against `st_size`: a premature EOF used to leave a truncated file
    that the size-based diff then accepted, which is how videos ended up
    unplayable (a truncated MP4/MOV still shows in Photos but its `moov` atom is
    at the tail). `_push_one` `stat`s streamed writes to catch a short write on
    the device. `.media_state.json` and `*.part` are never pushed to the device.
  - Offline regression suite: `tools/test_afc_media_safety.py`.
- The pre-apply summary in `main_window_mixins._confirm_apply_summary` shows a
  "Backup cache from: <date>" line (via `peek_cache_info`, best-effort, no
  device session) and — when the cache is enabled — an **"Update Cache"**
  button (`IOSSummaryDialog.extra_button`, result `2` →
  `_SUMMARY_UPDATE_CACHE`). Picking it runs `device_manager.refresh_backup_cache`
  on a `CacheUpdateThread` (modal `QProgressDialog`) and re-opens the summary
  with the fresh date; confirming proceeds with the refreshed cache.
- The master's Manifest.db stays FULL (rows for mid-stream-drained payloads
  remain), so `perform_protective_backup(incremental_ok=True)` runs a true
  incremental refresh — repeat applies upload only what changed on the device.
- Snapshot-probe tolerance: during an incremental refresh the device enumerates
  the prior backup's `Snapshot` payload directory (`DLContentsOfDirectory`),
  which does not exist in the cache layout (payloads sit directly under
  `<udid>/<xx>/<fileid>`). Upstream pymobiledevice3's handler crashes on
  `iterdir()` for a missing dir. A runtime shim in `src/restore/protective.py`
  (`_install_device_link_contents_shim`) answers a missing enumeration target
  with an empty listing (Apple's host behaviour), so the device treats the
  probe as "nothing to diff" and proceeds with a safe full rebuild instead of
  aborting the apply.
- The master is IMMUTABLE. An apply never prunes, tweak-injects into, or
  moves it. Instead it builds a disposable **restore view** under
  `<base>/view/<udid>` (`make_restore_view`): the metadata files
  (Manifest.db/.plist, Status.plist, Info.plist) are real-copied — pruning
  rewrites Manifest.db and a hardlink would corrupt the master — and the
  payloads are hardlinked (near-instant, size-free; a copy fallback covers a
  cross-device destination). The view is pruned + tweak-injected and restored
  from, then dropped (`discard_restore_view`); dropping it frees directory
  entries without touching a byte of payload data. The view root sits on the
  SAME filesystem as the master on purpose, so the hardlinks stay links
  instead of degrading into full copies.
  Consequences: the master keeps its FULL manifest forever (which is exactly
  what `perform_protective_backup(incremental_ok=True)` diffs against), a
  crashed apply can no longer leave the master half-pruned, and the old
  snapshot/regenerate cycle (and its self-heal path) is gone. A fresh
  Phase-0 live backup is still pruned **in place** in the restore (no copy at
  all — it is disposable, and a copy could spill onto another volume and
  OSError with ENOSPC); the retained run IS that pruned backup.
  (`make_protective_working_copy` still exists for the manual restore tools
  `restore_cache.py` / `apply_worker.py`, which never touch the master.)
- Freshness is tracked **per part**, not per cache:
  - `CACHE_REFRESH_SECS` (default 1800s) — how long the master stays
    usable without a device session.
  - `CACHE_MEDIA_REFRESH_SECS` (default 21600s) — how long the AFC photo
    store stays usable. Photos change far less often than preferences, and
    re-pulling the whole media tree on every apply was the second-largest
    cost after the Phase 5 push. When the master is still fresh but the photo
    store has aged out, only the photos are re-pulled
    (`ProtectiveBackupCache.refresh_media`, a diff — just the new objects
    transfer) instead of forcing a full master refresh.
  - The photo store's age is recorded separately in the cache's info JSON
    (`media_ts` vs `created_ts`), so a refresh that did not touch the photos
    does not reset their clock.
- PosterBoard work does **not** force a master refresh. The wallpaper
  database only needs the PosterBoard container, and the targeted
  PosterBoard-only backup pulls exactly that (everything else the device
  offers is drained mid-stream). The cache fast path therefore returns
  `pb_from_cache=False` — the caller then fetches a fresh database through
  the targeted channel instead of re-uploading the whole protective scope.
  Forcing a refresh for it was the main reason the cache felt useless:
  every wallpaper apply re-read the entire backup.
- Phase 5 pushes only what the device lacks: `restore_media_via_afc` diffs
  the store against the device's current AFC media tree (same size rule the
  pull side uses) and transfers only missing or size-mismatched files. A
  device that cannot list its media tree falls back to pushing everything —
  never to skipping. The explicit recovery restores ("Restore Data From
  Backup" / `restore_cache.py`) pass `diff=False`: there the store's copy
  must win over whatever the device holds, even at the same size.
- Per-phase timings are logged by `_restore_ios27` ("Phase timing — …"),
  because without them the dominant cost of an apply was invisible — which is
  exactly why the cache looked like it did nothing.
- Invalidated by UDID/iOS-version change. The master ALWAYS lives in the
  persistent store (never temp): it is the only copy of user data between
  Phase 2 (device wipe) and Phase 3 (restore), so a temp placement would
  permanently lose it on a reboot. The legacy temp-based base is still
  searched by `locate()` for migration of pre-existing caches.
- PosterBoard DB: kept mid-stream into the master when wallpapers are applied
  (`include_posterboard`; container included via a stock-format factory-info
  entry — verified working on iOS 27 db5) and extracted after the refresh
  (`extract_posterboard_db`); pruned from the restore copy so Phase 3 never
  clobbers the tweaked DB from Phase 2. The DB is resolved by FILE NAME —
  the store dir's structure version (61, 62, ...) varies between iOS
  releases and its name is not even present in some iOS 27.x upload paths
  (confirmed by the macOS bug report on iOS 27.0 build 24A435), so both the
  manifest query and the mid-stream filter match on the database filename
  `PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3` alone. The on-device DB runs in WAL mode: `-wal` is extracted and folded
  into one consolidated database via the SQLite online-backup API (the `-shm`
  is NEVER copied — a stale shm desyncs against the wal and is a classic
  source of "database disk image is malformed"); on failure it degrades to
  the plain main file. If anything in this chain fails, the apply degrades
  to the legacy separate `_backup_posterboard_database` instead of aborting.
- Stale-journal protection: every `PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3`
  injection (sparse OR Phase 3) ships 0-byte `-wal`/`-shm` companions
  (`posterboard_tweak.py`), so the device never replays old WAL frames over
  the freshly restored database — a top cause of "PosterBoard breaks after
  loading wallpapers".
- New-wallpaper inserts in `pb_config_manager.update_sqlite` allocate
  `posterId` ABOVE `MAX(posterId)` (not `sqlite_sequence.seq + 1`, which can
  collide after row deletions and corrupt the on-device database).
- Prune self-heal: kept rows must have payloads when flags=1 (a missing one
  aborts Phase 3 with MBErrorDomain/205); directory rows (flags=2) are kept
  unconditionally — dropping them causes renameatx ENOENT during restore.
  `verify_backup_payloads()` logs leftovers before Phase 3.
- Encrypted backups: supported when the user provides the backup password
  (prompted in `_prepare_protective_backup`; reused later for the Phase 3
  restore). The manifest is decrypted only locally on the pruned working
  copy (`clean_backup_for_restore` / `inject_file_into_backup` take a
  `manifest_password`). Without a password — or when the encryption state
  flips vs. what the master was built with — the cache is bypassed.
  Caveat: injected tweak payloads stay plaintext inside an otherwise
  device-encrypted backup, so injection is **always skipped** for encrypted
  backups (a decrypt mismatch would fail the restore). Also, encrypted +
  `needs_posterboard` forces the legacy separate PB backup
  (`(PreparedBackup, False)`).
  Kill switch: `GOLDENNUGGET_NO_BACKUP_CACHE=1`.

### `_apply_tweak_pass()`
- Generates every tweak's files in a single pass and restores them together
- iOS 27+: prompts for backup password if encryption is enabled (`use_encrypted_backup` pref)
- Writes a `.GlobalPreferences.plist` copy to the HomeDomain path
  (`FileLocation.globalPreferencesHomeDomain`) so user
  region/language/appearance survive the iOS 27 wipe. Note: this copy is **not
  merged** with the device's current file — it is written verbatim from the
  bundled base plist.
- Calls `start_restore(prepared_backup_root=...)` internally

### `start_restore()`
- Entry point for all restores (apply and reset)
- Opens a lockdown connection and delegates to `restore_files()`
- Passes `backup_password` for encrypted backups and `prepared_backup_root` down to the three-phase restore

### `_reset_tweaks()`
- Reset flow: `_raise_if_unsupported()` → build reset files → `start_restore()`
- **No original-plist capture.** The device's own plists are NOT pulled before
  the reset; stock values are written straight to the device on every iOS
  version. The old iOS-27-only capture (`psysbackup`, module
  `src/restore/original_plist.py`) is gone — it cost a full selective backup
  plus a lockdown session and did not buy anything: the managed-preferences
  copy the tweaks write to already holds the *tweaked* values, so restoring a
  captured "original" re-wrote the very tweaks the user asked to remove. A
  reset therefore discards any non-Nugget customisation in those plists.
- Plist reset targets for Springboard, Liquid Glass and Internal come from
  the tweak registry, alongside legacy targets. Liquid Glass is offered in
  the reset picker. Shared plist files reset together; opaque Siri AI archives
  use the separate Reset Siri AI Overrides tweak.
- What each `files_to_null` entry is written as:
  - **All supported versions (26.2+)** → `plistlib.dumps({})` (a valid but empty plist).
  - **Never** write a zero-byte plist on iOS 26.2+: a truncated
    `com.apple.springboard.plist` crashes SpringBoard at boot and sends the
    device into a boot loop. An empty dict parses and falls back to defaults.
- **Managed-pref tweaks live in TWO files.** mcxd copies every managed
  preference into the target app's own cfprefs domain on disk, so an applied
  tweak is visible both in `/var/Managed Preferences/mobile/<domain>.plist`
  (which Nugget owns) and in
  `/var/mobile/Library/Preferences/<domain>.plist` (where the merged value
  stays behind as an ordinary preference once the managed entry is gone).
  Emptying only the managed file therefore left the value in the mirror,
  where nothing manages it any more — this is what kept the Dynamic Island
  hidden after a reset. Two rules follow, both driven by
  `managed_pref_app_plists()` / `managed_pref_target()` in
  `src/tweaks/registry.py` (add a managed-pref target to the registry and
  both rules follow automatically):
  - the reset writes the mirror too (`{}` on all supported versions, owner 501) — never a
    zero-byte app plist, that is the boot-loop input above;
  - the mirrors are excluded from the protective backup
    (`_SKIP_APP_PREF_FILES` in `src/restore/protective.py`), because Phase 3
    restores that scope AFTER the sparse reset and handed the stale value
    straight back. Same reasoning as `statusBarOverrides` /
    `.GlobalPreferences.plist`.

## Restore Module (src/restore/)

### `restore_files()`
- Main restore orchestration
- Builds a `backup.Backup` object from the `FileToRestore` list
- Always delegates to `_restore_ios27()` (six-phase) — all supported devices (26.2+) go through this path

### `_restore_ios27()` — Six-Phase Restore
> The code executes **six** phases; the older docs summarised it as three, but
> Phase 3 ends at 90% and the last 10% belongs to a reboot-before-skip, the
> setup skip and a final reboot.

**Phase 1 (0-40%)**: Protective Backup
- With `prepared_backup_root` (cached master -> snapshotted, then pruned + tweak-injected **in place** and used as the restore source; fresh Phase-0 live backup -> pruned in place, no copy): no device backup runs here. Without it: `perform_protective_backup()` runs live. With `skip_protective_backup`: the phase is skipped entirely (user opted out on low disk space)
- Otherwise: `perform_protective_backup()` — selective backup of photos, Apple ID, settings
- `clean_backup_for_restore()` — prunes manifest to protective files only
- Injects ALL the apply's tweak files (`inject_files` from `restore_files`) into
  the pruned manifest when the prepared backup is unencrypted
  (`inject_all` in `restore_files`, plaintext injection) — the sparse pass
  (Phase 2) then has nothing left to deliver. Encrypted prepared backups can't
  hold plaintext-injected rows (per-file wrapped keys → MBErrorDomain/205), so
  on those the tweaks still ride the sparse pass; PosterBoard-only edge cases
  keep injecting just the AppDomain rows.
- **Preference baselines** (`_prepare_preference_merges` in `src/restore/inject.py`):
  every preference tweak (`is_preference_file` targets) is MERGED onto the
  device's current file from the backup. A file with NO manifest row does not
  exist on the device — the protective capture keeps every preference file in
  these domains — so the tweak payload is delivered as a NEW file (recorded in
  `preference_baseline_creates` and listed in the apply summary), never an
  apply abort (Commit 399853a's hard ValueError broke applies on any device
  without e.g. `com.apple.backboardd.plist` managed policy — do not reinstate).
  Preference resets (`PreferenceKeyReset`) against a missing row are skipped
  (nothing to reset, recorded in `preference_baseline_skips`); a
  FeatureFlags/Global.plist RESET still raises `FeatureFlagBaselineUnavailable`
  with its explicit instruction; rows that EXIST but have a missing payload or
  unreadable content still abort the injection loudly (the file may hold the
  user's baseline that a patch-only file would clobber).

**Phase 2 (40-60%)**: Sparse Restore — **no reboot** (default, merged phases)
- `perform_restore()` applies tweaks via sparse restore with `reboot=not merge_phases`; if it drops at 0% it waits 25 s and retries once on a fresh connection.
- **Default (`merge_phases=True`, merged phases)**: the device is NOT rebooted
  after the sparse restore, so it never enters the iOS 27 "safe state recovery"
  and never wipes. The Phase 3 protective restore then lands on the
  still-live device in the same session — the same delivery the
  PosterBoard-only path already used (to iOS it looks like a normal full
  restore, not a tamper). One session, no 20-minute wait, no data wipe.
- **`GOLDENNUGGET_NO_MERGE_PHASES=1`** restores the classic flow: sparse
  restore → reboot → "safe state recovery" wipe → reconnect → restore.
- **Skipped when everything is injected**: on an unencrypted prepared backup
  `restore_files()` diverts every payload to `inject_files`, drops the
  incidental iOS 27 scaffolding files (HomeDomain `.GlobalPreferences.plist`
  copy + skip-setup plists — `_is_ios27_scaffolding`), and Phase 2 sees an
  empty sparse list, so the protective restore (Phase 3) delivers the tweaks
  right after Phase 1 — no partial restore, no wipe.
- **Skipped for unchanged tweaks + new wallpapers**: the apply record in
  `lastapply.json` (`src/restore/lastapply.py`, per-UDID under the persistent
  app-data store) holds the sha1 signature of the last successfully applied
  sparse payload. When the freshly generated sparse signature matches it AND
  wallpapers are pending (`inject_files` non-empty), Phase 2 is skipped the
  same way — the device already carries the (unchanged) tweak files and Phase
  3 delivers the wallpapers. The record is written after every successful
  apply and cleared after a reset; `sparse_signature` excludes PosterBoard
  AppDomain files and the iOS 27 scaffolding, so only real tweak content is
  compared.

**Phase 3 (60-90%)**: Protective Restore
- Merged mode (default): reuses the SAME live `lockdown_client` from Phase 2 —
  no reconnect, no `_wait_for_device`. If the device still rebooted itself
  (a tweak that demands the security recovery), the dead session is caught
  (`ConnectionTerminatedError`/`OSError`/`TimeoutError`), it falls back to
  the classic reconnect path below, and the apply continues.
- Classic mode (`GOLDENNUGGET_NO_MERGE_PHASES=1`): `_wait_for_device()` —
  reconnects after reboot (default 20 min timeout). On
  timeout it no longer aborts the restore outright: if the caller passed a
  `prompt_choice` callback (apply/reset from the GUI do), it shows an
  **Abort/Resume** pop-up ("device too long without unlock after the security
  recovery"), and **Resume restarts a fresh waiting cycle** instead of killing
  the restore. Without the callback the classic `DeviceNotFoundError` is raised.
  The pop-up text distinguishes between the device "keeps asking for passcode"
  case (`PasswordRequiredError` seen during the cycle) and a plain no-show.
- `_restore_protective_backup()` — restores the Phase 1 backup, with password if encrypted; retries **18 times at fixed 3 s**, only for `_is_transient_restore_error` results

**Phase 4 (90-95%)**: `reboot_device()` — **before** the media restore and
  setup skip, so `restore_media_via_afc()` and `skip_all_setup27` run on a
  freshly-booted device (Phase 5). A merged still-live session would
  otherwise already carry a cloud configuration and only raise
  `CloudConfigurationAlreadyPresentError`.

**Phase 5 (95-98%)**: `_wait_for_device()` reconnects (only after a Phase 4
  reboot; the reused live session is closed first), then
  `restore_media_via_afc()` pushes the AFC-pulled photos/videos back (media
  travels only on that channel — it was excluded from the backup), then
  `skip_all_setup27()` — runs whenever skip-setup is requested, on every
  apply including the Phase 2-skipped ones (PosterBoard-only / unchanged
  tweaks + added wallpapers). The media push is the rescue path, so it runs on
  whatever store exists, but it **raises** instead of reporting success when
  the store is missing/empty or any file failed to land (the pre-apply
  `_require_media_copy` gate is what should have prevented the wipe). When the
  device was never wiped it
  typically already carries a cloud configuration and
  `SetCloudConfiguration` raises `CloudConfigurationAlreadyPresentError`,
  which is caught and treated as success (setup already handled) instead of
  aborting the apply.

**Phase 6 (98-100%)**: `reboot_device()` — only when auto-reboot is on, so
  the skipped setup takes effect on the next boot.

### `perform_protective_backup()` (src/restore/protective.py)
- Creates a selective device backup via mobilebackup2. The module keeps the
  whole live-backup pipeline (`perform_protective_backup`,
  `make_protective_working_copy`, `prune_protective_backups`,
  `clean_backup_for_restore`); the injection helpers live in
  `src/restore/inject.py` and the cache in `src/restore/protective_cache.py`
  (both re-exported from `protective.py`).
- Filters: keeps HomeDomain (Accounts, ConfigurationProfiles, Preferences, SpringBoard, ControlCenter, Shortcuts, WebClips — including each `.webclip/Storage` PWA payload — plus WebApp and WebKit/WebsiteData web-app data) and AddressBook (contacts: `Library/AddressBook/AddressBook.sqlitedb` + `-wal`/`-shm`, `AddressBookImages.sqlitedb`), CameraRoll/Media (photos), MessagesDomain (iMessage/SMS/MMS), SystemPreferencesDomain
- Skips: AppDomain-* containers (empty `Applications` in factory info), KeychainDomain
- Encryption: uses existing encryption if enabled, otherwise unencrypted
- Connection handling: the only retry is `ProtectiveBackupService.connect()`
  with **5 attempts** (backoff 2s, 4s, 8s, 15s); `perform_protective_backup`
  itself has no retry loop

### Live backup retention (src/restore/protective.py)
- `prune_protective_backups()` keeps the newest `PROTECTIVE_KEEP_RUNS=1` run and
  deletes every older run outright (no age guard, no payload dedupe).

### `clean_backup_for_restore()` (src/restore/protective.py)
- Prunes Manifest.db to protective files only (temp-table keep-set, single DELETE)
- Removes orphaned payload files
- Skipped for encrypted backups (device handles it)

### `_restore_protective_backup()` (src/restore/restore.py)
- Restores the pruned backup after the security recovery
- Retries up to **18 times, fixed 3s between attempts** (`max_retries = 18`), and
  only for results matching `_is_transient_restore_error` (SpringBoard /
  mobilebackup2 startup delay)
- Accepts `backup_password` for encrypted backups

## PosterBoard Backup (src/gui/dialogs/pb_dialog.py)

- PosterBoard fetch/rebuild scratch backups live under `posterboard_dir()/.work/`
  on the configured backup volume, with a local free-space preflight. Both use
  `ProtectiveBackupService(include_posterboard=True)`. A host disk-space failure
  raises `BackupDiskSpaceError` and stops apply with its original message.
- A DeviceLink purge request is not a final failure: respond with status -1,
  `DLPurgeDiskSpace failed to purge`, zero reclaimed bytes, and wait for the
  device verdict. Never fabricate available bytes or delete user files.
  A subsequent error 105 is surfaced with the destination and available space.
  Regression suite: `tools/test_posterboard_backup_space.py`.

### `targeted_posterboard_database_backup` (wizard channel)
- The "Fetch Database File" wizard (`PosterBoardDBWizard`) backs up ONLY the
  PosterBoard container via `targeted_posterboard_database_backup` in
  `src/restore/posterboard_backup.py` — no full-device backup, nothing extra
  written to disk (mid-stream drain), result is a WAL-merged sqlite at
  `<AppData>/PosterBoard/<udid>.sqlite3`, identical to the apply path.
- Retry logic: 3 attempts, backoff `min(2**attempt, 15)`s (2s, 4s) for connection errors
- Validates the extracted database before handing it to `update_database_file`

### `backup_posterboard_database()` (legacy)
- Backs up the whole device and extracts the PosterBoard SQLite database.
  Full-device backup; only kept as a fallback (whole-device backup is what
  used to make the wizard fail with "Backup Failed!", especially on macOS).

## Error Handling

### Device Lock Detection
- `is_device_locked_error()` — detects explicit device-lock messages,
  lockdown password/passcode-required errors, or code 208 (`ErrorCode` /
  `MBErrorDomain/208`), never an unrelated `MBErrorDomain` error (defined **once** in
  `src/exceptions/device_errors.py`; imported/aliased locally as
  `_is_device_locked_error` in `device_manager.py`, `protective.py`,
  `pb_dialog.py`)
- Used in: `backup_posterboard_database()`, `perform_protective_backup()`, `_backup_posterboard_database()`
- User message: "Device locked - unlock and keep awake"

### Connection Error Detection
- `is_connection_error()` — detects ConnectionTerminatedError, ConnectionError,
  OSError, asyncio.TimeoutError by `isinstance`, plus lowercase substring
  heuristics ("connection", "incomplete", "terminated") — same single
  definition in `device_errors.py`
- Retry logic: 3 attempts with backoff `min(2**attempt, 15)`s — actual delays are 2s and 4s
- Used in all backup/restore operations

### Global Crash Handler (src/exceptions/crash_handler.py)
- `install_crash_handler()` sets `sys.excepthook` (plus a `sys.unraisablehook`
  fallback) and is called once at `main_app` import, before the window is built.
- `CrashHandlerApp` is a `QApplication` subclass whose `notify()` routes
  exceptions raised inside Qt event handlers/slots to the same handler —
  PySide6 would otherwise print and drop them.
- On an uncaught exception it shows a `CrashDialog` with a **"Copy Error"**
  button (copies the full traceback to the clipboard) and a **"Continue"**
  button that dismisses the dialog and lets the session keep running (no
  data-loss exit). `KeyboardInterrupt` is still allowed to exit normally.
- Never raises: the crash handler safely falls back to stderr if no
  `QApplication` exists yet.

### Backup Encryption Handling
- Checks `get_will_encrypt()` before operations — but only ONCE per apply on the
  normal path: Phase 0's backup establishes the state, `_apply_tweak_pass`
  reuses `_known_backup_encryption` instead of opening a second lockdown
  session, and `perform_protective_backup` auto-resolves `include_keychain`
  from the same query unless it is pinned explicitly.
- iOS 27+ apply: prompts for password via QInputDialog if encryption is enabled and `use_encrypted_backup` is set
- Phase 3 passes the password to `mb.restore(password=backup_password)`

## Async/Await Patterns

All device communication uses async/await with pymobiledevice3:
- `create_using_usbmux()` — Lockdown connection
- `Mobilebackup2Service` — Backup/restore operations
- `AfcService` — File system access
- `InstallationProxyService` — App info
- `MobileConfigService` — Profile management

## Progress Reporting

Progress callbacks pass through the call chain:
```
update_label (UI)
  → _backup_progress() / progress_callback
  → perform_protective_backup() / backup_posterboard_database()
  → mb.backup() / mb.restore() progress callbacks
```

## Key Retry Configurations

| Operation | Max Retries | Backoff | Errors Handled |
|-----------|-------------|---------|----------------|
| Protective Backup connect | 5 | 2s, 4s, 8s, 15s | Connection |
| PosterBoard Backup | 3 | 2s, 4s | Connection, Device Locked |
| Phase 2 Sparse Restore | 2 | 25s once (if drop at 0%) | Transient |
| Phase 3 Restore | 18 | 3s fixed | Transient (service not ready) |
| InstallationProxy (AppDomain) | 3 | 2s, 4s, 8s | Any Exception |

## Data Flow Summary

```
User clicks "Apply Tweaks"
    |
_apply_changes()
    |_ _raise_if_unsupported()
    |_ [iOS 27+ only] _prepare_protective_backup()   [Phase 0: live backup (default) or cached master refresh]
    |     |_ cache OFF (default) -> fresh live perform_protective_backup()
    |     |_ cache ON (experimental) -> incremental master refresh; "reuse as-is" fast path only when NOT needs_posterboard;
    |     |     AFC media store kept in diff-sync over AFC (media/<udid>); pre-apply summary can force a refresh ("Update Cache")
    |     |_ wallpapers applied? -> include PosterBoard container in the backup + extract fresh DB after
    |_ targeted_posterboard_database_backup()        [iOS 26: the delivery channel, no Phase 0]
    |     |_ only the AppDomain-com.apple.PosterBoard container; everything else drained mid-stream
    |     |_ extract WAL-merged sqlite -> <AppData>/PosterBoard/<udid>.sqlite3
    |     |_ iOS 27+: run only when the Phase 0 backup could not yield the DB
    |_ _apply_tweak_pass(prepared_backup_root)
         |_ generate tweak files
         |_ backup encryption handling (iOS 27+ password prompt)
         |_ start_restore(prepared_backup_root)
|_ restore_files()
                    |_ _restore_ios27()
                         Phase 1 (0-40%):  cache master -> snapshot, then prune + inject tweaks in place (restore source)
                                          + clean_backup_for_restore() + inject ALL tweak files (inject_files, unencrypted only)
                                          (skipped entirely if the user opted out on low disk space)
                         Phase 2 (40-60%): perform_restore() (sparse) -> NO reboot (default, merged phases)
                                          (skipped when everything rides Phase 1's inject; encrypted backups keep sparse)
                                          (25s+retry if drop at 0%); GOLDENNUGGET_NO_MERGE_PHASES=1 restores the classic reboot+wipe
                        Phase 3 (60-90%): [merged] reuse live session -> _restore_protective_backup(password) [18x3s]
                                         [classic] _wait_for_device() -> _restore_protective_backup(password) [18x3s]
                                         (skipped when data protection was opted out)
                        Phase 4 (90-95%): reboot before media restore + skip-setup (only if reboot + skip-setup)
                        Phase 5 (95-98%): reconnect (if rebooted) + restore_media_via_afc() (AFC photos/videos,
                                          only when media_dir set) + skip_all_setup27()     (only if skip-setup)
                        Phase 6 (98-100%): reboot_device()                  (only if auto_reboot)
```

## Logging

- Unified stdlib logging: all modules log through the `GoldenNugget` logger
  hierarchy (rotating session file + console handler).
- `src/restore/protective.py` exports `log_info` / `log_warn` / `log_error`
  thin wrappers around `logging.getLogger("GoldenNugget.protective")` (they
  inherit the console + file handlers attached to `GoldenNugget`, and fall
  back to stderr for WARNING+ in headless contexts).
- Legacy `/tmp/goldennugget_log.txt` files created by `protective.py` are gone.
- Verbose logging: pass `--debug` to `main_app.py`; the stdlib logger path can be
  overridden with the `GOLDENNUGGET_LOG_FILE` env var

### Session Log Viewer (src/gui/dialogs/log_viewer.py)

`LogViewerDialog` shows the same session file a bug report gets, reachable
from the home header button (`IOSHomePage._logs_btn` → `open_logs`).

- **Read the file, never the handlers.** It tails the path from
  `get_log_path()` with a 1 s `QTimer`, holding the newest `TAIL_BYTES`
  (1 MiB) — the rotating handler writes up to 16 MiB per file, and the
  useful part of a session is always at the end.
- **The offset is a BYTE offset, always measured on the raw data.** Decode
  with `errors="replace"` (a bad byte must not kill the dialog) but never
  measure consumed length on the decoded text: one bad byte becomes a
  3-byte U+FFFD, the offset runs ahead, and real records get sliced in
  half for good. Only whole lines are consumed (`rfind(b"\n")`), so a
  half-written record is re-read next tick instead of being lost.
- **A shrinking file means rotation, not an error.** The rotating handler
  renames the file aside and starts a new one at the SAME path, so
  `size < offset` resets the buffer instead of rendering nothing.
- **Scrolling is terminal-like**: the view sticks to the bottom only if the
  user is already there, so following a live apply never yanks someone who
  scrolled up to read an error. The `Live` switch owns the poll.
- The level floor and search are applied by `filter_lines` to the raw
  lines. A record with an embedded newline (progress payloads do) is
  recognised by `record_rank` and inherits its record's verdict, so the
  traceback under an `ERROR` the user asked for is never filtered away.
- The fixed-pitch font comes from `_monospace_font()`, **not** from
  `styles.py` (which names no font family — one font everywhere). It asks
  `QFontDatabase.families()` directly because
  `QFontDatabase.systemFont(FixedFont)` reports a family whose
  `fixedPitch()` reads False on Windows; do not "simplify" it back.
- Offline regression suite: `tools/test_log_viewer.py`.
