# GoldenNugget — Verified Codebase Findings

Investigation of the GoldenNugget (PySide6 / iOS 26.2+ tweak tool, v9.1 / build 0)
source tree. Every statement below was confirmed by direct file reads with exact
`file:line` citations. Sections 1–9 cover mechanics; the final section gives an
ACCURATE / OUTDATED / MISSING verdict per claim.

> **Stale since 9.4 refactor.** The `file:line` citations throughout were
> verified against v9.1 and have shifted: `main_window.py` was split into
> `src/gui/main_window_mixins.py`, `restore/protective.py` was split into
> `inject.py` / `protective_cache.py`, and the classic designer stack was
> parked. Treat line numbers as pointers to the feature, not the exact line;
> the structural verdicts in the final section remain valid.

---

## 1. MainWindow and the Two UI Systems

### 1.1 Entry point and object graph

`main_app.py` is the dispatcher:
- CLI dispatch via `-m <module>` (`main_app.py:33-54`) or a trailing `.py` script
  (`main_app.py:56-64`), otherwise the GUI (`main_app.py:66-157`).
- GUI path: creates one `DeviceManager()` (`main_app.py:86`), mock devices in
  `--test-mode` (`main_app.py:89-118`), one `Settings("settings")` and one
  `Translator(app, settings)` (`main_app.py:122-125`), loads the last preset
  before the window exists (`main_app.py:133-143`), then a single `MainWindow`
  (`main_app.py:145`).
- `--debug` enables `setup_logging(log_file, logging.DEBUG, capture_pymobiledevice3=True)`
  (`main_app.py:73-77`); the log file is set from `GOLDENNUGGET_LOG_FILE` and
  defaults to **console-only** (`src/gui/logger.py:69-74`).

`MainWindow.__init__` (`src/gui/main_window.py:36-41`) stores `device_manager`,
`translator`, and `self.settings = self.translator.settings`, then sets up the
designer UI (`ui = Ui_Nugget()` at `main_window.py:41`, `setupUi` at :42).

### 1.2 Page enum vs. the designer stack

`Page` (`src/gui/pages/pages_list.py:5-20`) is a 15-member enum:
`Home=0, Gestalt=1, EUEnabler=2, StatusBar=3, Springboard=4, InternalOptions=5,
LiquidGlass=6, Daemons=7, Posterboard=8, Templates=9, Passcode=10, RiskyTweaks=11,
Tweaks=12, Apply=13, Settings=14`. `getPageName()` maps to display names
(`pages_list.py:22-40`).

The designer `Ui_Nugget` `pages` QStackedWidget also has 15 pages, in registration
order (`src/qt/mainwindow_ui.py`): homePage :1086, gestaltPage :1486,
euEnablerPage :1826, statusBarPage :2908, springboardOptionsPage :3351,
internalOptionsPage :3897, liquidGlassPage :4311, daemonsPage :4330,
posterboardPage :4850, templatesPage :4956, passcodeThemesPage :5115,
advancedOptionsPage :5311, tweaksPage :5416, applyPage :5585, settingsPage :5842.
A second designer stack `pbPages` exists at `mainwindow_ui.py:8555`.

**Key finding:** the designer stack is *never used as the live navigator*. In
`MainWindow.__init__` the whole `centralwidget` is parked into a hidden
`_classic_parking` widget (`main_window.py:150-152`); only `homePage`,
`sidebar`, `daemonsPage`, and `deviceBar` are pulled back out
(`main_window.py:153-157`). All navigation goes through two runtime stacks:

- `self.pages` dict (`main_window.py:74-84`) — classic page *objects* keyed by the
  enum: Home, Posterboard, StatusBar, Springboard, Internal(list), LiquidGlass,
  Daemons, Templates, Settings. (Only 9; no wrappers exist for Gestalt, EUEnabler,
  Passcode, RiskyTweaks, Tweaks, Apply — registered elsewhere or dead.)
- `self.content_stack` (`main_window.py:158-161`): index 0 = classic home
  (`ui.homePage`), index 1 = the whole iOS root widget, index 2 = classic daemons
  (`ui.daemonsPage`).
