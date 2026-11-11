from PySide6.QtCore import (
    QCoreApplication,
    QEasingCurve,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.ios.feature_icons import FEATURE_ICONS
from src.gui.theme import ColorThemeManager, theme_icon, theme_pixmap
from src.utils.pages import Page, get_resettable_pages

from .controls import GlassCheckBox, GlassPanel, LiquidButton
from .placement import reveal_sheet, sheet_rect


class RestoreSectionCard(QPushButton):
    def __init__(self,text,icon,parent=None):
        super().__init__(text,parent)
        self.setCheckable(True)
        self.setObjectName('resetSelection')
        self.setCursor(Qt.PointingHandCursor)
        self.icon_path=icon
        self.progress=1.0
        self.motion=QVariantAnimation(self)
        self.motion.setDuration(440)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.motion.valueChanged.connect(self._step)
        self.toggled.connect(self._select)

    def _step(self,value):
        self.progress=float(value)
        self.update()

    def _select(self,checked):
        self.motion.stop()
        self.progress=1.0
        if not QApplication.instance().property('liquid_reduce_motion'):
            self.motion.setStartValue(0.0)
            self.motion.setEndValue(1.0)
            self.motion.start()
        self.update()

    def paintEvent(self,event):
        colors=ColorThemeManager.instance().colors
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bounds=QRectF(self.rect()).adjusted(1,1,-1,-1)
        path=QPainterPath()
        path.addRoundedRect(bounds,8,8)
        p.fillPath(path,QColor(colors.bg_tertiary if self.isChecked() or self.underMouse() else colors.bg_secondary))
        p.setPen(QPen(QColor(245,247,250,110 if self.isChecked() else 32),1))
        p.drawPath(path)
        if self.progress<1:
            half=bounds.width()/2
            band=max(30,half*.6)
            fade=1-self.progress
            for direction in (1,-1):
                x=bounds.left()+half*self.progress if direction==1 else bounds.right()-half*self.progress
                beam=QLinearGradient(x-band,0,x+band,0)
                beam.setColorAt(0,QColor(255,255,255,0))
                beam.setColorAt(.5,QColor(255,255,255,round(140*fade)))
                beam.setColorAt(1,QColor(255,255,255,0))
                p.save()
                p.setClipRect(QRectF(bounds.left() if direction==1 else bounds.center().x(),0,half,self.height()))
                p.fillPath(path,beam)
                p.setPen(QPen(beam,2))
                p.drawPath(path)
                p.restore()
        color=colors.text_primary if self.isEnabled() else colors.text_disabled
        artwork=theme_pixmap(self.icon_path,color,26,self.devicePixelRatioF())
        p.drawPixmap(QRectF(12,(self.height()-26)/2,26,26),artwork,QRectF(artwork.rect()))
        p.setPen(QColor(color))
        p.setFont(self.font())
        text_bounds=QRectF(46,0,max(0,self.width()-72),self.height())
        p.drawText(text_bounds,Qt.AlignVCenter|Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.text(),Qt.ElideRight,int(text_bounds.width())))
        if self.isChecked():
            theme_icon(':/icon/check-circle.svg',color).paint(p,self.width()-25,(self.height()-16)//2,16,16)
        if self.hasFocus():
            p.setPen(QPen(QColor(colors.text_primary),1,Qt.DotLine))
            p.drawRoundedRect(bounds.adjusted(3,3,-3,-3),6,6)


class RestoreChangesPanel(GlassPanel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.anchor = None
        self.selected_pages = set()
        self.page_switches = {}
        self._device_uid = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        self.title = QLabel('Restore Changes')
        close = LiquidButton('×')
        close.setFixedSize(30, 30)
        close.setAccessibleName('Close restore selection')
        close.clicked.connect(self.hide)
        heading.addWidget(self.title, 1)
        heading.addWidget(close)
        layout.addLayout(heading)
        self.device = QLabel()
        self.device.setWordWrap(True)
        layout.addWidget(self.device)
        body = QHBoxLayout()
        body.setSpacing(20)
        from .panels import ReviewDevice
        self.phone = ReviewDevice()
        self.phone.setFixedSize(68, 96)
        self.phone.hide()
        body.addWidget(self.phone, 0, Qt.AlignTop)
        details = QVBoxLayout()
        details.setSpacing(12)
        details.setAlignment(Qt.AlignVCenter)
        body.addLayout(details, 1)
        layout.addLayout(body)
        self.description = QLabel('Choose which sections to restore.')
        self.description.setWordWrap(True)
        description_row = QHBoxLayout()
        self.description_icon = QLabel()
        self.description_icon.setFixedSize(22, 22)
        description_row.addWidget(self.description_icon, 0, Qt.AlignTop)
        description_row.addWidget(self.description, 1)
        details.addLayout(description_row)
        self.all_switch = GlassCheckBox('Select all sections')
        self.all_switch.toggled.connect(self._select_all)
        layout.addWidget(self.all_switch)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet('background:transparent;border:none;')
        self.body = QWidget()
        self.body.setStyleSheet('background:transparent;')
        self.rows = QGridLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setHorizontalSpacing(12)
        self.rows.setVerticalSpacing(4)
        self.rows.setAlignment(Qt.AlignTop)
        self.rows.setColumnStretch(0,1)
        self.rows.setColumnStretch(1,1)
        self.scroll.setMinimumHeight(118)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll)
        self.summary = QLabel('No sections selected')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        warning_box = QWidget()
        warning_box.setObjectName('restoreConnectionWarning')
        warning_box.setStyleSheet('QWidget#restoreConnectionWarning{background:rgba(255,196,69,24);border:1px solid rgba(255,196,69,95);border-radius:8px;}')
        warning_layout = QHBoxLayout(warning_box)
        warning_layout.setContentsMargins(12,12,12,12)
        warning_layout.setSpacing(10)
        self.warning_icon = QLabel()
        self.warning_icon.setFixedSize(22,22)
        warning_layout.addWidget(self.warning_icon,0,Qt.AlignTop)
        self.warning = QLabel("Don't unplug your phone during restore. Keep it connected, unlocked and awake.")
        self.warning.setWordWrap(True)
        warning_layout.addWidget(self.warning,1)
        layout.addWidget(warning_box)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()
        source = getattr(getattr(window, 'ios_home', None), '_device_preview', None)
        if source is not None:
            source.preview_changed.connect(self.refresh_phone)
        self.refresh_phone()
        self.hide()

    def _retheme(self):
        colors = ColorThemeManager.instance().colors
        for card in self.page_switches.values():
            card.update()
        self.title.setStyleSheet(f'font-size:18px;font-weight:600;color:{colors.text_primary};')
        self.device.setStyleSheet(f'font-size:13px;color:{colors.text_secondary};')
        for label in (self.description, self.summary):
            label.setStyleSheet(f'font-size:13px;color:{colors.text_secondary};')
        self.warning.setStyleSheet(f'font-size:12px;color:{colors.warning};')
        self.description_icon.setPixmap(theme_pixmap(':/icon/gear.svg',colors.text_secondary,22,self.devicePixelRatioF()))
        self.warning_icon.setPixmap(theme_pixmap(':/icon/cable.svg',colors.warning,22,self.devicePixelRatioF()))

    def refresh_phone(self, *_):
        from src.gui.ios.device_preview import render_phone
        manager = self.window.device_manager
        uid = manager.get_current_device_udid()
        source = getattr(getattr(self.window, 'ios_home', None), '_device_preview', None)
        image = getattr(source, '_image', None) if source is not None and getattr(source, '_udid', None) == uid else None
        model = getattr(manager, 'get_current_device_model', lambda: '')() or ''
        self.phone.image = image if image is not None else render_phone({}, model, disconnected=not bool(uid))
        self.phone.update()
        self.device.setText('Connected device' if uid else 'Connect your device to restore selected changes.')

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def _populate(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.selected_pages.clear()
        self.page_switches.clear()
        self.all_switch.blockSignals(True)
        self.all_switch.setChecked(False)
        self.all_switch.blockSignals(False)
        pages = get_resettable_pages(self.window.device_manager)
        pages.sort(key=lambda page: page != Page.Daemons)
        icons={Page.Daemons:FEATURE_ICONS['Daemons'],Page.StatusBar:FEATURE_ICONS['Status Bar'],
               Page.Springboard:FEATURE_ICONS['Tweaks'],Page.LiquidGlass:FEATURE_ICONS['Icon Themes'],
               Page.InternalOptions:FEATURE_ICONS['Community Catalog'],Page.Templates:FEATURE_ICONS['Templates']}
        for index, page in enumerate(pages):
            switch = RestoreSectionCard(QCoreApplication.translate('Nugget', page.getPageName()),
                                        icons.get(page,FEATURE_ICONS['Tweaks']))
            switch.setFixedHeight(48)
            switch.toggled.connect(lambda checked, p=page: self._toggle_page(p, checked))
            self.page_switches[page] = switch
            switch.setMinimumWidth(0)
            self.rows.addWidget(switch, index//2, index%2)
        row_count=(len(pages)+1)//2
        self._selector_height=row_count*48+max(0,row_count-1)*4+4
        available=max(80,self.window.height()-360)
        self.scroll.setMinimumHeight(min(self._selector_height,available))
        self.scroll.setMaximumHeight(self._selector_height)
        self._update_selection()

    def _toggle_page(self, page, checked):
        if checked:
            self.selected_pages.add(page)
        else:
            self.selected_pages.discard(page)
        self._update_selection()

    def _select_all(self, checked):
        for switch in self.page_switches.values():
            switch.setChecked(checked)

    def _update_selection(self):
        count = len(self.selected_pages)
        noun = 'section' if count == 1 else 'sections'
        self.summary.setText(f'{count} {noun} selected' if count else 'Choose at least one section to continue.')
        self.all_switch.blockSignals(True)
        self.all_switch.setChecked(bool(self.page_switches) and count == len(self.page_switches))
        self.all_switch.blockSignals(False)
        if self.anchor is not None:
            busy = self.window.apply_in_progress or getattr(self.window, '_cache_restore_in_progress', False)
            self.anchor.setEnabled(bool(count) and not busy and bool(self.window.device_manager.get_current_device_udid()))

    def panel_size(self):
        height=max(400,270+getattr(self,'_selector_height',118))
        return QSize(min(self.anchor.width(), self.window.width()-24), min(height, self.window.height()-100))

    def reposition(self):
        if self.anchor is not None:
            self.setGeometry(sheet_rect(self.window, self.anchor, self.panel_size()))

    def activate(self, anchor):
        if self.window.apply_in_progress or getattr(self.window, '_cache_restore_in_progress', False):
            self.window.show_ios_page(6)
            return
        if self.isVisible():
            self._confirm()
            return
        self.anchor = anchor
        self._device_uid = self.window.device_manager.get_current_device_udid()
        self.refresh_phone()
        self.window.liquid.restore.hide()
        self._populate()
        y = anchor.mapTo(self.window, QPoint()).y()
        required = self.panel_size().height()+20
        if y < required:
            bar = self.window.ios_home._scroll.verticalScrollBar()
            bar.setValue(max(0, bar.value()-(required-y)))
        reveal_sheet(self, self.window, anchor, self.panel_size(), duration=300)

    def showEvent(self, event):
        if self.anchor is not None:
            self.anchor.setText('Confirm Restore')
            self.anchor.setAccessibleName('Confirm Restore')
            self.anchor.setToolTip('Restore selected sections')
        self._update_selection()
        super().showEvent(event)

    def hideEvent(self, event):
        if self.anchor is not None:
            self.anchor.setText('Restore Changes')
            self.anchor.setAccessibleName('Restore Changes')
            self.anchor.setToolTip('Restore Changes')
            self.anchor.setEnabled(not self.window.apply_in_progress and not getattr(self.window, '_cache_restore_in_progress', False))
        super().hideEvent(event)

    def _confirm(self):
        manager = self.window.device_manager
        if not self.selected_pages or not manager.get_current_device_udid():
            return
        if self.window.apply_in_progress or getattr(self.window, '_cache_restore_in_progress', False):
            return
        if manager.get_current_device_udid() != self._device_uid:
            self._device_uid = manager.get_current_device_udid()
            self._populate()
            self.summary.setText('The selected device changed. Choose the sections again.')
            return
        pages = [page for page in self.page_switches if page in self.selected_pages]
        self.hide()
        self.window.apply_changes(pages)
        if self.window.apply_in_progress:
            self.window.show_ios_page(6)
