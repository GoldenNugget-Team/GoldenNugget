import logging
import sys
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QCoreApplication

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    # Non-*/shiboken-less environments (some frozen builds) always report valid.
    _shiboken_is_valid = lambda _obj: True


def _still_running(worker) -> bool:
    """True when ``worker`` is a live QThread still executing.

    These workers all wire ``finished -> deleteLater``, which frees the C++
    object before the window ever drops its stored reference — so a saved
    worker can already be a dead shiboken wrapper. Probing that wrapper
    raises ``RuntimeError`` ("Internal C++ object already deleted"), which
    must never escape from a closeEvent.
    """
    if worker is None:
        return False
    try:
        if not _shiboken_is_valid(worker):
            return False
        return worker.isRunning()
    except RuntimeError:
        return False

from src.controllers.preset_manager import PresetManager
from src.gui.app_shell import ShellUI
from src.gui.translator import Translator

if TYPE_CHECKING:
    from src.devicemanagement.device_manager import DeviceManager

from src.gui.ios.apply import IOSApplyPage
from src.gui.ios.catalog import IOSCatalogPage
from src.gui.ios.connect_placeholder import ConnectDevicePlaceholder
from src.gui.ios.daemons import IOSDaemonsPage
from src.gui.ios.home import IOSHomePage
from src.gui.ios.icon_themes import IOSIconThemesPage
from src.gui.ios.passcode_theme import IOSPasscodeThemePage
from src.gui.ios.posterboard import IOSPosterboardPage
from src.gui.ios.presets import IOSPresetsPage
from src.gui.ios.settings import IOSSettingsPage
from src.gui.ios.statusbar import IOSStatusBarPage
from src.gui.ios.templates import IOSTemplatesPage
from src.gui.ios.theme_manager import ThemeManager
from src.gui.ios.tweaks import IOSSectionPage, IOSTweaksPage
from src.gui.main_window_mixins import (
    ApplyMixin,
    DeviceBarMixin,
    NavigationMixin,
    SettingsMixin,
)
from src.gui.theme import ColorThemeManager, t, theme_icon, themed_stylesheet
from src.gui.thread_workers.apply_worker import DeviceMonitorThread
from src.tweaks.registry import Section

# Classic chrome (device bar + sidebar + home toolbar) uses monochrome white
# bootstrap SVGs; they must be recolored on every theme change.
_CLASSIC_THEMED_ICONS = {
    "phoneIconBtn": ":/icon/phone.svg",
    "refreshBtn": ":/icon/arrow-clockwise.svg",
    "homePageBtn": ":/icon/house.svg",
    "gestaltPageBtn": ":/icon/iphone-island.svg",
    "euEnablerPageBtn": ":/icon/geo-alt.svg",
    "statusBarPageBtn": ":/icon/features/status-bar.png",
    "passcodePageBtn": ":/icon/features/passcode-theme.png",
    "springboardOptionsPageBtn": ":/icon/app-indicator.svg",
    "internalOptionsPageBtn": ":/icon/hdd.svg",
    "liquidGlassPageBtn": ":/icon/liquid-glass.svg",
    "daemonsPageBtn": ":/icon/features/daemons.png",
    "iconThemesPageBtn": ":/icon/features/icon-themes.png",
    "presetsPageBtn": ":/icon/folder.svg",
    "applyPageBtn": ":/icon/check-circle.svg",
    "posterboardPageBtn": ":/icon/features/posterboard.png",
    "templatesPageBtn": ":/icon/file-earmark-text.svg",
    "settingsPageBtn": ":/icon/gear.svg",
    "mainDevBtn": ":/icon/github.svg",
    "discordBtn": ":/icon/discord.svg",
    "starOnGithubBtn": ":/icon/star.svg",
    "leminGithubBtn": ":/icon/github.svg",
    "leminTwitterBtn": ":/icon/twitter.svg",
    "leminKoFiBtn": ":/icon/currency-dollar.svg",
}

# Classic home "credits" buttons that hardcode dark borders in the .ui.
_CLASSIC_BORDERED_BTNS = [
    "helpFromBtn", "posterRestoreBtn", "snoolieBtn", "disfordottieBtn",
    "mikasaBtn", "wind0ws11AeroBtn", "translatorsBtn", "libiBtn",
    "duyBtn", "jjtechBtn", "qtBtn",
]