- `self.ios_pages` (`main_window.py:90-114`): 10 iOS pages —
  0 home, 1 tweaks, 2 posterboard, 3 daemons, 4 settings, 5 statusbar, 6 apply,
  7 springboard, 8 internal, 9 liquidglass. Indices 7–9 are `IOSSectionPage`
  instances built from the registry `Section` enum (`main_window.py:102-104`).

The final shell (`main_window.py:162-174`): a `shell` central widget containing
`deviceBar` on top and a `body_row` of `sidebar` + `content_stack`.

### 1.3 Shared iOS chrome

- One `IOSNavBar` instance is shared across all iOS subpages and reconfigured per
  page (`main_window.py:118-135`); titles come from `_ios_page_titles`, the only
  right action is "+ Add Tendies" on the posterboard page (:132-134).
- `_update_shared_nav` (`main_window.py:581-597`) hides the nav in classic mode or
  on the iOS home page (index 0), sets title/back/right per page.
- `apply_theme(theme)` (`main_window.py:548-579`) only switches chrome: classic =
  sidebar + deviceBar visible with margins; iOS = full-screen, lands on iOS home
  unless already inside the stack (`:565-567`), hides the shared header in classic
  mode (`:575`), and syncs the sidebar highlight.
- `_sync_sidebar_selection` (`main_window.py:599-630`) maps iOS-page index →
  sidebar button; daemons resolves to index 5; classic content_stack index 2
  (daemons) → button 5.
- Back navigation: an app-wide `eventFilter` handles ESC and the mouse Back/Extra1
  buttons (`main_window.py:645-658`) via `_go_back` (`:660-681`): iOS subpage → iOS
  home; classic action page → classic home; classic daemons → classic home.
- Sidebar buttons connect at `main_window.py:232-240`; e.g.
  `on_daemonsPageBtn_clicked` (`:702-710`) is **theme-dependent**: classic mode
  uses `self.pages[Page.Daemons].load()/refresh()` + `content_stack.setCurrentIndex(2)`;
  iOS mode uses `ios_daemons.refresh_from_tweaks()` + `show_ios_page(3)`.
- Other side buttons delegate to `show_ios_page` (statusbar 5, springboard 7,
  internal 8, liquidglass 9, posterboard 2, apply 6, settings 4)
  (`main_window.py:686-722`).

### 1.4 First launch, presets, apply wiring

- First launch: `InterfacePickerDialog` shows unless `ui/theme` already saved
  (`main_window.py:177-183`); choice is persisted via `theme_manager.save_theme`.
- Presets: `PresetManager` created at `main_window.py:48`; `_load_last_preset`
  (`:509-521`) prefers the "AutoSave" preset, else `last_loaded_preset`;
  `_register_tweak_autosave` (`:523-525`) + debounced `_save_autosave_preset`
  (`:535-544`) writes "AutoSave" 500 ms after any tweak change.
- Apply/reset: `on_applyTweaksBtn_clicked` → `apply_changes` (`:743-757`) which
  runs an `ApplyThread`; `on_removeTweaksBtn_clicked` → `ResetDialog` (`:739-741`).
  `update_label` (`:730-738`) mirrors progress into `ios_home.show_process_status`
  and `ios_apply.set_status`.
- Sudo prompt: `alert_message(None)` triggers a `QInputDialog` password box via
  `get_sudo_pwd()/set_sudo_pwd()` (`main_window.py:758-765`).
- Cache restore: `_start_cache_restore` uses `RestoreCacheThread`
  (`main_window.py:782-792`), wired off a button added to an `ApplyAlertMessage`
  that carries a `backup_path` (`:774-780`).

### 1.5 Classic page classes

Registered in `src/gui/pages/__init__.py` (9 exports). Verified classes:

- `HomePage` (`pages/main/home.py`): loads discord link + phone version label
  toggle.
- `PosterboardPage` (`pages/tools/posterboard.py:17+`): uses `MultiComboBox`
  (`src/qt/custom_elements/multicombobox.py`, 72 lines — checkable combo) for reset
  modes; writes `tweaks[TweakID.PosterBoard].resetModes` (:41-42).
- `StatusBarPage` (`pages/tools/status_bar.py`): wraps
  `tweaks[TweakID.StatusBar]` as `status_manager`.
- `SpringboardPage` / `InternalPage` / `LiquidGlassPage` (`pages/tools/*`): radio
  buttons bound via `createRadioBtns` to registry-driven `tweaks` entries.
