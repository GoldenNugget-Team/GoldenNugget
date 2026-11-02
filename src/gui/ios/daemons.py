from PySide6.QtCore import (
    Qt, QSize, QTimer, QCoreApplication, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QHBoxLayout, QLabel, QMessageBox,
    QGraphicsOpacityEffect, QSizePolicy, QFrame, QPushButton,
)

from src.gui.ios.components import IOSCard, IOSSectionHeader, IOSSwitch, IOSSearchField, IOSSearchEmpty, IOSSegmentedFilter, IOSSettingsAction
from PySide6.QtGui import QIcon
from src.controllers.favorites import TweakFavorites
from src.gui.theme import ColorThemeManager, theme_pixmap, theme_icon, t
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.tweak_loader import load_daemons
from src.tweaks.daemon_descriptions import DAEMON_DESCRIPTIONS
from src.tweaks.daemons_tweak import Daemon, NOTIFICATION_RECOVERY_DAEMONS

ANALYTICS_DAEMONS = (Daemon.AnalyticsHelper, Daemon.WifiAnalytics, Daemon.UsageTrackingAgent,
                     Daemon.AppleAds, Daemon.SettingsStats, Daemon.AudioAnalytics,
                     Daemon.EcosystemAnalytics, Daemon.CallAnalytics, Daemon.Feedback, Daemon.Metrics)
from src.controllers.hotload import HotLoad

# QWIDGETSIZE_MAX — PySide6 does not export the C macro, this is its value.
_NO_MAX_HEIGHT = 16777215

_ROW_SPACING = 12
_FAVORITE_SIZE = 44
_INFO_SIZE = 36


def _reserve_action_space(layout):
    space = QWidget()
    space.setFixedSize(_FAVORITE_SIZE + _ROW_SPACING + _INFO_SIZE, _FAVORITE_SIZE)
    space.setAttribute(Qt.WA_TransparentForMouseEvents)
    space.setStyleSheet("background: transparent;")
    layout.addWidget(space)


class _DaemonRows(QWidget):
    """The daemon rows, revealed as one block by the master switch.

    The rows live in their own widget so the whole block can be folded away from
    the page when daemon modifications are off. Geometry belongs to the layout,
    so the reveal animates ``maximumHeight``: 0 means folded away (the layout
    spacing collapses with it, so nothing is left behind) and the block growing
    back to its natural height reveals the rows one after another, top down —
    that is the cascade. A single ``QGraphicsOpacityEffect`` on the block fades
    it in over the top.

    Deliberately one effect for the whole block and not one per row: a per-row
    effect makes Qt render every row into its own pixmap on every frame
    (thousands of paint warnings on a 35-row list, and needless work on the
    device). The effect is dropped again when the run finishes, so a visible
    list renders exactly as it did before the animation existed.
    """

    FADE_IN_MS = 220
    UNFOLD_IN_MS = 340
    FADE_OUT_MS = 140
    UNFOLD_OUT_MS = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._rows: list = []
        self._group: QParallelAnimationGroup | None = None
        self._shown = True

    def append(self, widget: QWidget) -> QWidget:
        """Add a row (or a section header) to the animated block."""
        self._rows.append(widget)
        self._layout.addWidget(widget)
        return widget

    def snap(self, shown: bool) -> None:
        """Show/hide with no animation at all (page build, device change)."""
        self._stop()
        self._shown = shown
        self._detach_effects()
        self.setVisible(shown)
        self.setMaximumHeight(_NO_MAX_HEIGHT if shown else 0)

    def set_shown(self, shown: bool, animate: bool = True) -> None:
        """Show/hide the block, unrolling in (or folding away) when asked."""
        if shown == self._shown:
            if not animate:
                self.snap(shown)
            return
        self._shown = shown
        if animate:
            self._animate(shown)
        else:
            self.snap(shown)

    def _stop(self) -> None:
        if self._group is not None:
            self._group.stop()
            self._group.deleteLater()
            self._group = None

    def _detach_effects(self) -> None:
        if self.graphicsEffect() is not None:
            # setGraphicsEffect(None) deletes the old effect itself, so it must
            # not be deleteLater()d again (that raises in PySide6)
            self.setGraphicsEffect(None)

    def _animate(self, shown: bool) -> None:
        self._stop()
        self._detach_effects()
        group = QParallelAnimationGroup(self)

        # sizeHint comes from the layout and ignores visibility, but reveal the
        # block before asking, so the fold has something to grow into
        full = self.sizeHint().height()
        height = QPropertyAnimation(self, b"maximumHeight", self)
        if shown:
            self.setVisible(True)
            self.setMaximumHeight(0)
            height.setStartValue(0)
            height.setEndValue(full)
            height.setDuration(self.UNFOLD_IN_MS)
            height.setEasingCurve(QEasingCurve.Type.OutCubic)
        else:
            height.setStartValue(self.height() or full)
            height.setEndValue(0)
            height.setDuration(self.UNFOLD_OUT_MS)
            height.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(height)

        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0 if shown else 1.0)
        self.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setStartValue(0.0 if shown else 1.0)
        fade.setEndValue(1.0 if shown else 0.0)
        fade.setDuration(self.FADE_IN_MS if shown else self.FADE_OUT_MS)
        fade.setEasingCurve(
            QEasingCurve.Type.OutCubic if shown else QEasingCurve.Type.InCubic)
        group.addAnimation(fade)

        group.finished.connect(lambda: self._on_finished(shown))
        self._group = group
        group.start()

    def _on_finished(self, shown: bool) -> None:
        if shown:
            # never leave the fold at the height it had when the animation was
            # built: a resize or a font change could clip the rows afterwards
            self.setMaximumHeight(_NO_MAX_HEIGHT)
        else:
            self.setVisible(False)
            self.setMaximumHeight(0)
        self._stop()
        self._detach_effects()


