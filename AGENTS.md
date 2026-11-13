# GoldenNugget Async Operations

> Full codebase documentation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Linux Releases & the glibc Floor (CI + compile.py)

**The released x86_64 Linux bundle must start on glibc >= 2.34** (Ubuntu 22.04,
Debian 12, RHEL 9, Mint 21). Users reported "GoldenNugget doesn't work on
Linux" for every release built after the Python 3.15 swap because
`actions/setup-python` installs the RUNNER-NATIVE CPython: its `libpython`,
`lib-dynload` extension modules and the libraries PyInstaller copies from the
host (libxkbcommon, libmvec, libuuid, …) all demanded GLIBC_2.38/2.39, while
every shipping wheel sat far lower (PySide6 x86_64 = manylinux_2_34). The
bundle then died at start on older distros with
`GLIBC_2.38 not found … required by libpython3.15.so.1.0`.

The guarantee is structural, enforced by CI:

- **build-linux runs INSIDE `quay.io/pypa/manylinux_2_34_x86_64`** (AlmaLinux
  9 / glibc 2.34). Everything PyInstaller collects from the build environment
  is therefore ≤ 2.34 by construction. Python comes from
  **`uv python install 3.15`** (python-build-standalone, glibc 2.17 target),
  NOT from setup-python — do not reintroduce it in the Linux jobs.
- **`tools/check_glibc_floor.py` gates the result** (`--floor 2.34`
  default): it parses each ELF's `.gnu.version_r` (no `strings`-style text
  sniffs — they false-positive and false-negative) and fails CI when any
  bundled file would not load on the floor distro. The ARM job keeps
  `--floor 2.39` because PySide6's aarch64 wheel is manylinux_2_39 — the
  native `ubuntu-24.04-arm` runner stays there on purpose.
- **compile.py removes `libgcc_s.so.1` from the bundle** (post-build, Linux
  only): it is a manylinux-policy whitelisted SYSTEM runtime (gcc-12-base on
  Debian, libgcc on RHEL — universally present), and bundling the build
  container's copy pushed the floor to 2.35 for nothing.
- **compile.py adds `src/gui/liquid/assets`** to the bundle (all platforms):
  dock/notifications/experience load `more.svg`/`bell.svg`/`usb.svg` from
  `Path(__file__).parent/'assets'` at runtime, PyInstaller's analysis follows
  only imports, and every release to date rendered those buttons icon-less
  (Qt warnings "Cannot open file …/liquid/assets/*.svg" in a frozen app).
  It is a real bug on EVERY platform, not just Linux.
- PySide6 6.12's own wheels define the 2.34 floor; if a bumped dependency
  raises it (e.g. PySide6 6.13+ aarch64-style), decide DELIBERATELY: bump the
  floor + `DEFAULT_FLOOR` in the gate together, never silently.

Verified end to end (Nov 2026): a container-built bundle passes the gate (0
offenders) and launches (`GoldenNugget launched.`) on Ubuntu 22.04 with a
minimal desktop stack, where both released 9.6.2 and 9.7.5 die with
`GLIBC_2.38 not found` before any window exists.

This document describes the background threads, async backup/restore operations, and error handling used in GoldenNugget.

## Backend is Qt-free (hard rule, `src/utils/`)

Everything outside `src/gui/`, `src/qt/` and `main_app.py` — `src/controllers`,
`src/devicemanagement`, `src/restore`, `src/tweaks`, `src/utils`, `src/cli`,
`src/exceptions` — must import **no Qt** (`PySide6`, `shiboken6`, `PyQt*`), not
even lazily at module import. The CLI, the backup/restore engine and the tweak
compilers have to work on a machine without Qt. Guard:
`python tools/test_backend_qt_free.py` imports every backend module in a
subprocess with Qt blocked; any hit fails the test.

Replacements (all under `src/utils/`, all Qt-free):

