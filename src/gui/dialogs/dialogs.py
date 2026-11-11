from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QToolButton, QSizePolicy, QScrollArea, QFrame
from PySide6.QtGui import QFont, QIcon, QPixmap, QDesktopServices
from PySide6.QtCore import QCoreApplication, QSize, Qt, QUrl

from webbrowser import open_new_tab

from src.controllers.web_request_handler import Nugget_Repo, get_latest_version

class PBHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        QBtn = (
            QDialogButtonBox.Ok
        )
        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.setWindowTitle(self.tr("PosterBoard Info"))

        layout = QVBoxLayout()
        message = QLabel(self.tr("Descriptors will be under the Collections section when adding a new wallpaper.\n\nIf the wallpapers don't appear in the menu, you either have to wait a bit for them to load,\nor you've reached the maximum amount of wallpapers (15) and have to wipe them."))
        layout.addWidget(message)

        imgBox = QWidget()
        imgBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        imgBox.setStyleSheet("QWidget { background: none; padding: 0px; border: none; }")
        hlayout = QHBoxLayout()
        tut1 = QToolButton()
        tut1.setIconSize(QSize(138, 300))
        tut1.setStyleSheet("QToolButton { background: none; padding: 0px; border: none; }")
        tut1.setIcon(QIcon(QPixmap(":/gui/pb_tutorial1.png")))
        hlayout.addWidget(tut1)
        tut2 = QToolButton()
        tut2.setIconSize(QSize(138, 300))
        tut2.setStyleSheet("QToolButton { background: none; padding: 0px; border: none; }")
        tut2.setIcon(QIcon(QPixmap(":/gui/pb_tutorial2.png")))
        hlayout.addWidget(tut2)
        imgBox.setLayout(hlayout)

        layout.addWidget(imgBox)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)


# App version
from src.gui.version import App_Version, App_Build
from src.gui.theme import ColorThemeManager, FONT_FAMILY, t


class AboutProgramDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("About GoldenNugget"))
        self.setMinimumSize(500, 600)
        self.setModal(True)
        self._theme_styles = []
        self._retheme()
        QBtn = QDialogButtonBox.Ok
        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # App icon and name
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        icon_label = QLabel()
        icon_label.setPixmap(QPixmap(":/credits/big_nugget.png").scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header_layout.addWidget(icon_label)
        
        name_layout = QVBoxLayout()
        name_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        app_name = QLabel("GoldenNugget")
        app_name_font = QFont()
        app_name_font.setFamily(FONT_FAMILY)
        app_name_font.setPointSize(28)
        app_name_font.setBold(True)
        app_name.setFont(app_name_font)
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_layout.addWidget(app_name)
        
        version_str = f"v{App_Version}"
        if App_Build > 0:
            version_str += f" (beta {App_Build})"
        version_label = QLabel(version_str)
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style(version_label, "about_version")
        name_layout.addWidget(version_label)
        
        header_layout.addLayout(name_layout)
        layout.addLayout(header_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        self._style(separator, "about_separator")
        layout.addWidget(separator)
        
        # Description
        desc = QLabel(self.tr("Customize your iOS device with animated wallpapers, system tweaks, and more. Built for iOS 26.2+."))
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style(desc, "about_description")
        layout.addWidget(desc)
        
        # Credits section
        credits_title = QLabel(self.tr("Credits"))
        self._style(credits_title, "about_credit_heading")
        layout.addWidget(credits_title)
        
        # Scrollable credits
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._style(scroll, 'about_credits_scroll')

        credits_widget = QWidget()
        credits_layout = QVBoxLayout(credits_widget)
        credits_layout.setSpacing(8)
        credits_layout.setContentsMargins(8, 8, 8, 8)
        
        # Credits data - from original home page
        from src.gui.credits import CREDITS
        credits = CREDITS
        
        for title, name, url in credits:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            
            title_label = QLabel(f"{QCoreApplication.translate('SupportPanel', title)}:")
            self._style(title_label, "about_credit_role")
            item_layout.addWidget(title_label)
            
            name_btn = QToolButton()
            name_btn.setText(QCoreApplication.translate("SupportPanel", name))
            name_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style(name_btn, 'about_credit_name')
            name_btn.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            item_layout.addWidget(name_btn)
            item_layout.addStretch()
            
            credits_layout.addWidget(item)
        
        scroll.setWidget(credits_widget)
        layout.addWidget(scroll, 1)
        
        # Links
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        links_layout.setSpacing(24)
        
        github_btn = QToolButton()
        github_btn.setText("GitHub")
        github_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style(github_btn, "about_footer_link")
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/GoldenNugget-Team/GoldenNugget")))
        links_layout.addWidget(github_btn)
        
        website_btn = QToolButton()
        website_btn.setText(self.tr("Wallpapers"))
        website_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        website_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style(website_btn, "about_footer_link")
        website_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://cowabun.ga/wallpapers")))
        links_layout.addWidget(website_btn)
        
        discord_btn = QToolButton()
        discord_btn.setText("Discord")
        discord_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        discord_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style(discord_btn, "about_footer_link")
        discord_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/Rm6r4zeE3y")))
        links_layout.addWidget(discord_btn)
        
        layout.addLayout(links_layout)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _style(self, widget, key):
        self._theme_styles.append((widget, key))
        widget.setStyleSheet(t(key))

    def _retheme(self):
        self.setStyleSheet(t('about_dialog'))
        for widget, key in self._theme_styles:
            widget.setStyleSheet(t(key))


from src.gui.dialogs.update_dialog import UpdateDialog as UpdateAppDialog
