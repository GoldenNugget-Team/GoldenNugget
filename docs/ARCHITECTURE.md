# GoldenNugget Architecture

A guided tour of every part of the codebase: what each package does, how the
main flows work end-to-end, and which conventions hold the whole thing
together. For agent-facing operational notes see [AGENTS.md](../AGENTS.md);
for portable presets, diagnostic archives and read-only CLI inspection see
[PORTABLE_AND_DIAGNOSTICS.md](PORTABLE_AND_DIAGNOSTICS.md);
for the iOS 27 status-bar research see [iOS27_StatusBar_Research.md](iOS27_StatusBar_Research.md);
for line-level verified facts gathered during a codebase audit see [FINDINGS.md](FINDINGS.md).

```
main_app.py ──► src/gui/main_window.py ──► pages/ (classic UI)  +  ios/ (iOS-style UI)
                        │  (MainWindow = QMainWindow + DeviceBar/Settings/Navigation/Apply
                        │   mixins from src/gui/main_window_mixins.py)
                        ▼
            src/devicemanagement/device_manager.py   (apply / reset orchestration)
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
  src/tweaks/     src/restore/      src/controllers/
  (what to write) (how to write it) (helpers: plists, xml, presets, …)
```

---

## Entry point — `src/cli` / `nugget_cli.py` / `main_app.py`

The unified CLI dispatcher lives in `src/cli/main.py` (routing + usage text,
exposed via `src.cli`). The top-level `nugget_cli.py` is a thin shim that
delegates to `src.cli.main`, keeping the PyInstaller entry script unchanged.
It dispatches subcommands then falls through to the GUI:

```
GoldenNugget                          launch the GUI
GoldenNugget apply-wallpaper [TENDIE] [--udid UDID] [--list]
GoldenNugget restore-cache [...opts]  restore protective backup (cache master or live run; --source auto|cache|live; Phase-3 recovery)
GoldenNugget restore [same as above]  alias for restore-cache
GoldenNugget skip-setup [--udid]      mark all iOS setup panes completed
GoldenNugget -m <module>| <script>.py  backward-compatible dispatcher
```

`main_app.py` is the underlying GUI/CLI dispatcher:
1. Adds `src/qt` to `sys.path` (joined with `__file__`) so the generated
   resource modules import; silences warnings and Wayland text-input spam.
2. CLI forms: `python main_app.py -m <module>` runs a tool module (falls back
   to `<module>.__main__` for packages); a trailing `<file>.py` (that does not
   end in `.tendies`/`.batter`) is run via `runpy.run_path`.
3. GUI startup: `--test-mode` fabricates **two** mock devices (iPhone 15 Pro /
   iPhone 16) with no USB; `--debug` upgrades logging to DEBUG + captures
   pymobiledevice3; `GOLDENNUGGET_LOG_FILE` overrides the stdlib log path.
4. Restores the `last_loaded_preset` (or "AutoSave") before the window is
   built; handles `.tendies`/`.batter` args by adding them to the tweaks.

Build: `compile.py` calls `PyInstaller.__main__.run(...)` directly (it does
**not** consume `Nugget.spec` — that file only applies if you run
`pyinstaller Nugget.spec` manually). `version.txt` supplies Windows version
metadata only; macOS adds `--osx-bundle-identifier`/codesign. i18n is not
compiled by `compile.py` — `.qm`/`resources_rc.py` are produced by the
pyside6-lrelease/lupdate/rcc pipeline (README / CI).

Selected operation-only imports use Python 3.15's PEP 810
`__lazy_modules__` allowlist (backup/restore services, setup certificates,
wallpaper conversion and status-bar preset serialization). Dependencies load
on first use; Python 3.14 and earlier keep ordinary eager imports without a
syntax change. Entries name the fully qualified module after `from`, including
the package for `from . import ...`. Keep Qt resources, tweak registry/singleton
initialization, the SSL timeout patch and protective device-link shims eager;
imports inside functions or `try` blocks also stay eager, preserving optional
video dependency error handling. `tools/test_lazy_imports.py` checks deferral
and resolution in fresh processes, plus the older-Python fallback.

