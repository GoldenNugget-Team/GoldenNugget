"""Mixins for :class:`MainWindow`, breaking the monolithic GUI shell into
focused pieces: device-bar handling, settings/presets/theme, navigation and
the apply/reset flow. Each mixin only reaches ``self`` attributes that
``MainWindow.__init__`` installs, so they stay plain objects mixed into
``class MainWindow(QtWidgets.QMainWindow, DeviceBarMixin, SettingsMixin,
NavigationMixin, ApplyMixin)``.
"""

from typing import Optional
import os

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QCoreApplication

from src.controllers.video_handler import set_ignore_frame_limit
from src.devicemanagement.constants import Version
from src.gui.dialogs import AboutProgramDialog
from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.logger import get_logger
from src.gui.theme import ColorThemeManager
from src.gui.thread_workers.apply_worker import (
    ApplyAlertMessage,
    ApplyThread,
    RefreshDevicesThread,
    get_sudo_pwd,
    set_sudo_pwd,
)
from src.gui.version import App_Build, App_Version
from src.gui.ios.theme_manager import ThemeManager
from src.gui.ios.tweaks import _hidden_feature_names
from src.gui.pages.pages_list import Page
from src.tweaks.tweak_classes import set_tweak_change_callback
from src.tweaks.tweaks import tweaks, TweakID


class DeviceBarMixin:
    """Device refresh, selection and per-device interface updates."""

    def updateInterfaceForNewDevice(self):
        # update the home page
        self.pages[Page.Home].updatePhoneInfo()

        # Rebuild the tweak sections for the newly selected device: the pages
        # are constructed at startup before any device is known, so per-device
        # compatibility filtering (min_version / iphone_only / ipad_only) is
        # only correct when re-evaluated against the real connected device.
        for page in ("ios_tweaks", "ios_springboard", "ios_internal", "ios_liquidglass"):
            section_page = getattr(self, page, None)
            if section_page is not None:
                try:
                    section_page.rebuild()
                except Exception:
                    pass


    def _apply_hidden_feature_gating(self):
        """Hide the Sidebar buttons and iOS home cards for HotLoad-hidden
        features on this device. Kept central so the gating survives every
        re-apply point (device refresh / selection).

        Only ever HIDES — it never re-shows a button that HotLoad hid. The
        Status Bar page used to be force-hidden on iOS 27 because the Speakeasy
        feature flag could not be written; it now delivers the carrier name
        through StatusBarOverrides.archive, so the page stays reachable there
        (trimmed down to the carrier rows by the page itself).
        """
        hidden = _hidden_feature_names()
        if hidden:
            print(f"[HotLoad] Hiding feature pages: {', '.join(sorted(hidden))}")
        statusbar_hidden = "Status Bar" in hidden
        # Sidebar (classic shell) buttons
        btn_map = {
            "Liquid Glass": self.ui.liquidGlassPageBtn,
            "Springboard": self.ui.springboardOptionsPageBtn,
            "Internal": self.ui.internalOptionsPageBtn,
            "PosterBoard": self.ui.posterboardPageBtn,
            "Daemons": self.ui.daemonsPageBtn,
        }
        for feat, btn in btn_map.items():
            btn.setVisible(feat not in hidden)
        self.ui.statusBarPageBtn.setVisible(not statusbar_hidden)
        # iOS home cards
        card_map = {
            "PosterBoard": self.ios_home.posterboard_card,
            "Daemons": self.ios_home.daemons_card,
        }
        for feat, card in card_map.items():
            card.setVisible(feat not in hidden)
        self.ios_home.set_statusbar_visible(not statusbar_hidden)


    @QtCore.Slot()
    def refresh_devices(self):
        if not self.refresh_in_progress:
            self.refresh_in_progress = True
            self.ui.refreshBtn.setDisabled(True)
            self.refresh_worker_thread = RefreshDevicesThread(manager=self.device_manager, settings=self.settings)
            self.refresh_worker_thread.alert.connect(self.alert_message)
            self.refresh_worker_thread.finished.connect(self.refresh_devices_finished)
            self.refresh_worker_thread.finished.connect(self.refresh_worker_thread.deleteLater)
            self.refresh_worker_thread.start()


    def warn_for_dev_beta(self):
        ver = self.device_manager.get_current_device_version()
        if ver == "":
            return
        if Version(ver) > Version("26.0") and not self.device_manager.get_current_device_build()[-1].isdigit():
            self.alert_message(ApplyAlertMessage(
                txt=self.tr("Warning: You are on iOS 26 beta.\n\nThis has been known to cause problems and potentially lead to bootloops.\n\nUse at your own risk!"),
                title="Warning", icon=QtWidgets.QMessageBox.Warning
            ), log_to_console=False)


    def refresh_devices_finished(self):
        self.refresh_in_progress = False
        # The thread's own ``finished -> deleteLater`` already freed the C++
        # object; drop our reference so closeEvent never probes a dead wrapper.
        try:
            self.refresh_worker_thread = None
        except Exception:
            pass
        self.toggle_thread_btns(disabled=False)
        # clear the picker
        self.ui.devicePicker.clear()

        if len(self.device_manager.devices) == 0:
            self.ui.devicePicker.setEnabled(False)
            self.ui.devicePicker.addItem(self.noneText)
            self.show_home()

            # hide all pages
            self.ui.sidebarDiv1.hide()

            self.ui.gestaltPageBtn.hide()
            self.ui.statusBarPageBtn.hide()
            self.ui.springboardOptionsPageBtn.hide()
            self.ui.internalOptionsPageBtn.hide()
            self.ui.liquidGlassPageBtn.hide()
            self.ui.daemonsPageBtn.hide()
            self.ui.iconThemesPageBtn.hide()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.hide()

            self.ui.sidebarDiv2.hide()
            self.ui.applyPageBtn.hide()
            self.ui.jjtechBtn.hide()
            self.ui.duyBtn.show()

            # mirror in the iOS UI: no device → no status bar card
            if hasattr(self, "ios_home"):
                self.ios_home.set_statusbar_visible(False)
        else:
            self.ui.devicePicker.setEnabled(True)
            # populate the ComboBox with device names
            for device in self.device_manager.devices:
                tag = " (@ USB)" if device.connected_via_usb else " (@ WiFi)"
                self.ui.devicePicker.addItem(f"{device.name}{tag}")

            # show all pages
            self.ui.sidebarDiv1.show()
            self.ui.statusBarPageBtn.show()
            self.ui.springboardOptionsPageBtn.show()
            self.ui.internalOptionsPageBtn.show()
            self.ui.liquidGlassPageBtn.show()
            self.ui.daemonsPageBtn.show()
            self.ui.iconThemesPageBtn.show()
            self.ui.passcodePageBtn.hide()
            self.ui.posterboardPageBtn.show()

            self.ui.sidebarDiv2.show()
            self.ui.applyPageBtn.show()

            # HotLoad-hidden features are carved out of the Sidebar and iOS home
            self._apply_hidden_feature_gating()
        
        # update the selected device
        self.ui.devicePicker.setCurrentIndex(0)
        # HotLoad-hidden features are carved out of the Sidebar and iOS home
        self._apply_hidden_feature_gating()
        # keep the iOS home in sync
        self.ios_home.refresh_device_combo()
        self.ios_home.update_device_info()
        self.ios_home.update_status()


    def change_selected_device(self, index):
        if len(self.device_manager.devices) > 0:
            self.device_manager.set_current_device(index=index)
            # hide sidebar buttons that are for newer versions
            MinTweakVersions = {
                "no_patch": [self.ui.gestaltPageBtn],
                "26.0": [self.ui.liquidGlassPageBtn],
            }

            device_ver = Version(self.device_manager.data_singleton.current_device.version)
            # toggle option visibility for the minimum versions
            for version, views in MinTweakVersions.items():
                if version == "no_patch":
                    # these items only apply to unpatched devices, which do not exist on this fork
                    for view in views:
                        view.hide()
                else:
                    # show views if the version is higher
                    parsed_ver = Version(version)
                    for view in views:
                        view.setVisible(device_ver >= parsed_ver)
            # The Status Bar page is no longer force-hidden on iOS 27 -- the
            # carrier name is delivered through StatusBarOverrides.archive.
            # Visibility is owned by _apply_hidden_feature_gating() (HotLoad
            # aware), so just re-apply it here. The Solarium fallback tweak is
            # a different, iOS 26-only tweak and keeps its own gating.
            if device_ver >= Version("27.0"):
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(False)
            else:
                if hasattr(self, "ios_tweaks"):
                    self.ios_tweaks.set_force_solarium_fallback_visible(True)
            self._apply_hidden_feature_gating()

            # force video looping on iPads (loop gated off the classic widgets)
            is_iphone = self.device_manager.get_current_device_model().startswith("iPhone")
            if not is_iphone:
                # force looping
                tweaks[TweakID.PosterBoard].loop_video = True

            # sparse-restore book credits do not apply to this fork
            self.ui.jjtechBtn.hide()
            # swap out the current posterboard file
            tweaks[TweakID.PosterBoard].config_manager.update_for_saved_database(self.device_manager.get_current_device_udid())

            # show the PB if initial load is true
            if self.initial_load:
                self.initial_load = False
                if len(tweaks[TweakID.PosterBoard].tendies) > 0:
                    self.show_ios_page(2)
                elif len(tweaks[TweakID.Templates].templates) > 0:
                    # templates have no dedicated page in the unified shell
                    self.show_ios_page(2)
                self._sync_sidebar_selection()
        else:
            self.device_manager.set_current_device(index=None)

        # update the interface
        self.updateInterfaceForNewDevice()
        self.ios_home.update_device_info()
        self.ios_home.update_status()
        if index > -1:
            self.warn_for_dev_beta()



