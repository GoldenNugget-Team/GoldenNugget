"""Shared bottom navigation with scroll-direction reveal."""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QPointF, QSizeF, QEvent, QRect, QRectF, QVariantAnimation
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QPushButton, QAbstractScrollArea, QLayout, QGraphicsOpacityEffect
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion, QLinearGradient, QFont, QPixmap
from shiboken6 import isValid
from src.gui.theme import ColorThemeManager, theme_icon
from src.gui.slogans import launch_slogan

# The launch's slogan, shared with the liquid dock's brand (src/gui/slogans).
_LAUNCH_SLOGAN = launch_slogan()


class NavigationGlass(QFrame):
    def paintEvent(self, event):
        colors = ColorThemeManager.instance().colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(bounds, 29, 29)
        surface = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
        top = QColor(colors.bg_secondary)
        top.setAlpha(195)
        bottom = QColor(colors.bg_secondary)
        bottom.setAlpha(155)
        surface.setColorAt(0, top)
        surface.setColorAt(1, bottom)
        painter.fillPath(path, surface)
        sheen = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 28))
        sheen.setColorAt(0.5, QColor(255, 255, 255, 5))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)
        edge = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
        edge.setColorAt(0, QColor(255, 255, 255, 85))
        edge.setColorAt(1, QColor(colors.border))
        painter.setPen(QPen(edge, 1))
        painter.drawPath(path)