Windows-only packaging detail — **the abi3t compat DLL**: the Windows branch of
`compile.py` collects `python3t.dll` into the bundle root. cryptography ≥ 50
ships an abi3/abi3t wheel whose `hazmat/bindings/_rust.pyd` links
`python3t.dll`, but the official python.org Windows installer does **not** put
that DLL next to `python3XX.dll` — it installs it under a sibling
`abi3t-compat\` directory (CPython `Tools/msi/core/core_files.wxs`), which is
on no DLL search path. PyInstaller therefore cannot resolve the import, drops
it silently, and the frozen app dies at startup with `ImportError: DLL load
failed while importing _rust`. `compile.py` finds the DLL (in `abi3t-compat\`
or the install root, via `sys.base_prefix`/`sys.executable`), adds it with
`--add-binary ...;.` so it lands beside `python3XX.dll`/`python3.dll`, and
verifies it made it into `dist/GoldenNugget`. At runtime CPython's
`_Py_CheckPython3t()` (`Python/dynload_win.c`) preloads `python3t.dll` from
that directory, so the `_rust.pyd` import resolves. If the DLL cannot be found
while the installed cryptography needs it, the build fails loudly instead of
shipping a broken release.

## Global state — one real singleton, two process singletons

| Object | File | Purpose |
|---|---|---|
| `tweaks` | `src/tweaks/tweaks.py` | **The only true module-level singleton**: `dict[TweakID → Tweak instance]`; the single source of runtime tweak state both UIs read and write |
| `DeviceManager` | `src/devicemanagement/device_manager.py` | device discovery, apply/reset orchestration (one instance, created in `main_app.py`) |
| `DataSingleton` | `src/devicemanagement/data_singleton.py` | **not a real singleton** — a plain 6-line class holding `current_device` + `device_available`. Each `DeviceManager` owns its own instance (`device_manager.py:115`); there is no global accessor. Treat its per-manager value as the source (e.g. read `window.device_manager.data_singleton`). |

---

## src/devicemanagement/ — talking to the device

### `session.py`
`lockdown_session(serial)` — the **only** sanctioned way to open a lockdown
connection. Async context manager that always closes safely (a rebooted
device makes `close()` raise `ConnectionTerminatedError`, which must never
mask the real result). `create_using_usbmux` appears directly only where
connection ownership transfers to a caller (`_wait_for_device`,
`perform_restore`, `skip_setup`, `tools/` scripts).

### `constants.py`
- `Device` — plain data object (udid, version, model, locale…).
- `is_supported_by_fork(version)` — hard gate: iOS > 26.1 only.
- `Version` — re-export of `packaging.version.Version`.

### `preference_manager.py`
QSettings-backed user preferences (`auto_reboot`, `use_encrypted_backup`,
skip-setup options…) plus the PosterBoard saved-database helpers.

### `device_manager.py` — the orchestrator
Key methods:

- `_get_devices()` — usbmux scan; per-device lockdown probe; encryption check
  (blocks non-experimental encrypted use); builds `Device` objects.
- `apply_changes()` → `_apply_changes()` — the main flow, see below.
- `_prepare_protective_backup()` — Phase 0: cached protective backup; when
  wallpapers are applied, also includes the PosterBoard container and
  extracts its database right after the refresh. Returns a `PreparedBackup`.
- `_apply_tweak_pass()` — asks every loaded tweak to generate its files,
  merges them into one restore list, handles backup-encryption prompts,
  then calls `start_restore()`.
- `start_restore()` → `restore_files()` (src/restore).
- `reset_tweaks()` — builds "restore stock values" files per selected page.
  No pre-reset capture: the device's own plists are never pulled, because the
  managed-preferences copy the tweaks write to already holds the tweaked
  values, so restoring a captured "original" would re-apply the tweaks.
  Plist targets come from the tweak registry for Springboard, Liquid Glass
  and Internal, with legacy targets retained. Reset clears both managed
  preferences and their app-domain mirrors with valid empty dictionaries on
  all supported versions (26.2+). Sections sharing a plist reset together;
  opaque Siri AI archives use the separate Reset Siri AI Overrides tweak.

#### Apply flow (end-to-end)
```
apply_changes()
 ├─ _raise_if_unsupported()                    iOS < 26.2 hard-blocked
 ├─ _prepare_protective_backup()               Phase 0, iOS 27 only (cache, see below)
 │    ├─ encrypted? prompt password / bypass cache
 │    └─ wallpapers applied? include PB container + extract DB after refresh
 ├─ _backup_posterboard_database(force=True)   only if the cache could not
 │                                             provide a usable DB
 └─ _apply_tweak_pass(prepared_backup_root)
      ├─ every tweak.apply_tweak(...)          files generated into one list
      ├─ skip-setup + .GlobalPreferences copy  HomeDomain survival copies
      ├─ backup-encryption password handling   (iOS 27+)
      └─ start_restore(files, prepared_backup_root)
           └─ restore_files
                ├─ iOS >= 27.0 → _restore_ios27   six phases, below
                └─ iOS 26.2–26.x → perform_restore
                     plain sparse restore; no protective backup and no wipe
