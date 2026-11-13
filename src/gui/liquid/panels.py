import math
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import ColorThemeManager

from .appearance import GlassChoice, GlassSlider, InlinePalette
from .choice_editor import GlassComboBox as QComboBox
from .controls import GlassCheckBox, GlassPanel, LiquidActionButton, LiquidButton
from .motion import animate
from .placement import panel_rect


class PhoneRender(GlassPanel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(160,170)
        self.state='idle'
        self.progress=0
        self.name='iPhone'
        self.counts={'tweaks':0,'daemons':0}
        self.setAccessibleName('Device operation illustration')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w=min(128,self.width()-20)
        r=QRectF((self.width()-w)/2,8,w,self.height()-22)
        p.setPen(QPen(QColor('#7e8797'),2))
        p.setBrush(QColor('#080b13'))
        p.drawRoundedRect(r,24,24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#242938'))
        p.drawRoundedRect(QRectF(r.center().x()-23,r.top()+9,46,12),6,6)
        p.setPen(QColor('#e5eaf4'))
        p.setFont(QFont('Inter Variable',11))
        center=r.center()
        if self.state=='authentication':
            p.drawText(QRectF(r.left(),center.y()-40,w,30),Qt.AlignCenter,'Unlock iPhone')
            for i in range(6):
                p.setBrush(QColor('#ced6e5'))
                p.drawEllipse(QPointF(center.x()-32+i*13,center.y()+4),3,3)
        elif self.state=='recovery':
            p.drawText(QRectF(r.left(),center.y()-40,w,70),Qt.AlignCenter,'Connect to\ncomputer')
            p.drawLine(QPointF(center.x(),center.y()+40),QPointF(center.x(),r.bottom()-30))
        elif self.state in ('restore','setup','backup','media','tweaks'):
            pix=QPixmap(':/icon/apple.svg')
            if not pix.isNull():
                p.drawPixmap(round(center.x()-17),round(center.y()-45),34,40,pix)
            else:
                p.setFont(QFont('Helvetica Neue',30))
                p.drawText(QRectF(r.left(),center.y()-50,w,45),Qt.AlignCenter,'')
            track=QRectF(r.left()+20,center.y()+15,w-40,4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#343b4b'))
            p.drawRoundedRect(track,2,2)
            p.setBrush(QColor('#edf3ff'))
            p.drawRoundedRect(QRectF(track.left(),track.top(),track.width()*self.progress/100,4),2,2)
        else:
            p.setPen(QColor('#7b89a2'))
            p.drawText(QRectF(r.left()+10,center.y()-20,w-20,60),Qt.AlignCenter|Qt.TextWordWrap,self.name)
        p.setPen(QColor('#e5eaf4'))
        p.setFont(QFont('Helvetica Neue',10))
        p.drawText(QRectF(r.left()+6,r.bottom()-72,w-12,52),Qt.AlignCenter,
                   f"{self.counts['tweaks']} tweaks\n{self.counts['daemons']} daemons")
        p.setPen(QPen(QColor('#aeb9cb'),3))
        p.drawLine(QPointF(center.x()-19,r.bottom()-10),QPointF(center.x()+19,r.bottom()-10))


class DeviceDrawer(GlassPanel):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        outer=QVBoxLayout(self)
        outer.setContentsMargins(20,18,20,18)
        outer.setSpacing(12)
        top=QHBoxLayout()
        self.title=QLabel('Devices')
        close=LiquidButton('×')
        close.setFixedSize(30,30)
        close.setAccessibleName('Close device information')
        close.clicked.connect(self.hide)
        top.addWidget(self.title,1)
        top.addWidget(close)
        outer.addLayout(top)
        self.area=QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet('background:transparent;border:none;')
        body=QWidget()
        body.setStyleSheet('background:transparent;')
        self.area.setWidget(body)
        outer.addWidget(self.area,1)
        column=QVBoxLayout(body)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(16)
        self.empty=QWidget()
        empty=QVBoxLayout(self.empty)
        empty.setContentsMargins(0,0,0,0)
        empty.setSpacing(14)
        device_heading=QHBoxLayout()
        device_heading.setSpacing(14)
        self.symbol=QLabel()
        self.symbol.setFixedSize(44,58)
        self.symbol.setAlignment(Qt.AlignCenter)
        device_heading.addWidget(self.symbol)
        device_text=QVBoxLayout()
        device_text.setSpacing(4)
        self.empty_title=QLabel('No device connected')
        self.empty_title.setWordWrap(True)
        device_text.addWidget(self.empty_title)
        self.device_hint=QLabel('iPhone or iPad · USB connection')
        self.device_hint.setWordWrap(True)
        device_text.addWidget(self.device_hint)
        device_heading.addLayout(device_text,1)
        empty.addLayout(device_heading)
        self.instructions=[]
        for index,text in enumerate(('Connect with a USB data cable.',
                                     'Unlock your device.',
                                     'Tap Trust if prompted.'),1):
            row=QHBoxLayout()
            row.setSpacing(12)
            number=QLabel(str(index))
            number.setFixedSize(22,22)
            number.setAlignment(Qt.AlignCenter)
            label=QLabel(text)
            label.setWordWrap(True)
            row.addWidget(number)
            row.addWidget(label,1)
            empty.addLayout(row)
            self.instructions.append((number,label))
        column.addWidget(self.empty)
        self.connected=QWidget()
        connected=QVBoxLayout(self.connected)
        connected.setContentsMargins(0,0,0,0)
        connected.setSpacing(16)
        home=window.ios_home
        home.device_combo.setMinimumWidth(0)
        connected.addWidget(home.device_combo)
        summary=QHBoxLayout()
        summary.setSpacing(18)
        summary.addWidget(home._device_preview,0,Qt.AlignTop)
        info=QVBoxLayout()
        info.setAlignment(Qt.AlignVCenter)
        info.setSpacing(8)
        self.device_name=QLabel()
        self.device_name.setWordWrap(True)
        info.addWidget(self.device_name)
        home.device_software.setWordWrap(True)
        info.addWidget(home.device_software)
        self.connection=QLabel()
        self.connection.setWordWrap(True)
        info.addWidget(self.connection)
        summary.addLayout(info,1)
        connected.addLayout(summary)
        connected.addWidget(home.device_details)
        column.addWidget(self.connected)
        column.addStretch()
        self.status=QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.check=LiquidButton('Check connection')
        self.check.setFixedHeight(42)
        self.check.clicked.connect(self.check_connection)
        outer.addWidget(self.check)
        ColorThemeManager.instance().theme_changed.connect(self.retheme)
        self.retheme()
        self.refresh()
        self.hide()

    def paintEvent(self,event):
        from .controls import paint_dock_glass
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shape=QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),18,18)
        painter.fillPath(shape,QColor(ColorThemeManager.instance().colors.bg_secondary))
        paint_dock_glass(painter,shape)

    def retheme(self):
        from src.gui.theme import theme_pixmap
        c=ColorThemeManager.instance().colors
        self.title.setStyleSheet(f'font-size:17px;font-weight:600;color:{c.text_primary};')
        self.empty_title.setStyleSheet(f'font-size:16px;font-weight:600;color:{c.text_primary};')
        self.device_hint.setStyleSheet(f'font-size:12px;color:{c.text_secondary};')
        self.device_name.setStyleSheet(f'font-size:16px;font-weight:600;color:{c.text_primary};')
        self.connection.setStyleSheet(f'font-size:12px;color:{c.text_secondary};')
        self.status.setStyleSheet(f'font-size:12px;color:{c.text_secondary};')
        self.symbol.setPixmap(theme_pixmap(':/icon/phone.svg',c.text_secondary,42,self.devicePixelRatioF()))
        from src.gui.theme import theme_icon
        self.check.setIcon(theme_icon(':/icon/arrow-clockwise.svg',c.text_primary))
        self.check.setStyleSheet(f'QPushButton#liquidButton{{color:{c.text_primary};background:{c.bg_tertiary};border:1px solid rgba(255,255,255,35);border-radius:8px;padding:8px 12px;font-weight:600;}} QPushButton#liquidButton:hover{{border-color:rgba(255,255,255,90);}}')
        for number,label in self.instructions:
            number.setStyleSheet(f'font-size:12px;font-weight:600;color:{c.text_secondary};background:transparent;')
            label.setStyleSheet(f'font-size:13px;color:{c.text_secondary};')

    def check_connection(self):
        if not self.window.refresh_in_progress:
            self.window.refresh_devices()
        self.refresh()

    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        self.open()

    def panel_size(self):
        height=430 if self.window.device_manager.data_singleton.current_device is not None else 350
        return QSize(min(420,self.window.width()-32),min(height,self.window.height()-110))

    def open(self):
        if self.isVisible():
            return
        self.window.bottom_navigation.popup.hide()
        self.window.liquid.settings.hide()
        self.window.liquid.peek.dismiss()
        self.setGeometry(panel_rect(self.window,self.window.liquid.device_button,self.panel_size(),'bottom'))
        self.clearMask()
        self.show()
        self.raise_()
        QTimer.singleShot(0,self.refresh)

    def reposition(self):
        self.clearMask()
        self.setGeometry(panel_rect(self.window,self.window.liquid.device_button,self.panel_size(),'bottom'))

    def refresh(self):
        dm=self.window.device_manager
        dev=dm.data_singleton.current_device
        connected=dev is not None
        self.empty.setVisible(not connected)
        self.connected.setVisible(connected)
        scanning=bool(getattr(self.window,'refresh_in_progress',False))
        self.check.setEnabled(not scanning)
        self.check.setText('Checking connection...' if scanning else 'Check connection')
        self.status.setText('Checking for connected devices...' if scanning else
                            'No device detected. Check your cable and USB port.' if not connected else
                            'Keep your device connected during changes.')
        if connected:
            kind=str(getattr(dev,'connection_type','USB'))
            self.connection.setText('USB connection' if 'USB' in kind.upper() else 'Network connection')
            self.device_name.setText(self.window.ios_home.device_combo.currentText() or 'Connected device')


class WorkspaceSettings(GlassPanel):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        from .sounds import UiSounds
        self.sounds=UiSounds.instance()
        self.sounds.configure(window.settings)
        self.setFixedWidth(420)
        outer=QVBoxLayout(self)
        outer.setContentsMargins(4,4,4,4)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('background:transparent;border:none;')
        body=QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        column=QVBoxLayout(body)
        column.setContentsMargins(19,18,19,18)
        column.setSpacing(16)
        heading=QHBoxLayout()
        title=QLabel('App Settings')
        title.setStyleSheet('font-size:18px;font-weight:650;')
        title.setWordWrap(True)
        close=LiquidButton('×')
        close.setAccessibleName('Close app settings')
        close.clicked.connect(self.hide)
        heading.addWidget(title,1)
        heading.addWidget(close)
        column.addLayout(heading)
        full=LiquidButton('All application settings →')
        full.clicked.connect(lambda:window.bottom_navigation.navigate(4))
        from PySide6.QtWidgets import QGridLayout
        grid=QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0,1)
        grid.setColumnStretch(1,1)
        column.addLayout(grid)
        self._setting_tiles=[]
        def field(title,control,row,col,span=1):
            tile=QWidget()
            tile.setMinimumWidth(0)
            stack=QVBoxLayout(tile)
            stack.setContentsMargins(0,0,0,0)
            stack.setSpacing(6)
            if title:
                caption=QLabel(title)
                caption.setWordWrap(True)
                caption.setStyleSheet('font-size:12px;background:transparent;')
                stack.addWidget(caption)
            stack.addWidget(control)
            grid.addWidget(tile,row,col,1,span)
            self._setting_tiles.append(tile)
        self.language=QComboBox()
        self.language.setProperty('liveTranslateItems',True)
        source=window.ios_settings.lang_drp
        for i in range(source.count()):
            self.language.addItem(source.itemText(i))
        self.language.setCurrentIndex(source.currentIndex())
        self.language.activated.connect(window.ios_settings._on_lang_selected)
        field('Language',self.language,0,0)
        density=GlassChoice([('compact','Compact'),('comfortable','Comfortable')],
                            window.settings.value('liquid/card_density','comfortable'))
        density.setAccessibleName('Card layout')
        density.changed.connect(lambda value:window.liquid.set_card_density(value))
        field('Card layout',density,0,1)
        from .circle_palette import CirclePalette
        field('Accent color',CirclePalette(),1,0,2)
        slider=GlassSlider(Qt.Horizontal)
        slider.setRange(75,100)
        slider.setValue(int(window.settings.value('liquid/opacity',100)))
        slider.valueChanged.connect(self.opacity)
        field('Window opacity',slider,2,0)
        window.setWindowOpacity(slider.value()/100)
        edges=GlassChoice([(edge,edge.title()) for edge in ('top','bottom','left','right')],
                          window.bottom_navigation.edge)
        edges.setAccessibleName('Dock placement')
        edges.changed.connect(window.bottom_navigation.set_edge)
        field('Dock placement',edges,3,0,2)
        collapse=GlassCheckBox('Auto-collapse')
        collapse.setChecked(window.settings.value('liquid/collapse_idle',True,type=bool))
        collapse.toggled.connect(self.set_idle_collapse)
        field('',collapse,4,0)
        drawer=QComboBox()
        drawer.addItems(['Left','Right'])
        drawer.setCurrentIndex(1 if window.settings.value('liquid/device_edge','left')=='right'else 0)
        drawer.currentTextChanged.connect(lambda text:window.settings.setValue('liquid/device_edge',text.lower()))
        field('Device drawer',drawer,2,1)
        reduced=GlassCheckBox('Reduce motion')
        reduced.setChecked(window.settings.value('liquid/reduce_motion',False,type=bool))
        QApplication.instance().setProperty('liquid_reduce_motion', reduced.isChecked())
        reduced.toggled.connect(self.reduce_motion)
        field('',reduced,4,1)
        self.ui_sounds=GlassCheckBox('UI Sounds')
        self.ui_sounds.setChecked(self.sounds.enabled)
        self.ui_sounds.setAccessibleName('UI Sounds')
        self.ui_sounds.toggled.connect(self.sounds.set_enabled)
        field('',self.ui_sounds,5,0,2)
        column.addWidget(full)
        def retheme():
            colors=ColorThemeManager.instance().colors
            self.setStyleSheet('QFrame#liquidPanel{background:transparent;border:none;}'
                f'QLabel,QComboBox,QLineEdit{{color:{colors.text_primary};}}')
        ColorThemeManager.instance().theme_changed.connect(retheme)
        retheme()
        self.hide()

    def set_idle_collapse(self,value):
        self.window.settings.setValue('liquid/collapse_idle',value)
        dock=self.window.bottom_navigation
        if value:
            dock._collapse_timer.start()
        else:
            dock._collapse_timer.stop()
            dock.set_expanded(True)

    def reduce_motion(self, value):
        self.window.settings.setValue('liquid/reduce_motion',value)
        QApplication.instance().setProperty('liquid_reduce_motion',value)

    def opacity(self,value):
        self.window.setWindowOpacity(value/100)
        self.window.settings.setValue('liquid/opacity',value)

    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        self.open()

    def reposition(self):
        dock=self.window.bottom_navigation
        self.clearMask()
        self.setFixedWidth(min(420,self.window.width()-24))
        rect=panel_rect(self.window,dock.settings_button,
                        QSize(self.width(),min(580,self.window.height()-24)),dock.edge)
        if dock.edge=='left': rect.translate(-8,0)
        elif dock.edge=='right': rect.translate(8,0)
        elif dock.edge=='top': rect.translate(0,-8)
        else: rect.translate(0,8)
        self.setGeometry(rect)

    def paintEvent(self,event):
        from PySide6.QtGui import QPainterPath

        from .controls import paint_dock_glass
        dock=self.window.bottom_navigation
        rect=QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        edge=dock.edge
        if edge=='left': rect.adjust(10,0,0,0)
        elif edge=='right': rect.adjust(0,0,-10,0)
        elif edge=='top': rect.adjust(0,10,0,0)
        else: rect.adjust(0,0,0,-10)
        shape=QPainterPath()
        shape.addRoundedRect(rect,18,18)
        point=self.mapFromGlobal(dock.settings_button.mapToGlobal(dock.settings_button.rect().center()))
        tail=QPainterPath()
        if edge in ('left','right'):
            y=max(28,min(point.y(),self.height()-28))
            x=rect.left() if edge=='left' else rect.right()
            tip=0 if edge=='left' else self.width()
            tail.moveTo(x,y-12); tail.quadTo(tip,y,tip,y); tail.quadTo(x,y+3,x,y+12)
        else:
            x=max(28,min(point.x(),self.width()-28))
            y=rect.top() if edge=='top' else rect.bottom()
            tip=0 if edge=='top' else self.height()
            tail.moveTo(x-12,y); tail.quadTo(x,tip,x,tip); tail.quadTo(x+3,y,x+12,y)
        tail.closeSubpath()
        painter=QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        background=QColor(ColorThemeManager.instance().colors.bg_secondary)
        background.setAlpha(248)
        painter.fillPath(shape.united(tail),background)
        paint_dock_glass(painter,shape.united(tail))

    def hideEvent(self,event):
        finish=getattr(self,'_finish_settings_reveal',None)
        if finish:
            finish()
        super().hideEvent(event)

    def open(self):
        if self.isVisible():
            return
        self.window.liquid.device.hide()
        dock=self.window.bottom_navigation
        self.reposition()
        from .settings_reveal import reveal_settings
        reveal_settings(self,dock.settings_button,self._setting_tiles)



