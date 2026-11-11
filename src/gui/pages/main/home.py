from webbrowser import open_new_tab

from PySide6.QtCore import QCoreApplication

from src.devicemanagement.device_capabilities import device_os_name
from src.gui.preset_widget import PresetWidget
from src.gui.theme import ColorThemeManager
from src.qt.mainwindow_ui import Ui_Nugget

from ..page import Page


class HomePage(Page):
    def __init__(self, window, ui: Ui_Nugget):
        super().__init__()
        self.window = window
        self.ui = ui
        self.show_uuid = False
        self.preset_widget = None

    def load_page(self):
        ## HOME PAGE ACTIONS
        self.ui.phoneVersionLbl.linkActivated.connect(self.toggle_version_label)
        self.ui.discordBtn.clicked.connect(lambda: open_new_tab("https://discord.gg/Rm6r4zeE3y"))

        self._trim_to_logo_header()
        self._inject_preset_widget()

    def _trim_to_logo_header(self):
        """Match the clean new-home look: big logo + title, no button clutter.

        Hides the Discord/GitHub buttons beside the title and the credits
        button wall, so the classic home reads as just logo + text (+ the
        presets widget below).
        """
        for name in ("discordBtn", "starOnGithubBtn"):
            btn = getattr(self.ui, name, None)
            if btn is not None:
                btn.setVisible(False)
        credits = getattr(self.ui, "verticalWidget_6", None)
        if credits is not None:
            credits.setVisible(False)

    def _inject_preset_widget(self):
        """Add the active-preset banner at the bottom of the home page."""
        layout = self.ui.verticalLayout_2
        self.preset_widget = PresetWidget(
            window=self.window,
            on_manage=self.window.open_presets_section,
            ios_style=False)
        # Place it above the version label at the very bottom, then keep the
        # version label pinned below it.
        if hasattr(self.ui, "appVersionLbl"):
            layout.insertWidget(layout.indexOf(self.ui.appVersionLbl),
                                self.preset_widget)
        else:
            layout.addWidget(self.preset_widget)
        self.preset_widget.refresh()

    def refresh_preset_widget(self):
        if self.preset_widget is not None:
            self.preset_widget.refresh()

    ## ACTIONS
    def updatePhoneInfo(self):
        # name label
        self.ui.phoneNameLbl.setText(self.window.device_manager.get_current_device_name())
        # version label
        ver = self.window.device_manager.get_current_device_version()
        build = self.window.device_manager.get_current_device_build()
        self.show_uuid = False
        if ver != "":
            self.show_version_text(version=ver, build=build)
        else:
            self.ui.phoneVersionLbl.setText(QCoreApplication.tr("Please connect a device."))

    def toggle_version_label(self):
        if self.show_uuid:
            self.show_uuid = False
            ver = self.window.device_manager.get_current_device_version()
            build = self.window.device_manager.get_current_device_build()
            if ver != "":
                self.show_version_text(version=ver, build=build)
        else:
            self.show_uuid = True
            uuid = self.window.device_manager.get_current_device_udid()
            if uuid != "":
                c = ColorThemeManager.instance().colors
                self.ui.phoneVersionLbl.setText(
                    f"<a style=\"text-decoration:none; color: {c.text_secondary};\" href=\"#\">{uuid}</a>")

    def show_version_text(self, version: str, build: str):
        c = ColorThemeManager.instance().colors
        support_str: str = f"<span style=\"color: {c.success};\">" + QCoreApplication.tr("Supported!") + "</span></a>"
        if not self.window.device_manager.get_current_device_is_supported_by_fork():
            support_str = f"<span style=\"color: {c.error};\">" + QCoreApplication.tr("Not Supported.") + "</span></a>"
        elif self.window.device_manager.get_current_device_partially_supported():
            support_str = f"<span style=\"color: {c.warning};\">" + QCoreApplication.tr("Partially Supported") + "</span></a>"
        self.ui.phoneVersionLbl.setText(
            f"<a style=\"text-decoration:none; color: {c.text_secondary};\" href=\"#\">{device_os_name(self.window.device_manager.get_current_device_model())} {version} ({build}) {support_str}")
