# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QMetaObject,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTime,
    QUrl,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QFontDatabase,
    QGradient,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import resources_rc


class Ui_Nugget(object):
    def setupUi(self, Nugget):
        if not Nugget.objectName():
            Nugget.setObjectName(u"Nugget")
        Nugget.resize(1000, 600)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(Nugget.sizePolicy().hasHeightForWidth())
        Nugget.setSizePolicy(sizePolicy)
        Nugget.setMinimumSize(QSize(1000, 600))
        Nugget.setMaximumSize(QSize(1000, 600))
        Nugget.setWindowTitle(u"GoldenNugget")
        Nugget.setWindowOpacity(1.000000000000000)
        Nugget.setStyleSheet(u"QWidget {\n"
"    color: #FFFFFF;\n"
"    background-color: transparent;\n"
"	spacing: 0px;\n"
"}\n"
"\n"
"QWidget:focus {\n"
"    outline: none;\n"
"}\n"
"\n"
"QWidget [cls=central] {\n"
"    background-color: #1e1e1e;\n"
"	border-radius: 0px;\n"
"	border: 1px solid #4B4B4B;\n"
"}\n"
"\n"
"QLabel {\n"
"    font-size: 14px;\n"
"}\n"
"\n"
"QToolButton {\n"
"    background-color: #3b3b3b;\n"
"    border: none;\n"
"    color: #e8e8e8;\n"
"    font-size: 14px;\n"
"	min-height: 35px;\n"
"	icon-size: 16px;\n"
"	padding-left: 10px;\n"
"	padding-right: 10px;\n"
"	border-radius: 8px;\n"
"}\n"
"\n"
"QToolButton[cls=sidebarBtn] {\n"
"    background-color: transparent;\n"
"	icon-size: 24px;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}\n"
"\n"
"QToolButton:checked {\n"
"    background-color: #2860ca;\n"
"    color: #FFFFFF;\n"
"}\n"
"\n"
"QCheckBox {\n"
"	spacing: 8px;\n"
"	font-size: 14px;\n"
"}\n"
"\n"
"QRadioButton {\n"
"	spacing: 8px;\n"
"	font-size: 14px;\n"
"}\n"
""
                        "\n"
"QLineEdit {\n"
"	border: none;\n"
"	background-color: transparent;\n"
"	color: #FFFFFF;\n"
"	font-size: 14px;\n"
"}\n"
"\n"
"QScrollBar:vertical {\n"
"    background: transparent;\n"
"    width: 8px;\n"
"}\n"
"\n"
"QScrollBar:horizontal {\n"
"    background: transparent;\n"
"    height: 8px;\n"
"}\n"
"\n"
"QScrollBar::handle {\n"
"    background: #3b3b3b;\n"
"    border-radius: 4px;\n"
"}\n"
"\n"
"QScrollBar::handle:pressed {\n"
"    background: #535353;\n"
"}\n"
"\n"
"QScrollBar::add-line,\n"
"QScrollBar::sub-line {\n"
"    background: none;\n"
"}\n"
"\n"
"QScrollBar::add-page,\n"
"QScrollBar::sub-page {\n"
"    background: none;\n"
"}\n"
"\n"
"QSlider::groove:horizontal {\n"
"    background-color: #3b3b3b;\n"
"    height: 4px;\n"
"	border-radius: 2px;\n"
"}\n"
"\n"
"QSlider::handle:horizontal {\n"
"    background-color: #535353;\n"
"    width: 8px;\n"
"    margin: -8px 0;\n"
"    border-radius: 4px;\n"
"}\n"
"\n"
"QSlider::handle:horizontal:pressed {\n"
"    background-color: #3b82f7;\n"
"}\n"
"\n"
"QSl"
                        "ider::tick:horizontal {\n"
"    background-color: #535353;\n"
"    width: 1px;\n"
"}\n"
"")
        self.centralwidget = QWidget(Nugget)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setEnabled(True)
        self.centralwidget.setContextMenuPolicy(Qt.NoContextMenu)
        self.centralwidget.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        self.centralwidget.setProperty(u"cls", u"central")
        self.verticalLayout_11 = QVBoxLayout(self.centralwidget)
        self.verticalLayout_11.setObjectName(u"verticalLayout_11")
        self.deviceBar = QWidget(self.centralwidget)
        self.deviceBar.setObjectName(u"deviceBar")
        self.horizontalLayout_4 = QHBoxLayout(self.deviceBar)
        self.horizontalLayout_4.setSpacing(1)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.horizontalWidget_2 = QWidget(self.deviceBar)
        self.horizontalWidget_2.setObjectName(u"horizontalWidget_2")
        self.horizontalWidget_2.setMinimumSize(QSize(300, 0))
        self.horizontalLayout_19 = QHBoxLayout(self.horizontalWidget_2)
        self.horizontalLayout_19.setSpacing(1)
        self.horizontalLayout_19.setObjectName(u"horizontalLayout_19")
        self.horizontalLayout_19.setContentsMargins(0, 0, 0, 0)
        self.horizontalWidget_3 = QWidget(self.horizontalWidget_2)
        self.horizontalWidget_3.setObjectName(u"horizontalWidget_3")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.horizontalWidget_3.sizePolicy().hasHeightForWidth())
        self.horizontalWidget_3.setSizePolicy(sizePolicy1)
        self.horizontalLayout_15 = QHBoxLayout(self.horizontalWidget_3)
        self.horizontalLayout_15.setSpacing(0)
        self.horizontalLayout_15.setObjectName(u"horizontalLayout_15")
        self.horizontalLayout_15.setContentsMargins(0, 0, 0, 0)
        self.phoneIconBtn = QToolButton(self.horizontalWidget_3)
        self.phoneIconBtn.setObjectName(u"phoneIconBtn")
        self.phoneIconBtn.setEnabled(False)
        self.phoneIconBtn.setMinimumSize(QSize(0, 38))
        self.phoneIconBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-right-radius: 0px;\n"
