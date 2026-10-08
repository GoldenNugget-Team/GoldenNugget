from PySide6.QtCore import (
    QCoreApplication, QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QHBoxLayout, QLabel, QMessageBox,
    QGraphicsOpacityEffect, QSizePolicy,
)

from src.gui.ios.components import IOSSectionHeader, IOSSwitch, IOSSearchField, IOSSearchEmpty
from src.gui.theme import ColorThemeManager
from src.tweaks.tweaks import tweaks, TweakID
from src.tweaks.tweak_loader import load_daemons
from src.tweaks.daemons_tweak import Daemon, RECOMMENDED_ANALYTICS
from src.controllers.hotload import HotLoad, confirm_flagged

# QWIDGETSIZE_MAX — PySide6 does not export the C macro, this is its value.
_NO_MAX_HEIGHT = 16777215


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
        self._layout.setSpacing(8)
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
        self.screen_time_tweak = tweaks.get(TweakID.ClearScreenTimeAgentPlist)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 32)
        layout.setSpacing(8)

        self.search = IOSSearchField(self)
        layout.addWidget(self.search)

        # Master enable switch
        layout.addWidget(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Daemons to Disable")
        ))
        master_card = QWidget()
        master_row = QHBoxLayout(master_card)
        master_row.setContentsMargins(16, 10, 16, 10)
        master_row.setSpacing(12)
        c = ColorThemeManager.instance().colors
        master_label = QLabel(QCoreApplication.translate("Nugget", "Enable Daemon Modifications"))
        master_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        self._master_label = master_label
        master_row.addWidget(master_label, 1)
        self.master_switch = IOSSwitch(self.daemons_tweak.enabled)
        self.master_switch.toggled.connect(self._on_master_toggled)
        master_row.addWidget(self.master_switch)
        layout.addWidget(master_card)

        # Everything that acts on daemons lives in one block that the master
        # switch unrolls / folds away, so those rows only exist on screen while
        # daemon modifications are actually on. The Recommended shortcut is the
        # first row of that block: leaving it on screen next to a hidden list
        # would just look broken. The forced-by-HotLoad rows are in here too;
        # hiding them changes nothing safety-wise, because
        # _apply_hotload_daemon_forcing injects those keys at apply time no
        # matter what the switches (or a preset) say.
        self._rows = _DaemonRows(self)
        layout.addWidget(self._rows)

        # Recommended: one tap to disable every safe analytics/telemetry daemon.
        # Pure analytics/tracking/logging — nothing boot-critical, so this set
        # is confirmed safe to disable (mirrors MiniVoidyy/GoldenNugget-).
        self.recommended_card = QWidget()
        recommended_row = QHBoxLayout(self.recommended_card)
        recommended_row.setContentsMargins(16, 10, 16, 10)
        recommended_row.setSpacing(12)
        self._recommended_label = QLabel(QCoreApplication.translate(
            "Nugget", "Recommended (analytics, tracking & logging)"))
        self._recommended_label.setStyleSheet(
            f"color: {c.text_primary}; font-size: 15px; font-weight: 600;")
        recommended_row.addWidget(self._recommended_label, 1)
        self.recommended_switch = IOSSwitch(self._recommended_all_on())
        self.recommended_switch.toggled.connect(self._on_recommended_toggled)
        recommended_row.addWidget(self.recommended_switch)
        self._rows.append(self.recommended_card)

        self.daemon_cards = []
        self.daemon_switches = []
        self._daemon_labels = []
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
        for title, daemon in [
            (QCoreApplication.translate("Nugget", "Disable thermalmonitord"), Daemon.thermalmonitord),
            (QCoreApplication.translate("Nugget", "Disable OTA"), Daemon.OTA),
            (QCoreApplication.translate("Nugget", "Disable UsageTrackingAgent"), Daemon.UsageTrackingAgent),
            (QCoreApplication.translate("Nugget", "Disable Game Center"), Daemon.GameCenter),
            (QCoreApplication.translate("Nugget", "Disable ATWAKEUP"), Daemon.ATWAKEUP),
            (QCoreApplication.translate("Nugget", "Disable Tips Services"), Daemon.Tips),
            (QCoreApplication.translate("Nugget", "VPN Icon"), Daemon.VPN),
            (QCoreApplication.translate("Nugget", "Disable Chinese WLAN Service"), Daemon.ChineseLAN),
            (QCoreApplication.translate("Nugget", "Disable HealthKit"), Daemon.HealthKit),
            (QCoreApplication.translate("Nugget", "Disable AirPrint"), Daemon.AirPrint),
            (QCoreApplication.translate("Nugget", "Disable Assistive Touch"), Daemon.AssistiveTouch),
            (QCoreApplication.translate("Nugget", "Disable iCloud"), Daemon.iCloud),
            (QCoreApplication.translate("Nugget", "Disable Internet Tethering (Hotspot)"), Daemon.InternetTethering),
            (QCoreApplication.translate("Nugget", "Disable Passbook"), Daemon.PassBook),
            (QCoreApplication.translate("Nugget", "Disable Spotlight"), Daemon.Spotlight),
            (QCoreApplication.translate("Nugget", "Disable NanoTimeKit (Apple Watch Face Sync)"), Daemon.NanoTimeKit),
            (QCoreApplication.translate("Nugget", "Disable Voice Control"), Daemon.VoiceControl),
            (QCoreApplication.translate("Nugget", "Follow Up"), Daemon.FollowUp),
            (QCoreApplication.translate("Nugget", "Location Services"), Daemon.Location),
        ]:
            card, switch = self._make_daemon_switch(title, daemon)
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))

        # Analytics, data tracking & logging toggles (from MiniVoidyy/GoldenNugget-)
        # Safe telemetry/analytics daemons — nothing boot-critical.
        self._analytics_header = self._rows.append(IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Analytics, Data Tracking & Logging")
        ))
        analytics_start = len(self.daemon_cards)
        for title, daemon in [
            (QCoreApplication.translate("Nugget", "Disable Wi-Fi Analytics"), Daemon.WifiAnalytics),
            (QCoreApplication.translate("Nugget", "Disable System Analytics"), Daemon.AnalyticsHelper),
            (QCoreApplication.translate("Nugget", "Disable Call Analytics (RTC Reporting)"), Daemon.CallAnalytics),
            (QCoreApplication.translate("Nugget", "Disable CoreDuet (Battery/Usage Statistics)"), Daemon.CoreDuet),
            (QCoreApplication.translate("Nugget", "Disable Insight"), Daemon.Insight),
            (QCoreApplication.translate("Nugget", "Disable Metrics"), Daemon.Metrics),
            (QCoreApplication.translate("Nugget", "Disable Media Experience Analytics"), Daemon.MediaExperience),
            (QCoreApplication.translate("Nugget", "Disable Symptom Diagnostics"), Daemon.Symptomsd),
            (QCoreApplication.translate("Nugget", "Disable Statistical Diagnostics"), Daemon.StatisticalDiagnostic),
            (QCoreApplication.translate("Nugget", "Disable Wireless Diagnostics"), Daemon.WirelessDiagnostics),
            (QCoreApplication.translate("Nugget", "Disable Duet Heuristic"), Daemon.DuetHeuristic),
            (QCoreApplication.translate("Nugget", "Disable Duet Expert"), Daemon.DuetExpert),
            (QCoreApplication.translate("Nugget", "Disable Decisiond"), Daemon.Decisiond),
            (QCoreApplication.translate("Nugget", "Disable Triald (A/B Experiment Telemetry)"), Daemon.Triald),
            (QCoreApplication.translate("Nugget", "Disable Sociald"), Daemon.Sociald),
        ]:
            card, switch = self._make_daemon_switch(title, daemon)
            self.daemon_cards.append(card)
            self.daemon_switches.append((daemon, switch))

        self._analytics_cards = self.daemon_cards[analytics_start:]
        # Screen Time
        self._screen_time_header = IOSSectionHeader(
            QCoreApplication.translate("Nugget", "Disable Screen Time Agent")
        )
        layout.addWidget(self._screen_time_header)
        self._screen_time_card = None
        if self.screen_time_tweak is not None:
            card = QWidget()
            self._screen_time_card = card
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(16, 10, 16, 10)
            row_layout.setSpacing(12)
            label = QLabel(QCoreApplication.translate("Nugget", "Clear ScreenTimeAgent.plist file"))
            label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
            self._screen_time_label = label
            row_layout.addWidget(label, 1)
            self.screen_time_switch = IOSSwitch(self.screen_time_tweak.enabled)
            self.screen_time_switch.toggled.connect(self.screen_time_tweak.set_enabled)
            row_layout.addWidget(self.screen_time_switch)
            layout.addWidget(card)

        self.search_empty = IOSSearchEmpty(self)
        layout.addWidget(self.search_empty)
        self.search.textChanged.connect(self._apply_search)
        self._update_daemons_enabled()
        layout.addStretch()

    def _apply_search(self):
        searching = bool(self.search.text().strip())
        matches = 0
        for card in self.daemon_cards:
            visible = self.search.matches(card.property("searchText"))
            card.setVisible(visible)
            matches += visible
        self.recommended_card.setVisible(not searching)
        self._analytics_header.setVisible(any(not card.isHidden() for card in self._analytics_cards))
        screen_match = self._screen_time_card is not None and self.search.matches(
            self._screen_time_label.text(), self._screen_time_header.text(), "ScreenTimeAgent")
        self._screen_time_header.setVisible(screen_match)
        if self._screen_time_card is not None:
            self._screen_time_card.setVisible(screen_match)
        disabled_matches = matches and not self.daemons_tweak.enabled
        self.search_empty.setText(QCoreApplication.translate(
            "ListSearch", "Enable daemon modifications to see matching services.")
            if disabled_matches else QCoreApplication.translate("ListSearch", "No matches found."))
        self.search_empty.setVisible(searching and not screen_match and (not matches or disabled_matches))

    def _make_daemon_switch(self, title: str, daemon: Daemon):
        card = QWidget()
        card.setProperty("searchText", " ".join([title, daemon.name, *daemon.value]))
        row_layout = QHBoxLayout(card)
        row_layout.setContentsMargins(16, 10, 16, 10)
        row_layout.setSpacing(12)

        c = ColorThemeManager.instance().colors
        label = QLabel(title)
        label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        self._daemon_labels.append(label)
        row_layout.addWidget(label, 1)

        value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
        switch = IOSSwitch(value)
        switch.toggled.connect(
            lambda checked, d=daemon: self._on_daemon_toggled(d, checked)
        )
        row_layout.addWidget(switch)

        forced_name = getattr(daemon, "name", "")
        if forced_name in self._forced_daemons:
            # Safety rules force-disable this daemon: locked ON.
            switch.setChecked(True)
            switch.setEnabled(False)
            self._forced_switches.append(switch)
            note = QLabel(QCoreApplication.translate("Nugget", "safety rules"))
            note.setStyleSheet(f"color: {c.error}; font-size: 12px;")
            self._forced_notes.append(note)
            row_layout.addWidget(note)

        self._rows.append(card)
        return card, switch

    def _on_master_toggled(self, checked: bool):
        if checked and not self._confirm_daemon_enable():
            # User hit "Stop" in one of the warnings: keep the master off.
            self.master_switch.blockSignals(True)
            self.master_switch.setChecked(False)
            self.master_switch.blockSignals(False)
            return
        self.daemons_tweak.set_enabled(checked)
        self._update_daemons_enabled(animate=True)

    def _recommended_all_on(self) -> bool:
        """True when every daemon in RECOMMENDED_ANALYTICS is already active."""
        value = self.daemons_tweak.value
        if not value:
            return False
        return all(value.get(d.value[0], False) for d in RECOMMENDED_ANALYTICS)

    def _on_recommended_toggled(self, checked: bool):
        """Toggle every safe analytics/telemetry daemon at once."""
        if checked:
            if not self._confirm_daemon_enable():
                self.recommended_switch.blockSignals(True)
                self.recommended_switch.setChecked(False)
                self.recommended_switch.blockSignals(False)
                return
            self.master_switch.setChecked(True)
        for daemon in RECOMMENDED_ANALYTICS:
            if getattr(daemon, "name", "") in self._forced_daemons:
                # HotLoad safety rules force this daemon on — never untoggle it.
                continue
            self.daemons_tweak.set_multiple_values(daemon.value, value=checked)
            self._set_switch(daemon, checked)

    def _on_daemon_toggled(self, daemon: Daemon, checked: bool):
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
        if checked:
            self.master_switch.setChecked(True)
            if daemon is Daemon.Location:
                self._warn_location_daemon()

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
            if rule is not None and not confirm_flagged(rule, self):
                return False
            self._hotload_acked = True
        if settings is not None and settings.value("daemon_bootloop_warned", False, type=bool):
            return True
        self._confirming = True
        try:
            if not self._show_confirm_dialog(
                "Hold Up before pressing continue, this section can bootloop "
                "your phone. Don't cry about that you have not been notified then."
            ):
                return False
            if not self._show_confirm_dialog(
                "Creating full backup is hightly recommended"
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
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Hold Up"))
        box.setText(text)
        continue_btn = box.addButton(
            QCoreApplication.translate("Nugget", "Continue Anyway"),
            QW.QMessageBox.ButtonRole.AcceptRole)
        stop_btn = box.addButton(
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
        for card in self.daemon_cards:
            card.setEnabled(enabled)
        if hasattr(self, 'recommended_card'):
            self.recommended_card.setEnabled(enabled)
        for switch in self._forced_switches:
            switch.setChecked(True)
            switch.setEnabled(False)
        # the only caller that animates is the master switch itself; a build, a
        # device change or a theme change must never re-run the cascade
        self._rows.set_shown(enabled, animate=animate)
        self._apply_search()

    def refresh_from_tweaks(self):
        """Resync every switch with the current tweak state."""
        self.master_switch.blockSignals(True)
        self.master_switch.setChecked(self.daemons_tweak.enabled)
        self.master_switch.blockSignals(False)
        self._update_daemons_enabled()

        for daemon, switch in self.daemon_switches:
            value = self.daemons_tweak.value.get(daemon.value[0], False) if self.daemons_tweak.value else False
            switch.blockSignals(True)
            switch.setChecked(value)
            switch.blockSignals(False)

        for switch in self._forced_switches:
            switch.blockSignals(True)
            switch.setChecked(True)
            switch.setEnabled(False)
            switch.blockSignals(False)

        screen_time_switch = getattr(self, 'screen_time_switch', None)
        if screen_time_switch is not None:
            screen_time_switch.blockSignals(True)
            screen_time_switch.setChecked(self.screen_time_tweak.enabled)
            screen_time_switch.blockSignals(False)

        recommended_switch = getattr(self, 'recommended_switch', None)
        if recommended_switch is not None:
            recommended_switch.blockSignals(True)
            recommended_switch.setChecked(self._recommended_all_on())
            recommended_switch.blockSignals(False)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._master_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        for lbl in self._daemon_labels:
            lbl.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
        for note in self._forced_notes:
            note.setStyleSheet(f"color: {c.error}; font-size: 12px;")
        if hasattr(self, '_recommended_label'):
            self._recommended_label.setStyleSheet(
                f"color: {c.text_primary}; font-size: 15px; font-weight: 600;")
        if hasattr(self, '_screen_time_label'):
            self._screen_time_label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")


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
        self.content = IOSDaemonsContent(window, self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

    def refresh_from_tweaks(self):
        self.content.refresh_from_tweaks()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.content._retheme()