- `paths.py` — `app_data_dir()` / `cache_dir()` / `generic_*_dir()` /
  `ensure_dir()`. The app owns ONE folder per platform, named `gnugget`:
  `~/Library/Application Support/gnugget` on macOS, `%APPDATA%/gnugget` on
  Windows, `$XDG_DATA_HOME/gnugget` elsewhere (the cache follows the same rule
  under `~/Library/Caches`, `%LOCALAPPDATA%`, `$XDG_CACHE_HOME`). The module is
  the single source of truth for every path — never rebuild one by hand.
  `brand_dir(root)` returns _root_ unchanged when it already names the app's
  folder (including the pre-rename `GoldenNugget` names), so a backup volume
  chosen before the rename keeps its existing tree.
  GUI code must not use Qt `QStandardPaths` for app paths: the org/app names
  still answer the pre-rename folder (pinned by `tools/test_storage.py`), so
  every such write recreates the legacy tree and re-triggers the migration
  dialog — route caches through `cache_dir()`, user data through
  `app_data_dir()`.
  `legacy_app_data_dirs()` / `legacy_cache_dirs()` / `legacy_generic_dirs()` are
  the historical locations, used by the migration and by the recovery tools —
  not by normal reads. `tools/test_storage.py` pins all of it.
- `settings.py` — `Settings(app)` store (see below). `src/controllers/settings.py`
  is a thin re-export, so `from src.controllers.settings import Settings` keeps
  working.
- `i18n.py` — `QCoreApplication` stand-in with `translate()`/`tr()` plus
  `QT_TRANSLATE_NOOP`. **Keep those exact call shapes**: `pyside6-lupdate`
  extracts strings by name, not by origin, so backend modules import them from
  here instead of `PySide6.QtCore`. The GUI calls
  `i18n.install_translate(Qt.translate)` in `main_app.py`; when Qt is merely
  loaded in the process (GUI, tests) its translator is used automatically.
- `file_lock.py` (`FileLock` ← `QLockFile`), `observer.py` (`Signal` ←
  `QObject`/`Signal`), `color.py` (`RgbColor` ← `QColor`),
  `alerts.py` (`AlertIcon` ← `QMessageBox.Icon`; the GUI maps both in
  `main_window_mixins._qt_alert_icon`).
- `user_data_migration.py` — the one-time move of the pre-rename folder (see
  "User data folder" below).