class ReviewDevice(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.image=QPixmap()
        self.setMinimumSize(120,160)
        self.setMaximumWidth(210)
        self.setAccessibleName('Selected device render')

    def paintEvent(self,event):
        if self.image.isNull():
            return
        p=QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        size=self.image.size().scaled(self.width()-20,self.height()-12,Qt.KeepAspectRatio)
        target=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,
                      size.width(),size.height())
        p.drawPixmap(target,self.image,QRectF(self.image.rect()))


class RestoreDrawer(GlassPanel):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        self._confirming=False
        self.total=0
        self._selection=None
        self._readiness_worker=None
        self._readiness_state='checking'
        self._readiness_uid=''
        self._readiness_checked=0.0
        self._readiness_attempts=0
        self._pending_confirm=False
        self._flow=1.0
        self.was_busy=False
        self.counts={'tweaks':0,'daemons':0}
        outer=QVBoxLayout(self)
        outer.setContentsMargins(6,6,6,6)
        area=QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setStyleSheet('background:transparent;border:none;')
        content=QWidget()
        content.setStyleSheet('background:transparent;')
        area.setWidget(content)
        outer.addWidget(area)
        self.review_area=area
        self._progress_mode=False
        column=QVBoxLayout(content)
        column.setContentsMargins(18,14,18,16)
        column.setSpacing(12)
        column.setAlignment(Qt.AlignTop)
        heading=QHBoxLayout()
        title=QLabel('Review Changes')
        title.setStyleSheet('font-size:20px;font-weight:650;')
        close=LiquidButton('×')
        close.setFixedSize(32,32)
        close.setAccessibleName('Close apply review')
        close.clicked.connect(self.hide)
        heading.addWidget(title,1)
        heading.addWidget(close)
        column.addLayout(heading)
        self.device_name=QLabel()
        self.device_name.setWordWrap(True)
        self.device_name.setStyleSheet('font-size:13px;color:#b9bec9;')
        column.addWidget(self.device_name)
        body=QHBoxLayout()
        body.setSpacing(24)
        self.device_render=ReviewDevice()
        body.addWidget(self.device_render,2)
        info=QVBoxLayout()
        info.setSpacing(12)
        info.setAlignment(Qt.AlignTop)
        body.addLayout(info,5)
        column.addLayout(body,1)
        window.ios_home._device_preview.preview_changed.connect(self.refresh_device)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet('font-size:16px;font-weight:600;')
        info.addWidget(self.summary)
        self.conflicts=QLabel()
        self.conflicts.setWordWrap(True)
        info.addWidget(self.conflicts)
        checks=QLabel('Checking device readiness…')
        self.checks=checks
        checks.setWordWrap(True)
        checks.setStyleSheet('font-size:13px;padding:10px;background:rgba(255,255,255,8);border-radius:12px;')
        info.addWidget(checks)
        self.retry_connection=LiquidButton('Check connection again')
        self.retry_connection.clicked.connect(lambda:self.poll_readiness(force=True))
        self.retry_connection.hide()
        info.addWidget(self.retry_connection)
        self.disclosure=LiquidButton('Details ▾')
        self.disclosure.clicked.connect(self.toggle_details)
        info.addWidget(self.disclosure)
        self.details=QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setStyleSheet('font-size:12px;')
        info.addWidget(self.details)
        self.cache_update=LiquidButton('Update backup cache')
        self.cache_update.clicked.connect(self.update_cache)
        info.addWidget(self.cache_update)
        self.ack=GlassCheckBox('I understand and want to continue')
        self.ack.toggled.connect(self.update_confirm)
        info.addWidget(self.ack)
        self.note=QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet('font-size:12px;color:#b9bec9;')
        info.addWidget(self.note)
        self.confirm_button=window.ios_home.apply_btn
        self.progress_area=QScrollArea()
        self.progress_area.setWidgetResizable(True)
        self.progress_area.setFrameShape(QScrollArea.NoFrame)
        self.progress_area.setStyleSheet('background:transparent;border:none;')
        progress_body=QWidget()
        progress_column=QVBoxLayout(progress_body)
        progress_column.setContentsMargins(16,14,16,16)
        heading=QHBoxLayout()
        heading.addWidget(QLabel('Current operation'),1)
        dismiss=LiquidButton('×')
        dismiss.setAccessibleName('Close progress details')
        dismiss.clicked.connect(self.hide)
        heading.addWidget(dismiss)
        progress_column.addLayout(heading)
        progress_column.addStretch()
        self.progress_area.setWidget(progress_body)
        outer.addWidget(self.progress_area)
        self.progress_area.hide()
        self.window.ios_home.device_details.selection_counts_changed.connect(self.set_counts)
        self.hide()

    def paintEvent(self,event):
        from PySide6.QtGui import QLinearGradient, QPainterPath
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        c=ColorThemeManager.instance().colors
        fill=QLinearGradient(rect.topLeft(),rect.bottomRight())
        fill.setColorAt(0,QColor(c.bg_secondary))
        tint=QColor(c.accent).darker(400)
        fill.setColorAt(.65,tint)
        fill.setColorAt(1,QColor(c.bg_primary))
        p.setBrush(fill)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect,34,34)
        clip=QPainterPath()
        clip.addRoundedRect(rect,34,34)
        p.setClipPath(clip)
        x=-rect.width()+self._flow*rect.width()*3
        beam=QLinearGradient(x-150,0,x+150,rect.height())
        beam.setColorAt(0,QColor(255,255,255,0))
        beam.setColorAt(.5,QColor(255,255,255,20))
        beam.setColorAt(1,QColor(255,255,255,0))
        p.fillRect(rect,beam)

    def set_counts(self,counts,totals):
        self.counts=dict(counts)

    def refresh_device(self,*_args):
        from src.gui.ios.device_preview import render_phone
        manager=self.window.device_manager
        source=self.window.ios_home._device_preview
        uid=manager.get_current_device_udid()
        model=manager.get_current_device_model() or ''
        image=source._image if uid and source._udid==uid else None
        self.device_render.image=image if image is not None else render_phone({},model,disconnected=not bool(uid))
        self.device_render.update()
        name=self.window.ios_home.device_combo.currentText() if uid else 'No device connected'
        self.device_name.setText(name)

    def selection(self):
        import json

        from src.controllers.preset_manager import PresetManager
        return (self.window.device_manager.get_current_device_udid(),
                json.dumps(PresetManager()._serialize(),sort_keys=True,default=str))

    def toggle_details(self):
        self.details.setVisible(self.details.isHidden())
        self.disclosure.setText('Details ▴' if self.details.isVisible() else 'Details ▾')
        self.cache_update.setVisible(self.details.isVisible() and self.window._backup_cache_enabled())

    def update_cache(self):
        self.hide()
        self.window._run_cache_update()
        if not self.window.apply_in_progress:
            self.open()

    def readiness_valid(self):
        return (self._readiness_state=='ready'
                and self._readiness_uid==self.window.device_manager.get_current_device_udid())

    def stop_readiness(self):
        self._pending_confirm=False
        worker=self._readiness_worker
        if worker is not None and worker.isRunning():
            worker.cancel()

    def poll_readiness(self,force=False):
        import time
        if (self.window.apply_in_progress or getattr(self.window,'_cache_restore_in_progress',False)
                or self._progress_mode):
            return
        uid=self.window.device_manager.get_current_device_udid() or ''
        if not uid:
            self._readiness_state='disconnected'
            self._readiness_uid=''
            self.checks.setText('Connect and unlock your device to continue.')
            self.refresh_device()
            self.update_confirm()
            return
        if uid!=self._readiness_uid:
            self._readiness_state='checking'
            self._readiness_checked=0.0
            self._readiness_uid=uid
            self._readiness_attempts=0
            self.refresh_device()
        if self._readiness_worker is not None:
            return
        if not force:
            if self._readiness_state=='ready' or self._readiness_attempts>=3:
                return
            delay=(4,8,15)[min(self._readiness_attempts,2)]
            if time.monotonic()-self._readiness_checked<delay:
                return
        else:
            self._readiness_attempts=0
        from .readiness import DeviceReadiness
        worker=DeviceReadiness(uid)
        self._readiness_worker=worker
        worker.result.connect(self.accept_readiness)
        worker.finished.connect(self.readiness_finished)
        self.window.destroyed.connect(worker.cancel)
        QApplication.instance().aboutToQuit.connect(worker.cancel)
        if self._readiness_state=='checking':
            self.checks.setText('Checking connection…')
        self.update_confirm()
        worker.start()

    def readiness_finished(self):
        if self.sender() is self._readiness_worker:
            self._readiness_worker=None

    def accept_readiness(self,uid,state,message):
        import time
        if uid!=self.window.device_manager.get_current_device_udid():
            return
        self._readiness_uid=uid
        self._readiness_state=state
        if state not in ('ready','checking'):
            self.window.liquid.notifications.add('Device needs attention',message)
        self._readiness_checked=time.monotonic()
        self._readiness_attempts+=1
        self.retry_connection.setVisible(state!='ready')
        self.checks.setText(message)
        self.refresh_device()
        self.update_confirm()
        if self._pending_confirm:
            self._pending_confirm=False
            if state=='ready' and self.isVisible():
                self.confirm(verified=True)

    def update_confirm(self):
        self.confirm_button.setEnabled(self.total>0 and self.readiness_valid()
            and not self._pending_confirm and (self.ack.isHidden() or self.ack.isChecked()))

    def open(self):
        from src.controllers.risk_assessment import RiskLevel
        from src.controllers.tweak_conflicts import current_conflicts
        window=self.window
        self._progress_mode=False
        self.progress_area.hide()
        self.review_area.show()
        self.refresh_device()
        lines,self.total=window._build_apply_summary()
        window.ios_home.device_details._update_selection_counts()
        conflicts=current_conflicts(window.device_manager)
        report=window._risk_report()
        risk=report is not None and report.level==RiskLevel.HIGH
        self.summary.setText(f"{self.counts['tweaks']} tweaks · {self.counts['daemons']} daemons")
        self.conflicts.setText(f'{len(conflicts)} conflicts — review Details before continuing.' if conflicts else 'No conflicting preferences found.')
        details=[item.description() for item in conflicts]
        if report is not None:
            details.extend(factor.text for factor in report.sorted_factors())
        details.extend(lines)
        for callback in (window._storage_warning_line,window._storage_estimate_line,
                         window._battery_warning_line,window._compatibility_warning_line):
            value=callback()
            if value:
                details.append(value)
        if window._backup_cache_enabled():
            details.append(window._backup_cache_summary_line())
        details.append(window._time_estimate_line(self.total))
        self.details.setText('\n\n'.join(value for value in details if value))
        self.details.hide()
        self.cache_update.hide()
        self.disclosure.setText('Details ▾')
        self.ack.setChecked(False)
        self.ack.setVisible(bool(conflicts) or risk)
        if not self.total:
            self.note.setText('No changes selected. Choose a tweak or daemon first.')
        elif window.device_manager.get_current_device_partially_supported():
            self.note.setText('After confirmation: protective backup → apply → restore. Nothing starts before you confirm.')
        else:
            self.note.setText('Selected changes are applied only after you confirm.')
        self._selection=self.selection()
        self.update_confirm()
        from .placement import reveal_sheet
        anchor=window.ios_home.apply_btn
        from PySide6.QtCore import QPoint
        y=anchor.mapTo(window,QPoint()).y()
        if y<330:
            bar=window.ios_home._scroll.verticalScrollBar()
            bar.setValue(max(0,bar.value()-(330-y)))
        reveal_sheet(self,window,anchor,self.panel_size())
        self.poll_readiness(force=True)
        self.update_confirm()

    def panel_size(self):
        button=self.window.ios_home.apply_btn
        return QSize(min(button.width(),self.window.width()-32),min(460,self.window.height()-100))

    def reposition(self):
        if self._progress_mode:
            dock=self.window.bottom_navigation
            self.setGeometry(panel_rect(self.window,dock,
                QSize(min(600,self.window.width()-32),min(500,self.window.height()-100)),dock.edge))
        else:
            from .placement import sheet_rect
            self.setGeometry(sheet_rect(self.window,self.window.ios_home.apply_btn,self.panel_size()))

    def activate(self):
        if self.window.apply_in_progress or getattr(self.window,'_cache_restore_in_progress',False):
            self.open_progress()
            return
        if getattr(self.window,'_operation_result_visible',False):
            # A finished apply/reset leaves its result card up. Pressing Apply
            # Changes again starts a new review instead of reopening that result.
            self.window.dismiss_operation_result()
            self.open()
        elif self.isVisible():
            self.confirm()
        else:
            self.open()

    def confirm(self,_checked=False,verified=False):
        if not self.total or not self.ack.isHidden() and not self.ack.isChecked():
            return
        if self.selection()!=self._selection:
            self.open()
            self.note.setText('The selection or device changed. Please review it again.')
            return
        if not verified:
            self._pending_confirm=True
            self.checks.setText('Confirming connection…')
            self.update_confirm()
            self.poll_readiness(force=True)
            return
        if not self.readiness_valid():
            return
        self._confirming=True
        try:
            self.window.apply_tweaks_clicked()
        finally:
            self._confirming=False
        if not self.window.apply_in_progress:
            return
        self.hide()
        self.window.show_ios_page(6)
        dock=self.window.bottom_navigation
        dock.update_operation()

    def open_progress(self):
        self.hide()
        self.window.show_ios_page(6)

    def confirm_review(self):
        return (self._confirming and self.isVisible() and self.total>0 and self.readiness_valid()
                and self.selection()==self._selection
                and (self.ack.isHidden() or self.ack.isChecked()))

    def _set_action_label(self, text):
        button=self.window.ios_home.apply_btn
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(text)

    def showEvent(self,event):
        self._set_action_label('Confirm Changes')
        self.update_confirm()
        super().showEvent(event)

    def hideEvent(self,event):
        self.stop_readiness()
        self._set_action_label('Apply Changes')
        if not self.window.apply_in_progress:
            self.window.ios_home.apply_btn.setEnabled(True)
        super().hideEvent(event)

    def refresh(self):
        busy=self.window.apply_in_progress or getattr(self.window,'_cache_restore_in_progress',False)
        self.window.bottom_navigation.update_operation()
        if not busy and self.isVisible() and not self._progress_mode:
            self.poll_readiness()
        if busy and self.isVisible() and not self._progress_mode:
            self.hide()
        self.was_busy=busy