```

---

## src/tweaks/ — what gets written

### Registry-first design (`registry.py`)
Every *registry-managed* plist tweak is defined **once** as a `TweakSpec`:
`id`, `section` (Liquid Glass / SpringBoard / Internal Options), `title`
(marked with `QT_TRANSLATE_NOOP` — see below), `location`, `key`, `value`,
`kind` (`switch` / `text` / `number`, plus `min_value`/`max_value` for
numbers), compatibility (`min_version`, `max_version`, `iphone_only`,
`ipad_only`) and an optional `factory` for non-basic tweaks. The only
factory-backed spec is WatchOS Compatibility → an `AdvancedPlistTweak` over
`FileLocation.nanoregistry` (also `ipad_only=True`).

Not every plist tweak is a spec: `Daemons` (an `AdvancedPlistTweak` over
`disabled.plist`) and `ClearScreenTimeAgentPlist` (a `NullifyFileTweak`) are
hand-built in `load_daemons()`, and the three non-plist extra tweaks
(`PosterBoard`, `Templates`, `StatusBar`) live outside the registry.

**Translation:** titles are wrapped in `QT_TRANSLATE_NOOP("Nugget", title)` at
*definition* time (registry.py) so they reach pyside6-lupdate; the real
`QCoreApplication.translate("Nugget", spec.title)` happens at *render* time in
`src/gui/ios/tweaks.py`.

Consumers:
- `tweak_loader.load_plist_tweaks()` builds instances into `tweaks`
  (idempotent — already-loaded IDs keep their live instance so UI state
  survives re-entry; `load_daemons()` builds the hand-defined daemon tweaks
  separately).
- The iOS tweaks page renders sections straight from `SPECS_BY_SECTION`
  (`SPECS_BY_ID` powers compatibility lookups). Every section is wrapped in an
  `IOSCollapsibleSection` (`gui/ios/components.py`); the collapsed state is
  stored per section name in `tweaks_collapsed_sections` and restored on rebuild.
- `gui/ios/compat.py` evaluates `min_version` / `max_version` / device
  restrictions from the spec (public API unchanged).

Adding a tweak = adding one registry entry.

### Tweak classes (`tweak_classes.py`)
`Tweak` base (key/owner/group, `enabled=False`, change-notification via a
module-level callback that drives the autosave) with concrete generators:
- `BasicPlistTweak` — one key into one managed plist, **merges** into existing
  plists (does not wipe sibling keys).
- `AdvancedPlistTweak` — a dict of keys into one plist; `apply_tweak`
  **replaces** the whole plist dict (unlike BasicPlistTweak's merge);
  `set_multiple_values(keys, value)` stamps one value across many keys (used
  by the Daemons UI).
- `NullifyFileTweak` — writes a zero-byte file (plist nuking).
- Special generators live outside `tweak_classes.py`: `StatusBarTweak`
  (`status_bar/`), `PosterboardTweak` + `TemplatesTweak`
  (`posterboard/`). (There is **no** `PasscodeThemeTweak` — that class does
  not exist; only parked Qt-Designer chrome remains.)

`Daemons` is an `AdvancedPlistTweak` over the `Daemon` enum's bundle IDs
(`src/tweaks/daemons_tweak.py`); the class itself is enum-agnostic — the UI
translates `Daemon.X → [bundle IDs]`. Disabling the Location daemon on an
iPhone 14-family device (`iPhone14,*`) triggers a wallpaper-risk warning in
both UIs (the classic Daemons page embeds the same `IOSDaemonsContent`).

### PosterBoard subsystem (`tweaks/posterboard/`)
Wallpapers are always applied **as configurations written into the
PosterBoard sqlite database** (the old descriptor-file method was removed —
broken on iOS 26+).

- `posterboard_tweak.py` — `use_configs = True` (the descriptor apply method
  is gone, broken on iOS 26+), `structure_version = 61`. `verify_tendie` caps
  total descriptors at 10 and warns when a tendie ships its own `.sqlite3`
  (`unsafe_container`). `recursive_add` walks tendies/templates, randomizes
  UUIDs, classifies parenthesized descriptor types into Photos / Mercury /
  Collections extension providers, registers them (`add_config`), and stages
  the modified DB (`update_sqlite`) appended as an AppDomain file; `ordered`
  descriptors get reverse-sorted sequential ids. `update_plist_id` rewrites the
  identifier-bearing plists (descriptor identifier, userInfo's
  `wallpaperRepresentingIdentifier` and the wallpaper's own `identifier`);
  the wallpaper's family/name and its nested `lockAndHome.default` entry are
  left exactly as the source ships them. Optional live-photo
  (`create_live_photo_files`,
  bundling HEIC thumbnails + `.aar` via `wrap_in_aar`) and video-loop CAML
  (`create_video_loop_files`) generation via `video_handler`.
- `pb_config_manager.py` — the DB pipeline: pulls the live DB (from the
  protective-backup cache), validates (`_validate_posterboard_db` with
  `strict=True` for the classic schema, `strict=False` for any healthy
  poster-ish DB because the schema varies on iOS db5+; always runs
  `PRAGMA integrity_check`), stages config entries
  (`update_sqlite` re-writes `poster`/`posterAttributes`/`posterRoleMembership`
  rows, computing `roleSortKey`), and produces the modified database. It also
  surfaces the SQLCipher "disable backup encryption" error.
- `template_file.py` + `template_options/` — the `.batter`-style template
  format: JSON-defined option widgets (picker/remove/replace/set) that edit
  caml/xml/plist payloads at apply time. Each template owns its resources and
  preview mapping. Pickers initialize their applied selection from validated
  default indices and preserve edits when their controls are rebuilt; multiple
  selections carry option labels as item data. Numeric conversion must not
  mutate the option's stored vectors. Offline regressions:
  `tools/test_template_options.py`.
- `community_tweaks.py` — format 3 `.batter` `tweaks`: switchable tweaks that
  write plist keys or files to domain-mapped paths. `TemplatesTweak.community_writes`
  collects them; `DeviceManager._apply_tweak_pass` merges their plist keys into
  the built-in plists (built-in keys win) and refuses whole-file clashes.
  Switch states ride in presets as `Templates.tweak_states`, one dict per template.
- `status_bar/status_setter.py` + `status_bar_tweak.py` + `statusbar_archive.py`
  — the UI state is the binary `StatusBarOverrideData` struct (cffi,
  `-malign-double`), which is what gets written on **iOS 26 and below** as
  `/Library/SpringBoard/statusBarOverrides` in HomeDomain
  (`apply_classic_tweak`). On **iOS 27+** that file is no longer read and the
  `SpeakeasyNewStatusBar` feature flag cannot be written by a restore at all,
  so the tweak switches medium instead: `apply_ios27_tweak` stages
  `/Library/SpringBoard/StatusBarOverrides.archive`, an `NSKeyedArchiver`
  binary plist SpringBoard unarchives itself
  (`_SBSystemStatusStatusBarOverridesArchiveRecord` → `STStatusBarData` →
  `STStatusBarDataCellularEntry`), built by `statusbar_archive.py` with plain
  `plistlib`. Same HomeDomain as the classic path, so it is an ordinary
  restore file — no exploit and no out-of-band channel. An **enabled
  carrier override with a blank name** writes the entry with an empty
  string (the whole live entry is replaced, so the label draws nothing with
  no gap — OG Nugget behaviour, issue #83); `None` still means "unset" and
  omits the entry.
  **Scope on iOS 27 is the cellular entry only**: carrier name, service
  badge and signal bars (primary + secondary); the
  archive has no representation for the time/battery/icon overrides, so
  `src/gui/ios/statusbar.py` hides those rows on 27 instead of offering
  switches that do nothing. Everything else in the cellular entry is written
  with fixed verified values. Reset writes a *valid empty* record
  (`build_reset_archive()`), which SpringBoard decodes as "no overrides" and
  unlinks itself — the old FeatureFlags write is gone, since poking
  `/var/preferences` on iOS 27 risks tripping Security Recovery. Unverified on
  physical hardware: the format was validated on the iOS 27 simulator only.
  Reference research:
  <https://github.com/Prognosticate-X/ios27-carrier-lockscreen-research>

---

## src/restore/ — how it gets written

PosterBoard database fetches and rebuild pulls store temporary backups under
`posterboard_dir()/.work/`, so **Backup/Cache Location** and
`GOLDENNUGGET_BACKUP_DIR` cover scratch space too. Both use
`ProtectiveBackupService(include_posterboard=True)` and check that destination's
free space before opening a device connection. A filtered upload can still be
refused against the device's full backup estimate.

The DeviceLink shim answers `DLMessagePurgeDiskSpace` with a failed-purge status
and zero reclaimed bytes, then waits for the device's final result. It reports
real free space and never deletes user data to satisfy a purge. A subsequent
MBErrorDomain/105 becomes an actionable host-storage error with the backup path;
the apply path preserves it instead of reporting a missing PosterBoard DB.
Offline regressions: `tools/test_posterboard_backup_space.py`.

### `restore.py` — six-phase restore (`_restore_ios27`)
iOS 27 only. `restore_files` calls `_restore_ios27` when
`product_version >= 27.0`. iOS 26.2–26.x takes the other branch: a plain
`perform_restore`, with no protective backup and no safe-state-recovery wipe.

By default `merge_phases` is true, so Phase 2 does not reboot and the phone
is not wiped; the protective restore lands on the still-live device.
`GOLDENNUGGET_NO_MERGE_PHASES=1` restores the classic reboot into safe state
recovery. Phase 2 is also skipped entirely when the protective restore
already carries the apply (wallpaper-only, or an unchanged tweak set plus
new wallpapers).

```
Phase 0 (in device_manager): protective backup + PosterBoard DB
                  (fresh live perform_protective_backup(), or the persistent
                   cache master + incremental refresh when the experimental
                   cache is enabled)