class IOSDaemonsContent(QWidget):
    """iOS-style daemons controls, usable inside any scroll area or page."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window

        # Ensure daemons tweaks are loaded
        load_daemons()

        self.daemons_tweak = tweaks[TweakID.Daemons]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 32)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        from src.gui.ios.viewport_rows import ViewportRows
        self._viewport_rows = ViewportRows(self)
        self._favorites = TweakFavorites.instance()
        self._favorite_buttons = {}
        self.search = IOSSearchField(self)
        self.search.setPlaceholderText(self.tr("Search daemons…"))
        self.filter_control = IOSSegmentedFilter([
            (self.tr("All"), "all"), (self.tr("Enabled"), "enabled"),
            (self.tr("Disabled"), "disabled"),
            (self.tr("Favorites"), "favorites")], self)
        self.filter_control.setAccessibleName(self.tr("Daemon filter"))
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.filter_control)
        layout.addLayout(search_row)
        self.filter_control.currentIndexChanged.connect(self._apply_search)
        self._favorites.changed.connect(self._refresh_favorites)

        # Master enable switch
        layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Configuration")
        ))
        master_card = IOSCard()
        master_row = QHBoxLayout(master_card)
        master_row.setContentsMargins(16, 12, 16, 12)
        master_row.setSpacing(_ROW_SPACING)
        c = ColorThemeManager.instance().colors
        master_label = QLabel(QCoreApplication.translate("Nugget", "Enable Daemon Modifications"))
        master_label.setWordWrap(True)
        master_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        self._master_label = master_label
        master_text = QVBoxLayout()
        master_text.setSpacing(4)
        master_text.addWidget(master_label)
        master_detail = QLabel(self.tr("Each switch below stops a background service when you apply. Turning this master switch off does not undo changes already on the device."))
        master_detail.setWordWrap(True)
        master_detail.setProperty("daemonInformation", True)
        master_detail.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        master_text.addWidget(master_detail)
        master_row.addLayout(master_text, 1)
        self.master_switch = IOSSwitch(self.daemons_tweak.enabled)
        self.master_switch.toggled.connect(self._on_master_toggled)
        master_row.addWidget(self.master_switch)
        _reserve_action_space(master_row)
        layout.addWidget(master_card)

        # Shown while the master switch is off: without it the page is just a
        # lone switch over empty space, with no hint of what turning it on does.
        self._disabled_hint = QLabel(QCoreApplication.translate(
            "Nugget", "Turn this on to choose which system services (daemons) to "
            "disable: analytics, diagnostics and other background services. "
            "Nothing changes on your device until you apply tweaks."))
        self._disabled_hint.setWordWrap(True)
        self._disabled_hint.setContentsMargins(8, 0, 8, 0)
        self._disabled_hint.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        layout.addWidget(self._disabled_hint)

        self.recover_notifications_button = IOSSettingsAction(
            QCoreApplication.translate("Nugget", "Restore Call Notification Services"))
        self.recover_notifications_button.setToolTip(QCoreApplication.translate(
            "Nugget", "Re-enable Spotlight and services disabled by the previous Recommended set. "
            "Apply changes and reboot your device afterwards. Safety rules still apply."))
        self.recover_notifications_button.clicked.connect(self._restore_notification_services)
        layout.addWidget(self.recover_notifications_button)

        # Everything that acts on daemons lives in one block that the master
        # switch unrolls / folds away, so those rows only exist on screen while
        # daemon modifications are actually on. HotLoad safety rules still apply independently.
        self._rows = _DaemonRows(self)
        layout.addWidget(self._rows)

        self.daemon_cards = []
        self.daemon_switches = []
        self._daemon_labels = [master_detail]
        self._info_buttons = []
        self._forced_notes = []
        self._confirming = False
        self._hotload_acked = False

        self._forced_daemons: dict = {}
        self._forced_switches = []
        # HotLoad: daemons force-disabled on this device/iOS ({"Name": reason}).
        settings = getattr(self.window, "settings", None) if self.window is not None else None
        dm = getattr(self.window, "device_manager", None) if self.window is not None else None
        if dm is not None:
            self._forced_daemons = HotLoad(settings).disabled_daemons(
                device_version=dm.get_current_device_version(),
                device_model=dm.get_current_device_model())
        from src.gui.ios.incremental_builder import IncrementalBuilder
        self._building = True
        self._rows.hide()
        self._rows._layout.setEnabled(False)
        self._rows.setEnabled(False)
        self._loading_label = QLabel(self.tr("Loading controls…"), self)
        self._loading_label.hide()
        layout.addWidget(self._loading_label)
        self._category_lines = []
        self._category_groups = []
        self.master_switch.setEnabled(False)
        self._builder = IncrementalBuilder(self)
        self._builder.start(self._build_rows(layout, c))

    def _build_rows(self, layout, c):
        for title, daemon in [
            (QCoreApplication.translate("Nugget", 'Disable OTA Update Services'), Daemon.OTA),
            (QCoreApplication.translate("Nugget", 'Disable App Usage Reports'), Daemon.UsageTrackingAgent),
            (QCoreApplication.translate("Nugget", 'Disable Game Center'), Daemon.GameCenter),
            (QCoreApplication.translate("Nugget", 'Disable Tips Suggestions'), Daemon.Tips),
            (QCoreApplication.translate("Nugget", 'Disable IPsec VPN Connections'), Daemon.VPN),
            (QCoreApplication.translate("Nugget", 'Disable WAPI Wi-Fi Connections'), Daemon.ChineseLAN),
            (QCoreApplication.translate("Nugget", 'Disable Health Data Service'), Daemon.HealthKit),
            (QCoreApplication.translate("Nugget", 'Disable AirPrint'), Daemon.AirPrint),
            (QCoreApplication.translate("Nugget", 'Disable AssistiveTouch'), Daemon.AssistiveTouch),
            (QCoreApplication.translate("Nugget", 'Disable Cloud Media Service'), Daemon.iCloud),
            (QCoreApplication.translate("Nugget", 'Disable Personal Hotspot'), Daemon.InternetTethering),
            (QCoreApplication.translate("Nugget", 'Disable Wallet Pass Service'), Daemon.PassBook),
            (QCoreApplication.translate("Nugget", 'Disable System Search Updates'), Daemon.Spotlight),
            (QCoreApplication.translate("Nugget", 'Disable Siri and Voice Helpers'), Daemon.VoiceControl),
            (QCoreApplication.translate("Nugget", 'Disable Apple Ad Services'), Daemon.AppleAds),
            (QCoreApplication.translate("Nugget", 'Disable Apple News Updates'), Daemon.News),
            (QCoreApplication.translate("Nugget", 'Disable Family Sharing Updates'), Daemon.FamilySharing),
            (QCoreApplication.translate("Nugget", 'Disable TV Provider Sign-In Helper'), Daemon.VideoSubscriptions),
            (QCoreApplication.translate("Nugget", 'Disable Safari Bookmark Service'), Daemon.WebBookmarks),
            (QCoreApplication.translate("Nugget", 'Disable Wi-Fi Problem Logs'), Daemon.WifiLogging),
            (QCoreApplication.translate("Nugget", 'Disable Maps Background Service'), Daemon.Maps),
            (QCoreApplication.translate("Nugget", 'Disable Online Search Suggestions'), Daemon.SafariSuggestions),
            (QCoreApplication.translate("Nugget", 'Disable Reminders Background Service'), Daemon.Reminders),
            (QCoreApplication.translate("Nugget", 'Disable AirPlay Service'), Daemon.AirPlay),
            (QCoreApplication.translate("Nugget", 'Disable Game Services Helper'), Daemon.GameKitService),
            (QCoreApplication.translate("Nugget", 'Disable Companion Display Helper'), Daemon.Sidecar),
            (QCoreApplication.translate("Nugget", 'Disable Speech-to-Text Helper'), Daemon.SpeechRecognition),
            (QCoreApplication.translate("Nugget", 'Disable Test Locations'), Daemon.MockLocation),
            (QCoreApplication.translate("Nugget", 'Disable Feedback Background Tasks'), Daemon.Feedback),
            (QCoreApplication.translate("Nugget", 'Disable Settings Usage Reports'), Daemon.SettingsStats),
            (QCoreApplication.translate("Nugget", 'Disable Music Recognition'), Daemon.Shazam),
            (QCoreApplication.translate("Nugget", 'Disable Account Reminder Notices'), Daemon.FollowUp),
            (QCoreApplication.translate("Nugget", 'Disable Location Services'), Daemon.Location),
        ]:
            card, switch = self._make_daemon_switch(title, daemon)
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))
            yield

        self._screen_time_card = None
        self.screen_time_tweak = tweaks.get(TweakID.ClearScreenTimeAgentPlist)
        if self.screen_time_tweak is not None:
            card = IOSCard()
            self._screen_time_card = card
            card.setProperty("searchText", "Screen Time ScreenTimeAgent clear plist")
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(16, 12, 16, 12)
            row_layout.setSpacing(_ROW_SPACING)
            label = QLabel(QCoreApplication.translate(
                "Nugget", "Clear Saved Screen Time Settings"))
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
            self._screen_time_label = label
            text = QVBoxLayout()
            text.setSpacing(4)
            text.addWidget(label)
            detail = QLabel(self.tr("Clears one saved Screen Time settings file. Does not reliably remove app or website restrictions."))
            detail.setWordWrap(True)
            detail.setProperty("daemonInformation", True)
            detail.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
            self._daemon_labels.append(detail)
            text.addWidget(detail)
            row_layout.addLayout(text, 1)
            self.screen_time_switch = IOSSwitch(self.screen_time_tweak.enabled)
            self.screen_time_switch.toggled.connect(self._on_screen_time_toggled)
            row_layout.addWidget(self.screen_time_switch)
            _reserve_action_space(row_layout)
            self._screen_time_group = card
            self._rows.append(card)

        self._service_cards = list(self.daemon_cards)

        # Analytics, data tracking & logging toggles (from MiniVoidyy/GoldenNugget-)
        analytics_start = len(self.daemon_cards)
        for title, daemon in [
            (QCoreApplication.translate("Nugget", 'Disable System Problem Reports'), Daemon.Diagnostics),
            (QCoreApplication.translate("Nugget", 'Disable Crash Reports and System Logs'), Daemon.CrashReports),
            (QCoreApplication.translate("Nugget", 'Disable Wi-Fi Usage Reports'), Daemon.WifiAnalytics),
            (QCoreApplication.translate("Nugget", 'Disable System Usage Reports'), Daemon.AnalyticsHelper),
            (QCoreApplication.translate("Nugget", 'Disable Audio Problem Reports'), Daemon.AudioAnalytics),
            (QCoreApplication.translate("Nugget", 'Disable Cross-Device Usage Reports'), Daemon.EcosystemAnalytics),
            (QCoreApplication.translate("Nugget", 'Disable Call Quality Reports'), Daemon.CallAnalytics),
            (QCoreApplication.translate("Nugget", 'Disable Activity-Based Suggestions'), Daemon.CoreDuet),
            (QCoreApplication.translate("Nugget", 'Disable Insight Helper'), Daemon.Insight),
            (QCoreApplication.translate("Nugget", 'Disable System Measurement Reports'), Daemon.Metrics),
            (QCoreApplication.translate("Nugget", 'Disable Playback Control Service'), Daemon.MediaExperience),
            (QCoreApplication.translate("Nugget", 'Disable Network Health Reports'), Daemon.Symptomsd),
            (QCoreApplication.translate("Nugget", 'Disable Statistical Problem Reports'), Daemon.StatisticalDiagnostic),
            (QCoreApplication.translate("Nugget", 'Disable Wireless Troubleshooting'), Daemon.WirelessDiagnostics),
            (QCoreApplication.translate("Nugget", 'Disable Background Scheduling Helper'), Daemon.DuetHeuristic),
            (QCoreApplication.translate("Nugget", 'Disable Activity Prediction Helper'), Daemon.DuetExpert),
            (QCoreApplication.translate("Nugget", 'Disable Apple Feature Trials'), Daemon.Triald),
            (QCoreApplication.translate("Nugget", 'Disable Social Account Helper'), Daemon.Sociald),
        ]:
            card, switch = self._make_daemon_switch(title, daemon)
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))
            yield

        self._analytics_cards = self.daemon_cards[analytics_start:]
        self._experimental_cards = []
        self._experimental_switches = []
        self._risky_cards = []
        for title, daemon, information in (
            ('Disable Temperature Monitoring', Daemon.thermalmonitord, 'Disrupts temperature monitoring; can cause instability.'),
            ('Disable ATWAKEUP Helper', Daemon.ATWAKEUP, 'Reported to cause repeated interface restarts with AirPods when disabled.'),
        ):
            card, switch = self._make_daemon_switch(self.tr(title), daemon, self.tr(information))
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))
            self._risky_cards.append(card)
            yield
        self._organize_rows()
        self.search_empty = IOSSearchEmpty(self)
        layout.addWidget(self.search_empty)
        from src.gui.ios.visibility_batch import VisibilityBatch
        self._visibility_batch = VisibilityBatch(self)
        self.search.textChanged.connect(self._visibility_batch.cancel)
        self.search.connect_filter(self._apply_search)
        self._rows._layout.setEnabled(True)
        self._building = False
        self._loading_label.hide()
        self.master_switch.setEnabled(True)
        layout.addStretch()
        self.refresh_from_tweaks()
        self._viewport_rows.request()
        page = getattr(self.window, "ios_daemons", None)
        if page is not None:
            page._applied_theme_revision = ColorThemeManager.instance().revision

    def _organize_rows(self):
        from src.gui.ios.daemon_categories import CATEGORY_ORDER, DAEMON_CATEGORIES, REPORTS_CATEGORY, ACCOUNTS_CATEGORY
        grouped = {title: [] for title in CATEGORY_ORDER}
        for card, (daemon, switch) in zip(self.daemon_cards, self.daemon_switches):
            if any(key in self.daemons_tweak.never_enable for key in daemon.value):
                card.hide()
                continue
            category = "Risky tweaks" if card in self._risky_cards else REPORTS_CATEGORY if daemon in ANALYTICS_DAEMONS else DAEMON_CATEGORIES.get(daemon.name, "System Services")
            card.setProperty("searchText", f'{self.tr(category)} {card.property("searchText")}')
            grouped[category].append(card)
        if self._screen_time_card is not None:
            self._screen_time_card.setProperty("sortTitle", "clear screentime")
            grouped[ACCOUNTS_CATEGORY].append(self._screen_time_card)
        while self._rows._layout.count():
            self._rows._layout.takeAt(0)
        self._rows._rows = []
        self._category_groups = []
        self._category_lines = []
        self._analytics_rows = grouped[REPORTS_CATEGORY]
        for title in CATEGORY_ORDER:
            cards = grouped[title]
            if not cards:
                continue
            group = QWidget(self._rows)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 16, 0, 0)
            group_layout.setSpacing(10)
            heading = IOSSectionHeader(self.tr(title))
            heading.setToolTip(self.tr("{0} controls").format(len(cards)))
            group_layout.addWidget(heading)
            separator = QFrame(group)
            separator.setFixedHeight(1)
            self._category_lines.append(separator)
            group_layout.addWidget(separator)
            from src.gui.liquid.cards import ControlGrid, prepare_card
            grid = ControlGrid()
            group_layout.addLayout(grid)
            if title == REPORTS_CATEGORY:
                self._analytics_group = group
                master = IOSCard()
                row = QHBoxLayout(master)
                row.setContentsMargins(16, 12, 16, 12)
                row.setSpacing(_ROW_SPACING)
                text = QVBoxLayout()
                label = QLabel(self.tr("Disable All Analytics"))
                self._daemon_labels.append(label)
                self._analytics_count_label = QLabel()
                self._analytics_count_label.setProperty("daemonInformation", True)
                self._daemon_labels.append(self._analytics_count_label)
                text.addWidget(label)
                text.addWidget(self._analytics_count_label)
                row.addLayout(text, 1)
                self.analytics_switch = IOSSwitch(False)
                self.analytics_switch.toggled.connect(self._toggle_all_analytics)
                row.addWidget(self.analytics_switch)
                _reserve_action_space(row)
                prepare_card(master)
                grid.addWidget(master)
            for card in sorted(cards, key=lambda row: str(row.property("sortTitle")).casefold()):
                grid.addWidget(card)
                card.show()
            self._rows.append(group)
            self._category_groups.append((group, cards))
        self._sync_analytics_switch()
        self._retheme()

    def _sync_analytics_switch(self):
        values = self.daemons_tweak.value or {}
        count = sum(all(values.get(key) is True for key in daemon.value) for daemon in ANALYTICS_DAEMONS)
        self.analytics_switch.blockSignals(True)
        self.analytics_switch.setChecked(count == len(ANALYTICS_DAEMONS))
        self.analytics_switch.blockSignals(False)
        self._analytics_count_label.setText(self.tr("{0} of {1} controls selected. Turn on to disable all; turn off to re-enable all after Apply.").format(count, len(ANALYTICS_DAEMONS)))
        self._analytics_count_label.setWordWrap(True)

    def _toggle_all_analytics(self, checked):
        if not self.daemons_tweak.enabled or (checked and not self._confirm_daemon_enable()):
            self._sync_analytics_switch()
            return
        for daemon in ANALYTICS_DAEMONS:
            if not checked and daemon.name in self._forced_daemons:
                continue
            self.daemons_tweak.set_multiple_values(daemon.value, value=checked)
            self._set_switch(daemon, checked)
        self._sync_analytics_switch()
        self._apply_search()

    def _apply_search(self, *_args):
        if getattr(self, "_building", False):
            return
        self._filter_rows()

    def _filter_rows(self):
        searching = bool(self.search.text().strip())
        mode = self.filter_control.currentData()
        favorites = self._favorites.names()
        matches = 0
        operations = []
        visibility = {}
        for card, (daemon, switch) in zip(self.daemon_cards, self.daemon_switches):
            visible = (not any(key in self.daemons_tweak.never_enable for key in daemon.value)
                       and self.search.matches(card.property("searchText")))
            if mode == "enabled":
                visible = visible and switch.isChecked()
            elif mode == "disabled":
                visible = visible and not switch.isChecked()
            elif mode == "favorites":
                visible = visible and "daemon:" + daemon.name in favorites
            operations.append((card, visible))
            visibility[card] = visible
            matches += visible
        if self._screen_time_card is not None:
            visible = mode == "all" and self.search.matches(self._screen_time_card.property("searchText"))
            operations.append((self._screen_time_card, visible))
            visibility[self._screen_time_card] = visible
            matches += visible
        for group, cards in self._category_groups:
            operations.append((group, any(visibility.get(card, False) for card in cards)))
        disabled_matches = matches and not self.daemons_tweak.enabled
        self.search_empty.setText(QCoreApplication.translate(
            "ListSearch", "Enable daemon modifications to see matching services.")
            if disabled_matches else QCoreApplication.translate("ListSearch", "No matches found."))
        operations.append((self.search_empty, bool((searching or mode != "all") and (not matches or disabled_matches))))
        self._visibility_batch.apply(self._rows, operations)

    def _make_daemon_switch(self, title: str, daemon: Daemon, information: str = ""):
        from src.gui.ios.feature_news import control_title
        title = control_title(title)
        information = information or self.tr(DAEMON_DESCRIPTIONS.get(daemon.name, ""))
        card = IOSCard()
        card.setProperty("searchText", " ".join([title, information, daemon.name, *daemon.value]))
        card.setProperty("sortTitle", title.removeprefix(self.tr("Disable ")).casefold())
        row_layout = QHBoxLayout(card)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(_ROW_SPACING)

        c = ColorThemeManager.instance().colors
        label = QLabel(title)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        self._daemon_labels.append(label)
        if information:
            text = QVBoxLayout()
            text.setSpacing(5)
            text.addWidget(label)
            detail = QLabel(information)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
            detail.setProperty("daemonInformation", True)
            self._daemon_labels.append(detail)
            text.addWidget(detail)
            row_layout.addLayout(text, 1)
            card.setToolTip(information + "\n\n" + "\n".join(daemon.value))
        else:
            row_layout.addWidget(label, 1)

        value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
        dangerous = any(key in self.daemons_tweak.never_enable for key in daemon.value)
        if dangerous:
            value = False
        switch = IOSSwitch(value)
        switch.toggled.connect(
            lambda checked, d=daemon: self._on_daemon_toggled(d, checked)
        )
        from src.gui.ios.feature_news import add_new_badge
        add_new_badge(row_layout, "daemon:" + daemon.name, card)
        row_layout.addWidget(switch)
        from src.gui.liquid.controls import FavoriteButton
        favorite = FavoriteButton(self)
        favorite.setFixedSize(_FAVORITE_SIZE, _FAVORITE_SIZE)
        favorite.setCheckable(True)
        favorite.setIconSize(QSize(23, 23))
        favorite.setCursor(Qt.PointingHandCursor)
        favorite.setAccessibleName(self.tr("Favorite: {0}").format(title))
        favorite.setToolTip(self.tr("Add or remove from favorites"))
        favorite.setStyleSheet(t("tweak_favorite_button"))
        self._favorite_buttons["daemon:" + daemon.name] = favorite
        self._update_favorite(favorite, "daemon:" + daemon.name in self._favorites.names())
        favorite.toggled.connect(lambda checked, name="daemon:" + daemon.name:
                                 self._favorites.set_favorite(name, checked))
        row_layout.addWidget(favorite)
        info = QPushButton(card)
        info.setFixedSize(_INFO_SIZE, _INFO_SIZE)
        info.setIcon(theme_icon(":/icon/questionmark.circle.svg", c.text_secondary))
        info.setIconSize(QSize(19, 19))
        info.setCursor(Qt.PointingHandCursor)
        info.setToolTip(self.tr("About {0}").format(title))
        info.setAccessibleName(info.toolTip())
        info.setStyleSheet(t("tweak_info_button"))
        info.clicked.connect(lambda: self._show_daemon_info(title, information, daemon))
        self._info_buttons.append(info)
        row_layout.addWidget(info)

        if dangerous:
            switch.setEnabled(False)
            note = QLabel(QCoreApplication.translate(
                "Nugget", "blocked (boot-loop protection)"))
            note.setFixedWidth(100)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {c.error}; font-size: 12px;")
            self._forced_notes.append(note)
            row_layout.insertWidget(row_layout.indexOf(switch), note)

        forced_name = getattr(daemon, "name", "")
        if forced_name in self._forced_daemons:
            # Safety rules force-disable this daemon: locked ON.
            switch.setChecked(True)
            switch.setEnabled(False)
            self._forced_switches.append(switch)
            note = QLabel(QCoreApplication.translate("Nugget", "safety rules"))
            note.setFixedWidth(100)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {c.error}; font-size: 12px;")
            self._forced_notes.append(note)
            row_layout.insertWidget(row_layout.indexOf(switch), note)

        from src.gui.liquid.selection_card import bind_selection_card
        bind_selection_card(card,switch, favorite_feedback=True)
        row = self._viewport_rows.wrap(card)
        row.setParent(self._rows)
        row.hide()
        return row, switch

    def _show_daemon_info(self, title, information, daemon):
        from src.gui.dialogs.confirmation import ConfirmationDialog
        message = self.tr("Intended effect") + "\n" + information
        message += "\n\n" + self.tr(
            "The exact effects depend on your system version. Some older service names may be ignored. "
            "A service name alone does not confirm that stopping it is safe.")
        message += "\n\n" + self.tr(
            "Turn the service switch off and apply again to allow it to run. "
            "The master switch only controls whether changes are included.")
        dialog = ConfirmationDialog(self, title, message, self.tr("Close"),
                                    subject="\n".join(daemon.value))
        dialog.cancel_btn.hide()
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _update_favorite(self, button, selected):
        button.blockSignals(True)
        button.setChecked(selected)
        colors = ColorThemeManager.instance().colors
        button.setIcon(QIcon(theme_pixmap(
            ":/icon/star-fill.svg" if selected else ":/icon/star.svg",
            '#d6b967' if selected else colors.text_secondary, 23,
            self.devicePixelRatioF())))
        button.blockSignals(False)

    def _refresh_favorites(self):
        names = self._favorites.names()
        for name, button in self._favorite_buttons.items():
            self._update_favorite(button, name in names)
        self._apply_search()

    def _on_master_toggled(self, checked: bool):
        if checked and not self._confirm_daemon_enable():
            # User hit "Stop" in one of the warnings: keep the master off.
            self.master_switch.blockSignals(True)
            self.master_switch.setChecked(False)
            self.master_switch.blockSignals(False)
            return
        self.daemons_tweak.set_enabled(checked)
        self._update_daemons_enabled(animate=True)
        pages = getattr(self.window, "ios_pages", None)
        if pages is not None:
            QTimer.singleShot(0, lambda: self.window._update_shared_nav(
                pages.currentIndex()))

    def _restore_notification_services(self):
        if not self.daemons_tweak.enabled:
            self.master_switch.setChecked(True)
            if not self.daemons_tweak.enabled:
                return
        for daemon in NOTIFICATION_RECOVERY_DAEMONS:
            if daemon.name in self._forced_daemons:
                continue
            # Write explicit False values: dropping keys does not reliably undo
            # a previously applied launchd disabled override on the device.
            self.daemons_tweak.set_multiple_values(daemon.value, value=False)
            self._set_switch(daemon, False)
        self.refresh_from_tweaks()
        QMessageBox.information(
            self, QCoreApplication.translate("Nugget", "Call Notification Services"),
            QCoreApplication.translate(
                "Nugget", "Service settings are ready. Apply changes and reboot your device "
                "to re-enable them. Services locked by safety rules remain disabled."))

    def _on_daemon_toggled(self, daemon: Daemon, checked: bool):
        if not self.daemons_tweak.enabled:
            self._set_switch(daemon, bool(self.daemons_tweak.value.get(daemon.value[0], False)))
            return
        forced_name = getattr(daemon, "name", "")
        if not checked and forced_name in self._forced_daemons:
            # Safety rules force this daemon off — it cannot be re-enabled.
            reason = self._forced_daemons.get(forced_name)
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Daemon Locked by Safety Rules"),
                QCoreApplication.translate(
                    "Nugget",
                    "GoldenNugget safety rules force-disable this daemon on your "
                    "setup, so it cannot be re-enabled.\n\n{0}").format(reason or ""))
            self._set_switch(daemon, True)
            return
        if checked and not self._confirm_daemon_enable():
            # Revert the individual toggle so nothing gets applied.
            self._set_switch(daemon, False)
            return
        self.daemons_tweak.set_multiple_values(daemon.value, value=checked)
        self._sync_analytics_switch()
        self._apply_search()
        if checked:
            self.master_switch.setChecked(True)
            if daemon is Daemon.Location:
                self._warn_location_daemon()

    def _on_screen_time_toggled(self, checked: bool):
        if not self.daemons_tweak.enabled:
            self.screen_time_switch.blockSignals(True)
            self.screen_time_switch.setChecked(self.screen_time_tweak.enabled)
            self.screen_time_switch.blockSignals(False)
            return
        if checked and not self._confirm_daemon_enable():
            self.screen_time_switch.blockSignals(True)
            self.screen_time_switch.setChecked(False)
            self.screen_time_switch.blockSignals(False)
            return
        self.screen_time_tweak.set_enabled(checked)

    def _set_switch(self, daemon: Daemon, value: bool):
        for d, switch in self.daemon_switches:
            if d is daemon:
                switch.blockSignals(True)
                switch.setChecked(value)
                switch.blockSignals(False)
                return

    def _confirm_daemon_enable(self) -> bool:
        """Show the bootloop + backup warnings once; the acknowledgement is
        stored in GoldenNugget settings (not in presets), so it only pops up
        the first time daemons are enabled for this install."""
        if self._confirming:
            return True
        settings = getattr(self.window, "settings", None) if self.window is not None else None
        # HotLoad: if the Daemons tweak is flagged dangerous for this
        # device/iOS, warn first. Acked once per page instance.
        if not self._hotload_acked:
            dm = getattr(self.window, "device_manager", None)
            version = dm.get_current_device_version() if dm is not None else None
            model = dm.get_current_device_model() if dm is not None else None
            hotload = HotLoad(settings)
            rule = hotload.rule_for(
                "Daemons", device_version=version, device_model=model)
            if rule is not None:
                # Imported here: ``src.gui.dialogs`` pulls in the pages, which
                # import this module again (circular at import time).
                from src.gui.dialogs.hotload_warning import confirm_flagged
                if not confirm_flagged(rule, self):
                    return False
            self._hotload_acked = True
        if settings is not None and settings.value("daemon_bootloop_warned", False, type=bool):
            return True
        self._confirming = True
        try:
            if not self._show_confirm_dialog(
                "Stopping system services can leave your device stuck restarting or unable to start. "
                "Recovery may require restoring the device."
            ):
                return False
            if not self._show_confirm_dialog(
                "Make a full device backup before applying these changes."
            ):
                return False
            if settings is not None:
                settings.setValue("daemon_bootloop_warned", True)
                settings.sync()
            return True
        finally:
            self._confirming = False

    def _show_confirm_dialog(self, text: str) -> bool:
        import PySide6.QtWidgets as QW
        box = QW.QMessageBox(self)
        box.setIcon(QW.QMessageBox.Icon.Warning)
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Before you continue"))
        box.setText(text)
        continue_btn = box.addButton(
            QCoreApplication.translate("Nugget", "Continue Anyway"),
            QW.QMessageBox.ButtonRole.AcceptRole)
        box.addButton(
            QCoreApplication.translate("Nugget", "Stop"),
            QW.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(continue_btn)
        box.exec()
        return box.clickedButton() is continue_btn

    def _warn_location_daemon(self):
        """Location Services daemon keeps PosterBoard alive on iPhone 14."""
        dm = getattr(self.window, "device_manager", None)
        model = dm.get_current_device_model() if dm is not None else ""
        # "iPhone14," matches the whole iPhone 14 lineup (regular, Plus,
        # Pro, Pro Max — iPhone14,2 ... iPhone14,8).
        if not model.startswith("iPhone14,"):
            return
        QMessageBox.warning(
            self,
            QCoreApplication.translate("Nugget", "Wallpaper Risk on iPhone 14"),
            QCoreApplication.translate(
                "Nugget",
                "Disabling Location Services has been reported to break wallpapers "
                "(PosterBoard) on iPhone 14. If your wallpaper disappears after "
                "applying, re-enable this daemon and apply again."))

    def _update_daemons_enabled(self, animate: bool = False):
        enabled = self.daemons_tweak.enabled
        self._rows.setEnabled(enabled)
        if self._screen_time_card is not None:
            self._screen_time_group.setEnabled(enabled)
        for switch in self._forced_switches:
            switch.setChecked(True)
            switch.setEnabled(False)

        screen_time_switch = getattr(self, "screen_time_switch", None)
        if screen_time_switch is not None:
            screen_time_switch.setEnabled(enabled)
        # the only caller that animates is the master switch itself; a build, a
        # device change or a theme change must never re-run the cascade
        self._rows.set_shown(enabled, animate=animate)
        self._disabled_hint.setVisible(not enabled)
        self._apply_search()

    def refresh_from_tweaks(self):
        """Resync every switch with the current tweak state."""
        if getattr(self, "_building", False):
            return
        signature = (self.daemons_tweak.enabled,
                     tuple(sorted((self.daemons_tweak.value or {}).items())),
                     getattr(getattr(self, 'screen_time_tweak', None), 'enabled', False))
        if (signature == getattr(self, '_refresh_signature', None)
                and self.master_switch.isChecked() == self.daemons_tweak.enabled):
            return
        self._refresh_signature = signature
        self.master_switch.blockSignals(True)
        self.master_switch.setChecked(self.daemons_tweak.enabled)
        self.master_switch.blockSignals(False)
        self._update_daemons_enabled()

        for daemon, switch in self.daemon_switches:
            value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
            if switch.isChecked() != value:
                switch.blockSignals(True)
                switch.setChecked(value)
                switch.blockSignals(False)

        if hasattr(self, "screen_time_switch"):
            self.screen_time_switch.blockSignals(True)
            self.screen_time_switch.setChecked(self.screen_time_tweak.enabled)
            self.screen_time_switch.blockSignals(False)

        for switch in self._forced_switches:
            switch.blockSignals(True)
            switch.setChecked(True)
            switch.setEnabled(False)
            switch.blockSignals(False)

        self._sync_analytics_switch()
        self._apply_search()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._master_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px; background-color: transparent;")
        self._disabled_hint.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        for lbl in self._daemon_labels:
            lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;" if lbl.property("daemonInformation") else f"color: {c.text_primary}; font-size: 15px;")
        for name, button in self._favorite_buttons.items():
            self._update_favorite(button, name in self._favorites.names())
        for button in self._info_buttons:
            button.setStyleSheet(t("tweak_info_button"))
            button.setIcon(theme_icon(":/icon/questionmark.circle.svg", c.text_secondary))
        for note in self._forced_notes:
            note.setStyleSheet(f"color: {c.error}; font-size: 12px;")
        for separator in self._category_lines:
            separator.setStyleSheet(f"background-color: {c.border}; border: none;")
        if hasattr(self, '_screen_time_label'):
            self._screen_time_label.setStyleSheet(
                f"color: {c.text_primary}; font-size: 15px;")


class IOSDaemonsPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        c = ColorThemeManager.instance().colors
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self._scroll = scroll
        self.content = None
        layout.addWidget(scroll)

    def prepare_content(self, *, finish=True):
        if self.content is None:
            self.content = IOSDaemonsContent(self.window, self)
            self._scroll.setWidget(self.content)
        if finish:
            self.content._builder.finish()

    def showEvent(self, event):
        self.prepare_content(finish=False)
        super().showEvent(event)
        self.refresh_from_tweaks()

    def refresh_from_tweaks(self):
        if self.content is not None:
            self.content.refresh_from_tweaks()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        if self.content is not None:
            self.content._retheme()