**Settings store + migration.** `Settings(app)` writes
`<app data>/preferences/<org>/<app>.json` (`GOLDENNUGGET_PREFERENCES_DIR`
relocates it; `tools/run_tests.py` points it at the per-suite sandbox). On first
use it reads the legacy QSettings data **read-only** — macOS CFPreferences
`~/Library/Preferences/com.<org>.<app>.plist` (keys stored with `.` are mapped
back to `/`), Linux INI in `$XDG_CONFIG_HOME`, Windows
`HKCU\Software\<org>\<app>` — and never rewrites or deletes it, so downgrading
keeps the old values. A JSON store written by a build that still used the
pre-rename `GoldenNugget` folder is read too (and wins, being newer), so an
app that starts before the move does not begin from defaults; an explicit
`GOLDENNUGGET_PREFERENCES_DIR` disables that history. **A read never writes** —
the merged view is persisted by the first `setValue`, which is what keeps a
store opened before the migration (the theme manager) from creating the new
JSON and making the move skip the old one. `Settings` reads through
to the legacy `Nugget` org before `GoldenNugget`; `value(key, default,
type=bool|str|int|float)` keeps QSettings' coercion rules. Do not reintroduce
`QSettings` in backend code, and do not assume `isinstance(x, QSettings)`
anywhere (the GUI's accent/theme managers use the same `Settings` store now).

**User data folder (`gnugget`) + the migration window.** The app used to keep
everything under `GoldenNugget`; it is `gnugget` now (both brand names are
accepted by `brand_dir`, the old ones only as _sources_). Existing installs are
moved once, at startup, by `src/gui/dialogs/data_migration.py`:
`maybe_prompt_migration()` runs in `main_app.py` right after
`configure_appearance` and **before** `Settings("settings")` is constructed, so
nothing has written to the new folder yet. The window is deliberately shaped
like a .dmg installer (black-and-white icon left, progress bar in the middle,
colour icon right, Migrate button under the bar); the move itself is Qt-free
`src/utils/user_data_migration.py`:

- `plan_migration()` is read-only — it lists the top-level entries, their file
  count and size, so the window can show the cost before the user commits.
- `run_migration()` `shutil.move`s every entry (a same-volume move is an
  instant rename, so the multi-GB backup cache costs nothing extra). It never
  overwrites: an entry that already exists in the new folder is skipped and
  reported ("the user's current file wins"). Duplicate destinations across the
  two legacy trees are skipped the same way, the nested one winning.
- The old _doubled_ layout (`GoldenNugget/GoldenNugget/backup_cache`,
  `History`, `LastTheme`, `IconThemes`) is laid **over the top** of the new root
  instead of landing in a `gnugget/GoldenNugget/` subfolder.
- The loose generic folders (`Application Support/PosterBoard`, `Backups`,
  `StatusBar`) move into `gnugget/<name>`; the cache folders (`Caches/
GoldenNugget`) move to `Caches/gnugget`.
- Emptied legacy roots are removed afterwards; anything that was skipped or
  failed keeps its folder alive. A failed entry is reported per file and left
  in place.
- Dismissing the window is remembered for that exact plan in
  `<app data>/.migration_declined` (signature = the planned
  source→destination pairs), so it does not nag, and Settings → Backup →
  "Move User Data" re-opens it (`migrate_now()`). A changed plan (new files in
  the old folder) asks again. `GOLDENNUGGET_NO_DATA_MIGRATION=1` skips the
  window entirely (headless/CI) and `--test-mode` never shows it.
- Everything the user could still need is copied/moved, never deleted, and the
  old `~/Library/Preferences/com.goldennugget*.plist` files stay untouched.
  Offline suites: `tools/test_user_data_migration.py`,
  `tools/test_data_migration_dialog.py`.

**No dialogs in the backend — use ports.** Questions are injected by the GUI:
`src/gui/dialogs/posterboard_prompts.py` (`install()` wires the PosterBoard
import prompts into `posterboard_tweak`) and
`src/gui/dialogs/hotload_warning.py` (`confirm_flagged`) — `hotload.py` only
returns the rule. Adding a backend prompt means adding a port here, never
`from PySide6... import QMessageBox` in `src/`.

**Presentation lives in the GUI.** The CAML/tendie preview renderer is
`src/gui/preview/` (`ca/`, `tendie_preview.py`); language switching is
`src/gui/translator.py` + `src/gui/live_translation.py`; the template-option
_models_ stay in `src/tweaks/posterboard/template_options/` while their widgets
are `src/gui/template_option_editors.py` (`create_interface`, `bind_previews`,
`update_preview`). Keep model logic out of the editors and widget code out of
the models.

**Crash handling is split.** `src/exceptions/crash_handler.py` owns
classification (`_classify`), the report/issue-body builders, the startup
banner, the faulthandler dump and `sys.excepthook`; it presents through a
pluggable presenter (`set_presenter`) and prints to stderr when there is none
(CLI). `src/gui/crash_ui.py` holds `CrashDialog`, `CrashHandlerApp`,
`install_notify_guard`, the Qt message handler and `show_error_dialog`, and
`install_crash_handler()` there installs both halves. GUI code that needs the
dialog imports it from `src.gui.crash_ui`.

**CLI is headless.** `src/cli/common.py::bootstrap()` only builds `Settings`;
there is no `QApplication` and no offscreen-platform juggling.

## Window Frame (src/gui/window_chrome.py)

The main window is **frameless** (`Qt.FramelessWindowHint`): the OS paints no
title bar, so the app's surface reaches the window edge on macOS, Windows and
Linux alike. `MainWindow.__init__` installs the chrome right after
`setCentralWidget(shell)`; everything the native frame used to do is drawn and
handled by `WindowChrome`:

- **Buttons** — close / minimize / zoom, painted by `WindowButton` and floated
  over the window's top-left corner (`CONTROLS_LEFT`, `CONTROLS_TOP`), raised on
  every relayout so no page can ever cover them. The style follows the OS
  (`CHROME_STYLE`, picked from `QGuiApplication.platformName()`) — **macOS**
  keeps the traffic lights up there, while **Windows and Linux** get the
  desktop's own caption-button look: right-aligned flat `44x32` buttons with
  hover wash (`close` lights up native red), placed by `_relayout` in the
  top-right corner (`FLAT_EDGE_INSET` 8px), the version label moves to the
  top-left and `LiquidNavBar.set_trailing_inset` (`CONTROLS_TRAILING_INSET`)
  reserves their room where mac reserves `set_leading_inset`. The glyphs appear on hover and
  the group greys out while the window is inactive (`isActiveWindow()`), which
  is why a `widget.grab()` screenshot always shows them grey.
- **Name** — `WindowChrome.title` draws the window title where a title bar puts
  it, but only while the shared header is hidden (the home page is full
  screen). Pages with the header already name themselves. It follows
  `WindowTitleChange` and is `WA_TransparentForMouseEvents`, so it never eats a
  drag.
- **Zoom** — `toggle_zoom()` fills `screen().availableGeometry()` instead of
  `showMaximized()`: a maximized _frameless_ window covers the Windows taskbar,
  and this behaves identically on every desktop. The previous geometry is
  restored on the way back, and the rounded mask is dropped while zoomed,
  maximized or full screen.
- **Rounded corners** — `_apply_shape()` asks the OS first
  (`src/gui/native_corners.py`) and falls back to a mask built by
  `rounded_region()` (`CORNER_RADIUS`). The clip is dropped while
  zoomed/maximized/full screen, where it would cut the window's edges.
  - _Native_ — a radius belongs to the window **frame**, which a frameless
    window does not have and Qt has no API for, so the two platforms that
    expose one are driven directly: **macOS** clips the `NSWindow` content
    view's layer (`cornerRadius` + `masksToBounds`, through `ctypes`/`objc` —
    antialiased, and the window keeps its native drop shadow) and **Windows 11**
    rounds via `DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)`, whose
    failure on Windows 10 is the signal to keep the mask.
    `native_corners.prepare_window()` must run at install time: the macOS clip
    only shows through if the window is non-opaque, and Qt applies
    `WA_TranslucentBackground` when it _creates_ the native window. Setting the
    attribute later leaves it opaque (verified).
  - _Guard_ — the backend is chosen by **platform plugin name**
    (`QGuiApplication.platformName()`, `"cocoa"`/`"windows"`), not by
    `sys.platform`: under `QT_QPA_PLATFORM=offscreen` `winId()` is a made-up
    number, and handing it to `objc_msgSend` aborts the process inside AppKit
    (an Objective-C exception Python cannot catch). Every native call is also
    wrapped, and reports failure instead of raising.
  - _Mask (fallback)_ — exact in shape but a 1-bit `QRegion`, so that edge is
    hard. The region samples the arc itself (`CORNER_STEPS` per corner) because
    `QPainterPath.toFillPolygon` flattens a 10px corner into four vertices — a
    chamfer instead of a circle — and it is built one pixel past the window
    because a region counts a pixel as inside only when its centre is.