- `DaemonsPage` (`pages/tools/daemons.py`, 25 lines): embeds `IOSDaemonsContent`
  inside the classic scroll layout and delegates `refresh()` to
  `refresh_from_tweaks()` — *the classic daemons page is the iOS daemons content*.
- `TemplatesPage` (`pages/tools/templates.py`): file picker for `.batter`,
  `create_ui` per template.
- `SettingsPage` (`pages/main/settings.py`): presets UI, PosterBoard DB section,
  about button, language dropdown, iOS/classic toggle, encrypted-backup checkbox;
  reparents the designer `pbSetupPage` into Settings (:160-173).

---

## 2. The "Three Singletons"

The notion that GoldenNugget keys on three global objects is **partly true**:

1. **`tweaks`** — a real module-level singleton dict. `src/tweaks/tweaks.py`
   builds it with only three hand-defined entries (PosterBoard, Templates,
   StatusBar). Every other tweak is registered lazily and idempotently into the
   same dict by `load_plist_tweaks()` (`src/tweaks/tweak_loader.py:13-15`, driven
   by `registry.SPECS`), plus `load_daemons()` for the two daemons entries
   (`tweak_loader.py:27-44`). All UI (classic and iOS) mutates these same objects.

2. **`DeviceManager`** — one instance created in `main_app.py:86` and passed into
   `MainWindow`; not module-global but single-instance in the process.

3. **`DataSingleton`** — **not actually a singleton.** `src/devicemanagement/
   data_singleton.py` (6 lines) is a plain class holding `current_device` and
   `device_available` with no module-level instance or global accessor. Each
   `DeviceManager` owns its own instance at `device_manager.py:115`. The name is
   aspirational; the value is per-`DeviceManager`, not process-wide.

`IOSDaemonsContent._warn_location_daemon` (`src/gui/ios/daemons.py`) reads the
model through `window.device_manager`, so it sees the real current device.

---

## 3. Thread Workers

All device work runs in `QThread` subclasses that emit signals for the UI.

### 3.1 `PBDBThread` (`src/gui/thread_workers/pb_worker.py:8-37`)
- Declared signals (:9-11): `progress=Signal(float)`, `infoLbl=Signal(str)`,
  `alert=Signal(object)` (Applies `ApplyAlertMessage`).
- **No `finished` is declared** — callers use the inherited `QThread.finished`
  (`pb_dialog.py:235-236`).
- `run()` (:27-37) calls `do_work()` (`:24-25`), emitting labels/progress through
  `update_label`/`update_progress` and wrapping failures into an `ApplyAlertMessage`
  Critical; it also emits "Backup Failed!" via `infoLbl`.

### 3.2 `ApplyThread` (`src/gui/thread_workers/apply_worker.py`)
- `ApplyAlertMessage` (:9-15): `txt`, `title`, `icon`, `detailed_txt`, `backup_path`.
- `_SudoState` (:18-35): thread-safe `set_sudo_pwd`/`get_sudo_pwd`; `get_pwd()`
  **clears** the stored value after reading (:26-34).
- Signals (:46-50): `progress=Signal(str)`, `alert=Signal(object)` (None = sudo
  prompt), `finished_with_result=Signal(bool,str)`, `request_text=Signal(str,str,object)`.
- `update_label` (:67-71): `'sudo_pwd'` text → `alert.emit(None)` else progress.
- `prompt_password` (:76-85): routes a modal text request through `request_text`
  + a `queue.Queue` with a 10-minute timeout (`_PROMPT_TIMEOUT_SEC = 600`, :57) —
  password dialogs are *always* built on the main thread.
- `run()` (:87-103): `_do_work` then `finished_with_result`; failures emit a
  Critical `ApplyAlertMessage` with traceback plus `finished_with_result(False, ...)`.
- `_do_work` (:105-109): `manager.apply_changes(...)` if no `reset_pages`, else
  `manager.reset_tweaks(...)`.

### 3.3 `RestoreCacheThread` (`apply_worker.py:112-230`)
- Standalone Phase-1+3 restore for post-failure data recovery. Signals: `progress`,
  `alert`, `finished_with_result` (:121-123).