class SettingsMixin:
    """Settings/preset loading, theme switching and app-version label."""

    def loadSettings(self):
        try:
            # load the settings
            auto_reboot = self.settings.value("auto_reboot", True, type=bool)
            ignore_frame_limit = self.settings.value("ignore_pb_frame_limit", False, type=bool)
            disable_tendies_limit = self.settings.value("disable_tendies_limit", False, type=bool)
            auto_refresh_posterboard = self.settings.value("auto_refresh_posterboard", True, type=bool)
            use_backup_cache = self.settings.value("use_backup_cache", True, type=bool)

            skip_setup = self.settings.value("skip_setup", True, type=bool)
            supervised = self.settings.value("supervised", False, type=bool)
            organization_name = self.settings.value("organization_name", "", type=str)
            use_encrypted_backup = self.settings.value("use_encrypted_backup", False, type=bool)
            use_afc_media = self.settings.value("use_afc_media", True, type=bool)
            tweak_autosave = self.settings.value("tweak_autosave", True, type=bool)

            self.device_manager.pref_manager.auto_reboot = auto_reboot
            set_ignore_frame_limit(ignore_frame_limit)
            self.device_manager.pref_manager.disable_tendies_limit = disable_tendies_limit
            self.device_manager.pref_manager.auto_refresh_posterboard = auto_refresh_posterboard
            self.device_manager.pref_manager.use_backup_cache = use_backup_cache
            self.device_manager.pref_manager.use_encrypted_backup = use_encrypted_backup
            self.device_manager.pref_manager.use_afc_media = use_afc_media
            self.device_manager.pref_manager.skip_setup = skip_setup
            self.device_manager.pref_manager.supervised = supervised
            self.device_manager.pref_manager.organization_name = organization_name
            self.device_manager.pref_manager.tweak_autosave = tweak_autosave
        except Exception as e:
            # Never silent: a NameError here used to abort every assignment
            # below it, so the app quietly booted with default preferences
            # (and the Settings switches read back OFF after a restart).
            get_logger("gui").warning("loadSettings failed: %s", e, exc_info=True)


    def autosave_enabled(self) -> bool:
        """Whether the AutoSave preset is written/loaded at all.

        Read through instead of cached on the window so flipping the Settings
        switch takes effect immediately, with no restart.
        """
        try:
            return bool(self.device_manager.pref_manager.tweak_autosave)
        except Exception:
            # never let a missing pref break tweak handling: autosave is the
            # historical default, so fall back to it
            return True


    def _load_last_preset(self):
        """Load the latest autosaved preset on startup.

        Prefers the AutoSave preset (written on every tweak change) so the UI
        restores the most recent configuration. Falls back to the last
        manually-loaded preset when no autosave exists.

        With autosave turned off the AutoSave preset is NOT loaded: the file is
        deliberately left on disk (it can still be loaded by hand), but
        restoring a frozen snapshot on every launch would be misleading when
        the app no longer keeps it up to date.
        """
        if self.autosave_enabled() and "AutoSave" in self.preset_manager.list_presets():
            self.preset_manager.load_preset("AutoSave")
            # Rewrite AutoSave right away so stale entries (e.g. daemons that
            # are no longer exposed in the UI) are purged from disk on the
            # next launch instead of lingering in the file forever.
            self._save_autosave_preset()
            return
        last_preset = self.settings.value("last_loaded_preset", "", type=str)
        if last_preset:
            self.preset_manager.load_preset(last_preset)


    def _register_tweak_autosave(self):
        """Register callback to auto-save preset when tweaks change."""
        set_tweak_change_callback(self._on_tweak_changed)


    def _on_tweak_changed(self):
        """Called when any tweak value changes - schedule autosave."""
        # Keep the visible configuration summary/counts in sync while the
        # user is toggling controls; these widgets intentionally do not rebuild
        # the whole page for every switch change.
        try:
            if hasattr(self, "ios_home"):
                self.ios_home.refresh_summary()
            for page in getattr(self, "ios_pages", []):
                content = getattr(page, "content", None)
                if content is not None and hasattr(content, "refresh_section_counts"):
                    content.refresh_section_counts()
        except Exception:
            pass
        if not self.autosave_enabled():
            # Still registered (so the callback is never dangling) but inert:
            # no debounce timer is even scheduled while the option is off.
            return
        if self._preset_autosave_pending:
            return
        self._preset_autosave_pending = True
        # Debounce: save after 500ms of no changes
        QtCore.QTimer.singleShot(500, self._save_autosave_preset)


    def _save_autosave_preset(self):
        """Save current tweak state to AutoSave preset."""
        self._preset_autosave_pending = False
        if not self.autosave_enabled():
            # Second guard: a debounce timer scheduled before the switch was
            # flipped off still fires, and must not resurrect the file.
            return
        try:
            self.preset_manager.save_preset(
                "AutoSave", "Automatic save of last tweak configuration", tags=["auto"],
                device_model=self.device_manager.get_current_device_model() or "",
                ios_version=self.device_manager.get_current_device_version() or "")
        except Exception:
            pass  # Silent fail - autosave is best-effort


    def apply_theme(self, theme: int):
        """Apply the UI mode WITHOUT navigating away.

        CLASSIC: sidebar + classic home; iOS-style pages open as actions.
        IOS: full-screen iOS UI with the shared header providing back
        navigation. Only the chrome changes — the current page stays put.
        """
        self.theme_manager.save_theme(theme)
        is_ios = theme == ThemeManager.IOS
        self.ui.sidebar.setVisible(not is_ios)
        self.ui.deviceBar.setVisible(not is_ios)
        if is_ios:
            # iOS mode: full-screen, no padding
            self.shell_layout.setContentsMargins(0, 0, 0, 0)
            self.shell_layout.setSpacing(0)
            self.body_row.setSpacing(0)
            # entering the new UI: land on its home unless already inside it.
            # A UI-mode switch re-lays out the whole shell, so no page slide.
            if self.content_stack.currentIndex() != 1:
                self.content_stack.setCurrentIndex(1)
                self.set_ios_page(0, animate=False)
            self._update_shared_nav(self.ios_pages.currentIndex())
        else:
            # Classic mode: add padding around the shell
            self.shell_layout.setContentsMargins(16, 16, 16, 16)
            self.shell_layout.setSpacing(12)
            self.body_row.setSpacing(16)
            # classic UI hides the shared header except on pages that need it
            # (Icon Themes keeps "+ Add Icon")
            self._update_shared_nav(self.ios_pages.currentIndex())
            if self.ios_pages.currentIndex() == 0:
                # the iOS home has no meaning inside the classic shell
                self.show_home()
        self._sync_sidebar_selection()


    def updateAppVersionLabel(self):
        new_text: str = self.ui.appVersionLbl.text()
        new_text = new_text.replace("%VERSION", App_Version)
        if App_Build > 0:
            new_text = new_text.replace("%BETATAG", f"(beta {App_Build})")
        else:
            new_text = new_text.replace("%BETATAG", "")
        self.ui.appVersionLbl.setText(new_text)


    def _sync_settings(self):
        """Sync settings to disk immediately after critical changes."""
        try:
            self.settings.sync()
        except Exception:
            pass  # Best effort