- **Drag** — the shared header, the sidebar, and the blank strip across the
  window's top (`DRAG_STRIP_HEIGHT`) move the window. `_accepts_press()` walks
  up to any button/slider/input/list and refuses the drag, so a control is
  never swallowed. `startSystemMove()` is asked first (window snapping, edge
  docking); this macOS box returns False, so the manual `move()` fallback is
  not optional.
- **Resize** — `RESIZE_MARGIN` px of every edge/corner start a resize, with the
  matching cursor from `cursor_for_edges()`. `startSystemResize()` is tried
  first; otherwise `_resize()` drives `setGeometry`, clamped to the window's
  minimum size. The edge cursor is refreshed by a 120 ms poll
  (`_poll_cursor`) — turning on mouse tracking across the whole widget tree
  just for the border would tax every page's mouse handling.
- **Insets** — surfaces in the top-left corner leave room for the buttons:
  `LiquidNavBar.set_leading_inset(CONTROLS_INSET)`,
  `NavigationSidebar.set_top_inset(TITLE_BAR_HEIGHT)` and, for pages that reach
  the window's top edge, `set_top_inset(CONTENT_TOP_INSET)` (currently only
  `IOSHomePage`, via `CONTENT_TOP_INSET + its own CONTENT_TOP_MARGIN`).
  `WindowChrome` calls them from `install_window_chrome(..., pages=...)`.

**Never call `QWidget.window()` here.** Several pages keep their own
`self.window` attribute, which shadows the Qt method, so `widget.window()`
raises `TypeError: 'MainWindow' object is not callable`. `_top_level()` walks
the parent chain instead, and `tools/test_window_chrome.py` fails if a
`.window()` call reappears. Same file pins the mask, the edge math, the
drag-target rules, the title visibility and the button wiring.

## Startup & Lazy Pages (src/gui/main_window.py)

Startup is measured until `QApplication.exec` is entered; the window must be
on screen as early as possible. Three rules keep it that way — each of them
used to cost 0.3-0.5 s on its own:

- **The window stylesheet is applied ONCE, before the pages exist.**
  `QWidget.setStyleSheet` re-polishes every descendant, so a second application
  after the tree is built walked thousands of widgets again. `_apply_global_stylesheet`
  therefore runs right after `self.ios_pages` is created and composes the base
  template (`t("global")`) with the liquid overlay
  (`src/gui/liquid/overlay.py:liquid_overlay_css()` — inputs, scrollbars,
  sliders). `LiquidExperience._style` must NOT touch the window stylesheet;
  it only restyles the nav bar. Same reason `ios_pages.setStyleSheet(t("page_bg"))`
  lives before the pages.
- **Only the home page is constructed up front.** `_reserve_page(name, factory)`
  adds a placeholder widget to `ios_pages` (keeping the numeric page indices
  used by `_ios_page_titles`, `_nav_right_actions` and `set_ios_page` stable)
  and records the factory in `_lazy_pages`. The first access builds the page
  into its reserved slot:
  - `self.ios_settings` / `getattr(window, "ios_presets", …)` etc. build on
    access through `MainWindow.__getattr__` → `_build_lazy_page`;
  - `set_ios_page(index)` resolves the slot through `page_at(index)`, so
    navigation always shows the real page, never the placeholder;
  - `built_page(name)` is the _probe_ form — it returns None instead of
    building. Use it wherever code only wants to know whether a page exists
    (device gate, close/exit worker checks, `refresh_catalog_badge`);
  - `call_on_page(name, method, *args)` applies a startup call to a page that
    may not exist yet (it is replayed when the page is built) —
    `LiquidExperience._clean_home` uses it for `ios_apply.set_status_only`.
  - `_nav_right_actions` stores **callables**, never bound methods, or
    registering the action would build PosterBoard/Templates/Passcode Theme.
  - The Apply page's live busy state is re-applied when it is built
    (`_build_lazy_page`), because `_update_device_gate` skips missing pages.
  - `_prewarm_control_pages` (Tweaks + Daemons content) runs from a
    1200 ms single-shot **child QTimer** so that work lands after the window
    has painted (a bare `QTimer.singleShot` with a bound method would call into
    a deleted window when the app is closed within that second).