- `run()` → `_do_work` → `asyncio.run(self._restore())` (:146-148).
- `_restore` (:150-197): locates the cache (`_find_cache_base` checks
  `<temp>/goldennugget_protective_cache` and `AppDataLocation/GoldenNugget/backup_cache`,
  :211-230), builds a working copy via `make_protective_working_copy`, prunes with
  `clean_backup_for_restore`, verifies payloads, then calls `_restore_protective_backup`
  with `reboot=False, skip_apps=True` (no reboot — user is mid-boot).
- Password sourced from `manager._get_backup_password()` (:205-209).

### 3.4 `RefreshDevicesThread` (`apply_worker.py:233-253`)
- Signal `alert=Signal(object)`; `run()` → `manager.get_devices(settings, alert_window)`.
  Used by `MainWindow.refresh_devices` (`main_window.py:263-272`), which guards with
  `refresh_in_progress` and re-enables buttons in `refresh_devices_finished`
  (`:295-361`).

---

## 4. Dialogs

`src/gui/dialogs/__init__.py` exports `PBHelpDialog`, `UpdateAppDialog`,
`AboutProgramDialog` (from `dialogs.py`), `ResetDialog` (`reset_dialog.py`),
`PosterBoardDBWizard` (`pb_dialog.py`).

- `PBHelpDialog` (`dialogs.py:1-42`): shows `:/gui/pb_tutorial1.png` and
  `:/gui/pb_tutorial2.png`.
- `AboutProgramDialog` (`dialogs.py:56-232`): icon/version, credits list
  (:150-165) with cell-based clickable links, GitHub/wallpapers/Discord buttons.
- `UpdateAppDialog` (`dialogs.py:234-267`): Ok/Cancel; `accept()` opens
  `https://github.com/{Nugget_Repo}` (:264-266).
- `ResetDialog` (`reset_dialog.py:5-48`): checkboxes from
  `get_resettable_pages()`; `accept()` calls `apply_reset(selected_pages)` only if
  non-empty (:44-47). `get_resettable_pages` (`pages_list.py:42-50`) returns
  [StatusBar (if < iOS 27), Springboard, InternalOptions, Daemons].
- `PosterBoardDBWizard` (`pb_dialog.py:101-238`): 3-step wizard; on page 1 it
  builds a `PBDBThread` and connects `progress/infoLbl/alert/finished`
  (:231-237); `finished` → `finish_backup_thread` (:187-192). Renames the DB label
  via the `sqlite:` prefix hack (:180-185).

---

## 5. Controllers (`src/controllers/`)