class NavigationMixin:
    """Page structure, shared IOS nav bar and sidebar selection."""

    # Pages allowed to keep the iOS-style header inside the CLASSIC shell.
    # Each one has a right action that is otherwise unreachable on the page
    # itself (Icon Themes "+ Add Icon"). The PosterBoard page keeps its header
    # in iOS mode only: it already has its own in-page "Import Files" card,
    # so the header's "+ Add Tendies" would be redundant chrome in classic.
    _classic_nav_pages = (10,)

    def _update_shared_nav(self, index: int):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            use_nav = index in self._classic_nav_pages
            self.ios_nav.setVisible(use_nav)
            if not use_nav:
                return
        # the iOS home page is full-screen — no header at all
        self.ios_nav.setVisible(index != 0)
        if index == 0:
            self.ios_nav.clear_right_action()
            return
        title = self._ios_page_titles.get(index, "")
        self.ios_nav.set_title(title)
        self.ios_nav.set_back_visible(True)
        right = self._nav_right_actions.get(index)
        if right:
            self.ios_nav.set_right_action(right[0], right[1])
        else:
            self.ios_nav.clear_right_action()


    def _sync_sidebar_selection(self):
        """Move the checked highlight of the sidebar to the active view."""
        btns = (self.ui.homePageBtn, self.ui.posterboardPageBtn,
            self.ui.springboardOptionsPageBtn, self.ui.internalOptionsPageBtn,
            self.ui.liquidGlassPageBtn, self.ui.daemonsPageBtn,
            self.ui.applyPageBtn, self.ui.settingsPageBtn,
            self.ui.statusBarPageBtn, self.ui.iconThemesPageBtn)
        page_to_btn = {
            0: 0,   # home
            2: 1,   # posterboard
            7: 2,   # springboard
            8: 3,   # internal
            9: 4,   # liquid glass
            3: 5,   # daemons
            6: 6,   # apply
            4: 7,   # settings
            5: 8,   # status bar
            10: 9,  # icon themes
        }
        idx = None
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            if self.content_stack.currentIndex() == 0:
                idx = 0
            elif self.content_stack.currentIndex() == 1:
                idx = page_to_btn.get(self.ios_pages.currentIndex())
            elif self.content_stack.currentIndex() == 2:
                idx = 5
        else:
            idx = page_to_btn.get(self.ios_pages.currentIndex())
        target = btns[idx] if idx is not None else None
        for b in btns:
            b.setChecked(b is target)


    def show_home(self):
        """Open the home page of the ACTIVE UI mode."""
        if self.theme_manager.current_theme == ThemeManager.IOS:
            self.content_stack.setCurrentIndex(1)
            self.set_ios_page(0)
            self._update_shared_nav(0)
        else:
            self.content_stack.setCurrentIndex(0)
        self._refresh_preset_widgets()
        self._sync_sidebar_selection()


    def _refresh_preset_widgets(self):
        """Keep the active-preset banners on both home pages in sync."""
        try:
            self.pages[Page.Home].refresh_preset_widget()
        except Exception:
            pass
        try:
            self.ios_home.refresh_preset_widget()
        except Exception:
            pass


    def show_ios_page(self, index: int):
        self.content_stack.setCurrentIndex(1)
        self.set_ios_page(index)


    # iOS-style page transition: the incoming page slides in from the right, one
    # full page width, so it enters from off-screen rather than merely nudging.
    # Only the content area moves — the shared nav bar above the stack stays put,
    # which is what the stock iOS push looks like.
    #
    # The curve is deliberately soft and the duration long: a short OutCubic
    # reads as a snap on a page as tall as the window, so it drifts in instead.
    # Returning to Home uses the reverse direction so the back navigation feels
    # like a real stack pop instead of an abrupt page replacement.
    PAGE_SLIDE_MS = 240
    HOME_PAGE = 0

    def set_ios_page(self, index: int, animate: bool = True):
        """The only place that switches the iOS page stack.

        Guards the index, snaps any page still mid-slide to its final spot and
        then slides the incoming page in. Home enters from the left when it is
        opened as the destination of a back navigation.
        """
        stack = self.ios_pages
        if not isinstance(index, int) or index < 0 or index >= stack.count():
            return
        if stack.currentIndex() == index:
            return
        self._stop_page_slide()
        stack.setCurrentIndex(index)
        page = stack.widget(index)
        if animate and stack.isVisible():
            self._slide_page_in(page, from_left=index == self.HOME_PAGE)

    def _slide_page_in(self, page, from_left=False):
        y = page.y()
        if page.width() <= 0 or page.height() <= 0:
            page.move(QtCore.QPoint(0, y))
            return
        anim = QtCore.QPropertyAnimation(page, b"pos", self)
        start_x = -page.width() if from_left else page.width()
        start_pos = QtCore.QPoint(start_x, y)
        end_pos = QtCore.QPoint(0, y)
        # Move before starting the animation so the freshly selected page is
        # never painted once at its final position and then snapped away.
        page.move(start_pos)
        anim.setDuration(self.PAGE_SLIDE_MS + (40 if from_left else 0))
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._page_slide_anim = anim
        anim.finished.connect(self._stop_page_slide)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_page_slide(self):
        """End a running page slide at once, so no page is left half-slid."""
        anim = getattr(self, "_page_slide_anim", None)
        if anim is None:
            return
        self._page_slide_anim = None
        try:
            page = anim.targetObject()
            anim.stop()
        except RuntimeError:
            return
        if page is not None:
            try:
                page.move(QtCore.QPoint(0, page.y()))
            except RuntimeError:
                pass


    def open_presets_section(self):
        """Open the dedicated preset manager page."""
        self.content_stack.setCurrentIndex(1)
        self.set_ios_page(12)
        self._update_shared_nav(12)
        self._sync_sidebar_selection()


    def eventFilter(self, obj, event):
        """Handle ESC and the mouse back button as navigation-back."""
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        try:
            etype = event.type()
        except (AttributeError, TypeError):
            return False
        if etype == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            return self._go_back()
        if etype == QtCore.QEvent.Type.MouseButtonPress and event.button() in (
                QtCore.Qt.MouseButton.BackButton, QtCore.Qt.MouseButton.ExtraButton1):
            return self._go_back()
        return False


    def _go_back(self) -> bool:
        """Navigate back.

        IOS mode: subpage -> iOS home (stay there).
        CLASSIC mode: any action page backs out to the classic home.
        """
        if self.content_stack.currentIndex() == 1:
            if self.theme_manager.current_theme == ThemeManager.IOS:
                if self.ios_pages.currentIndex() != 0:
                    self.set_ios_page(0)
                    return True
                return False
            # classic shell: action pages back out straight to classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        if self.content_stack.currentIndex() == 2:
            # classic daemons page -> classic home
            self.content_stack.setCurrentIndex(0)
            self._sync_sidebar_selection()
            return True
        return False


    def on_homePageBtn_clicked(self):
        self.show_home()


    def on_statusBarPageBtn_clicked(self):
        self.show_ios_page(5)
        self._sync_sidebar_selection()


    def on_springboardOptionsPageBtn_clicked(self):
        self.show_ios_page(7)
        self._sync_sidebar_selection()


    def on_internalOptionsPageBtn_clicked(self):
        self.show_ios_page(8)
        self._sync_sidebar_selection()


    def on_liquidGlassPageBtn_clicked(self):
        self.show_ios_page(9)
        self._sync_sidebar_selection()


    def on_daemonsPageBtn_clicked(self):
        if self.theme_manager.current_theme == ThemeManager.CLASSIC:
            self.pages[Page.Daemons].load()
            self.pages[Page.Daemons].refresh()
            self.content_stack.setCurrentIndex(2)
        else:
            self.ios_daemons.refresh_from_tweaks()
            self.show_ios_page(3)
        self._sync_sidebar_selection()


    def on_iconThemesPageBtn_clicked(self):
        self.show_ios_page(10)
        self._sync_sidebar_selection()


    def on_posterboardPageBtn_clicked(self):
        self.show_ios_page(2)
        self._sync_sidebar_selection()


    def on_applyPageBtn_clicked(self):
        self.show_ios_page(6)
        self._sync_sidebar_selection()


    def on_settingsPageBtn_clicked(self):
        self.show_ios_page(4)
        self._sync_sidebar_selection()


    def show_about_dialog(self):
        dialog = AboutProgramDialog(self)
        dialog.exec()