"	border-bottom-right-radius: 0px;\n"
"	min-height: 38px;\n"
"	margin-top: 1px;\n"
"}")
        icon = QIcon()
        icon.addFile(u":/icon/phone.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.phoneIconBtn.setIcon(icon)

        self.horizontalLayout_15.addWidget(self.phoneIconBtn)

        self.devicePicker = QComboBox(self.horizontalWidget_3)
        self.devicePicker.setObjectName(u"devicePicker")
        self.devicePicker.setStyleSheet(u"#devicePicker {\n"
"	background-color: #3b3b3b;\n"
"    border: none;\n"
"    color: #e8e8e8;\n"
"    font-size: 14px;\n"
"    min-height: 38px;\n"
"	min-width: 35px;\n"
"	padding-left: 8px;\n"
"}\n"
"\n"
"#devicePicker::drop-down {\n"
"    image: url(:/icon/caret-down-fill.svg);\n"
"	icon-size: 16px;\n"
"    subcontrol-position: right center;\n"
"	margin-right: 8px;\n"
"}\n"
"\n"
"#devicePicker QAbstractItemView {\n"
"	background-color: #3b3b3b;\n"
"    outline: none;\n"
"	margin-top: 1px;\n"
"}\n"
"\n"
"#devicePicker QAbstractItemView::item {\n"
"	background-color: #3b3b3b;\n"
"	color: #e8e8e8;\n"
"	min-height: 38px;\n"
"    padding-left: 8px;\n"
"}\n"
"\n"
"#devicePicker QAbstractItemView::item:hover {\n"
"    background-color: #535353;\n"
"    color: #ffffff;\n"
"}")
        self.devicePicker.setPlaceholderText(u"None")
        self.devicePicker.setDuplicatesEnabled(True)

        self.horizontalLayout_15.addWidget(self.devicePicker)


        self.horizontalLayout_19.addWidget(self.horizontalWidget_3)

        self.refreshBtn = QToolButton(self.horizontalWidget_2)
        self.refreshBtn.setObjectName(u"refreshBtn")
        self.refreshBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refreshBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"}")
        icon1 = QIcon()
        icon1.addFile(u":/icon/arrow-clockwise.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.refreshBtn.setIcon(icon1)
        self.refreshBtn.setCheckable(False)
        self.refreshBtn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.refreshBtn.setProperty(u"cls", u"btn")

        self.horizontalLayout_19.addWidget(self.refreshBtn)


        self.horizontalLayout_4.addWidget(self.horizontalWidget_2)

        self.titleBar = QToolButton(self.deviceBar)
        self.titleBar.setObjectName(u"titleBar")
        self.titleBar.setEnabled(False)
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.titleBar.sizePolicy().hasHeightForWidth())
        self.titleBar.setSizePolicy(sizePolicy2)
        self.titleBar.setStyleSheet(u"QToolButton {\n"
"	border-top-left-radius: 0px;\n"
"	border-bottom-left-radius: 0px;\n"
"}")
        self.titleBar.setText(u"GoldenNugget")

        self.horizontalLayout_4.addWidget(self.titleBar)


        self.verticalLayout_11.addWidget(self.deviceBar)

        self.body = QWidget(self.centralwidget)
        self.body.setObjectName(u"body")
        self.body.setMinimumSize(QSize(0, 20))
        self.horizontalLayout_18 = QHBoxLayout(self.body)
        self.horizontalLayout_18.setObjectName(u"horizontalLayout_18")
        self.horizontalLayout_18.setContentsMargins(0, 0, 0, 0)
        self.sidebar = QWidget(self.body)
        self.sidebar.setObjectName(u"sidebar")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.sidebar.sizePolicy().hasHeightForWidth())
        self.sidebar.setSizePolicy(sizePolicy3)
        self.sidebar.setMinimumSize(QSize(300, 0))
        self.sidebar.setStyleSheet(u"QFrame {\n"
"	color: #414141;\n"
"}")
        self.verticalLayout = QVBoxLayout(self.sidebar)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 9, 9, 0)
        self.homePageBtn = QToolButton(self.sidebar)
        self.homePageBtn.setObjectName(u"homePageBtn")
        sizePolicy2.setHeightForWidth(self.homePageBtn.sizePolicy().hasHeightForWidth())
        self.homePageBtn.setSizePolicy(sizePolicy2)
        self.homePageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon2 = QIcon()
        icon2.addFile(u":/icon/house.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.homePageBtn.setIcon(icon2)
        self.homePageBtn.setCheckable(True)
        self.homePageBtn.setChecked(True)
        self.homePageBtn.setAutoExclusive(True)
        self.homePageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.homePageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.homePageBtn)

        self.sidebarDiv1 = QFrame(self.sidebar)
        self.sidebarDiv1.setObjectName(u"sidebarDiv1")
        self.sidebarDiv1.setStyleSheet(u"QFrame {\n"
"	color: #414141;\n"
"}")
        self.sidebarDiv1.setFrameShadow(QFrame.Plain)
        self.sidebarDiv1.setFrameShape(QFrame.Shape.HLine)

        self.verticalLayout.addWidget(self.sidebarDiv1)

        self.posterboardPageBtn = QToolButton(self.sidebar)
        self.posterboardPageBtn.setObjectName(u"posterboardPageBtn")
        self.posterboardPageBtn.setEnabled(True)
        sizePolicy2.setHeightForWidth(self.posterboardPageBtn.sizePolicy().hasHeightForWidth())
        self.posterboardPageBtn.setSizePolicy(sizePolicy2)
        self.posterboardPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon3 = QIcon()
        icon3.addFile(u":/icon/wallpaper.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.posterboardPageBtn.setIcon(icon3)
        self.posterboardPageBtn.setCheckable(True)
        self.posterboardPageBtn.setAutoExclusive(True)
        self.posterboardPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.posterboardPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.posterboardPageBtn)

        self.gestaltPageBtn = QToolButton(self.sidebar)
        self.gestaltPageBtn.setObjectName(u"gestaltPageBtn")
        sizePolicy2.setHeightForWidth(self.gestaltPageBtn.sizePolicy().hasHeightForWidth())
        self.gestaltPageBtn.setSizePolicy(sizePolicy2)
        self.gestaltPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon4 = QIcon()
        icon4.addFile(u":/icon/iphone-island.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.gestaltPageBtn.setIcon(icon4)
        self.gestaltPageBtn.setIconSize(QSize(24, 28))
        self.gestaltPageBtn.setCheckable(True)
        self.gestaltPageBtn.setAutoExclusive(True)
        self.gestaltPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.gestaltPageBtn.setArrowType(Qt.NoArrow)
        self.gestaltPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.gestaltPageBtn)

        self.euEnablerPageBtn = QToolButton(self.sidebar)
        self.euEnablerPageBtn.setObjectName(u"euEnablerPageBtn")
        sizePolicy2.setHeightForWidth(self.euEnablerPageBtn.sizePolicy().hasHeightForWidth())
        self.euEnablerPageBtn.setSizePolicy(sizePolicy2)
        self.euEnablerPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon5 = QIcon()
        icon5.addFile(u":/icon/geo-alt.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.euEnablerPageBtn.setIcon(icon5)
        self.euEnablerPageBtn.setCheckable(True)
        self.euEnablerPageBtn.setAutoExclusive(True)
        self.euEnablerPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.euEnablerPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.euEnablerPageBtn)

        self.statusBarPageBtn = QToolButton(self.sidebar)
        self.statusBarPageBtn.setObjectName(u"statusBarPageBtn")
        sizePolicy2.setHeightForWidth(self.statusBarPageBtn.sizePolicy().hasHeightForWidth())
        self.statusBarPageBtn.setSizePolicy(sizePolicy2)
        self.statusBarPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon6 = QIcon()
        icon6.addFile(u":/icon/wifi.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.statusBarPageBtn.setIcon(icon6)
        self.statusBarPageBtn.setCheckable(True)
        self.statusBarPageBtn.setAutoExclusive(True)
        self.statusBarPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.statusBarPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.statusBarPageBtn)

        self.passcodePageBtn = QToolButton(self.sidebar)
        self.passcodePageBtn.setObjectName(u"passcodePageBtn")
        self.passcodePageBtn.setEnabled(True)
        sizePolicy2.setHeightForWidth(self.passcodePageBtn.sizePolicy().hasHeightForWidth())
        self.passcodePageBtn.setSizePolicy(sizePolicy2)
        self.passcodePageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon7 = QIcon()
        icon7.addFile(u":/icon/lock.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.passcodePageBtn.setIcon(icon7)
        self.passcodePageBtn.setCheckable(True)
        self.passcodePageBtn.setAutoExclusive(True)
        self.passcodePageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.passcodePageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.passcodePageBtn)

        self.springboardOptionsPageBtn = QToolButton(self.sidebar)
        self.springboardOptionsPageBtn.setObjectName(u"springboardOptionsPageBtn")
        sizePolicy2.setHeightForWidth(self.springboardOptionsPageBtn.sizePolicy().hasHeightForWidth())
        self.springboardOptionsPageBtn.setSizePolicy(sizePolicy2)
        self.springboardOptionsPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon8 = QIcon()
        icon8.addFile(u":/icon/app-indicator.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.springboardOptionsPageBtn.setIcon(icon8)
        self.springboardOptionsPageBtn.setCheckable(True)
        self.springboardOptionsPageBtn.setAutoExclusive(True)
        self.springboardOptionsPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.springboardOptionsPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.springboardOptionsPageBtn)

        self.internalOptionsPageBtn = QToolButton(self.sidebar)
        self.internalOptionsPageBtn.setObjectName(u"internalOptionsPageBtn")
        sizePolicy2.setHeightForWidth(self.internalOptionsPageBtn.sizePolicy().hasHeightForWidth())
        self.internalOptionsPageBtn.setSizePolicy(sizePolicy2)
        self.internalOptionsPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon9 = QIcon()
        icon9.addFile(u":/icon/hdd.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.internalOptionsPageBtn.setIcon(icon9)
        self.internalOptionsPageBtn.setCheckable(True)
        self.internalOptionsPageBtn.setAutoExclusive(True)
        self.internalOptionsPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.internalOptionsPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.internalOptionsPageBtn)

        self.liquidGlassPageBtn = QToolButton(self.sidebar)
        self.liquidGlassPageBtn.setObjectName(u"liquidGlassPageBtn")
        sizePolicy2.setHeightForWidth(self.liquidGlassPageBtn.sizePolicy().hasHeightForWidth())
        self.liquidGlassPageBtn.setSizePolicy(sizePolicy2)
        self.liquidGlassPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon10 = QIcon()
        icon10.addFile(u":/icon/liquid-glass.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.liquidGlassPageBtn.setIcon(icon10)
        self.liquidGlassPageBtn.setCheckable(True)
        self.liquidGlassPageBtn.setAutoExclusive(True)
        self.liquidGlassPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.liquidGlassPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.liquidGlassPageBtn)

        self.daemonsPageBtn = QToolButton(self.sidebar)
        self.daemonsPageBtn.setObjectName(u"daemonsPageBtn")
        sizePolicy2.setHeightForWidth(self.daemonsPageBtn.sizePolicy().hasHeightForWidth())
        self.daemonsPageBtn.setSizePolicy(sizePolicy2)
        self.daemonsPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon11 = QIcon()
        icon11.addFile(u":/icon/toggles.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.daemonsPageBtn.setIcon(icon11)
        self.daemonsPageBtn.setCheckable(True)
        self.daemonsPageBtn.setAutoExclusive(True)
        self.daemonsPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.daemonsPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.daemonsPageBtn)

        self.iconThemesPageBtn = QToolButton(self.sidebar)
        self.iconThemesPageBtn.setObjectName(u"iconThemesPageBtn")
        sizePolicy2.setHeightForWidth(self.iconThemesPageBtn.sizePolicy().hasHeightForWidth())
        self.iconThemesPageBtn.setSizePolicy(sizePolicy2)
        self.iconThemesPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon12 = QIcon()
        icon12.addFile(u":/icon/brush.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.iconThemesPageBtn.setIcon(icon12)
        self.iconThemesPageBtn.setCheckable(True)
        self.iconThemesPageBtn.setAutoExclusive(True)
        self.iconThemesPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.iconThemesPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.iconThemesPageBtn)

        self.sidebarDiv2 = QFrame(self.sidebar)
        self.sidebarDiv2.setObjectName(u"sidebarDiv2")
        self.sidebarDiv2.setStyleSheet(u"QFrame {\n"
"	color: #414141;\n"
"}")
        self.sidebarDiv2.setFrameShadow(QFrame.Plain)
        self.sidebarDiv2.setFrameShape(QFrame.Shape.HLine)

        self.verticalLayout.addWidget(self.sidebarDiv2)

        self.applyPageBtn = QToolButton(self.sidebar)
        self.applyPageBtn.setObjectName(u"applyPageBtn")
        sizePolicy2.setHeightForWidth(self.applyPageBtn.sizePolicy().hasHeightForWidth())
        self.applyPageBtn.setSizePolicy(sizePolicy2)
        self.applyPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon13 = QIcon()
        icon13.addFile(u":/icon/check-circle.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.applyPageBtn.setIcon(icon13)
        self.applyPageBtn.setCheckable(True)
        self.applyPageBtn.setAutoExclusive(True)
        self.applyPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.applyPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.applyPageBtn)

        self.settingsPageBtn = QToolButton(self.sidebar)
        self.settingsPageBtn.setObjectName(u"settingsPageBtn")
        sizePolicy2.setHeightForWidth(self.settingsPageBtn.sizePolicy().hasHeightForWidth())
        self.settingsPageBtn.setSizePolicy(sizePolicy2)
        self.settingsPageBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon14 = QIcon()
        icon14.addFile(u":/icon/gear.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.settingsPageBtn.setIcon(icon14)
        self.settingsPageBtn.setCheckable(True)
        self.settingsPageBtn.setAutoExclusive(True)
        self.settingsPageBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.settingsPageBtn.setProperty(u"cls", u"sidebarBtn")

        self.verticalLayout.addWidget(self.settingsPageBtn)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer)


        self.horizontalLayout_18.addWidget(self.sidebar)

        self.main = QWidget(self.body)
        self.main.setObjectName(u"main")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.main.sizePolicy().hasHeightForWidth())
        self.main.setSizePolicy(sizePolicy4)
        self._3 = QVBoxLayout(self.main)
        self._3.setSpacing(0)
        self._3.setObjectName(u"_3")
        self._3.setContentsMargins(9, 0, 0, 0)
        self.pages = QStackedWidget(self.main)
        self.pages.setObjectName(u"pages")
        self.homePage = QWidget()
        self.homePage.setObjectName(u"homePage")
        font = QFont()
        font.setFamilies([u".AppleSystemUIFont"])
        self.homePage.setFont(font)
        self.verticalLayout_2 = QVBoxLayout(self.homePage)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.horizontalWidget_13 = QWidget(self.homePage)
        self.horizontalWidget_13.setObjectName(u"horizontalWidget_13")
        self.horizontalLayout = QHBoxLayout(self.horizontalWidget_13)
        self.horizontalLayout.setSpacing(10)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 9, 0, 9)
        self.toolButton_9 = QToolButton(self.horizontalWidget_13)
        self.toolButton_9.setObjectName(u"toolButton_9")
        self.toolButton_9.setEnabled(False)
        self.toolButton_9.setStyleSheet(u"QToolButton {\n"
"	icon-size: 24px;\n"
"	background-color: transparent;\n"
"	padding-left: 0px;\n"
"	padding-right: 5px;\n"
"	border-radius: 0px;\n"
"}")
        self.toolButton_9.setIcon(icon)

        self.horizontalLayout.addWidget(self.toolButton_9)

        self.verticalWidget_15 = QWidget(self.horizontalWidget_13)
        self.verticalWidget_15.setObjectName(u"verticalWidget_15")
        self.verticalLayout_3 = QVBoxLayout(self.verticalWidget_15)
        self.verticalLayout_3.setSpacing(6)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.phoneNameLbl = QLabel(self.verticalWidget_15)
        self.phoneNameLbl.setObjectName(u"phoneNameLbl")
        font1 = QFont()
        font1.setBold(False)
        self.phoneNameLbl.setFont(font1)
        self.phoneNameLbl.setText(u"Phone")

        self.verticalLayout_3.addWidget(self.phoneNameLbl)

        self.phoneVersionLbl = QLabel(self.verticalWidget_15)
        self.phoneVersionLbl.setObjectName(u"phoneVersionLbl")
        self.phoneVersionLbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.phoneVersionLbl.setText(u"<a style=\"text-decoration:none; color: white\" href=\"#\">Version</a>")
        self.phoneVersionLbl.setTextFormat(Qt.RichText)
        self.phoneVersionLbl.setOpenExternalLinks(False)

        self.verticalLayout_3.addWidget(self.phoneVersionLbl)


        self.horizontalLayout.addWidget(self.verticalWidget_15)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_3)


        self.verticalLayout_2.addWidget(self.horizontalWidget_13)

        self.line_4 = QFrame(self.homePage)
        self.line_4.setObjectName(u"line_4")
        self.line_4.setStyleSheet(u"QFrame {\n"
"	color: #414141;\n"
"}")
        self.line_4.setFrameShadow(QFrame.Plain)
        self.line_4.setFrameShape(QFrame.Shape.HLine)

        self.verticalLayout_2.addWidget(self.line_4)

        self.horizontalWidget_14 = QWidget(self.homePage)
        self.horizontalWidget_14.setObjectName(u"horizontalWidget_14")
        self.horizontalLayout_27 = QHBoxLayout(self.horizontalWidget_14)
        self.horizontalLayout_27.setSpacing(50)
        self.horizontalLayout_27.setObjectName(u"horizontalLayout_27")
        self.horizontalLayout_27.setContentsMargins(0, 0, 0, 0)
        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_27.addItem(self.horizontalSpacer_2)

        self.bigNuggetBtn = QToolButton(self.horizontalWidget_14)
        self.bigNuggetBtn.setObjectName(u"bigNuggetBtn")
        self.bigNuggetBtn.setStyleSheet(u"QToolButton {\n"
"	background-color: transparent;\n"
"	padding: 0px;\n"
"}")
        icon15 = QIcon()
        icon15.addFile(u":/credits/big_nugget.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.bigNuggetBtn.setIcon(icon15)
        self.bigNuggetBtn.setIconSize(QSize(150, 200))

        self.horizontalLayout_27.addWidget(self.bigNuggetBtn)

        self.verticalWidget_16 = QWidget(self.horizontalWidget_14)
        self.verticalWidget_16.setObjectName(u"verticalWidget_16")
        self.verticalLayout_26 = QVBoxLayout(self.verticalWidget_16)
        self.verticalLayout_26.setObjectName(u"verticalLayout_26")
        self.verticalLayout_26.setContentsMargins(0, 0, 0, 0)
        self.verticalSpacer_11 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_26.addItem(self.verticalSpacer_11)

        self.label_2 = QLabel(self.verticalWidget_16)
        self.label_2.setObjectName(u"label_2")
        font2 = QFont()
        font2.setBold(True)
        self.label_2.setFont(font2)
        self.label_2.setStyleSheet(u"QLabel {\n"
"	font-size: 35px;\n"
"}")
        self.label_2.setText(u"GoldenNugget")
        self.label_2.setAlignment(Qt.AlignCenter)

        self.verticalLayout_26.addWidget(self.label_2)

        self.verticalSpacer_12 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_26.addItem(self.verticalSpacer_12)

        self.horizontalLayout_8 = QHBoxLayout()
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.horizontalLayout_8.setContentsMargins(-1, -1, 0, 0)
        self.discordBtn = QToolButton(self.verticalWidget_16)
        self.discordBtn.setObjectName(u"discordBtn")
        self.discordBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon16 = QIcon()
        icon16.addFile(u":/icon/discord.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.discordBtn.setIcon(icon16)
        self.discordBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_8.addWidget(self.discordBtn)

        self.starOnGithubBtn = QToolButton(self.verticalWidget_16)
        self.starOnGithubBtn.setObjectName(u"starOnGithubBtn")
        self.starOnGithubBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        icon17 = QIcon()
        icon17.addFile(u":/icon/star.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.starOnGithubBtn.setIcon(icon17)
        self.starOnGithubBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_8.addWidget(self.starOnGithubBtn)


        self.verticalLayout_26.addLayout(self.horizontalLayout_8)

        self.verticalSpacer_4 = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_26.addItem(self.verticalSpacer_4)


        self.horizontalLayout_27.addWidget(self.verticalWidget_16)

        self.horizontalSpacer_12 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_27.addItem(self.horizontalSpacer_12)


        self.verticalLayout_2.addWidget(self.horizontalWidget_14)

        self.verticalWidget_6 = QWidget(self.homePage)
        self.verticalWidget_6.setObjectName(u"verticalWidget_6")
        self.verticalLayout_25 = QVBoxLayout(self.verticalWidget_6)
        self.verticalLayout_25.setSpacing(15)
        self.verticalLayout_25.setObjectName(u"verticalLayout_25")
        self.verticalLayout_25.setContentsMargins(0, 30, 0, 30)
        self.horizontalWidget_15 = QWidget(self.verticalWidget_6)
        self.horizontalWidget_15.setObjectName(u"horizontalWidget_15")
        self.horizontalWidget_15.setEnabled(True)
        self.horizontalLayout_6 = QHBoxLayout(self.horizontalWidget_15)
        self.horizontalLayout_6.setSpacing(0)
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.horizontalLayout_6.setContentsMargins(0, 0, 0, 0)
        self.mainDevBtn = QToolButton(self.horizontalWidget_15)
        self.mainDevBtn.setObjectName(u"mainDevBtn")
        self.mainDevBtn.setEnabled(True)
        self.mainDevBtn.setMinimumSize(QSize(150, 35))
        self.mainDevBtn.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")
        icon18 = QIcon()
        icon18.addFile(u":/icon/github.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.mainDevBtn.setIcon(icon18)
        self.mainDevBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_6.addWidget(self.mainDevBtn)

        self.horizontalSpacer = QSpacerItem(10, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_6.addItem(self.horizontalSpacer)

        self.toolButton_14 = QToolButton(self.horizontalWidget_15)
        self.toolButton_14.setObjectName(u"toolButton_14")
        self.toolButton_14.setEnabled(False)
        sizePolicy2.setHeightForWidth(self.toolButton_14.sizePolicy().hasHeightForWidth())
        self.toolButton_14.setSizePolicy(sizePolicy2)
        self.toolButton_14.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")

        self.horizontalLayout_6.addWidget(self.toolButton_14)

        self.horizontalSpacer_5 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_6.addItem(self.horizontalSpacer_5)


        self.verticalLayout_25.addWidget(self.horizontalWidget_15)

        self.verticalSpacer_16 = QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.verticalLayout_25.addItem(self.verticalSpacer_16)

        self.horizontalWidget_27 = QWidget(self.verticalWidget_6)
        self.horizontalWidget_27.setObjectName(u"horizontalWidget_27")
        self.horizontalLayout_86 = QHBoxLayout(self.horizontalWidget_27)
        self.horizontalLayout_86.setSpacing(0)
        self.horizontalLayout_86.setObjectName(u"horizontalLayout_86")
        self.horizontalLayout_86.setContentsMargins(0, 0, 0, 0)
        self.toolButton_16 = QToolButton(self.horizontalWidget_27)
        self.toolButton_16.setObjectName(u"toolButton_16")
        self.toolButton_16.setEnabled(False)
        self.toolButton_16.setMinimumSize(QSize(145, 35))
        self.toolButton_16.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")

        self.horizontalLayout_86.addWidget(self.toolButton_16)

        self.leminBtn = QToolButton(self.horizontalWidget_27)
        self.leminBtn.setObjectName(u"leminBtn")
        self.leminBtn.setEnabled(True)
        self.leminBtn.setMinimumSize(QSize(150, 35))
        self.leminBtn.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")
        icon19 = QIcon()
        icon19.addFile(u":/credits/LeminLimez.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.leminBtn.setIcon(icon19)
        self.leminBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_86.addWidget(self.leminBtn)

        self.leminTwitterBtn = QToolButton(self.horizontalWidget_27)
        self.leminTwitterBtn.setObjectName(u"leminTwitterBtn")
        self.leminTwitterBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.leminTwitterBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-right-radius: 0px;\n"
"	border-bottom-right-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")
        icon20 = QIcon()
        icon20.addFile(u":/icon/twitter.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.leminTwitterBtn.setIcon(icon20)

        self.horizontalLayout_86.addWidget(self.leminTwitterBtn)

        self.leminGithubBtn = QToolButton(self.horizontalWidget_27)
        self.leminGithubBtn.setObjectName(u"leminGithubBtn")
        self.leminGithubBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.leminGithubBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")
        self.leminGithubBtn.setIcon(icon18)

        self.horizontalLayout_86.addWidget(self.leminGithubBtn)

        self.leminKoFiBtn = QToolButton(self.horizontalWidget_27)
        self.leminKoFiBtn.setObjectName(u"leminKoFiBtn")
        self.leminKoFiBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.leminKoFiBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-left-radius: 0px;\n"
"	border-bottom-left-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")
        icon21 = QIcon()
        icon21.addFile(u":/icon/currency-dollar.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        self.leminKoFiBtn.setIcon(icon21)

        self.horizontalLayout_86.addWidget(self.leminKoFiBtn)

        self.horizontalSpacer_41 = QSpacerItem(10, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_86.addItem(self.horizontalSpacer_41)

        self.horizontalSpacer_42 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_86.addItem(self.horizontalSpacer_42)


        self.verticalLayout_25.addWidget(self.horizontalWidget_27)

        self.horizontalWidget_16 = QWidget(self.verticalWidget_6)
        self.horizontalWidget_16.setObjectName(u"horizontalWidget_16")
        self.horizontalLayout_2 = QHBoxLayout(self.horizontalWidget_16)
        self.horizontalLayout_2.setSpacing(0)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.horizontalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.helpFromBtn = QToolButton(self.horizontalWidget_16)
        self.helpFromBtn.setObjectName(u"helpFromBtn")
        self.helpFromBtn.setEnabled(True)
        self.helpFromBtn.setMinimumSize(QSize(140, 35))
        self.helpFromBtn.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")
        self.helpFromBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_2.addWidget(self.helpFromBtn)

        self.posterRestoreBtn = QToolButton(self.horizontalWidget_16)
        self.posterRestoreBtn.setObjectName(u"posterRestoreBtn")
        sizePolicy2.setHeightForWidth(self.posterRestoreBtn.sizePolicy().hasHeightForWidth())
        self.posterRestoreBtn.setSizePolicy(sizePolicy2)
        self.posterRestoreBtn.setMinimumSize(QSize(0, 37))
        self.posterRestoreBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.posterRestoreBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-right-radius: 0px;\n"
"	border-bottom-right-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_2.addWidget(self.posterRestoreBtn)

        self.snoolieBtn = QToolButton(self.horizontalWidget_16)
        self.snoolieBtn.setObjectName(u"snoolieBtn")
        self.snoolieBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.snoolieBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_2.addWidget(self.snoolieBtn)

        self.disfordottieBtn = QToolButton(self.horizontalWidget_16)
        self.disfordottieBtn.setObjectName(u"disfordottieBtn")
        sizePolicy2.setHeightForWidth(self.disfordottieBtn.sizePolicy().hasHeightForWidth())
        self.disfordottieBtn.setSizePolicy(sizePolicy2)
        self.disfordottieBtn.setMinimumSize(QSize(0, 37))
        self.disfordottieBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.disfordottieBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_2.addWidget(self.disfordottieBtn)

        self.mikasaBtn = QToolButton(self.horizontalWidget_16)
        self.mikasaBtn.setObjectName(u"mikasaBtn")
        sizePolicy2.setHeightForWidth(self.mikasaBtn.sizePolicy().hasHeightForWidth())
        self.mikasaBtn.setSizePolicy(sizePolicy2)
        self.mikasaBtn.setMinimumSize(QSize(0, 37))
        self.mikasaBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mikasaBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-left-radius: 0px;\n"
"	border-bottom-left-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_2.addWidget(self.mikasaBtn)

        self.wind0ws11AeroBtn = QToolButton(self.horizontalWidget_16)
        self.wind0ws11AeroBtn.setObjectName(u"wind0ws11AeroBtn")
        sizePolicy2.setHeightForWidth(self.wind0ws11AeroBtn.sizePolicy().hasHeightForWidth())
        self.wind0ws11AeroBtn.setSizePolicy(sizePolicy2)
        self.wind0ws11AeroBtn.setMinimumSize(QSize(0, 37))
        self.wind0ws11AeroBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.wind0ws11AeroBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-left-radius: 0px;\n"
"	border-bottom-left-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")
        self.wind0ws11AeroBtn.setIcon(icon18)
        self.wind0ws11AeroBtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self.horizontalLayout_2.addWidget(self.wind0ws11AeroBtn)


        self.verticalLayout_25.addWidget(self.horizontalWidget_16)

        self.horizontalWidget = QWidget(self.verticalWidget_6)
        self.horizontalWidget.setObjectName(u"horizontalWidget")
        self.horizontalLayout_24 = QHBoxLayout(self.horizontalWidget)
        self.horizontalLayout_24.setSpacing(0)
        self.horizontalLayout_24.setObjectName(u"horizontalLayout_24")
        self.horizontalLayout_24.setContentsMargins(0, 0, 0, 0)
        self.toolButton_15 = QToolButton(self.horizontalWidget)
        self.toolButton_15.setObjectName(u"toolButton_15")
        self.toolButton_15.setEnabled(False)
        self.toolButton_15.setMinimumSize(QSize(145, 35))
        self.toolButton_15.setStyleSheet(u"QToolButton {\n"
"	background: none;\n"
"}")

        self.horizontalLayout_24.addWidget(self.toolButton_15)

        self.translatorsBtn = QToolButton(self.horizontalWidget)
        self.translatorsBtn.setObjectName(u"translatorsBtn")
        self.translatorsBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.translatorsBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-right-radius: 0px;\n"
"	border-bottom-right-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_24.addWidget(self.translatorsBtn)

        self.libiBtn = QToolButton(self.horizontalWidget)
        self.libiBtn.setObjectName(u"libiBtn")
        sizePolicy2.setHeightForWidth(self.libiBtn.sizePolicy().hasHeightForWidth())
        self.libiBtn.setSizePolicy(sizePolicy2)
        self.libiBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.libiBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_24.addWidget(self.libiBtn)

        self.duyBtn = QToolButton(self.horizontalWidget)
        self.duyBtn.setObjectName(u"duyBtn")
        self.duyBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.duyBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_24.addWidget(self.duyBtn)

        self.jjtechBtn = QToolButton(self.horizontalWidget)
        self.jjtechBtn.setObjectName(u"jjtechBtn")
        sizePolicy2.setHeightForWidth(self.jjtechBtn.sizePolicy().hasHeightForWidth())
        self.jjtechBtn.setSizePolicy(sizePolicy2)
        self.jjtechBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.jjtechBtn.setStyleSheet(u"QToolButton {\n"
"	border-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_24.addWidget(self.jjtechBtn)

        self.qtBtn = QToolButton(self.horizontalWidget)
        self.qtBtn.setObjectName(u"qtBtn")
        sizePolicy2.setHeightForWidth(self.qtBtn.sizePolicy().hasHeightForWidth())
        self.qtBtn.setSizePolicy(sizePolicy2)
        self.qtBtn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.qtBtn.setStyleSheet(u"QToolButton {\n"
"	border-top-left-radius: 0px;\n"
"	border-bottom-left-radius: 0px;\n"
"	background: none;\n"
"	border: 1px solid #3b3b3b;\n"
"	border-left: none;\n"
"}\n"
"\n"
"QToolButton:pressed {\n"
"    background-color: #535353;\n"
"    color: #FFFFFF;\n"
"}")

        self.horizontalLayout_24.addWidget(self.qtBtn)


        self.verticalLayout_25.addWidget(self.horizontalWidget)


        self.verticalLayout_2.addWidget(self.verticalWidget_6)

        self.appVersionLbl = QLabel(self.homePage)
        self.appVersionLbl.setObjectName(u"appVersionLbl")
        self.appVersionLbl.setAlignment(Qt.AlignRight|Qt.AlignTrailing|Qt.AlignVCenter)

        self.verticalLayout_2.addWidget(self.appVersionLbl)

        self.pages.addWidget(self.homePage)
        self.daemonsPage = QWidget()
        self.daemonsPage.setObjectName(u"daemonsPage")
        self.verticalLayout_14 = QVBoxLayout(self.daemonsPage)
        self.verticalLayout_14.setObjectName(u"verticalLayout_14")
        self.verticalLayout_14.setContentsMargins(0, 0, 0, 0)
        self.daemonsScrollArea = QScrollArea(self.daemonsPage)
        self.daemonsScrollArea.setObjectName(u"daemonsScrollArea")
        self.daemonsScrollArea.setWidgetResizable(True)
        self.daemonsScrollContent = QWidget()
        self.daemonsScrollContent.setObjectName(u"daemonsScrollContent")
        self.daemonsScrollContent.setGeometry(QRect(0, 0, 100, 100))
        self.daemonsScrollLayout = QVBoxLayout(self.daemonsScrollContent)
        self.daemonsScrollLayout.setObjectName(u"daemonsScrollLayout")
        self.daemonsScrollLayout.setContentsMargins(0, 0, 0, 0)
        self.daemonsScrollArea.setWidget(self.daemonsScrollContent)

        self.verticalLayout_14.addWidget(self.daemonsScrollArea)

        self.pages.addWidget(self.daemonsPage)

        self._3.addWidget(self.pages)


        self.horizontalLayout_18.addWidget(self.main)


        self.verticalLayout_11.addWidget(self.body)

        Nugget.setCentralWidget(self.centralwidget)

        self.retranslateUi(Nugget)

        self.devicePicker.setCurrentIndex(-1)
        self.pages.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(Nugget)
    # setupUi

    def retranslateUi(self, Nugget):
        self.homePageBtn.setText(QCoreApplication.translate("Nugget", u"    Home", None))
        self.posterboardPageBtn.setText(QCoreApplication.translate("Nugget", u"    Posterboard", None))
        self.gestaltPageBtn.setText(QCoreApplication.translate("Nugget", u"     Mobile Gestalt", None))
        self.euEnablerPageBtn.setText(QCoreApplication.translate("Nugget", u"    Eligibility", None))
        self.statusBarPageBtn.setText(QCoreApplication.translate("Nugget", u"    Status Bar", None))
        self.passcodePageBtn.setText(QCoreApplication.translate("Nugget", u"    Passcode Themes", None))
        self.springboardOptionsPageBtn.setText(QCoreApplication.translate("Nugget", u"    SpringBoard", None))
        self.internalOptionsPageBtn.setText(QCoreApplication.translate("Nugget", u"    Internal", None))
        self.liquidGlassPageBtn.setText(QCoreApplication.translate("Nugget", u"    Liquid Glass", None))
        self.daemonsPageBtn.setText(QCoreApplication.translate("Nugget", u"    Daemons", None))
        self.iconThemesPageBtn.setText(QCoreApplication.translate("Nugget", u"    Icon Themes", None))
        self.applyPageBtn.setText(QCoreApplication.translate("Nugget", u"    Apply", None))
        self.settingsPageBtn.setText(QCoreApplication.translate("Nugget", u"    Settings", None))
        self.bigNuggetBtn.setText(QCoreApplication.translate("Nugget", u"...", None))
        self.discordBtn.setText(QCoreApplication.translate("Nugget", u"  Join the Discord", None))
        self.starOnGithubBtn.setText(QCoreApplication.translate("Nugget", u" Star on GitHub", None))
        self.mainDevBtn.setText(QCoreApplication.translate("Nugget", u"  awesomenull", None))
        self.toolButton_14.setText(QCoreApplication.translate("Nugget", u"Main Developer", None))
        self.toolButton_16.setText(QCoreApplication.translate("Nugget", u"Nugget Creator", None))
        self.leminBtn.setText(QCoreApplication.translate("Nugget", u"  LeminLimez", None))
        self.leminTwitterBtn.setText(QCoreApplication.translate("Nugget", u"...", None))
        self.leminGithubBtn.setText(QCoreApplication.translate("Nugget", u"...", None))
        self.leminKoFiBtn.setText(QCoreApplication.translate("Nugget", u"...", None))
        self.helpFromBtn.setText(QCoreApplication.translate("Nugget", u"With Help From", None))
#if QT_CONFIG(tooltip)
        self.posterRestoreBtn.setToolTip(QCoreApplication.translate("Nugget", u"dootskyre, dulark, forcequitOS, pengubow, Middo, and SerStars", None))
#endif // QT_CONFIG(tooltip)
        self.posterRestoreBtn.setText(QCoreApplication.translate("Nugget", u"PosterRestore Team\n"
"Posterboard", None))
        self.snoolieBtn.setText(QCoreApplication.translate("Nugget", u"Snoolie\n"
".aar Handling", None))
        self.disfordottieBtn.setText(QCoreApplication.translate("Nugget", u"disfordottie\n"
"Feature Flags", None))
        self.mikasaBtn.setText(QCoreApplication.translate("Nugget", u"Mikasa\n"
"Quiet Daemon", None))
#if QT_CONFIG(tooltip)
        self.wind0ws11AeroBtn.setToolTip(QCoreApplication.translate("Nugget", u"iOS 27 Support", None))
#endif // QT_CONFIG(tooltip)
        self.wind0ws11AeroBtn.setText(QCoreApplication.translate("Nugget", u"Wind0ws11Aero\n"
"iOS 27", None))
        self.toolButton_15.setText(QCoreApplication.translate("Nugget", u"Additional Thanks", None))
        self.translatorsBtn.setText(QCoreApplication.translate("Nugget", u"Translators", None))
        self.libiBtn.setText(QCoreApplication.translate("Nugget", u"pymobiledevice3", None))
        self.duyBtn.setText(QCoreApplication.translate("Nugget", u"Duy Tran\n"
"bl_sbx", None))
        self.jjtechBtn.setText(QCoreApplication.translate("Nugget", u"JJTech\n"
"Sparserestore", None))
        self.qtBtn.setText(QCoreApplication.translate("Nugget", u"Qt Creator", None))
        self.appVersionLbl.setText(QCoreApplication.translate("Nugget", u"GoldenNugget GUI - Version %VERSION %BETATAG", None))
        pass
    # retranslateUi