class _PageSpinner(QtWidgets.QWidget):
    """Rotating-arc busy indicator for the first-open loading screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self._angle = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):
        self._timer.start(40)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, event):
        # The accent is read at paint time: no retheme wiring needed and the
        # indicator always shows the current accent. Theme slots are hex
        # strings, so a QColor has to be built here (QPen takes a color
        # string only solo, without the width).
        #
        # Paint is guarded: a raise inside paintEvent poisons the whole
        # backing store on Windows (cascading "painter not active" until
        # restart), so the spinner must never contribute one.
        try:
            pen = QtGui.QPen(
                QtGui.QColor(ColorThemeManager.instance().colors.accent), 2.5)
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(pen)
            painter.drawArc(self.rect().adjusted(3, 3, -3, -3),
                            self._angle * 16, 300 * 16)
        except Exception:
            logging.getLogger("GoldenNugget.gui").exception("loading spinner paint failed")


class PageLoadingSlot(QtWidgets.QWidget):
    """Placeholder stack slot of a reserved page: spinner + Loading text.

    While a page is not built yet this is what the user sees on first
    navigation; the real page replaces it in the same slot (MainWindow.
    _finish_page_build) and stays cached there afterwards.
    """

    SLIDE_PX = 16  # intro lift: the content slides up by this while fading in

    def __init__(self, parent=None):
        super().__init__(parent)
        # One animated wrapper: the slot centers it, and showEvent fades the
        # wrapper in while it settles SLIDE_PX upward. The spinner is shared
        # (keeps one QTimer) and the label sits inside the same wrapper.
        self._body = QtWidgets.QWidget(self)
        body_layout = QtWidgets.QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(_PageSpinner(), 0,
                              QtCore.Qt.AlignmentFlag.AlignHCenter)
        body_layout.addSpacing(10)
        self.label = QtWidgets.QLabel(
            QCoreApplication.translate("Nugget", "Loading… Please Wait"))
        # A styled QLabel is a styled-background widget and would paint a
        # dark box over the themed page — keep it transparent (styling
        # contract) and let the window-wide color rule pick the text color.
        self.label.setStyleSheet("background-color: transparent;")
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        body_layout.addWidget(self.label, 0,
                              QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(self._body, 0)
        layout.addStretch(2)

    def showEvent(self, event):
        super().showEvent(event)
        # One event-loop pass so the layout has placed _body; the intro
        # animates from a true position, not (0, 0).
        QtCore.QTimer.singleShot(0, self._play_intro)

    def _play_intro(self):
        """Let the loading content settle upward (no opacity effect: one that
        sits over a 40 ms-updating spinner re-renders its source pixmap
        mid-paint on Windows and poisons the backing store with
        "painter not active" spam).

        Uses the house ``animate`` helper, so the accessibility
        ``liquid_reduce_motion`` switch plays it instantly.
        """
        from awesomeui.liquid.motion import animate
        body = self._body
        y = body.y()
        body.move(QtCore.QPoint(0, y + self.SLIDE_PX))
        animate(self, y + self.SLIDE_PX, y,
                lambda value: body.move(QtCore.QPoint(0, round(value))),
                duration=280)


class MainWindow(QtWidgets.QMainWindow, DeviceBarMixin, SettingsMixin,
                 NavigationMixin, ApplyMixin):
    IOS_CONTENT_MAX_WIDTH = 1200

    def __init__(self, device_manager: "DeviceManager", translator: Translator):
        super(MainWindow, self).__init__()
        self.device_manager = device_manager
        self.translator = translator
        self.settings = self.translator.settings
        self.ui = ShellUI()
        from src.gui.widgets import NavigationSidebar
        self.ui.sidebar.hide()
        self.ui.sidebar = NavigationSidebar(self.ui, self)
        # Window floor: exactly 1000x600 (min == max). Keep that as the
        # minimum, but let the user grow it: at 600px most pages scroll.
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Preferred)
        self.noneText = self.tr("None")
        self.apply_in_progress = False
        self.refresh_in_progress = False
        self._device_change_refresh_pending = False
        self._device_refresh_timer = QtCore.QTimer(self)
        self._device_refresh_timer.setSingleShot(True)
        self._device_refresh_timer.timeout.connect(self._refresh_after_device_event)
        # False until the first device scan resolves; the connect placeholder
        # must not be shown while that scan is still running (the device list
        # is empty then, even with a phone plugged in).
        self.device_scan_completed = False
        # GoldenNugget Mobile one-shot promo: None until the first scan resolves
        # (no pop-up just because the app started with a phone plugged in),
        # then tracks whether a phone was connected after the last scan.
        self._mobile_promo_prev_connected = None
        self._mobile_promo_shown = False
        self._cache_restore_in_progress = False
        self._cache_restore_thread = None

        self.preset_manager = PresetManager()
        self._preset_autosave_pending = False

        self.loadSettings()
        self._load_last_preset()
        self._register_tweak_autosave()

        self.initial_load = True

        # hide every page
        self.ui.posterboardPageBtn.hide()
        self.ui.euEnablerPageBtn.hide()
        self.ui.statusBarPageBtn.hide()
        self.ui.springboardOptionsPageBtn.hide()
        self.ui.internalOptionsPageBtn.hide()
        self.ui.liquidGlassPageBtn.hide()
        self.ui.daemonsPageBtn.hide()
        self.ui.iconThemesPageBtn.hide()
        self.ui.passcodePageBtn.hide()
        self.ui.applyPageBtn.hide()
        self.ui.sidebarDiv1.hide()
        self.ui.sidebarDiv2.hide()

        # theme manager stores the active UI mode (classic sidebar shell vs
        # full-screen iOS); apply_theme() below applies it
        self.theme_manager = ThemeManager(self)

        # Color theme manager (single dark palette + accent)
        self._color_theme = ColorThemeManager.instance()
        self._color_theme.theme_changed.connect(self._on_color_theme_changed)

        # build the iOS-style pages stack
        # 0 = home, 1 = tweaks, 2 = posterboard, 3 = daemons, 4 = settings,
        # 5 = statusbar, 6 = apply, 7 = springboard, 8 = internal, 9 = liquidglass,
        # 10 = icon themes, 11 = passcode themes, 12 = presets, 13 = community catalog,
        # 14 = tweak templates
        self.ios_pages = QtWidgets.QStackedWidget(self)
        self.ios_pages.setStyleSheet(t("page_bg"))
        # Apply the window-wide stylesheet while the stack is still empty. Qt
        # re-polishes every descendant on setStyleSheet, so applying it after
        # the 15 pages exist walked the whole tree a second time (~0.5 s).
        # Pages built below inherit it when they are polished.
        self._apply_global_stylesheet()
        # Only the home page is on screen at startup. Building the other
        # fourteen pages costs ~0.5 s together (settings and status bar alone
        # ~0.18 s each) and most sessions never open more than a few of them,
        # so each one reserves its stack slot now and is constructed on first
        # access (``self.ios_settings`` etc. triggers it, see __getattr__).
        # The slots are what keeps the numeric page indices in the title/action
        # tables below stable.
        self._lazy_pages = {}
        self._pending_page_calls = {}
        # First-open builds queued by navigation (see _defer_page_build):
        # between scheduling and the deferred construction the reserved slot
        # keeps its PageLoadingSlot and page_at must not build under it.
        self._pending_page_builds = set()
        self._page_names = {0: "ios_home"}
        self.ios_home = IOSHomePage(self)
        self.ios_pages.addWidget(self.ios_home)
        self._reserve_page("ios_tweaks", lambda: IOSTweaksPage(self))
        self._reserve_page("ios_posterboard", lambda: IOSPosterboardPage(self))
        self._reserve_page("ios_daemons", lambda: IOSDaemonsPage(self))
        self._reserve_page("ios_settings", lambda: IOSSettingsPage(self))
        self._reserve_page("ios_statusbar", lambda: IOSStatusBarPage(self))
        self._reserve_page("ios_apply", lambda: IOSApplyPage(self))
        self._reserve_page("ios_springboard", lambda: IOSSectionPage(self, Section.SPRINGBOARD))
        self._reserve_page("ios_internal", lambda: IOSSectionPage(self, Section.INTERNAL))
        self._reserve_page("ios_liquidglass", lambda: IOSSectionPage(self, Section.LIQUID_GLASS))
        self._reserve_page("ios_iconthemes", lambda: IOSIconThemesPage(self))
        self._reserve_page("ios_passthemes", lambda: IOSPasscodeThemePage(self))
        self._reserve_page("ios_presets", lambda: IOSPresetsPage(self))
        self._reserve_page("ios_catalog", lambda: IOSCatalogPage(self))
        self._reserve_page("ios_templates", lambda: IOSTemplatesPage(self))

        # Shared reusable header: one instance for every iOS subpage,
        # reconfigured on page change (title / back / right action).
        from awesomeui.liquid.navigation import LiquidNavBar

        self.ios_nav = LiquidNavBar("", on_back=self._go_back)
        self._ios_page_titles = {
            0: "GoldenNugget",
            1: QtCore.QCoreApplication.translate("Nugget", "Tweaks"),
            2: "PosterBoard",
            3: QtCore.QCoreApplication.translate("Nugget", "Daemons"),
            4: QtCore.QCoreApplication.translate("Nugget", "Settings"),
            5: QCoreApplication.translate("Nugget", "Status Bar"),
            6: QCoreApplication.translate("Nugget", "Apply"),
            7: QtCore.QCoreApplication.translate("Nugget", "SpringBoard"),
            8: QtCore.QCoreApplication.translate("Nugget", "Internal"),
            9: QtCore.QCoreApplication.translate("Nugget", "Liquid Glass"),
            10: QtCore.QCoreApplication.translate("Nugget", "Icon Themes"),
            11: QCoreApplication.translate("Nugget", "Passcode Theme"),
            12: QCoreApplication.translate("Nugget", "Presets"),
            13: QCoreApplication.translate("Nugget", "Community Catalog"),
            14: QCoreApplication.translate("Nugget", "Templates"),
        }
        self._nav_right_actions = {
            # Resolved lazily: the action belongs to a page that may not be
            # built yet (see _reserve_page).
            2: (QCoreApplication.translate("Nugget", "+ Add Tendies"),
                lambda: self.ios_posterboard.show_add_tendies_dialog),
            14: (QCoreApplication.translate("Nugget", "+ Import Templates"),
                 lambda: self.ios_templates.show_add_templates_dialog),
            11: (QCoreApplication.translate("Nugget", "+ Theme"),
                 lambda: self.ios_passthemes.choose_theme_dialog),
        }
        self.ios_pages.currentChanged.connect(self._update_shared_nav)

        ios_root = QtWidgets.QWidget(self)
        # The shared header spans the window's full width, like a title bar:
        # the traffic-light buttons live over the window's left edge and the
        # back capsule hangs directly under them, so the header must reach that
        # edge on every window size (see ``LiquidNavBar``). Only the page
        # *content* lives in the centred column capped at
        # IOS_CONTENT_MAX_WIDTH — on a wide window full-bleed rows put a switch
        # a screen away from its label.
        ios_root_layout = QtWidgets.QVBoxLayout(ios_root)
        ios_root_layout.setContentsMargins(0, 0, 0, 0)
        ios_root_layout.setSpacing(0)
        # The header is one surface with the window (LiquidNavBar paints the
        # page background itself), so the wrapper carries no inset: the old
        # 8px margin existed only to give a floating glass panel room for its
        # rounded corners.
        nav_wrap = QtWidgets.QWidget(ios_root)
        nav_wrap.setObjectName("iosNavWrap")
        nav_wrap_layout = QtWidgets.QVBoxLayout(nav_wrap)
        nav_wrap_layout.setContentsMargins(0, 0, 0, 0)
        nav_wrap_layout.setSpacing(0)
        nav_wrap_layout.addWidget(self.ios_nav)
        ios_root_layout.addWidget(nav_wrap)
        ios_root_hbox = QtWidgets.QHBoxLayout()
        ios_root_hbox.setContentsMargins(0, 0, 0, 0)
        ios_root_hbox.setSpacing(0)
        ios_column = QtWidgets.QWidget(ios_root)
        ios_column.setMaximumWidth(self.IOS_CONTENT_MAX_WIDTH)
        ios_root_hbox.addStretch(0)
        ios_root_hbox.addWidget(ios_column, 1)
        ios_root_hbox.addStretch(0)
        ios_column_layout = QtWidgets.QVBoxLayout(ios_column)
        ios_column_layout.setContentsMargins(0, 0, 0, 0)
        ios_column_layout.setSpacing(0)
        ios_column_layout.addWidget(self.ios_pages, 1)
        ios_root_layout.addLayout(ios_root_hbox, 1)
        from src.gui.liquid.dock import LiquidDock as BottomNavigation
        self.bottom_navigation = BottomNavigation(self, ios_root)

        # Unified shell: classic sidebar + [classic home | iOS root | classic daemons].
        # The sidebar is the only survivor of the old UI chrome; most pages
        # render through the iOS-style stack. Daemons has been ported to the
        # same iOS-style interface and lives as its own classic page. The REST
        # of the classic UI is parked (hidden, alive): wrappers and flows still
        # reference its widgets.
        self._classic_parking = QtWidgets.QWidget(self)
        self._classic_parking.hide()
        self.ui.centralwidget.setParent(self._classic_parking)
        self.ui.homePage.setParent(None)
        self.ui.sidebar.setParent(None)
        self.ui.daemonsPage.setParent(None)
        # the top device bar (phone icon + picker) comes back too
        self.ui.deviceBar.setParent(None)
        self.content_stack = QtWidgets.QStackedWidget(self)
        self.content_stack.addWidget(self.ui.homePage)   # 0 = classic home
        self.content_stack.addWidget(ios_root)           # 1 = iOS pages
        self.content_stack.addWidget(self.ui.daemonsPage)  # 2 = classic daemons
        # 3 = no-device placeholder (shown while no iPhone is connected)
        self.connect_placeholder = ConnectDevicePlaceholder(self)
        self.content_stack.addWidget(self.connect_placeholder)
        shell = QtWidgets.QWidget(self)
        shell.setProperty("cls", "central")  # picks up the global #1e1e1e background
        self.shell_layout = QtWidgets.QVBoxLayout(shell)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.shell_layout.setSpacing(0)
        self.shell_layout.addWidget(self.ui.deviceBar)
        self.body_row = QtWidgets.QHBoxLayout()
        self.body_row.setContentsMargins(0, 0, 0, 0)
        self.body_row.setSpacing(0)
        self.body_row.addWidget(self.ui.sidebar)
        self.body_row.addWidget(self.content_stack, 1)
        self.shell_layout.addLayout(self.body_row)
        self.setCentralWidget(shell)

        # The window's frame is drawn by the app: the OS title bar is gone and
        # the traffic-light buttons, drag surfaces and edges live here.
        from src.gui.window_chrome import install_window_chrome
        self.window_chrome = install_window_chrome(
            self, self.ios_nav, self.ui.sidebar, pages=(self.ios_home,))

        self.apply_theme(self.theme_manager.current_theme)

        # Back navigation: ESC key and mouse back button go to the home page
        QtWidgets.QApplication.instance().installEventFilter(self)

        # Update the app version/build number label
        self.updateAppVersionLabel()

        ## DEVICE BAR
        self.ui.refreshBtn.clicked.connect(self.refresh_devices)
        self.ui.refreshBtn.setToolTip(QCoreApplication.translate("Nugget", "Refresh connected devices"))
        self.ui.devicePicker.currentIndexChanged.connect(self.change_selected_device)
        self._device_monitor_thread = DeviceMonitorThread(self)
        self._device_monitor_thread.devices_changed.connect(self._on_device_connection_changed)
        self._device_monitor_thread.usb_devices_changed.connect(self._on_usb_devices_changed)
        self._device_monitor_thread.start()
        self.refresh_devices()
        # The refresh above runs on a worker thread, so the device list is still
        # empty here. _update_device_gate() deliberately does NOT show the
        # connect placeholder until that first scan finishes — otherwise the
        # "No device connected" screen stayed up for the whole scan (seconds)
        # even when a supported phone was already plugged in.
        self._update_device_gate()

        ## SIDE BAR ACTIONS
        self.ui.homePageBtn.clicked.connect(self.on_homePageBtn_clicked)
        self.ui.statusBarPageBtn.clicked.connect(self.on_statusBarPageBtn_clicked)
        self.ui.springboardOptionsPageBtn.clicked.connect(self.on_springboardOptionsPageBtn_clicked)
        self.ui.internalOptionsPageBtn.clicked.connect(self.on_internalOptionsPageBtn_clicked)
        self.ui.liquidGlassPageBtn.clicked.connect(self.on_liquidGlassPageBtn_clicked)
        self.ui.daemonsPageBtn.clicked.connect(self.on_daemonsPageBtn_clicked)
        self.ui.iconThemesPageBtn.clicked.connect(self.on_iconThemesPageBtn_clicked)
        self.ui.posterboardPageBtn.clicked.connect(self.on_posterboardPageBtn_clicked)
        self.ui.templatesPageBtn.clicked.connect(self.on_templatesPageBtn_clicked)
        self.ui.applyPageBtn.clicked.connect(self.on_applyPageBtn_clicked)
        self.ui.settingsPageBtn.clicked.connect(self.on_settingsPageBtn_clicked)

        self.ui.presetsPageBtn.clicked.connect(self.on_presetsPageBtn_clicked)

        # The initial themed global stylesheet is applied earlier (before the
        # pages are built) so the tree is polished once, not twice.
        from src.gui.liquid.experience import LiquidExperience
        self.liquid = LiquidExperience(self)
        # Tweaks/Daemons are NOT pre-built: both rebuild themselves from
        # showEvent(), so opening either page costs its build once — exactly
        # what the user asked for ("build a page only when they enter it").
        # A timer prewarm was tried and dropped: it landed back-to-back with
        # the startup device scans/imports and multiplied the visible hitches.

    def _reserve_page(self, name: str, factory):
        """Reserve a stack slot for a page that is built on first access.

        The placeholder keeps every page index stable (the title/action tables
        and navigation code address pages by number), while deferring the
        widget construction until something actually asks for it. The
        placeholder is the first-open loading screen (spinner + label).
        """
        index = self.ios_pages.addWidget(PageLoadingSlot())
        self._lazy_pages[name] = (index, factory)
        self._page_names[index] = name

    def page_at(self, index: int):
        """Return the page in a stack slot, building it if still reserved.

        Page navigation goes through the index (``set_ios_page``), so the slot
        has to resolve to the real widget before the stack shows it. While a
        first-open build is queued (see ``_defer_page_build``) the loading
        screen stays in the slot instead of building under the spinner.
        """
        name = getattr(self, "_page_names", {}).get(index)
        if name is not None and name in self._lazy_pages:
            if name in self._pending_page_builds:
                return self.ios_pages.widget(index)
            return self._build_lazy_page(name)
        return self.ios_pages.widget(index)

    def _build_lazy_page(self, name: str):
        """Construct a reserved page in place and return it."""
        index, factory = self._lazy_pages.pop(name)
        stack = self.ios_pages
        current = stack.currentIndex()
        page = factory()
        placeholder = stack.widget(index)
        stack.insertWidget(index, page)
        if placeholder is not None:
            stack.removeWidget(placeholder)
            placeholder.deleteLater()
        # The slot is reused, so restoring the selection is only defensive.
        if stack.currentIndex() != current:
            stack.setCurrentIndex(current)
        setattr(self, name, page)
        if name == "ios_apply" and hasattr(page, "set_busy"):
            # The apply page mirrors live apply state, which may have changed
            # while it did not exist yet (gate updates skip missing pages).
            page.set_busy(self.apply_in_progress
                          or getattr(self, '_cache_restore_in_progress', False))
        for method, args, kwargs in self._pending_page_calls.pop(name, ()):
            try:
                getattr(page, method)(*args, **kwargs)
            except Exception:  # a missing hook must never break navigation
                pass
        return page

    def _defer_page_build(self, index: int, name: str):
        """First navigation to a reserved page: show the loading screen now.

        The stack is switched to the reserved slot immediately (currentChanged
        updates the shared header), so the spinner + "Loading… Please Wait"
        paint while the real page is constructed one timer pass later instead
        of freezing the click handler. Once built the page lives in the slot
        and every later navigation takes the normal cached path.
        """
        if name in self._lazy_pages and name not in self._pending_page_builds:
            self._pending_page_builds.add(name)
            logging.getLogger("GoldenNugget.gui").info(
                "Page %s: loading screen shown, build deferred", name)
            QtCore.QTimer.singleShot(
                50, lambda: self._finish_page_build(index, name))
        stack = self.ios_pages
        if stack.currentIndex() != index:
            self._stop_page_slide()
            stack.setCurrentIndex(index)
            logging.getLogger("GoldenNugget.gui").info(
                "Page %s: loading screen is now current (index %s)", name, index)

    def _finish_page_build(self, index: int, name: str):
        """Deferred first-open build: construct the page in its reserved slot."""
        self._pending_page_builds.discard(name)
        if name not in self._lazy_pages:
            logging.getLogger("GoldenNugget.gui").info(
                "Page %s: deferred build skipped — built elsewhere already", name)
            return
        try:
            self._build_lazy_page(name)
        except RuntimeError:
            return  # window torn down while the build was queued
        except Exception:
            # The build failing must never leave the loading screen in the
            # slot with no visible signal; surface it through the crash
            # machinery (which presents a dialog on the GUI thread) rather
            # than silently parking the user on the spinner.
            logging.getLogger("GoldenNugget.gui").exception(
                "Page %s: deferred build failed", name)
            import traceback

            from src.gui.crash_ui import show_error_dialog
            show_error_dialog(
                f"Failed to load the {index} page ({name})",
                traceback.format_exc())
            return
        logging.getLogger("GoldenNugget.gui").info(
            "Page %s: first-open build finished", name)
        if self.ios_pages.currentIndex() != index:
            return  # navigated elsewhere while loading — keep that page up
        page = self.ios_pages.widget(index)
        if (hasattr(page, "_retheme")
                and getattr(page, "_applied_theme_revision", -1)
                != self._color_theme.revision):
            page._retheme()
            page._applied_theme_revision = self._color_theme.revision
        self._update_shared_nav(index)

    def call_on_page(self, name: str, method: str, *args, **kwargs):
        """Call a page method now if the page exists, else when it is built.

        Startup code configures pages that are no longer constructed up front
        (``LiquidExperience._clean_home`` sets the Apply page's status-only
        mode); the call is replayed on construction instead of forcing it.
        """
        page = self.__dict__.get(name)
        if page is not None:
            return getattr(page, method)(*args, **kwargs)
        self._pending_page_calls.setdefault(name, []).append((method, args, kwargs))
        return None

    def built_page(self, name: str):
        """Return a reserved page only if it was already constructed.

        Use this for probes: plain ``getattr`` on a reserved name builds the
        page, which is the point for navigation but pure cost for a check.
        """
        return self.__dict__.get(name)

    def __getattr__(self, name: str):
        # QWidget raises AttributeError for unknown attributes; the reserved
        # page names resolve by building the page on first access.
        lazy = self.__dict__.get("_lazy_pages")
        if lazy and name in lazy:
            return self._build_lazy_page(name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}")

    def run_first_launch_prompts(self):
        """Present the first-launch dialogs AFTER the window is on screen.

        Running them inside __init__ (before show()) opens them over an
        unmapped parent, which on several platforms renders them transparent
        and stuttering. Called from main_app right after widget.show().
        """
        # The first-launch interface picker ("Sidebar / Modern") is gone with
        # the sidebar mode; drop a stale marker so nothing re-asks for it.
        if not self.settings.value("ui/interface_choice_done", False, type=bool):
            self.settings.setValue("ui/interface_choice_done", True)
            self._sync_settings()

        # First launch: remind the user to back up the device before tweaking
        # (keeps asking until they confirm a backup was made)
        if not self.settings.value("backup_prompt_done", False, type=bool):
            if self.prompt_first_launch_backup():
                self.settings.setValue("backup_prompt_done", True)
                self._sync_settings()

        # Linux: usbmuxd / libimobiledevice are required to see an iPhone.
        # Offer to install them (the system asks for the password).
        if "--test-mode" not in sys.argv:
            from src.gui.dialogs.linux_deps_dialog import (
                prompt_and_install,
                should_prompt_on_startup,
            )
            if should_prompt_on_startup(self):
                prompt_and_install(self, from_startup=True)

    # ---- Color theme reactivity ------------------------------------------

    def _apply_global_stylesheet(self):
        """Re-apply the global stylesheet using the current color theme."""
        from awesomeui.liquid.overlay import liquid_overlay_css
        # One stylesheet for the whole window: the base template plus the
        # liquid overlay (inputs/scrollbars/sliders). Composing them here keeps
        # the tree polished once — a second setStyleSheet after startup would
        # walk every widget again (~0.3 s).
        self.setStyleSheet(t("global") + liquid_overlay_css())
        # Also update the QPalette so native widgets pick up the colors
        self._color_theme.apply_to_app()
        # Re-style the ios_pages stack
        self.ios_pages.setStyleSheet(t("page_bg"))
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            self._retheme_classic()

    def _retheme_classic(self):
        """Re-color the classic shell: chrome icons, device picker, version
        link and the hardcoded-dark credit buttons."""
        c = self._color_theme.colors

        # Recolor white SVG chrome icons to the current text color
        for obj_name, res in _CLASSIC_THEMED_ICONS.items():
            widget = getattr(self.ui, obj_name, None)
            if widget is not None:
                widget.setIcon(theme_icon(res, c.text_primary))

        # Device picker keeps its default stylesheet (classic look).

        # Version link inherits white from the shell defaults — restyle to text_secondary
        self.ui.phoneNameLbl.setStyleSheet(f"color: {c.text_primary};")
        self.ui.phoneVersionLbl.setText(
            f'<a style="text-decoration:none; color:{c.text_secondary}" href="#">Version</a>')

        self.ui.sidebar._retheme()

        # Credit buttons hardcode #3b3b3b borders in the generated .ui
        bordered_style = themed_stylesheet("classic_bordered_btn")
        for obj_name in _CLASSIC_BORDERED_BTNS:
            widget = getattr(self.ui, obj_name, None)
            if widget is not None:
                widget.setStyleSheet(bordered_style)

    def _on_color_theme_changed(self):
        """Called when the color theme (accent) changes."""
        self._apply_global_stylesheet()
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            return
        page = self.ios_pages.currentWidget()
        if page is not None and hasattr(page, "_retheme"):
            page._retheme()
            page._applied_theme_revision = self._color_theme.revision

    def closeEvent(self, event):
        """Guard window close so device threads never get destroyed mid-run.

        Destroying a QThread object while its native thread is still running
        is what produces the "QThread: Destroyed while thread '' is still
        running" crash — and for a restore/apply it can cut the device
        operation short right in the middle of a Manifest.db write, leaving
        the backup corrupted (the reported MBErrorDomain/205 fallout).
        """
        terminating = []
        if getattr(self, "apply_in_progress", False):
            terminating.append(QCoreApplication.translate("Nugget", "apply/reset"))
        if getattr(self, "_cache_restore_in_progress", False):
            terminating.append(QCoreApplication.translate("Nugget", "data restore"))
        pt_worker = getattr(self.built_page("ios_passthemes"), "_worker", None)
        if _still_running(pt_worker):
            terminating.append(QCoreApplication.translate("Nugget", "passcode theme write"))
        pairing_worker = getattr(
            self.built_page("ios_settings"), "_reset_pairing_thread", None)
        if _still_running(pairing_worker):
            terminating.append(QCoreApplication.translate("Nugget", "pairing reset"))
        if terminating:
            reply = QtWidgets.QMessageBox.question(
                self,
                QCoreApplication.tr("Background device operation"),
                QCoreApplication.translate(
                    "Nugget",
                    "A device %1 is running. Closing now can interrupt it "
                    "mid-write and leave the protective backup corrupted.\n\n"
                    "Close anyway?").replace(
                        "%1", " and ".join(terminating)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # User insisted: let the operation wind down on its own so the
            # thread is not destroyed mid-run. Device loops all have bounded
            # timeouts, so this terminates.
            for worker in (
                getattr(self, "worker_thread", None),
                getattr(self, "_cache_restore_thread", None),
                pairing_worker,
                pt_worker,
            ):
                if _still_running(worker):
                    try:
                        worker.wait()
                    except RuntimeError:
                        pass
        self._device_selection_closing = True
        self._posterboard_waiting = {}
        for worker in list(getattr(self, "_posterboard_selection_workers", {}).values()):
            if _still_running(worker) and not worker.wait(2000):
                event.ignore()
                return
        if not self.ios_home.stop_device_info():
            event.ignore()
            return
        if not self.ios_home._device_preview.stop() or not self.ios_home._picker_preview.stop():
            event.ignore()
            return
        scan_worker = getattr(self, "refresh_worker_thread", None)
        if _still_running(scan_worker):
            try:
                scan_worker.wait(8000)
            except RuntimeError:
                pass
        # Cosmetic, but still a QThread: it is parented to the window, so it
        # must not be destroyed while it is counting.
        badge_worker = getattr(self.ios_home, "_catalog_badge_worker", None)
        if _still_running(badge_worker):
            try:
                badge_worker.wait(5000)
            except RuntimeError:
                pass
        monitor_worker = getattr(self, "_device_monitor_thread", None)
        if _still_running(monitor_worker):
            monitor_worker.request_stop()
            try:
                monitor_worker.wait(10000)
            except RuntimeError:
                pass
        self._flush_autosave()
        super().closeEvent(event)
