"""The hand-built stand-in for the deleted Qt Designer file (``Ui_Nugget``).

The classic shell is parked in the modern app: the sidebar and the device
bar never become visible (the iOS-mode window renders its own controls),
but navigation, gating and retheme code still manage them through
``self.ui``. This object keeps every attribute those call-sites touch with
the old Designer names; anything whose visible Classic counterpart died
with the Designer file (RTL credit buttons, phone labels) resolves lazily
to a throwaway stub, so ``hide()``/``setEnabled()`` on it stay harmless
no-ops. The class-level annotations below declare the full surface the
code touches, mirroring what the generated file used to provide.
"""

from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from awesomeui import SidebarItem


class ShellUI:
    """Attribute bag replacing the generated ``Ui_Nugget``."""

    # -- parked device bar -------------------------------------------------
    deviceBar: QWidget
    devicePicker: QComboBox
    phoneIconBtn: QToolButton
    titleBar: QToolButton
    refreshBtn: QToolButton
    phoneNameLbl: QLabel
    phoneVersionLbl: QLabel
    appVersionLbl: QLabel

    # -- sidebar: real mount + items NavigationSidebar rewrites in place ---
    sidebar: QWidget
    sidebarDiv1: Any
    sidebarDiv2: Any
    centralwidget: QWidget
    homePage: QWidget
    daemonsPage: QWidget
    homePageBtn: SidebarItem
    posterboardPageBtn: SidebarItem
    templatesPageBtn: SidebarItem
    gestaltPageBtn: SidebarItem
    euEnablerPageBtn: SidebarItem
    statusBarPageBtn: SidebarItem
    passcodePageBtn: SidebarItem
    springboardOptionsPageBtn: SidebarItem
    internalOptionsPageBtn: SidebarItem
    liquidGlassPageBtn: SidebarItem
    daemonsPageBtn: SidebarItem
    iconThemesPageBtn: SidebarItem
    presetsPageBtn: SidebarItem
    applyPageBtn: SidebarItem
    settingsPageBtn: SidebarItem

    # -- parked classic buttons tugged by the device gate / RTL fix-up -----
    jjtechBtn: QWidget
    duyBtn: QWidget
    leminTwitterBtn: QWidget
    leminKoFiBtn: QWidget
    posterRestoreBtn: QWidget
    translatorsBtn: QWidget
    mikasaBtn: QWidget
    qtBtn: QWidget

    def __init__(self):
        # Device bar (parked): phone icon, title, picker, refresh.
        self.deviceBar = QWidget()
        deviceBar_layout = QHBoxLayout(self.deviceBar)
        deviceBar_layout.setContentsMargins(10, 6, 10, 6)
        deviceBar_layout.setSpacing(8)
        self.phoneIconBtn = QToolButton(self.deviceBar)
        self.phoneIconBtn.setObjectName("phoneIconBtn")
        self.phoneIconBtn.setIcon(QIcon(":/icon/phone.svg"))
        self.titleBar = QToolButton(self.deviceBar)
        self.titleBar.setObjectName("titleBar")
        self.titleBar.setEnabled(False)
        self.titleBar.setText(QCoreApplication.translate("Nugget", "GoldenNugget"))
        self.devicePicker = QComboBox(self.deviceBar)
        self.devicePicker.setObjectName("devicePicker")
        self.refreshBtn = QToolButton(self.deviceBar)
        self.refreshBtn.setObjectName("refreshBtn")
        self.refreshBtn.setIcon(QIcon(":/icon/arrow-clockwise.svg"))
        deviceBar_layout.addWidget(self.phoneIconBtn)
        deviceBar_layout.addWidget(self.titleBar, 1)
        deviceBar_layout.addWidget(self.devicePicker)
        deviceBar_layout.addWidget(self.refreshBtn)

        # Sidebar (parked): NavigationSidebar() overwrites the item
        # attributes declared above with its own SidebarItem objects.
        self.sidebar = QWidget()

        # Classic page slots in the content stack: never shown, only kept
        # so the stack indices the code navigates by stay stable.
        self.homePage = QWidget()
        self.daemonsPage = QWidget()
        self.centralwidget = QWidget()

        # Parked widgets: hidden label/buttons the dead classic code touches.
        self.appVersionLbl = QLabel()
        self.appVersionLbl.hide()
        self.phoneNameLbl = QLabel()
        self.phoneNameLbl.hide()
        self.phoneVersionLbl = QLabel()
        self.phoneVersionLbl.hide()
        self.jjtechBtn = QWidget()
        self.jjtechBtn.hide()
        self.duyBtn = QWidget()

    def __getattr__(self, name: str) -> Any:
        # Any attribute beyond the built ones belongs to a widget that died
        # with the Designer file: return an inert stub so hide()/show()/
        # setStyleSheet()/setEnabled() on it keep working as no-ops.
        if name.startswith("_"):
            raise AttributeError(name)
        stub = QWidget()
        self.__dict__[name] = stub
        return stub