class ApplyMixin:
    """Apply/reset orchestration, alerts and dialog prompts."""

    # IOSSummaryDialog extra-button result when the user asks to update the
    # backup cache from the pre-apply summary (QDialog.Accepted=1/Rejected=0).
    _SUMMARY_UPDATE_CACHE = 2

    def update_label(self, txt: str):
        # Mirror progress into the iOS surfaces (home indicator + Apply page)
        try:
            if txt:
                self.ios_home.show_process_status(txt)
                self.ios_apply.set_status(txt)
        except Exception:
            pass


    def remove_tweaks_clicked(self):
        dialog = ResetDialog(device_manager=self.device_manager, apply_reset=self.apply_changes)
        dialog.exec()


    @QtCore.Slot()
    def apply_tweaks_clicked(self):
        self.apply_changes()


    def _build_apply_summary(self) -> tuple:
        """Human-readable breakdown of what an apply would change.

        Returns ``(lines, total)`` — ``lines`` feed the pre-apply summary
        dialog, ``total`` is the summed change count (0 = nothing to do).
        """
        from src.tweaks.registry import SPECS_BY_SECTION, Section
        from src.tweaks.tweak_loader import load_plist_tweaks, load_daemons
        load_plist_tweaks()
        load_daemons()

        lines = []
        total = 0

        def add(label, count):
            nonlocal total
            if count > 0:
                total += count
                lines.append(f"• {label}: {count}")

        for section in Section:
            enabled = sum(
                1 for spec in SPECS_BY_SECTION[section]
                if getattr(tweaks.get(spec.id), "enabled", False))
            if enabled:
                add(QCoreApplication.translate("Nugget", section.value), enabled)

        pb = tweaks.get(TweakID.PosterBoard)
        if pb is not None:
            add(QCoreApplication.translate("Nugget", "PosterBoard"), len(pb.tendies))

        tmpl = tweaks.get(TweakID.Templates)
        if tmpl is not None:
            add(QCoreApplication.translate("Nugget", "Templates"), len(tmpl.templates))

        st = tweaks.get(TweakID.StatusBar)
        if st is not None:
            try:
                add(QCoreApplication.translate("Nugget", "Status Bar"), st.count_overrides())
            except Exception:
                pass

        dm = tweaks.get(TweakID.Daemons)
        if dm is not None:
            add(QCoreApplication.translate("Nugget", "Daemons"),
                sum(1 for v in getattr(dm, "value", {}).values() if v))

        it = tweaks.get(TweakID.IconThemes)
        if it is not None:
            add(QCoreApplication.translate("Nugget", "Icon Themes"), len(it.themes))

        return lines, total


    def _confirm_apply_summary(self) -> bool:
        """Show the pre-apply summary; True only if the user confirms.

        When the backup cache is enabled, an extra "Update Cache" button lets
        the user force a cache refresh right here — the running summary shows
        the cache's creation date, the refresh runs in a background thread,
        and the dialog re-opens with the fresh date.
        """
        if not self.device_manager.get_current_device_udid():
            QtWidgets.QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "No iPhone connected"),
                QCoreApplication.translate(
                    "Nugget", "Connect and unlock an iPhone before applying tweaks."))
            return False
        cache_enabled = self._backup_cache_enabled()
        while True:
            lines, total = self._build_apply_summary()
            if not lines:
                QtWidgets.QMessageBox.information(
                    self,
                    QCoreApplication.translate("Nugget", "Nothing to apply"),
                    QCoreApplication.translate(
                        "Nugget",
                        "No tweaks, daemons, wallpapers or templates are enabled. "
                        "Enable something first."))
                return False
            if cache_enabled:
                cache_line = self._backup_cache_summary_line()
                if cache_line:
                    lines.append(cache_line)
            storage_warning = self._storage_warning_line()
            if storage_warning:
                lines.append(storage_warning)
            storage_estimate = self._storage_estimate_line()
            if storage_estimate:
                lines.append(storage_estimate)
            lines.append(self._time_estimate_line(total))
            battery_warning = self._battery_warning_line()
            if battery_warning:
                lines.append(battery_warning)
            compatibility_warning = self._compatibility_warning_line()
            if compatibility_warning:
                lines.append(compatibility_warning)
            from src.gui.ios.components import IOSSummaryDialog
            dlg = IOSSummaryDialog(
                title=QCoreApplication.translate("Nugget", "Apply Tweaks"),
                lines=lines,
                muted=QCoreApplication.translate(
                    "Nugget",
                    "Your device reboots when it's done — remember to turn Find My "
                    "back on afterwards. A protective backup runs first."),
                confirm_text=QCoreApplication.translate("Nugget", "Apply"),
                extra_button=(QCoreApplication.translate("Nugget", "Update Cache")
                              if cache_enabled else ""),
                parent=self, details_callback=self._show_apply_preview)
            res = dlg.exec()
            if res == self._SUMMARY_UPDATE_CACHE:
                self._run_cache_update()
                # Re-open the summary (with the refreshed cache date) so the
                # user can review and then confirm or cancel.
                continue
            return res == QtWidgets.QDialog.Accepted and self._confirm_tweak_conflicts()

    def _storage_warning_line(self):
        """Return a warning when the selected device has little free space."""
        info = getattr(self, "_storage_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or not current_udid or info.get("udid") != current_udid:
            return None
        total = int(info.get("total", 0) or 0)
        free = int(info.get("free", 0) or 0)
        if total <= 0 or free < 0:
            return None
        # iOS restores need working room in addition to the tweak payloads.
        # Use the larger of 5 GiB or 10% of the data volume as a conservative
        # warning threshold; this warns without blocking the user's choice.
        threshold = max(5 * 1024 ** 3, int(total * 0.10))
        if free >= threshold:
            return None
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Low iPhone storage: {0} GB free. Restoring tweaks may require "
            "at least {1} GB free and could fail if the device runs out of space."
        ).format(f"{free / (1024 ** 3):.1f}", f"{threshold / (1024 ** 3):.1f}")

    def _storage_estimate_line(self):
        """Show the recommended working room for backup and restore."""
        info = getattr(self, "_storage_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or not current_udid or info.get("udid") != current_udid:
            return None
        total = int(info.get("total", 0) or 0)
        if total <= 0:
            return None
        recommended = max(5 * 1024 ** 3, int(total * 0.10))
        return QCoreApplication.translate(
            "Nugget",
            "Estimated working space: keep at least {0} GB free for the backup and restore."
        ).format(f"{recommended / (1024 ** 3):.1f}")

    def _time_estimate_line(self, selected_count):
        """Give a deliberately conservative estimate for the apply flow."""
        count = max(1, int(selected_count or 0))
        seconds = 120 + (count * 8)
        minutes, remainder = divmod(seconds, 60)
        if remainder >= 30:
            minutes += 1
        return QCoreApplication.translate(
            "Nugget",
            "Estimated time: about {0} minutes, depending on the iPhone and connection."
        ).format(minutes)

    def _battery_warning_line(self):
        info = getattr(self, "_battery_info", None)
        current_udid = self.device_manager.get_current_device_udid()
        if not info or info.get("udid") != current_udid:
            return None
        percent = info.get("percent")
        if percent is None or bool(info.get("charging", False)) or percent > 20:
            return None
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Low iPhone battery: {0}%. Connect the charger before restoring."
        ).format(int(percent))

    def _compatibility_warning_line(self):
        from src.gui.ios.compat import compatibility_reasons, device_family
        from src.tweaks.registry import SPECS_BY_ID
        version = self.device_manager.get_current_device_version() or ""
        model = self.device_manager.get_current_device_model() or ""
        if not version or not model:
            return None
        family = device_family(model)
        is_iphone = None if family is None else family == "iphone"
        incompatible = []
        for tweak_id, spec in SPECS_BY_ID.items():
            tweak = tweaks.get(tweak_id)
            if tweak is None or not getattr(tweak, "enabled", False):
                continue
            reasons = compatibility_reasons(tweak_id, version, model, is_iphone)
            if reasons:
                incompatible.append((spec.title, "; ".join(reasons)))
        if not incompatible:
            return None
        names = ", ".join(f"{title} ({reason})" for title, reason in incompatible[:4])
        if len(incompatible) > 4:
            names += QCoreApplication.translate("Nugget", " and more")
        return QCoreApplication.translate(
            "Nugget",
            "⚠ Compatibility warning: {0} selected tweak(s) do not match {1} ({2}): {3}."
        ).format(len(incompatible), version, model, names)

    def _confirm_tweak_conflicts(self):
        from src.controllers.tweak_conflicts import current_conflicts
        from src.gui.theme import t
        conflicts = current_conflicts(self.device_manager)
        if not conflicts:
            return True
        dialog = QtWidgets.QMessageBox(self)
        dialog.setStyleSheet(t("confirm_dialog"))
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        dialog.setWindowTitle(QCoreApplication.translate("TweakConflicts", "Conflicting tweaks"))
        dialog.setText(QCoreApplication.translate(
            "TweakConflicts", "Some selected tweaks contradict or overwrite each other. "
            "Return to the list to change your selection, or continue with the current selection."))
        dialog.setInformativeText("\n\n".join(item.description() for item in conflicts[:5]))
        dialog.setDetailedText("\n\n".join(item.description() for item in conflicts))
        back = dialog.addButton(QCoreApplication.translate("TweakConflicts", "Review selection"),
                                QtWidgets.QMessageBox.RejectRole)
        proceed = dialog.addButton(QCoreApplication.translate("TweakConflicts", "Continue anyway"),
                                   QtWidgets.QMessageBox.AcceptRole)
        proceed.setObjectName("cancelBtn")
        dialog.setDefaultButton(back)
        dialog.setEscapeButton(back)
        dialog.exec()
        return dialog.clickedButton() is proceed

    def _show_apply_preview(self, parent):
        from src.controllers.apply_preview import load_preview, preview_lines, safe_capture_preview
        from src.gui.dialogs.apply_preview import ApplyPreviewDialog
        manager = self.device_manager
        preview = safe_capture_preview(manager)
        if preview is None:
            lines = [QCoreApplication.translate(
                "ApplyPreview", "The preview could not be built. See the session log for details.")]
        else:
            previous = load_preview(manager.get_current_device_udid(),
                                    manager.get_current_device_version())
            lines = preview_lines(preview, previous)
            from src.controllers.tweak_conflicts import current_conflicts
            conflicts = current_conflicts(manager)
            if conflicts:
                lines = [QCoreApplication.translate("TweakConflicts", "Conflicting tweaks")] + [
                    item.description() for item in conflicts] + lines
        dialog = ApplyPreviewDialog(lines, parent)
        dialog.exec()
        dialog.deleteLater()

    def _backup_cache_enabled(self) -> bool:
        return (self.device_manager.pref_manager.use_backup_cache
                and not os.environ.get("GOLDENNUGGET_NO_BACKUP_CACHE"))

    def _backup_cache_summary_line(self) -> str:
        udid = self.device_manager.get_current_device_udid()
        if not udid:
            return ""
        from src.restore.protective_cache import peek_cache_info
        info = peek_cache_info(udid)
        q = QCoreApplication.translate
        if info is None:
            return q(
                "Nugget",
                "• Backup cache: none yet (will be created on this apply)")
        return q(
            "Nugget",
            "• Backup cache from: {0} (reused if fresh)").format(
                info.get("created") or "unknown")

    def _run_cache_update(self) -> bool:
        """Force a backup-cache refresh in a background thread, modally.

        Returns True only when the refresh ran to completion. The progress
        dialog stays open until ``finished_with_result`` fires; a failure
        already surfaced through the alert pipeline.
        """
        from src.gui.thread_workers.apply_worker import CacheUpdateThread
        udid = self.device_manager.get_current_device_udid()
        if not udid:
            QtWidgets.QMessageBox.information(
                self,
                QCoreApplication.translate("Nugget", "Update Cache"),
                QCoreApplication.translate(
                    "Nugget", "No device is selected. Connect your device first."))
            return False
        worker = CacheUpdateThread(manager=self.device_manager)
        self._cache_update_thread = worker  # keep a strong ref while running
        prog = QtWidgets.QProgressDialog(
            QCoreApplication.translate(
                "Nugget", "Updating backup cache..."),
            "", 0, 0, self)
        prog.setWindowTitle(QCoreApplication.translate("Nugget", "Update Cache"))
        prog.setWindowModality(QtCore.Qt.WindowModal)
        prog.setCancelButton(None)
        prog.setMinimumDuration(0)
        result = [False]

        def _on_progress(txt):
            prog.setLabelText(txt)

        def _on_finish(ok: bool, _err: str):
            result[0] = ok
            prog.close()

        worker.progress.connect(_on_progress)
        worker.finished_with_result.connect(_on_finish)
        worker.alert.connect(self.alert_message)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        # Modal event loop — worker signals keep flowing until _on_finish closes it.
        prog.exec()
        return result[0]


    def apply_changes(self, reset_pages: list=None):
        if not self.apply_in_progress:
            # Applies (not resets) get a what-will-change summary first.
            if reset_pages is None and not self._confirm_apply_summary():
                return
            if reset_pages is None:
                self._prepare_rollback_preset()
            self.apply_in_progress = True
            self.toggle_thread_btns(disabled=True)
            self.worker_thread = ApplyThread(manager=self.device_manager, settings=self.settings, reset_pages=reset_pages)
            self.worker_thread.progress.connect(self.update_label)
            self.worker_thread.alert.connect(self.alert_message)
            self.worker_thread.request_text.connect(self.on_password_request)
            self.worker_thread.choice_prompt.connect(self.on_choice_prompt)
            self.worker_thread.finished_with_result.connect(self.finish_apply_thread)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.start()

    def _prepare_rollback_preset(self):
        """Keep the last successful apply available as a one-click rollback."""
        import shutil
        try:
            source = self.preset_manager.get_preset_path("__LastApplied")
            target = self.preset_manager.get_preset_path("__Rollback")
            if os.path.isfile(source):
                shutil.copyfile(source, target)
        except Exception:
            pass

    def _save_last_applied_preset(self):
        try:
            self.preset_manager.save_preset(
                "__LastApplied", "Internal rollback snapshot", tags=["internal"],
                device_model=self.device_manager.get_current_device_model() or "",
                ios_version=self.device_manager.get_current_device_version() or "")
        except Exception:
            pass


    def alert_message(self, alert: Optional[ApplyAlertMessage], log_to_console: bool = True):
        if alert is None:
            # do sudo dialog input
            get_sudo_pwd() # clear if it is already there
            pwd, ok = QtWidgets.QInputDialog.getText(None, "Enter Sudo Password", "Enter Your Computer's Password:", QtWidgets.QLineEdit.Password, "")
            if ok and pwd:
                set_sudo_pwd(pwd)
            return
        if log_to_console:
            print(alert.txt)
        # Backend messages that did not pick an explicit icon default to
        # the error renderer (QMessageBox.Critical).
        icon = alert.icon if alert.icon is not None else QtWidgets.QMessageBox.Critical
        # Apply/reset failures carry a traceback: route them through the same
        # parsed crash dialog (severity/likely cause + Copy Error + Report on
        # GitHub + Open Log), instead of a raw QMessageBox.
        if (icon == QtWidgets.QMessageBox.Critical
                and alert.exc_type is not None and alert.detailed_txt):
            from src.exceptions.crash_handler import show_error_dialog, _classify
            info = _classify(alert.exc_type, alert.exc_value)
            self._embedded_alert_error(alert, info)
            return
        detailsBox = QtWidgets.QMessageBox()
        detailsBox.setIcon(icon)
        detailsBox.setWindowTitle(alert.title)
        detailsBox.setText(alert.txt)
        if alert.detailed_txt != None:
            detailsBox.setDetailedText(alert.detailed_txt)
        restore_btn = None
        if alert.backup_path:
            restore_btn = detailsBox.addButton(
                self.tr("Restore data from backup"), QtWidgets.QMessageBox.AcceptRole)
        detailsBox.exec()
        if restore_btn is not None and detailsBox.clickedButton() is restore_btn:
            self._start_cache_restore()


    def _embedded_alert_error(self, alert: ApplyAlertMessage, info: dict):
        """Show an apply failure through the crash/error dialog."""
        # Need the restore callback to survive the dialog's exec() lifetime.
        def _restore():
            self._start_cache_restore()
        from src.exceptions.crash_handler import show_error_dialog
        show_error_dialog(
            summary=alert.txt,
            traceback_text=alert.detailed_txt,
            info=info,
            backup_path=alert.backup_path,
            on_restore=_restore if alert.backup_path else None,
        )


    def _start_cache_restore(self):
        from src.gui.thread_workers.apply_worker import RestoreCacheThread
        if getattr(self, '_cache_restore_in_progress', False):
            return
        if self.apply_in_progress:
            # A restore and an apply/reset must never drive the device at the
            # same time — both open their own lockdown sessions.
            self.alert_message(ApplyAlertMessage(
                txt="Cannot restore data while an apply/reset is in progress.",
                title="Restore data",
                icon=QtWidgets.QMessageBox.Warning,
            ), log_to_console=False)
            return
        self._cache_restore_in_progress = True
        # Hold the thread on the window like ApplyThread/RefreshDevicesThread
        # do. A bare local reference lets the Python wrapper be garbage-
        # collected while the native thread is still running, which Qt reports
        # as the "QThread: Destroyed while thread '' is still running" crash
        # in the middle of a device restore.
        worker = RestoreCacheThread(manager=self.device_manager)
        self._cache_restore_thread = worker
        worker.progress.connect(self._update_restore_label)
        worker.alert.connect(self.alert_message)
        # The media push can hit a device that is paired but still locked after
        # the reboot, so the recovery needs the same Abort/Resume dialog the
        # apply gets.
        worker.choice_prompt.connect(self.on_choice_prompt)
        worker.finished_with_result.connect(self._finish_cache_restore)
        worker.finished.connect(self._cache_restore_thread_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()


    def _update_restore_label(self, txt: str):
        try:
            self.ios_home.show_process_status(txt)
        except Exception:
            pass


    def _finish_cache_restore(self, success: bool, error_msg: str = ""):
        self._cache_restore_in_progress = False
        if not success or error_msg:
            try:
                self.alert_message(ApplyAlertMessage(
                    txt=f"Restore data: {error_msg or 'failed'}",
                    title="Restore data",
                    icon=QtWidgets.QMessageBox.Critical,
                ), log_to_console=False)
            except Exception:
                pass


    def _cache_restore_thread_finished(self):
        # run() returned, so the native thread is done; drop the window's
        # reference (deleteLater is already queued via the other connection).
        try:
            self._cache_restore_thread = None
        except Exception:
            pass


    def on_password_request(self, title: str, label: str, box):
        try:
            password, ok = QtWidgets.QInputDialog.getText(
                self, title, label, QtWidgets.QLineEdit.Password)
            box.put(password if (ok and password) else None)
        except Exception:
            try:
                box.put(None)
            except Exception:
                pass


    def on_choice_prompt(self, title: str, text: str, box):
        """Main-thread Abort/Resume dialog (e.g. device locked too long after
        the security recovery). Built here — never on the worker thread — and
        the decision is boxed back to the waiting worker."""
        try:
            mbox = QtWidgets.QMessageBox(self)
            mbox.setWindowTitle(title)
            mbox.setIcon(QtWidgets.QMessageBox.Warning)
            mbox.setText(text)
            abort_btn = mbox.addButton(
                QCoreApplication.tr("Abort"), QtWidgets.QMessageBox.RejectRole)
            resume_btn = mbox.addButton(
                QCoreApplication.tr("Resume"), QtWidgets.QMessageBox.AcceptRole)
            mbox.setDefaultButton(resume_btn)
            mbox.exec()
            result = "abort" if mbox.clickedButton() is abort_btn else "resume"
        except Exception:
            result = "abort"
        try:
            box.put(result)
        except Exception:
            pass


    def finish_apply_thread(self, success: bool = False, error_msg: str = ""):
        self.apply_in_progress = False
        self.toggle_thread_btns(disabled=False)
        try:
            self.ios_settings._refresh_history()
        except Exception:
            pass
        worker = getattr(self, 'worker_thread', None)
        is_reset = worker is not None and worker.reset_pages is not None
        # Show completion indicator on the iOS home page
        try:
            if success:
                self.ios_home.show_process_status(
                    QCoreApplication.tr("Reset complete!") if is_reset else QCoreApplication.tr("Apply complete!"),
                    success=True)
            else:
                self.ios_home.show_process_status(
                    QCoreApplication.tr("Operation failed"), success=False)
        except Exception:
            pass
        if success:
            if worker is not None and not is_reset:
                self._save_last_applied_preset()
                self.prompt_star_on_github()
        else:
            # Show error notification if not already shown via alert
            if error_msg and "timed out" not in error_msg.lower():
                self.alert_message(ApplyAlertMessage(
                    txt=f"Operation failed: {error_msg}",
                    title="Error",
                    icon=QtWidgets.QMessageBox.Critical
                ), log_to_console=False)


    def prompt_star_on_github(self):
        if self.settings.value("star_prompt_done", False, type=bool):
            return
        self.settings.setValue("star_prompt_done", True)
        self._sync_settings()
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(self.tr("Enjoying GoldenNugget?"))
        box.setText(self.tr("If you like GoldenNugget, please consider giving it a star on GitHub!"))
        star_btn = box.addButton(self.tr("Star on GitHub"), QtWidgets.QMessageBox.AcceptRole)
        box.addButton(self.tr("Not now"), QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == star_btn:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QtCore.QUrl("https://github.com/awesomenull-dev/GoldenNugget"))


    def prompt_first_launch_backup(self) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(QCoreApplication.translate("Nugget", "Back up your device"))
        box.setText(QCoreApplication.translate(
            "Nugget",
            "Have you made a backup of your iPhone? Tweaks and daemon changes "
            "are risky — a bad tweak can bootloop the device or force a full "
            "restore, which erases everything. Create a backup in iTunes or "
            "Finder before using GoldenNugget."))
        box.setDetailedText(QCoreApplication.translate(
            "Nugget",
            "Back up your iPhone before tweaking:\n"
            "• Windows: iTunes → your device → Back Up Now\n"
            "• Mac: Finder → your device → Back Up Now\n\n"
            "GoldenNugget's own protected backup also runs automatically when "
            "you apply tweaks, but a full iTunes/Finder backup is the only "
            "complete safety net."))
        # Explicit opaque background: the dialog inherits the app's global
        # ``QWidget { background-color: transparent }`` rule otherwise and
        # would render see-through.
        c = ColorThemeManager.instance().colors
        box.setStyleSheet(f"""
            QMessageBox {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; background: transparent; }}
            QPushButton {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                border: 1px solid {c.border};
                border-radius: 6px;
                padding: 6px 16px;
                min-width: 80px;
            }}
            QPushButton:hover {{ background-color: {c.surface_hover}; }}
            QPushButton:pressed {{ background-color: {c.border}; }}
        """)
        got_it = box.addButton(
            QCoreApplication.translate("Nugget", "Got it, I'm backed up"),
            QtWidgets.QMessageBox.AcceptRole)
        box.addButton(
            QCoreApplication.translate("Nugget", "I'll do it later"),
            QtWidgets.QMessageBox.RejectRole)
        # Make sure the dialog comes to the front and grabs input focus
        # (otherwise clicks can be swallowed by the window around it).
        box.raise_()
        box.activateWindow()
        box.exec()
        return box.clickedButton() is got_it


    def toggle_thread_btns(self, disabled: bool):
        if disabled or not self.apply_in_progress:
            self.ios_apply.set_busy(disabled)
        if disabled or not self.refresh_in_progress:
            self.ui.refreshBtn.setDisabled(disabled)