Phase 1 (0-40%):  cache master → a disposable restore VIEW (pruned manifest
                  copy + hardlinked payloads), pruned + tweak-injected; the
                  master itself is never modified, so it keeps its full
                  manifest for the next incremental refresh and a crashed
                  apply cannot leave it half-pruned; a fresh Phase-0 live
                  backup is pruned IN PLACE (no /tmp copy ever)
                  → clean_backup_for_restore() prune
                  → inject PosterBoard files (pb_inject_files, AppDomain)
Phase 2 (40-60%): perform_restore() sparse restore. Default merge_phases
                  does not reboot, so there is no safe-state-recovery wipe.
                  GOLDENNUGGET_NO_MERGE_PHASES=1 reboots into that wipe.
                  Skipped entirely when the protective restore already
                  carries the apply:
                  • PosterBoard-only applies — every payload is diverted to
                    pb_inject_files, the incidental scaffolding files are
                    dropped, the sparse list is empty
                  • unchanged tweaks + added wallpapers — the generated
                    sparse payload matches lastapply.json (per-device record
                    of the last successfully applied tweak set, written after
                    every successful apply, cleared on reset), so the device
                    already has those tweak files and Phase 3's protective
                    restore delivers the wallpapers right after Phase 1 —
                    no partial restore, no wipe)
Phase 3 (60-90%): _wait_for_device() (20 min budget, _RECONNECT_TIMEOUT);
                  on timeout the GUI gets an Abort/Resume pop-up — Resume
                  restarts a fresh waiting cycle instead of aborting (no
                  callback → classic DeviceNotFoundError)
                  → _restore_protective_backup() puts user data back
                  (max_retries=18, fixed 3s sleep, only for transient errors)
Phase 4 (90-95%): reboot_device()  — before the media restore and setup skip,
                  so skip runs on a freshly-booted device (a merged still-live
                  session would otherwise already carry a cloud config and
                  SetCloudConfiguration only raises AlreadyPresent)
Phase 5 (95-98%): _wait_for_device() reconnects (only after a Phase 4 reboot),
                  then restore_media_via_afc() pushes the AFC-pulled
                  photos/videos back (they were excluded from the backup) —
                  as a DIFF against the device's own media tree, so only the
                  files the device actually lacks are transferred; the
                  explicit recovery restores pass diff=False so the store's
                  copy always wins
                  then skip_all_setup27()  — if skip-setup requested, on every
                  apply including Phase 2-skipped ones; a device that was never
                  wiped may still hit CloudConfigurationAlreadyPresentError
                  (treated as success)
Phase 6 (98-100%): reboot_device()  — only if auto_reboot (default on iOS 27),
                  so the skipped setup takes effect on the next boot