class NavigationPanel(QFrame):
    def __init__(self, navigation):
        super().__init__(navigation.window, Qt.Popup | Qt.FramelessWindowHint)
        self.navigation = navigation
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("bottomNavigationPanel")
        self.setStyleSheet("QFrame#bottomNavigationPanel { background: transparent; border: none; }")
        self.body = QFrame(self)
        self.body.setObjectName("bottomNavigationPanelBody")
        self._progress = 0.0
        self._origin_x = 0.0
        self._surface = QColor()
        self._border = QColor()
        self.expansion = QVariantAnimation(self)
        self.expansion.setDuration(320)
        self.expansion.setEasingCurve(QEasingCurve.OutCubic)
        self.expansion.valueChanged.connect(self._expand)
        self.opacity = QGraphicsOpacityEffect(self.body)
        self.body.setGraphicsEffect(self.opacity)
        self.content_layout = QHBoxLayout(self.body)
        self.content_layout.setContentsMargins(12, 10, 12, 10)
        self.content_layout.setSizeConstraint(QLayout.SetNoConstraint)
        self.panel = None

    def open(self, panel, title):
        tabs = self.navigation.window.ios_home.control_tabs
        self.index = tabs.indexOf(panel)
        self.title = tabs.tabText(self.index)
        self.icon = tabs.tabIcon(self.index)
        self.previous = tabs.currentWidget()
        blocked = tabs.blockSignals(True)
        tabs.removeTab(self.index)
        tabs.blockSignals(blocked)
        self.panel = panel
        self.navigation._panel_title = title
        self.content_layout.addWidget(panel)
        panel.setAutoFillBackground(False)
        panel.show()
        width = min(max(450, panel.minimumSizeHint().width() + 24), self.navigation.window.width() - 32)
        height = max(156, panel.minimumSizeHint().height() + 20) if title == 'Devices' else 100
        self.resize(width, height + 14)
        button = next(button for button, _, name in self.navigation._buttons if name == title)
        anchor = button.mapToGlobal(QPoint(button.width() // 2, 0))
        screen = self.navigation.screen().availableGeometry()
        x = max(screen.left() + 8, min(anchor.x() - width // 2, screen.right() - width - 8))
        pill_top = self.navigation.pill.mapToGlobal(QPoint(0, 0)).y()
        self.move(x, max(screen.top() + 8, pill_top - self.height() + 10))
        self._origin_x = anchor.x() - x
        self.expansion.stop()
        self._expand(0.0)
        self.show()
        self.expansion.setStartValue(0.0)
        self.expansion.setEndValue(1.0)
        self.expansion.start()
        self.navigation._sync_selection()

    def _expand(self, value):
        self._progress = float(value)
        progress = self._progress
        height = self.height() - 14
        width = 72 + (self.width() - 72) * progress
        left = (self._origin_x - 36) * (1 - progress)
        top = height * (1 - progress)
        self.body.setGeometry(QRect(round(left), round(top), round(width), max(1, round(height * progress))))
        self.opacity.setOpacity(max(0.0, min(1.0, (progress - 0.15) / 0.85)))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bubble = QRectF(self.body.geometry()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(bubble, 26, 26)
        neck = QPainterPath()
        neck.addRoundedRect(QRectF(self._origin_x - 30, max(bubble.top(), bubble.bottom() - 18),
                                  60, self.height() - max(bubble.top(), bubble.bottom() - 18)), 16, 16)
        path = path.united(neck)
        painter.setPen(QPen(self._border, 1))
        painter.setBrush(self._surface)
        painter.drawPath(path)

    def hideEvent(self, event):
        self.expansion.stop()
        if self.panel is not None:
            tabs = self.navigation.window.ios_home.control_tabs
            panel, self.panel = self.panel, None
            self.content_layout.removeWidget(panel)
            blocked = tabs.blockSignals(True)
            tabs.insertTab(self.index, panel, self.icon, self.title)
            tabs.setCurrentWidget(self.previous)
            tabs.blockSignals(blocked)
            self.navigation._panel_title = None
            self.navigation._sync_selection()
        super().hideEvent(event)


class NavigationBrand(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(214, 52)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self._title = self.tr("GoldenNugget")
        self._slogan = _LAUNCH_SLOGAN
        self.setAccessibleName(self._title)
        self.setAccessibleDescription(self._slogan)
        self.setToolTip(self._slogan)
        self._icon = QPixmap(":/credits/big_nugget.png")
        self._hover = 0.0
        self._phase = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._set_hover)
        self._shimmer = QVariantAnimation(self)
        self._shimmer.setDuration(1800)
        self._shimmer.setStartValue(0.0)
        self._shimmer.setEndValue(1.0)
        self._shimmer.setLoopCount(-1)
        self._shimmer.valueChanged.connect(self._set_phase)

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _set_phase(self, value):
        self._phase = float(value)
        self.update()

    def enterEvent(self, event):
        self._fade.stop()
        self._fade.setStartValue(self._hover)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._shimmer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._shimmer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._hover)
        self._fade.setEndValue(0.0)
        self._fade.start()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._fade.stop()
        self._shimmer.stop()
        self._hover = 0.0
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        sweep = QLinearGradient(-self.width() + self._phase * self.width() * 2, 0,
                                self._phase * self.width() * 2, self.height())
        sweep.setColorAt(0.0, QColor("#91602D"))
        sweep.setColorAt(0.35, QColor("#C99744"))
        sweep.setColorAt(0.55, QColor("#FFE4A0"))
        sweep.setColorAt(0.8, QColor("#C99744"))
        sweep.setColorAt(1.0, QColor("#91602D"))
        icon_rect = QRectF(8, 7, 38, 38)
        if self._hover:
            painter.setOpacity(self._hover * 0.18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(sweep)
            painter.drawRoundedRect(icon_rect.adjusted(-4, -2, 4, 2), 13, 13)
            painter.setOpacity(1.0)
        if not self._icon.isNull():
            fitted = QSizeF(self._icon.size().scaled(38, 38, Qt.KeepAspectRatio))
            artwork = QRectF(QPointF(), fitted)
            artwork.moveCenter(icon_rect.center())
            painter.drawPixmap(artwork, self._icon, QRectF(self._icon.rect()))
        title_font = QFont(self.font())
        title_font.setPixelSize(17)
        title_font.setWeight(QFont.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor("#BC8B45"))
        title_rect = QRectF(58, 5, self.width() - 66, 21)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self._title)
        slogan_font = QFont(self.font())
        slogan_font.setPixelSize(10)
        painter.setFont(slogan_font)
        painter.setPen(QColor("#B08B58"))
        slogan_rect = QRectF(58, 27, self.width() - 66, 23)
        painter.drawText(slogan_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._slogan)
        if self._hover:
            painter.setOpacity(self._hover)
            painter.setPen(QPen(sweep, 1))
            painter.setFont(title_font)
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self._title)
            painter.setFont(slogan_font)
            painter.drawText(slogan_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._slogan)


class BottomNavigation(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self._shown = True
        self._buttons = []
        self._panel_title = None
        self.setObjectName("bottomNavigation")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("QWidget#bottomNavigation { background: transparent; border: none; }")
        self.popup = NavigationPanel(self)
        self._scroll_positions = {}
        self._scroll_token = 0
        self.setMaximumHeight(82)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 12)
        row.addStretch()
        self.pill = NavigationGlass(self)
        self.pill.setObjectName("bottomNavigationPill")
        self.pill.installEventFilter(self)
        buttons = QHBoxLayout(self.pill)
        buttons.setContentsMargins(7, 5, 7, 5)
        buttons.setSpacing(4)
        self.brand = NavigationBrand(self.pill)
        self.brand.clicked.connect(self._open_home)
        buttons.addWidget(self.brand)
        home = window.ios_home
        entries = [
            ('Devices', ':/icon/phone.svg', lambda: self._open_panel(home._devices_page, "Devices")),
            ('Home', ':/icon/house.svg', self._open_home),
            ('Presets', ':/icon/folder.svg', self._open_presets),
            ('Settings', ':/icon/gear.svg', lambda: window.set_ios_page(4)),
        ]
        for title, icon, callback in entries:
            button = QPushButton(self.tr(title), self.pill)
            button.setCheckable(True)
            button.setMinimumHeight(48)
            button.setMinimumWidth(114)
            button.setIconSize(QSize(21, 21))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            self._buttons.append((button, icon, title))
        row.addWidget(self.pill)
        row.addStretch()
        self.animation = QPropertyAnimation(self, b'maximumHeight', self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        window.ios_pages.currentChanged.connect(self._page_changed)
        home.control_tabs.currentChanged.connect(self._sync_selection)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()
        self._page_changed()
        parent.installEventFilter(self)
        self.animation.valueChanged.connect(lambda _: self._position_bar())
        QTimer.singleShot(0, self._position_bar)

    def eventFilter(self, watched, event):
        if watched is self.pill and event.type() in (QEvent.Resize, QEvent.Move):
            self._update_hit_region()
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.popup.hide()
            self._position_bar()
        return super().eventFilter(watched, event)

    def _update_hit_region(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.pill.geometry()), 29, 29)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _position_bar(self):
        parent = self.parentWidget()
        if parent is not None:
            height = min(82, self.maximumHeight())
            self.setGeometry(0, parent.height() - height, parent.width(), height)
            self._update_hit_region()
            self.raise_()

    def _open_panel(self, panel, title):
        if self.popup.isVisible():
            same_panel = self.popup.panel is panel
            self.popup.hide()
            if same_panel:
                return
        self.reveal(True)
        self.popup.open(panel, title)

    def _open_home(self):
        self.popup.hide()
        self.window.set_ios_page(0)
        self._sync_selection()

    def _open_presets(self):
        self.popup.hide()
        self.window.ios_home.open_presets_section()
        self._sync_selection()

    def _page_changed(self, *_):
        self.popup.hide()
        self.reveal(True)
        self._attach_scrolls()
        QTimer.singleShot(0, self._attach_scrolls)
        self._sync_selection()

    def _attach_scrolls(self):
        if not isValid(self) or not isValid(self.window.ios_pages):
            return
        page = self.window.ios_pages.currentWidget()
        if page is None:
            return
        for scroll in page.findChildren(QAbstractScrollArea):
            bar = scroll.verticalScrollBar()
            if bar.property("bottomNavigationWatched"):
                continue
            self._scroll_token += 1
            token = self._scroll_token
            bar.setProperty("bottomNavigationWatched", True)
            self._scroll_positions[token] = bar.value()
            bar.valueChanged.connect(lambda value, key=token, owner=page: self._scrolled(key, owner, value))
            bar.destroyed.connect(lambda *_args, key=token: self._scroll_positions.pop(key, None))
        self._sync_selection()

    def _scrolled(self, token, page, value):
        if token not in self._scroll_positions or not isValid(self) or not isValid(self.window.ios_pages):
            return
        previous = self._scroll_positions[token]
        self._scroll_positions[token] = value
        if page is not self.window.ios_pages.currentWidget():
            return
        if self.window.ios_pages.currentIndex() == 0 or value <= 0:
            self.reveal(True)
        elif abs(value - previous) >= 3:
            self.reveal(value < previous)

    def _sync_selection(self, *_):
        page = self.window.ios_pages.currentIndex()
        selected = (self._panel_title or
                    ('Settings' if page == 4 else 'Presets' if page == 12 else
                     'Home' if page == 0 else ''))
        for button, _, title in self._buttons:
            button.setChecked(title == selected)

    def reveal(self, shown):
        if shown == self._shown:
            return
        self._shown = shown
        self.animation.stop()
        self.animation.setStartValue(self.maximumHeight())
        self.animation.setEndValue(82 if shown else 0)
        self.animation.start()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.pill.setStyleSheet('QFrame#bottomNavigationPill { background:transparent; border:none; }')
        self.pill.update()
        self.popup._surface = QColor(c.bg_secondary)
        self.popup._surface.setAlpha(205)
        self.popup._border = QColor(c.border)
        self.popup.body.setStyleSheet('QFrame#bottomNavigationPanelBody { background: transparent; border: none; }')
        self.popup.update()
        for button, icon, _ in self._buttons:
            button.setIcon(theme_icon(icon, c.text_primary))
            button.setStyleSheet(f'''
                QPushButton {{ color:{c.text_secondary}; background:transparent; border:none;
                    border-radius:23px; padding:6px 14px; font-size:15px; font-weight:600; }}
                QPushButton:checked {{ background:{c.accent}; color:{c.text_inverse}; }}
                QPushButton:hover:!checked {{ background:{c.surface_hover}; color:{c.text_primary}; }}
            ''')