- **Nothing on the startup path may construct a page just to read a widget.**
  The liquid workspace panel used to copy its language list from
  `window.ios_settings.lang_drp`; it now fills the combo from
  `available_languages` (the same table) and only delegates to the Settings
  page when that page already exists.

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
  `theme_pixmap(resource, color, size, dpr)` (scales the SVG _before_ tinting, so
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
- The self-built shell stands in for the deleted Qt Designer file:
  `self.ui` is `src/gui/app_shell.py::ShellUI` (parked device bar + sidebar
  mount + content-stack slots; any attribute beyond the built ones resolves
  lazily to an inert QWidget stub). Do not hand a raw `QWidget()` bag where
  a widget attribute is used for real state (`text()`/`icon()`); park new
  chrome widgets explicitly in `ShellUI`.
- **The preset popup is a child widget, never a window.** `PresetPopup`
  (`src/gui/ios/preset_menu.py`) parents itself to the main window and draws
  over it with `raise_()`. Do **not** turn it into a top-level `Qt.Popup` or
  `Qt.Tool`: a Popup relies on Qt's implicit mouse/keyboard grab, which not
  every platform plugin provides (when the grab fails it is silently dismissed
  right after `show()`), and _any_ top-level window gets its own decorations
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
- **Classic UI is fully removed (was TEMP)** — `src/qt/mainwindow.ui` AND its
  generated `mainwindow_ui.py` are deleted; `self.ui` is
  `src/gui/app_shell.py::ShellUI`, the classic home/daemons pages are gone
  (only `available_languages` survives under `src/gui/pages/`), and the
  Settings "iOS-style Interface" switch is hidden with
  `ThemeManager.load_theme` always returning `IOS`. There is **no sidebar
  mode**: the optional `ui/show_sidebar` navigation panel, the Settings
  switch, the first-launch `InterfacePickerDialog` and its preview code are
  all gone — `ui/interface_choice_done` is only stamped so an old install is
  never asked again (and the Modern home always carries the bottom dock).
  The sidebar still builds (`NavigationSidebar`) because navigation/gating
  code manages its items through the old `ui.<name>Btn` names, but it stays
  parked/hidden. Reviving Classic means rebuilding the Designer stack from
  scratch; the dead `CLASSIC` branches in `main_window_mixins` are
  unreachable but retained.
  Keep the first-run sidebar choice separate from the legacy chrome mode.
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

Tapping _Manage_ on the home-screen preset banner opens `PresetPopup` instead of
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
  single click _selects_ a preset, a **double click applies it** (which restarts
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
**RemotePairing** pairing record — the transport the app needs on iOS 26.4+.
The pairing section is a single button, **"Send Remote Pairing"**.

- Device logic (`mobile_helper.py`) is the only consumer allowed to pair with a
  device whose record is not known yet — everything still goes through
  `lockdown_session`.
- **The export is RemotePairing** (`export_remote_pairing_file()`). It is
  host-initiated and **promptless**: pair-setup runs on
  `com.apple.dt.remotepairingdeviced.lockdown`, i.e. over the lockdown link
  that is already trusted, so there is no Wi-Fi pairing, no PIN, no on-device
  Trust dialog and no **Settings → Developer → Paired Macs** step (the flow
  iLoader/AltStore use). pymobiledevice3 exposes it as
  `RemotePairingLockdownService`; a first pairing ends with
  `RemotePairingCompletedError` (the endpoint closes the link) and a later
  export pair-verifies with the cached key pair instead. `mobile_remote_pairing_xml()`
  writes the app's three keys: the key pair from the service's cached record
  plus `service.identifier` — the UUIDv3-of-hostname the device stores as the
  host's `accountID`, which pymobiledevice3 keeps out of its own record.
  `alt_irk` is **not** written: it is the device's mDNS key, only needed for
  Bonjour discovery, and the phone reaches the device over the tunnel where
  pair-verify uses the key pair alone.
- Delivery rides `HouseArrestService` (`VendContainer`): the record must land
  exactly at `Documents/pairingfile.mobiledevicepairing` (`AppPaths.pairingFile`
  on the app side) — filename and location are contract, not convenience.
  `AppNotInstalledError` is translated into a save-to-disk prompt: the XML is
  already in hand, so the fallback is a plain write (the manual AirDrop route
  when the app is not installed yet).
- **The phone's own record is never overwritten.** On iOS 17+ the app's setup
  guide pairs itself over RemotePairing and writes an `.rppairing` record
  (`identifier`/`private_key`/`public_key`) to the same path; that record uses
  a transport a desktop lockdown record cannot provide, and replacing it left
  the app unpaired (`InvalidVPN` on iOS 26.4+ — the transport check rejects a
  userspace utun VPN). `send_pairing_to_app()` reads the file first and
  `pairing_file_action()` keeps an app-generated record ("kept"); only a
  missing, damaged or old lockdown record is replaced ("delivered"), and the
  dialog reports which happened.
- The **lockdown** helpers (`read_pairing_record()`, `pairing_record_xml()`,
  `export_pairing_file()`) are still there for older systems and other
  callers, but no longer have a button. `read_pairing_record()` returns the
  record **the host already holds** (no re-pair), **completed** with the keys
  the host record cannot carry: it is keyed by its file name, so it has no
  `UDID`, and older records omit `WiFiMACAddress` — both are read from the live
  device (`complete_pairing_record`). The mobile app's lockdown parser
  (`Vendor/MinimuxerCommon/PairingFile.swift`) requires all ten keys and
  rejects the file otherwise. `pairing_record_xml()` dumps it as an **XML
  plist**: the mobile app's importer (`PairingRecord.accept`) only parses UTF-8
  text plists — a binary plist is silently refused there — and refuses
  (instead of writing a dead file) when a `UDID` is still missing. Offline
  suite: `tools/test_mobile_helper_pairing.py`.
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
     extracted DB at `<app data>/PosterBoard/<udid>.sqlite3`.
   - Both are skipped if `GOLDENNUGGET_SKIP_PB_BACKUP=1`.
4. `_apply_tweak_pass()` — generate all tweak files, handle backup encryption, then `start_restore(prepared_backup_root=...)`

### Protective Backup Cache (src/restore/protective_cache.py)

`ProtectiveBackupCache` keeps a per-device master copy of the protective
backup in the persistent app-data store
(`<app data>/backup_cache/master/<udid>`; `<app data>` is the `gnugget` folder
from `src.utils.paths`):

- **Storage location is configurable** — Settings → Backup →
  "Backup/Cache Location" (`backup_storage_dir` in the `Settings("settings")`
  QSettings store; env override `GOLDENNUGGET_BACKUP_DIR` for headless tools
  like `restore_cache.py`). `src/restore/storage.py` is the single source of
  truth: `cache_base()` (backup_cache), `protective_base()` (live backup
  runs), `posterboard_dir()` and `legacy_backups_dir()` all derive from the
  same root so a small system drive (e.g. a 28 GB `C:`) can be relieved by
  pointing them at e.g. `D:\GoldenNugget\` (the app folder is appended there
  only if the root does not already end in a brand name, see
  `src.utils.paths.brand_dir`). Unset → `<app data>/{backup_cache,protective,
PosterBoard,Backups}`. The recovery tools (`apply_worker.py`,
  `restore_cache.py`) also search the pre-rename `GoldenNugget` trees as a
  read-only fallback (recovery of caches that were never migrated).
- **EXPERIMENTAL, ON BY DEFAULT** — the cache engages unless the user turns
  off "Use Fast Backup Cache (Experimental)" in Settings
  (`pref.use_backup_cache`). Cache off → the classic live
  `perform_protective_backup()` / `_backup_posterboard_database()` path runs.
  Kill switch still hard-disables it:
  `GOLDENNUGGET_NO_BACKUP_CACHE=1`.
- **AFC media store** — the bulk photo trees (DCIM, PhotoStreamsData) ride a
  persistent per-device mirror at `<app data>/backup_cache/media/<udid>`
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
  copy the tweaks write to already holds the _tweaked_ values, so restoring a
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
- **Preference sections reset by writing valid empty plists.** The reset
  delivers `PreferenceNullify(plistlib.dumps({}))` — a minimal, valid, never
  zero-byte empty plist — as the whole file (inject.py delivers nullify
  payloads as-is, with no baseline merge and no baseline requirement). This
  is why the reset no longer depends on the backup: a file the device
  received as a NEW file (no manifest row, e.g. SwiftUI.plist) is reset the
  same way as any other — the device parses the empty dict and falls back to
  its defaults. The reset works repeatedly without a re-apply. One wrinkle:
  a managed location and its native twin name the SAME file (the
  `.GlobalPreferences` mirror), so `restore.py::merge_duplicates` keeps the
  Nullify marker when collapsing them — a plist merge would emit a plain
  empty dict that the injector rejects as an unverified reset.
- **Two locations stay keyed removals, never whole-file nullified.**
  `preference_reset_plan` keeps `PreferenceKeyReset` for
  `FileLocation.featureflags` (FeatureFlags/Global.plist carries every
  feature flag on the device — wiping it would undo flags GoldenNugget does
  not own) and `FileLocation.disabledDaemons` (launchd's disabled.plist
  holds services GoldenNugget never disabled). Keyed resets still resolve
  against created-file history: `src/restore/created_baselines.py` persists,
  per device, the last payload delivered as a new file
  (`<app data>/LastApply/<udid>.created.json`, written by `start_restore`
  after a successful restore via the `created_baseline_payloads` ContextVar);
  the injector resolves a keyed reset with no backup row against that record.
- **The reset plan's location set is the union of the record and the
  registry.** `preference_reset_plan` (`src/controllers/default_reset.py`)
  covers both the applied-selection record's locations and the tweak
  registry's static entries for the selected sections: a tweak applied
  before records existed — or whose record an earlier reset consumed — is
  still reset. Dynamic sets stay recorded-only (Daemons: a reset with no
  record raises "no verified reset payload").

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
  unreadable content abort with the payload size recorded for triage — EXCEPT
  `ManagedPreferencesDomain`, where an unreadable/missing baseline degrades to
  whole-payload delivery (recorded in `preference_baseline_creates` + log):
  managed files carry pushed policy, not user data, the tweak/reset payload IS
  the whole intended file, and re-capturing after a retry yields the same
  unreadable payload (issue #85: iOS 26.6 → 27.0.1 upgrade, e.g.
  `mobile/com.apple.Accessibility.plist` / `mobile/com.apple.springboard.plist`),
  so the abort made the apply unrecoverable.

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
- The pre-start Find My wait inside `_restore_once` is bounded: the first
  swallowed failure opens ONE window (`_PHASE3_WAIT_WINDOW_SEC`, 15 min) that
  spans every outer retry attempt; on expiry the last error surfaces as a
  final NuggetException — a wedged device can no longer hang Phase 3 forever
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
  `<app data>/PosterBoard/<udid>.sqlite3`, identical to the apply path.
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

### Global Crash Handler (split: src/exceptions/crash_handler.py + src/gui/crash_ui.py)

- **The Qt-free core** owns classification (`_classify`), the report/issue-body
  builders, the startup banner, the faulthandler dump and
  `sys.excepthook` + `threading.excepthook` (plain worker threads) + a
  `sys.unraisablehook` fallback. It presents through a pluggable presenter
  (`set_presenter`) and prints to stderr when there is none (CLI / early
  startup); installed once at `main_app` import, before the window is built.
- **The GUI half** (`src/gui/crash_ui.py`) owns `CrashDialog`, `CrashHandlerApp`
  (whose `notify` guard routes Qt event-handler/slot exceptions the core would
  otherwise never see), `show_error_dialog` / `report_error` (the presenter),
  the Qt message handler and `install_crash_handler()`, which installs both
  halves. GUI code that needs the dialog imports it from
  `src.gui.crash_ui` — never from the core.
- On an uncaught exception it shows a `CrashDialog` with a **"Copy Error"**
  button (copies the full traceback to the clipboard) and a **"Restart App"**
  button; `KeyboardInterrupt` still exits normally.
- **NEVER build/exec a dialog from a worker thread — the handler is
  thread-aware by contract.** A crash reported off the GUI thread (exception
  escaping a QThread run(), a slot PySide executed in the emitter's thread)
  must not instantiate `QWidget`/`NSWindow` there: on macOS that is an instant
  `NSInternalInconsistencyException` ("NSWindow should only be instantiated
  on the main thread!") aborting the whole process — the crash handler itself
  used to BE that abort. The core's `_handle_crash` checks
  `_on_main_thread()` and never runs `os.execv` for a worker-thread crash;
  the GUI's `show_error_dialog` / `_on_gui_thread()` post a thread-safe
  `_CrashEvent` into `CrashHandlerApp.event()` (via `QApplication.postEvent`)
  where the dialog is built and exec'd. Keep new callers of
  `show_error_dialog` on that contract; a widget may only be created after
  `_on_gui_thread()` says yes (or after a queued event).
- Never raises: the crash handler safely falls back to stderr if no
  `QApplication` exists yet.

### Backup Encryption Handling

- Checks `get_will_encrypt()` before operations — but only ONCE per apply on the
  normal path: Phase 0's backup establishes the state, `_apply_tweak_pass`
  reuses `_known_backup_encryption` instead of opening a second lockdown
  session, and `perform_protective_backup` auto-resolves `include_keychain`
  from the same query unless it is pinned explicitly.
- **Windows-safe encrypted-manifest prune shim**
  (`_install_encrypted_manifest_prune_shim` in `src/restore/protective.py`,
  issue #87): upstream `Mobilebackup2Service.prune_backup_manifest` (10.7.1)
  keeps a `NamedTemporaryFile(delete=True)` OPEN while re-opening the same
  path by name — on Windows that is `PermissionError: [Errno 13]` (temp files
  get `O_TEMPORARY`), invisible on POSIX so mac/CI never saw it. The shim
  replaces the whole classmethod: `delete=False`, close before use, `unlink`
  in `finally`. Regression suite: `tools/test_encrypted_manifest_prune.py`.
  Drop the shim when a pymobiledevice3 release carries the upstream fix.
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

| Operation                     | Max Retries | Backoff                  | Errors Handled                |
| ----------------------------- | ----------- | ------------------------ | ----------------------------- |
| Protective Backup connect     | 5           | 2s, 4s, 8s, 15s          | Connection                    |
| PosterBoard Backup            | 3           | 2s, 4s                   | Connection, Device Locked     |
| Phase 2 Sparse Restore        | 2           | 25s once (if drop at 0%) | Transient                     |
| Phase 3 Restore               | 18          | 3s fixed                 | Transient (service not ready) |
| InstallationProxy (AppDomain) | 3           | 2s, 4s, 8s               | Any Exception                 |

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
    |     |_ extract WAL-merged sqlite -> <app data>/PosterBoard/<udid>.sqlite3
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

# Maintainer Notes

NO hardcoded lines in tests or any other stuff.
Example is "~/Projects/GoldenNugget" in test
Always lift project via ruff and pyright