```

`prepared_backup_root` is a `PreparedBackup(root, manifest_password)`; when
absent (encrypted-without-password / kill switch), Phase 1 falls back to an
in-place `perform_protective_backup()`.

The AFC media cache skips a file only when the previous pull was verified and
both its size and device modification time match. Older markers without file
times trigger a fresh pull on the next cache refresh. Transfers stream through
bounded buffers, verify sizes (after closing the remote file on writes), and
reject files that change while being pulled. Local payloads and completion
markers use unique temporary files followed by an atomic rename. Cancellation
closes file handles and services and joins the parallel media task; resuming a
paused media restore opens a fresh lockdown session. Offline coverage lives in
`tools/test_afc_media_safety.py` and `tools/test_afc_regressions.py`.

Progress ranges are the real `_PHASE_BACKUP_END=40`, `_PHASE_TWEAK_END=60`,
and the hardcoded `95`/`98`/`100` bounds in `_restore_ios27` — the old
"Phase 3 = 60-100%" summary is simplified: the last 10% belongs to the
reboot-before-skip, the setup skip and the final reboot.

Phase 3 details: `perform_protective_backup` itself has **no** retry loop —
the only retry is `ProtectiveBackupService.connect()` with **5** attempts
(backoff 2, 4, 8, 15 s). Phase 3 restore retries transient errors only
(`_is_transient_restore_error`: ConnectionTerminatedError/OSError, ssl,
"InvalidService", "SpringBoard ... ready for a restore", "start ... service").

Phase 2 has its own guard: if the sparse restore drops at 0% it waits 25 s and
retries once on a fresh connection (`max_sparse_attempts = 2`).

A 1-hour stale-working-copy GC removes old `nugget_protective_*` temp dirs at
the start of `_restore_ios27`.

Sparse staging itself lives in `backup.py` (Status.plist `Version: 3.3` +
sqlite `Manifest.db`, the same format as the protective backup) and
`__init__.py::perform_restore` (with `GOLDENNUGGET_KEEP_SPARSE` debug copy
support). `_Mobilebackup2NoEscrow` is used when a fresh post-wipe re-pair
carries no EscrowBag.

### The `restore/` package — protective backup, injection and the cache
The protective backup pipeline lives in `protective.py` (live backup,
working copies, prune/dedupe, clean-for-restore); the backup-file injector
was split out to `inject.py` (blob builders + `inject_file_into_backup`) and
the `ProtectiveBackupCache` to `protective_cache.py` (both re-exported from
`protective.py`):
- `ProtectiveBackupCache` — per-device master copy in the persistent app-data
  store (`<AppData>/GoldenNugget/backup_cache/master/<udid>`). The master keeps
  a FULL Manifest.db (rows for drained payloads stay) so mobilebackup2 can run
  true incremental refreshes; invalidated by UDID/iOS-version change or by the
  encryption state flipping. Usability is decided by `_usable_manifest()`: an
  intact SQLite Manifest.db **or** a recognised encrypted one
  (`_is_encrypted_backup`) — an encrypted Manifest.db is AES bytes and never
  validates as SQLite, so requiring SQLite made an encrypted master permanently
  unusable and every apply silently ran a **full** re-upload (255k+ placeholder
  files instead of a diff; issue #81). A master whose Manifest.plist cannot be
  read counts as unusable rather than raising out of `locate()`. A refresh that
  fails or is cancelled deletes the cache marker JSON (payload files stay), so
  the next apply rebuilds instead of diffing against an indeterminate mirror.
  It ALWAYS lives in the persistent store — it is
  the only copy of user data between Phase 2 (wipe) and Phase 3 (restore), so
  a temp placement is permanent-loss-on-reboot. A legacy temp base is still
  scanned by `locate()` for migration. The whole location is relocatable:
  Settings → Backup → "Backup/Cache Location" stores `backup_storage_dir` in
  the `Settings("settings")` QSettings store (`src/restore/storage.py` is the
  single source of truth for `cache_base()` / `protective_base()` /
  `posterboard_dir()` / `legacy_backups_dir()`, env override
  `GOLDENNUGGET_BACKUP_DIR` wins over the setting; unset = historical
  `<AppData>/GoldenNugget/...` defaults) so a small system drive can point
  everything at another volume. During an incremental refresh the device
  probes the prior backup's `Snapshot` payload dir via `DLContentsOfDirectory`;
  `protective.py`'s `_install_device_link_contents_shim` answers a missing dir
  with an empty listing (real hosts do the same) so the probe can't crash the
  apply.
- `perform_protective_backup(..., incremental_ok)` — selective backup:
  pymobiledevice3's native `filter_callback` drains non-protective uploads
  mid-stream while their manifest rows survive (that is what makes the next
  incremental cheap). Keep-set: CameraRoll/Media (photos),
  SystemPreferencesDomain, HomeDomain Accounts / ConfigurationProfiles /
  Preferences / SpringBoard / ControlCenter / Shortcuts / WebClips (incl. the
  `.webclip/Storage` PWA data) / WebApp / WebKit/WebsiteData, optionally the
  PosterBoard DB.
  (Note: the module's own doc-comment at `protective.py:212-220` claims
  ConfigurationProfiles was reverted, but the code still keeps it.)
  - **Progress labels** come from `backup_category_for()` (module level, so
    the mapping is testable). It normalises the upload name through
    `_device_tree_name()`, so iOS 26's domain-qualified names
    (`CameraRollDomain/Media/…`) and iOS 27's raw tree (`/.b/<n>/Media/…`)
    land in the same category. Without the tree normalisation every iOS 27
    upload fell through to the generic "Device data" label — the phrase a
    stalled apply appeared to be frozen on (issue #81).
  - **A log heartbeat** (`Backup upload heartbeat: seen=… kept=…`) fires at
    most once a minute from the filter, so a wedged transfer is
    distinguishable from a slow one instead of the log simply stopping.
  - **A DeviceLink silence budget** (`install_recv_timeout()` in
    `device_link_adapter.py`) wraps `DeviceLink._recvall` in
    `asyncio.wait_for` — the single choke point for everything the device
    sends. Silence for `DEFAULT_RECV_TIMEOUT_SECS` (900s, override with
    `GOLDENNUGGET_BACKUP_STALL_SECS`) raises `DeviceLinkStalled` instead of
    blocking in `readexactly` forever. Its message deliberately avoids the
    connection-error keywords, so `is_connection_error()` does not replay the
    whole backup as a transient link flap. The negotiated mode/root/encryption
    state and the budget are logged before `mb.backup`.
- `make_protective_working_copy()` — hardlink clone (metadata real-copied);
  pruning never corrupts the master. Used by the manual restore tools
  (`restore_cache.py`, `apply_worker.py`).
- `make_restore_view()` — the main apply flow's equivalent for the cache
  master: a disposable VIEW of the master (pruned manifest copy + hardlinked
  payloads) that the apply prunes and tweak-injects instead of the master
  itself. The master stays a pristine full-manifest mirror, so the next
  incremental refresh still diffs against a complete manifest and a crashed
  apply cannot leave it half-pruned. `discard_restore_view()` removes it
  afterwards — the hardlinks mean no payload data is touched.
- `clean_backup_for_restore()` — prunes to the keep-set; self-heals by
  dropping regular-file rows whose payload is missing (MBErrorDomain/205)
  while keeping directory rows (renameatx ENOENT). Encrypted manifests are
  decrypted/pruned/re-encrypted locally via pymobiledevice3 when a password
  is supplied (prune only touches the working copy, never the master).
- `inject_file_into_backup()` — adds fresh tweak content so injected tweaks
  survive the wipe through Phase 3's native restore. **Only PosterBoard files
  (`pb_inject_files`, `AppDomain-com.apple.PosterBoard`) are injected today** —
  the old `_HOME_DOMAIN_TWEAK_PATHS`/`_SYSTEM_PREFERENCES_TWEAK_PATHS`
  constants were removed (dead code). For **encrypted** backups injection is
  **always skipped** (plaintext payloads would fail the restore agent's
  decrypt).
- `extract_posterboard_db()` — resolves the PB database by FILE NAME
  (structure version varies), pulls `-wal`/`-shm` siblings and checkpoints
  them into one consolidated database.
- `verify_backup_payloads()` — last-line diagnostic before Phase 3.
- `prune_protective_backups()` — keeps only the newest
  `PROTECTIVE_KEEP_RUNS=1` run and deletes every older run outright (no age
  guard, no payload dedupe). Called strictly AFTER a successful backup so the
  last good run is never retired before the new one exists.
- `check_disk_space()` — sizes the requirement from the device's
  real used storage; `GOLDENNUGGET_MIN_FREE_GB` overrides the floor and
  `GOLDENNUGGET_CACHE_REFRESH_SECS` tunes the cache refresh interval.

---

## src/gui/ — two UIs, one state

Application colors live separately in `gui/theme/`: a single dark palette
(`DARK`) provides named slots and eight accent choices (`ACCENT_PRESETS`) that
swap `accent`/`accent_hover`/`accent_pressed` only.
`ColorThemeManager.set_accent()` saves `accent_color` in QSettings; there is no
light/dark switch and the OS color scheme is not followed (Qt's colour scheme is
pinned dark).
Native widget palettes cover active, inactive and disabled states, while
pages, shared components and open dialogs reapply their themed styles.
Color-only labels must explicitly use a transparent background so their
palette window color cannot obscure card surfaces. Offline theme regressions
are in `tools/test_theme.py`.

The pre-apply summary includes **View changes**, a read-only, scrollable
selection comparison (`controllers/apply_preview.py`,
`gui/dialogs/apply_preview.py`). It compares against the last successful apply
for the same UDID and iOS version, accounts for HotLoad exclusions and forced
daemon values, and lists the current wallpaper/template/icon queue separately.
Deselecting a tweak is explicitly not a reset. Before the first recorded apply,
or after a reset/version change, it shows current selections without inventing
device values. Preview history is an atomic `.json.preview` sidecar next to the
existing last-apply signature; it never changes sparse-restore routing. Capture
runs before tweak generation and is saved only after apply succeeds; successful
reset invalidates it. Opening the preview generates no payloads and opens no
device session.

Before starting an apply worker, the GUI also checks enabled plist writers
with `controllers/tweak_conflicts.py`. It warns about differing values for the
same key, a whole-file replacement or clear that overwrites another tweak,
and simultaneous forced RTL/LTR layout. HotLoad-skipped tweaks are excluded.
The warning defaults to reviewing the selection; continuing is explicit and
never toggles a tweak automatically. These checks cover known plist conflicts,
not every possible interaction with wallpapers, templates or device software.
The same conflicts appear in View changes.

The summary also opens with a **risk verdict** (`controllers/risk_assessment.py`,
`gui/ios/risk_panel.py`): Low / Medium / High plus the most serious reasons.
It combines a per-tweak and per-daemon risk table, registry compatibility,
warn-only HotLoad `risk` rules for the device's iOS version, conflicts, battery,
free space, wallpaper packages, a first apply on this iOS version and the
number of tweaks changed at once. It works on preset-shaped data, so the same
verdict is shown for an imported share code and for every preset in the
community catalog (`controllers/preset_catalog.py`,
`gui/dialogs/preset_catalog.py`; see docs/PORTABLE_AND_DIAGNOSTICS.md). A High verdict disables Apply until
the user ticks "I understand the risks". The verdict is advice: an unlisted
tweak is Low only because nothing is known against it.

**Preview on iPhone** (`gui/ios/device_twin.py`, `gui/dialogs/device_twin.py`)
draws the selection on a full Lock Screen and Home Screen in a frame that
matches the device: Dynamic Island, notch or Home button (unknown devices use
the island shape). `build_state()` works on preset-shaped data, so the Apply
page, the pre-apply summary, a saved preset and an Import Code result all use
the same picture. It draws the status bar overrides (via `statusbar_preview`),
Dynamic Island off, the Lock Screen footnote and supervision text, Liquid Glass
on/off for the clock, Dock and icons, the search button, the Clock icon seconds
hand, the build number, RTL order, icon themes and the first PosterBoard
wallpaper's preview. Tweaks that are incompatible with the device are not drawn;
tweaks without a visible result are counted in the legend instead. It is a
stylised drawing, not a device screenshot.

Apply and reset workers append a bounded local operation history through
`controllers/apply_history.py`. Settings shows the ten newest entries with
timestamp, operation, device, iOS version and result; it can clear the history
without touching presets, backups or the device.

Settings keeps preset Load/Delete/Refresh separate from the Export/Partial
Export/Import row. Imports validate their container structure before saving,
preserve legacy files without metadata, and store the preset without activating
it. Existing JSON export semantics remain unchanged (PosterBoard is excluded;
template and icon entries reference local assets rather than bundling them).

The `Page` enum (`pages_list.py`) and the designer `pages` QStackedWidget
share 15 indices, but the designer stack is **parked** (`main_window.py:150-152`)
and is not the live navigator. Real navigation uses:
- `self.pages` — dict of the 9 live classic page wrappers (`pages/main/*`,
  `pages/tools/*`), keyed by `Page`.
- `self.content_stack` — classic home / iOS root / classic daemons / connect placeholder.
- `self.ios_pages` — 15 hand-built iOS pages (`ios/`): home, tweaks,
  posterboard, daemons, settings, statusbar, apply, springboard, internal,
  liquidglass, icon themes, passcode themes, presets, community catalog and
  templates. Springboard, internal and liquidglass are `IOSSectionPage` built
  from the registry `Section` enum. PosterBoard (index 2) owns Tendies and Video;
  Templates (index 14, `ios/templates.py`) owns `.batter` tweak imports/editors
  and the Batter Builder link. Each has a home tile, sidebar item and independent
  HotLoad feature visibility. Catalog template installs refresh `ios_templates`.

- **Classic** — Qt Designer (`mainwindow.ui` → `mainwindow_ui.py`) wrappers in
  `pages/main/*` and `pages/tools/*`. The classic Daemons page literally embeds
  the shared `IOSDaemonsContent`.
- **iOS-style** — hand-built widgets in `ios/`, rendered from the registry
  where applicable; a single shared `IOSNavBar` is reconfigured per page.
- Both bind to the same `tweaks` instances — toggling in either UI changes the
  same state. `theme_manager.py` (`CLASSIC`/`IOS`) only *persists* the choice;
  `MainWindow.apply_theme()` actually flips the chrome.
- Dialogs: PosterBoard fetch wizard (`pb_dialog.py`, 3-step `PosterBoardDBWizard`
  + `PBDBThread`), reset picker (`reset_dialog.py`), about/update/help
  (`dialogs.py`).
- Thread workers (`thread_workers/`): 
  - `PBDBThread` (`pb_worker.py`) — signals `progress`/`infoLbl`/`alert`; there
    is **no declared** `finished` (callers use inherited `QThread.finished`).
  - `ApplyThread` — applies/resets; `alert.emit(None)` triggers the sudo prompt;
    `prompt_password` builds password dialogs on the main thread via
    `request_text`, with a 10-minute timeout.
  - `RestoreCacheThread` — standalone Phase-1+3 recovery (working copy → prune →
    verify → `_restore_protective_backup`, `reboot=False, skip_apps=True`).
    Reachable both from a failed-apply error dialog and from the
    Settings → Backup "Restore Data From Backup" button, which re-runs the
    phase-3 data restore without re-applying tweaks (`skip_apps=True` keeps the
    PosterBoard container and thus the applied wallpapers).
  - `RefreshDevicesThread` — device refresh.

## src/controllers/ — support services

Local transfer/inspection modules:
- `preset_bundle.py`: atomic portable preset export/import with hashed template
  and icon assets; `PresetManager` retains the legacy JSON path. Import stores
  selections without activation. `gui/dialogs/file_task.py` runs transfers off
  the GUI thread.
- `archive_safety.py`: shared ZIP path, link, duplication and expansion checks.
- `wallpaper_validation.py`: bounded offline package report; exposed through
  `gui/dialogs/wallpaper_validation.py` and `cli/cmd_wallpaper.py`.
- `diagnostics.py`: allowlisted metadata and redacted log tails, with an editable
  GUI preview in `gui/dialogs/diagnostics.py` and local CLI exports.
- `apply_plan.py`: CLI dry-run built from the existing preview, compatibility
  and conflict rules. Preview-only preset loading avoids copying icon assets or
  instantiating templates. It never calls device apply/reset or generates a
  restore payload.
- `cli/output.py`: common versioned JSON envelope, with progress on stderr.

| Module | Role |
|---|---|
| `settings.py` | QSettings: writes to org `GoldenNugget`, falls back to legacy `Nugget`; SIGBUS-avoiding `value()` |
| `preset_manager.py` | export/import/apply of tweak presets (`PRESET_VERSION=2`; serializes all tweaks except PosterBoard; statusbar uses cffi base64). `export_preset(..., include=)` performs a **partial export** — filters the preset's tweaks to a given subset of `TweakID`s and marks the metadata as `partial` with the `included` list |
| `translator.py` | language switching (`os.execl` restart), RTL fixes, `.ts/.qm` pipeline via pyside6-lupdate/lrelease |
| `plist_handler.py` / `xml_handler.py` | plist key writes; namespace-aware XML/caml value setters matching on `nuggetId`/`id` (hardened `eval` for `nuggetOffset` equations) |
| `video_handler.py` | ffmpeg/opencv video→CAML conversion for video wallpapers (400-frame limit) |
| `files_handler.py` / `path_handler.py` | bundled-resource access, Windows path fixes |
| `web_request_handler.py` | update checks against the GitHub releases API |
| `nugget_logger.py` / `aar.py` | logging setup; `.aar` assembly (`wrap_in_aar`) |

## Conventions

- **Errors**: `NuggetException(message, detailed_text)` for user-facing
  failures. Connection/locked classification lives **once** in
  `src/exceptions/device_errors.py` (`is_device_locked_error`,
  `is_connection_error`) and is imported (aliased) by other modules, feeding
  the retry loops (`min(2**attempt, 15)s` connection backoff; Phase 3 restore
  uses 18 × fixed 3 s for transient errors only).
- **Logging**: unified stdlib logging on the `GoldenNugget` logger hierarchy.
  `src/restore/protective.py` exports `log_info/log_warn/log_error` thin wrappers
  around `logging.getLogger("GoldenNugget.protective")` (console + rotating
  session file; WARNING+ falls back to stderr headless) — the legacy
  `/tmp/goldennugget_log.txt` files are gone. `GOLDENNUGGET_LOG_FILE` overrides
  the stdlib `setup_logging` path (`gui/logger.py` respects both the env var and
  an AppData default); `--debug` on `main_app.py` upgrades to DEBUG + captures
  pymobiledevice3.
- **i18n**: registry titles use `QT_TRANSLATE_NOOP("Nugget", …)` at definition
  time and are evaluated with `QCoreApplication.translate("Nugget", …)` at
  render time; other UI strings translate inline. Catalogs are crowdsourced in
  the gNugget-i18n submodule and synced by CI (note: the `i18n/` submodule may
  be unchecked out locally).
- **Kill switches / env**: `GOLDENNUGGET_NO_BACKUP_CACHE`,
  `GOLDENNUGGET_SKIP_PB_BACKUP`, `GOLDENNUGGET_MIN_FREE_GB`,
  `GOLDENNUGGET_CACHE_REFRESH_SECS`, `GOLDENNUGGET_BACKUP_STALL_SECS`,
  `GOLDENNUGGET_PB_SPARSE`, `GOLDENNUGGET_KEEP_SPARSE`, `GOLDENNUGGET_LOG_FILE`.
- **Testing**: offline regression for the backup cache in
  `tools/test_protective_cache.py`, cache placement in
  `tools/test_cache_placement.py` and the backup progress labels in
  `tools/test_backup_category.py` (no device needed); smoke run =
  `QT_QPA_PLATFORM=offscreen python main_app.py --test-mode`. `tools/` also
  holds device operation utilities (backups, syslog capture, sparse inspection).


## awesomeUI widget library

Shared widgets now come from the vendored `awesomeui/` package, sourced from
`~/Projects/awesomeUI/awesomeui`. It contains the theme-aware controls, standalone
Sidebar and other independent widgets, PhoneFrame, MultiComboBox, and
ResizableImageLabel. It imports only PySide6 and the standard library.
`src/gui/widgets.py` binds it to GoldenNugget's existing theme manager, `t()`,
icon renderer, and lazy visible-widget theme connections. Pages import shared
controls through this adapter. `src/gui/ios/components.py` retains the
application's input/summary dialogs and compatibility exports. The phone-frame
and Designer custom-element modules also retain compatibility imports.

MainWindow replaces the generated sidebar at runtime with awesomeUI Sidebar;
existing `ui.*PageBtn` references point to its items so feature gating and page
callbacks use the same controllers. The generated Designer module is unchanged.
The full-screen iOS layout and persisted theme/accent behavior are preserved.
Settings → Appearance → Show Sidebar enables navigation alongside the iOS pages
without switching layouts or leaving the current page. It is off by default,
applies immediately, and persists as `ui/show_sidebar` in the app settings.
Application-specific pages, safety dialogs, restore progress and device logic
remain owned by GoldenNugget; they compose the shared controls.

Update the library with `python3 tools/sync_awesomeui.py` (optional `--source
/path/to/awesomeUI`), then verify with `--check`. The manifest records working-tree
SHA-256 hashes as well as the source commit. Runtime and frozen builds use the
checked-in copy, with no sibling-checkout or pip-install requirement. PyInstaller
collects the statically imported modules and ships the upstream license. Include
`awesomeui/controls.py` when running translation extraction; its original
translation contexts are preserved.


## Performance implementation notes (2026-10-23)

Payload writers use `src/utils/payload.py` for bounded streaming, SHA-1 and
atomic replacement without modifying hardlinked snapshots. Injection accepts
path-backed sources; sparse backups and Live Photo/AAR creation stream files.
Prune inventories once, retains a separate post-injection safety verification,
and optionally hands its max-inode result to the immediately following injector.
Recovery working copies stay on the source volume. Snapshot metadata uses
independent clones when supported, and generation replacement retires the old
tree for background cleanup while preserving rollback/crash recovery.

AFC uses at most four file/metadata tasks only when the client exposes its
packet demultiplexer and write lock; legacy clients stay sequential. Disk work
runs outside the event loop, and cancellation drains active disk operations
before handles close. Pause/reconnect occurs between completed transfer batches.
Completeness checks reuse parent-directory metadata only within a fresh pass;
there is no persistent cached safety verdict. Normal Phase 5 uses the verified
current media set; manual recovery retains the full historical-store default.

CAML keeps indexed, reusable transition trees and bounded static-layer caches.
The existing HSL preview approximation operates on raw RGBA without PNG or a
redundant color-space roundtrip. ZIP-backed tendie assets are lazy with a bounded
shared byte cache. GUI archive work uses file workers; the icon catalog only
creates cards near the viewport. Autosave captures immutable data, debounces
changes, writes atomically in the background and flushes on shutdown.

See `docs/PERFORMANCE_CHANGES.md` for the complete audit mapping, measurements
and remaining filesystem/device-dependent costs. Run
`python3 tools/run_tests.py test_performance_regressions` for the new offline
invariants in addition to the existing AFC/backup/GUI suites.


## Restore and state boundaries (October 2026 refactoring)

The public entrypoints remain compatible; their responsibilities now live in
smaller components. The implementation/status map and measurements are in
[REFACTORING_CHANGES.md](REFACTORING_CHANGES.md).

- `restore/verification.py`: `VerificationResult` distinguishes verified,
  unavailable and failed. `protective.verify_backup_payloads` keeps the legacy
  missing-path list on success and **raises** when verification cannot run.
  `PruneResult` exposes removal counts and the optional inode hint explicitly.
- `restore/recovery.py`: common prune/inject/verify preparation for normal apply
  and GUI/CLI recovery. Normal apply sets `require_media_complete=True` before
  any prune; manual rescue keeps a separate policy for available media.
- `restore/context.py` and the phase helpers in `restore/restore.py`: options,
  current connection ownership, sparse delivery, protective restore and final
  reboot/media/setup steps. Reconnect replacements are published on exceptions
  too, so cleanup closes the current client.
- `restore/backup_store.py`: local working copies, snapshots, regeneration and
  payload inventory. Metadata remains independently copied; payloads can be
  hardlinked. `protective.py` re-exports the established public helpers.
- `restore/device_link_adapter.py`: idempotent compatibility shims for the
  pinned mobilebackup2 client. `restore/media_store.py` owns the AFC marker and
  local path verification; `afc_transport.py` owns capability detection/types.
- `utils/async_disk.py`: initializes the canonical executor on Python 3.15,
  including standalone recovery imports. Mutating disk calls join their worker before propagating
  cancellation, including repeated cancellation. Rollback must not race a
  still-running copy/prune/injection.
- `controllers/tweak_compiler.py`: explicit compilation dependencies,
  registered handlers and owned `TweakArtifacts`; encryption/device execution
  remains in DeviceManager. Temporary payload paths live through restore.
- `tweaks/store.py`: subscriptions, batch notifications and injected service
  stores. The GUI retains the default shared store. `PresetManager.snapshot()`
  returns detached serializable state for background writers.
- Preset repository, validation and transactional application are separated in
  `preset_repository.py`, `preset_codec.py`, `preset_apply.py`.
- `gui/autosave.py` schedules writes and relays worker notifications into Qt;
  `controllers/autosave_state.py` tracks revisions/errors. `gui/dialogs/file_task.py`
  limits local work to two worker threads and 64 admitted jobs. Mandatory writes
  drain on exit; previews support cooperative cancellation.
- Template metadata/package resources and the Qt editor are separate. Legacy
  option GUI adapters remain supported. `PatchSession` batches ordered setter
  edits and flushes before replace/delete/rename operations.
- Mutable CAML edits use `CADocument.edit()` or `touch()` to invalidate caches.
  The decoded image LRU has a 64 MiB budget; this is not a total process memory
  limit and does not cap a currently needed oversized image.

Regression command: `python3 tools/run_tests.py test_refactoring_regressions`.
