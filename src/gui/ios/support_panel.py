from PySide6.QtCore import QCoreApplication, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from awesomeui.liquid.controls import LiquidCard
from src.gui.credits import CREDIT_AVATAR_SOURCES, CREDIT_AVATARS, CREDITS
from src.gui.ios.contributor_media import TRANSLATIONS_REPOSITORY, ContributorMedia
from src.gui.theme import ColorThemeManager, t, theme_pixmap


def _tr(text):
    return QCoreApplication.translate("SupportPanel", text)


class ContributorCredit(QWidget):
    def __init__(self):
        super().__init__()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _retheme(self):
        colors = ColorThemeManager.instance().colors
        self.setStyleSheet(t('support_panel') + f"""
            QPushButton#supportCreditLink {{ background:transparent; border:none;
                color:{colors.text_primary}; font-size:13px; text-align:left; padding:0; }}
            QPushButton#supportCreditLink:hover {{ color:{colors.accent}; }}
            QToolButton#supportAvatar {{ color:{colors.text_secondary}; font-size:18px; }}
        """)


class _ProfileCard(LiquidCard):
    """A developer tile drawn with the same liquid-glass treatment as the home tiles.

    The glass (translucent fill, sheen, rim and pointer reflection) comes from
    ``LiquidCard.paintEvent``; the tile is never painted by a stylesheet, so the
    ``supportProfile`` rule only keeps the surface transparent.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('supportProfile')
        self.setProperty('liquidHomeCard', True)
        self.setMouseTracking(True)

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._scroll_active():
            self.shift(1.0)


class SupportPanel(LiquidCard):
    def __init__(self, parent=None, links=None):
        super().__init__(parent)
        self.setProperty('silentHoverAudio',True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)
        self.title = QLabel(_tr('Developers'))
        self.title.setObjectName('supportTitle')
        layout.addWidget(self.title)
        if links is None:
            links = CommunityLinks(self)
            layout.addWidget(links)
        self.discord = links.discord
        self.github = links.github
        team = QHBoxLayout()
        team.setSpacing(12)
        portraits = (
            ":/credits/awesomenull.png",
            ":/credits/windows11aero.png",
            ":/credits/kik4311.png",
            ":/credits/LeminLimez.png",
        )
        for (role, name, url), portrait in zip(CREDITS[:len(portraits)], portraits):
            team.addWidget(self._profile(role, name, url, portrait), 1)
        layout.addLayout(team)
        credits = LiquidCard(self)
        credits_layout = QVBoxLayout(credits)
        credits_layout.setContentsMargins(20, 18, 20, 18)
        credits_layout.setSpacing(16)
        heading = QLabel(_tr('Contributors & Acknowledgments'), credits)
        heading.setStyleSheet(t('home_tile_title'))
        credits_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(16)
        acknowledgements = [credit for credit in CREDITS[len(portraits):]
                            if credit[0] not in ('Translations', 'Legacy Translations')]
        credit_rows = (len(acknowledgements) + 1) // 2
        for index, (role, name, url) in enumerate(acknowledgements):
            grid.addWidget(self._credit(role, name, url), index % credit_rows, index // credit_rows)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        credits_layout.addLayout(grid)
        self._translation_group = ContributorCredit()
        translation_layout = QVBoxLayout(self._translation_group)
        translation_layout.setContentsMargins(0, 10, 0, 0)
        translation_layout.setSpacing(8)
        heading = QPushButton(_tr('Translations'))
        heading.setObjectName('supportCreditLink')
        heading.setCursor(Qt.PointingHandCursor)
        heading.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            f'https://github.com/{TRANSLATIONS_REPOSITORY}/graphs/contributors')))
        translation_layout.addWidget(heading, 0, Qt.AlignLeft)
        self._translation_status = QLabel(_tr('Loading translation contributors…'))
        self._translation_status.setObjectName('supportMuted')
        self._translation_status.setWordWrap(True)
        translation_layout.addWidget(self._translation_status)
        self._translation_grid = QGridLayout()
        self._translation_grid.setSpacing(8)
        self._translation_grid.setAlignment(Qt.AlignLeft)
        translation_layout.addLayout(self._translation_grid)
        credits_layout.addWidget(self._translation_group)
        self._translations_started = False
        layout.addWidget(credits)
        self._retheme()
        self._load_translation_contributors(True)

    def _profile(self, role, name, url, portrait):
        tile = _ProfileCard()
        tile.setMinimumHeight(188)
        column = QVBoxLayout(tile)
        column.setContentsMargins(16, 18, 16, 16)
        column.setSpacing(9)
        avatar = QToolButton()
        avatar.setFixedSize(92, 92)
        avatar.setIconSize(QSize(88, 88))
        avatar.setIcon(QIcon(self._portrait(portrait)))
        avatar.setObjectName('supportAvatar')
        avatar.setToolTip(f'{name} · {role}')
        avatar.setAccessibleName(f'{name} · {role}')
        avatar.setCursor(Qt.PointingHandCursor)
        avatar.clicked.connect(lambda _, link=url: QDesktopServices.openUrl(QUrl(link)))
        ContributorMedia.instance().avatar(avatar, url, self._set_remote_portrait)
        column.addWidget(avatar, 0, Qt.AlignHCenter)
        name_button = QPushButton(name)
        name_button.setObjectName('supportName')
        name_button.setCursor(Qt.PointingHandCursor)
        name_button.clicked.connect(lambda _, link=url: QDesktopServices.openUrl(QUrl(link)))
        column.addWidget(name_button)
        caption = QLabel(_tr(role))
        caption.setObjectName('supportMuted')
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignCenter)
        column.addWidget(caption)
        column.addStretch()
        return tile

    @staticmethod
    def _credit(role, name, url):
        entry = ContributorCredit()
        row = QHBoxLayout(entry)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        if role == 'PosterBoard Help':
            from pathlib import Path
            icon = QLabel(entry)
            icon.setFixedSize(52, 52)
            icon.setStyleSheet('background:#f4a4ce; border:2px solid #ed78b5; border-radius:26px;')
            image = QPixmap(str(Path(__file__).resolve().parents[2] / 'qt' / 'credits' / 'posterboard-help.png'))
            icon.setPixmap(image.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            icon.setAlignment(Qt.AlignCenter)
            icon.setToolTip(_tr(role))
            row.addWidget(icon)
        else:
            row.addWidget(SupportPanel._avatar_button(name, url, entry, role))
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        row.addLayout(column, 1)
        label = QLabel(_tr(role))
        label.setObjectName('supportMuted')
        column.addWidget(label)
        link = QPushButton(name)
        link.setObjectName('supportCreditLink')
        link.setCursor(Qt.PointingHandCursor)
        link.setToolTip(name)
        link.clicked.connect(lambda _, target=url: QDesktopServices.openUrl(QUrl(target)))
        column.addWidget(link, 0, Qt.AlignLeft)
        return entry


    @staticmethod
    def _avatar_button(name, url, parent, role='Translations'):
        portrait = CREDIT_AVATARS.get(url)
        avatar = QToolButton(parent)
        avatar.setObjectName('supportAvatar')
        avatar.setFixedSize(52, 52)
        avatar.setIconSize(QSize(48, 48))
        if portrait:
            avatar.setIcon(QIcon(SupportPanel._portrait(portrait)))
        elif url.startswith(('https://discord.gg/', 'https://discord.com/invite/')):
            avatar.setIcon(QIcon(theme_pixmap(':/icon/discord.svg', '#5865F2', 48, avatar.devicePixelRatioF())))
        else:
            avatar.setText(name[:1].upper())
        ContributorMedia.instance().avatar(
            avatar, CREDIT_AVATAR_SOURCES.get(url, url), SupportPanel._set_remote_portrait)
        avatar.setAccessibleName(f'{name} · {role}')
        avatar.setToolTip(name)
        avatar.setCursor(Qt.PointingHandCursor)
        avatar.clicked.connect(lambda _, target=url: QDesktopServices.openUrl(QUrl(target)))
        return avatar

    def _load_translation_contributors(self, expanded):
        if not expanded or self._translations_started:
            return
        self._translations_started = True
        self._translation_status.setText(_tr('Loading translation contributors…'))
        import weakref

        from shiboken6 import isValid
        target = weakref.ref(self)

        def ready(people, complete):
            panel = target()
            if panel is None or not isValid(panel):
                return
            if not people:
                panel._translation_status.setText(_tr('Unable to load translation contributors. Open the linked repository to see everyone.'))
                panel._translations_started = False
                return
            panel._translation_status.setVisible(not complete)
            panel._translation_status.setText(_tr('Some contributors could not be loaded.'))
            for index, login in enumerate(people):
                panel._translation_grid.addWidget(
                    panel._avatar_button(login, f'https://github.com/{login}', panel._translation_group),
                    index // 12, index % 12)
        ContributorMedia.instance().contributors(TRANSLATIONS_REPOSITORY, ready)

    @staticmethod
    def _set_remote_portrait(button, data):
        image = QPixmap()
        if image.loadFromData(data):
            button.setText('')
            button.setIcon(QIcon(SupportPanel._portrait(image)))

    @staticmethod
    def _portrait(resource):
        source = QPixmap(resource).scaled(
            176, 176, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        image = QPixmap(176, 176)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        mask = QPainterPath()
        mask.addEllipse(QRectF(0, 0, 176, 176))
        painter.setClipPath(mask)
        painter.drawPixmap((176 - source.width()) // 2, (176 - source.height()) // 2, source)
        painter.end()
        image.setDevicePixelRatio(2)
        return image

    def _retheme(self):
        super()._retheme()
        self.setStyleSheet('QFrame#liquidPanel{background:transparent;border:none;}' + t("support_panel"))
        if hasattr(self, '_translation_status'):
            colors = ColorThemeManager.instance().colors
            self._translation_status.setStyleSheet(f'color:{colors.text_secondary}; font-size:13px; background:transparent;')


class CommunityLinks(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(340)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        self._counts = []
        for title in ('Tweaks', 'Daemons'):
            card = QWidget(self)
            card.setObjectName('selectionCount')
            card.setFixedHeight(80)
            column = QVBoxLayout(card)
            column.setContentsMargins(12, 10, 12, 10)
            column.setSpacing(4)
            value = QLabel('0', card)
            value.setAlignment(Qt.AlignCenter)
            caption = QLabel(_tr(title + ' enabled'), card)
            caption.setAlignment(Qt.AlignCenter)
            column.addWidget(value)
            column.addWidget(caption)
            layout.addWidget(card, 0, len(self._counts))
            self._counts.append((title.lower(), card, value, caption))
        self._links = []
        for title, icon, url in (
            ('Golden Nugget Support', ':/icon/discord.svg', 'https://discord.gg/F7ssrHjdgK'),
            ('Source Code', ':/icon/github.svg', 'https://github.com/GoldenNugget-Team/GoldenNugget'),
        ):
            button = QPushButton(self)
            button.setObjectName('communityLink')
            button.setFixedHeight(80)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(_tr(title))
            button.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            column = QVBoxLayout(button)
            column.setContentsMargins(10, 9, 10, 9)
            column.setSpacing(3)
            badge = QLabel(button)
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignCenter)
            top = QGridLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setColumnMinimumWidth(0, 16)
            top.setColumnMinimumWidth(2, 16)
            top.setColumnStretch(1, 1)
            top.addWidget(badge, 0, 1, Qt.AlignCenter)
            arrow = QLabel('↗', button)
            arrow.setFixedSize(16, 20)
            arrow.setAlignment(Qt.AlignCenter)
            top.addWidget(arrow, 0, 2, Qt.AlignTop | Qt.AlignRight)
            column.addLayout(top)
            heading = QLabel(_tr(title), button)
            heading.setAlignment(Qt.AlignCenter)
            heading.setWordWrap(True)
            heading.setFixedHeight(30)
            column.addWidget(heading)
            for label in (badge, heading, arrow):
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(button, 1, len(self._links))
            self._links.append((button, icon, badge, heading, arrow))
        self.discord = self._links[0][0]
        self.github = self._links[1][0]
        self._retheme()

    def set_counts(self, counts, totals):
        for key, card, value, caption in self._counts:
            value.setText(str(counts.get(key, 0)))
            card.setToolTip(_tr('{0} available').format(totals.get(key, 0)))

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        for key, card, value, caption in self._counts:
            card.setStyleSheet(f'QWidget#selectionCount {{ background:{c.bg_secondary}; border:1px solid {c.border}; border-radius:16px; }}')
            value.setStyleSheet(f'color:{c.accent}; background:transparent; font-size:26px; font-weight:700;')
            caption.setStyleSheet(f'color:{c.text_secondary}; background:transparent; font-size:12px;')
        dark = QColor(c.bg_secondary).lightnessF() < 0.5
        for button, icon, badge, heading, arrow in self._links:
            color = '#5865F2' if 'discord' in icon else '#FFFFFF' if dark else '#24292F'
            badge.setPixmap(theme_pixmap(icon, color, 24, self.devicePixelRatioF()))
            badge.setStyleSheet('background:transparent;')
            arrow.setStyleSheet(f'background:transparent; color:{c.text_secondary}; font-size:15px;')
            heading.setStyleSheet(f'background:transparent; color:{c.text_primary}; font-size:12px; font-weight:500;')
            button.setStyleSheet(f"""
                QPushButton#communityLink {{ background:{c.bg_secondary};
                    border:1px solid {c.border}; border-radius:16px; padding:0; }}
                QPushButton#communityLink:hover {{ background:{c.surface_hover}; }}
                QPushButton#communityLink:pressed {{ border-color:{c.text_secondary}; }}
            """)