| File | Purpose | Verified detail |
|------|---------|-----------------|
| `settings.py` | Persistence | Dual `QSettings`: writes to org `"GoldenNugget"`, reads falling back to legacy `"Nugget"` (`:8-9,15-17`); SIGBUS-avoiding `value()` that only forwards `type=` when not None (`:22-29`). |
| `translator.py` | Localization | `get_saved_locale_code`, `set_default_locale`, `set_new_language` (full `os.execl` restart), `load_translations` (qtbase from `QLibraryInfo.TranslationsPath`, app qm from `:/translations`), `fix_ui_for_rtl` for `ar`/`ar_SA`/`ar_EG`. |
| `preset_manager.py` | Presets | `PRESET_VERSION=2`, dir `AppDataLocation/GoldenNugget/Presets`; serialize includes all `tweaks` **except** PosterBoard (`:201-205`); serialization for statusbar uses cffi `StatusBarOverrideData` base64 (:222-226); `_apply` loads every tweak first (`:257-262`). |
| `video_handler.py` | Video→.tendies | `cv2`/`ffmpeg` imported lazily by `_ensure_video_libs()` on first video op (`cv2_successful` is `None` until then); `set_ignore_frame_limit`; `FRAME_LIMIT=400` in `create_caml`, raises `VideoLengthException` above it. Adaptive export (issue #86): a CAKeyframeAnimation keeps every key image decoded on-device, so frames beyond the 512 MiB decoded budget are skipped (fps ≤ 30) and downscaled before a 10-fps output floor is broken; duration preserved. Offline suite: `tools/test_video_handler_export.py`. |
| `web_request_handler.py` | Update check | `Nugget_Repo = "awesomenull-dev/GoldenNugget/releases/latest"`; `requests` imported lazily inside `get_latest_version()`; `is_update_available(version, build)`; `get_latest_version()` caches, strips `v`, returns None on 404/errors. |
| `xml_handler.py` | XML patching | Namespace-aware `set_xml_value` matching on `nuggetId`/`id`; `parse_equation` uses `eval` with empty builtins; `nuggetOffset` handling. |
| `files_handler.py` | Bundle files | `get_bundle_files` for .tendies/.batter extraction. |
| `path_handler.py` | Paths | `fix_windows_path` shims used around temp dirs. |
| `nugget_logger.py` | Logging | `init_logging`; file at `AppDataLocation/Logs` (fallback `~/.nugget_logs`). |
| `aar.py` | .aar writer | `wrap_in_aar` assembly with hardcoded `contents.plist` + `settlingEffect.mov` entries. |
| `plist_handler.py` | Plist merge | `recursive_set`/`write_plist_value` helpers. |

Note: `MultiComboBox` is a GUI element, not a controller
(`src/qt/custom_elements/multicombobox.py`, 72 lines).

---

## 6. Exceptions (`src/exceptions/`)

- `nugget_exception.py`: `NuggetException(message, detailed_text)` (10 lines).
- `device_errors.py`: **shared** classification helpers —
  `is_device_locked_error` (:7-10, ErrorCode 208 / "Device locked" / MBErrorDomain)
  and `is_connection_error` (:13-21, `ConnectionTerminatedError`, `ConnectionError`,
  `OSError`, `asyncio.TimeoutError`, plus lowercase substring heuristics).
- `posterboard_exceptions.py`: `VideoLengthException(NuggetException)` and
  `PBTemplateException`.

**Important:** `device_manager.py:29`, `restore/original_plist.py:159-160`, and
`pb_dialog.py:37-38` import these two helpers with aliases — they are *not*
redefined in those files. This contradicts AGENTS.md (see §9).

---

## 7. i18n Pipeline

- The repo declares the `i18n` git submodule → `https://github.com/awesomenull-dev/
  gNugget-i18n.git` (`.gitmodules`). The `i18n/` directory is **empty (not
  checked out)** in this workspace.
- Compiled translation files live under `src/qt/translations/`
  (`Nugget_<locale>.ts` + `.qm` for ab, ar, ar_SA, ar_EG, bg, cs, de, de_AT, es,
  es_MX, fr, fr_BE, fr_CA, ga, …) with a `compile_languages.sh`.
- `I18N_SETUP.md` documents the flow: gNugget-i18n repo → GitHub Action
  `notify-goldennugget-i18n.yml` (push) → repository_dispatch to this repo →
  `sync-translations.yml` (weekly Sunday 03:00 UTC) → `scripts/sync_translations.py`
  → `pyside6-lrelease` → `pyside6-rcc resources.qrc` → commit/push back.
- `SettingsPage.load_available_languages` + `on_langDrp_activated`
  (`pages/main/settings.py:285-300`) and the iOS equivalent
  (`ios/settings.py:248-295`) drive the in-app switcher and restart via
  `translator.set_new_language(lang, restart=True)`.
- `main_app.py:16` silences Qt Wayland text-input spam via `QT_LOGGING_RULES`.

---

## 8. ThemeManager

`src/gui/ios/theme_manager.py` (42 lines, complete):
- `CLASSIC = 0`, `IOS = 1` (:6-7).
- Persistence: `QSettings("GoldenNugget", "GoldenNugget")`, key `ui/theme`
  ("classic"/"ios") (:11,18-25).
- Owns a `QStackedWidget` but is **not** the navigator: `set_classic_widget`
  inserts at 0 (`:27-31`), `set_ios_widget` replaces index 1 (`:33-38`),
  `switch_to` **only saves the preference** (`:40-42`) — the comment at :41 says
  container switching happens in `MainWindow.apply_theme()`.
- `apply_theme` is therefore the single place that actually flips chrome
  (`main_window.py:548-579`). iOS Settings `themeToggleChk`/`IOSSettingsPage`
  call `theme_manager.switch_to(...)` **then** `window.apply_theme(...)`
  (`pages/main/settings.py:278-283`; `ios/settings.py:49-51`).

---

## 9. Code-vs-Documentation Discrepancies (AGENTS.md)

| # | Documentation states | Verified reality | Verdict |
|---|---------------------|------------------|---------|
| 1 | Error helpers `is_device_locked_error`/`is_connection_error` are "defined in `device_manager.py`, `protective.py`, `original_plist.py`, `pb_dialog.py`" (AGENTS.md:155-161) | They are defined **once** in `src/exceptions/device_errors.py` and imported (aliased) by those modules | **OUTDATED** |
| 2 | PBDBThread signals: `progress(float)`, `infoLbl(str)`, `finished` (AGENTS.md) | Signals are `progress`, `infoLbl`, **`alert`**; `finished` is inherited from `QThread`, never declared | **OUTDATED** (incomplete) |
| 3 | "The iOS tweaks page renders its sections straight from `SPECS_BY_SECTION`" (AGENTS.md Tweak Registry) | Confirmed: `ios/tweaks.py:13` imports `SPECS_BY_SECTION`; `IOSSectionContent` iterates sections → `SPECS_BY_SECTION[section]` (`ios/tweaks.py:261-266`) | **ACCURATE** |
| 4 | "Device compatibility (min iOS version, iPad/iPhone) is part of the spec; `src/gui/ios/compat.py` only evaluates it" | Confirmed: `TweakSpec` carries `min/max_version`, `iphone_only`, `ipad_only` (`registry.py:30-45`); `is_tweak_compatible` only evaluates them (`ios/compat.py:11-36`) | **ACCURATE** |
| 5 | AGENTS.md implies a single "Page enum → designer stack index" mapping | The enum's values match the *designer* `pages` stack order, but the live UI navigates via `self.content_stack` (3 entries) + `self.ios_pages` (10 entries); `self.pages` dict only holds 9 classic wrappers | **OUTDATED / misleading** |
| 6 | AGENTS.md reset flow "…builds reset files…" | iOS 26.2+ guarded; reset uses captured originals with `materialize_plist` and safely-null plists (`device_manager.py:938-1038`); details not in AGENTS.md | **MISSING from doc** |
| 7 | AGENTS.md "Protective Backup Cache … iOS 27" | Match, but the cache uses `<temp>/goldennugget_protective_cache` and RestoreCacheThread is available for recovery | Mostly **ACCURATE**, extra detail MISSING |

---

## Verdicts on Claims A–G

- **A — "Page enum doubles as the QStackedWidget index"** → **OUTDATED.**
  Enum values match the designer `pages` stack (`mainwindow_ui.py:1086-5842`), but
  that stack is parked (`main_window.py:150-152`). Live navigation uses
  `self.content_stack` (0/1/2) and `self.ios_pages` (0–9) — distinct index spaces.
- **B — "Classic and iOS UIs share the same tweak state"** → **ACCURATE.**
  Both mutate the module-level `tweaks` dict (via `page.py:createRadioBtns` and
  `IOSSwitch`/`TextInputDialog` handlers in `ios/tweaks.py:188-287`); the classic
  daemons page is literally the iOS daemons content (`pages/tools/daemons.py`).
- **C — "Device work runs off the UI thread"** → **ACCURATE.**
  `ApplyThread`, `RefreshDevicesThread`, `PBDBThread`, `RestoreCacheThread` all
  extend `QThread` and communicate purely via signals.
- **D — "Tweak registry is the single source of truth for plist tweaks"** →
  **ACCURATE.** `SPECS`/`SPECS_BY_ID`/`SPECS_BY_SECTION` (`registry.py:75-148`)
  drive `tweak_loader.load_plist_tweaks`, the iOS pages, and `compat.py`.
- **E — "Three singletons: tweaks, DeviceManager, DataSingleton"** →
  **OUTDATED / MISLEADING.** Only `tweaks` is a real singleton. `DataSingleton`
  is a per-`DeviceManager` plain object (`device_manager.py:115`) with no global
  accessor; fresh constructions exist elsewhere (e.g. `ios/daemons.py:152`).
- **F — "PBDBThread exposes a `finished` signal"** → **MISLEADING.**
  No `finished` is declared (`pb_worker.py:9-11`); consumers rely on inherited
  `QThread.finished`, and `alert` is missing from the documented signal list.
- **G — "i18n is managed via the gNugget-i18n git submodule"** → **ACCURATE with
  caveat.** `.gitmodules` + `I18N_SETUP.md` confirm the design; the `i18n/`
  checkout is empty in this workspace, so live sources are the compiled files in
  `src/qt/translations/`.