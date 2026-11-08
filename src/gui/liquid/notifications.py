import math
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from awesomeui.liquid.controls import GlassPanel, LiquidButton
from awesomeui.liquid.placement import reveal_panel
from src.gui.theme import ColorThemeManager, theme_pixmap


class BellButton(LiquidButton):
    def __init__(self,parent=None):
        super().__init__('',parent)
        self.setProperty('dockReveal',0.0)
        self.setProperty('dockCollapsedWidth',52)
        self._ring_progress=1.0
        self._ring=QVariantAnimation(self)
        self._ring.setDuration(720)
        self._ring.setStartValue(0.0)
        self._ring.setEndValue(1.0)
        self._ring.setEasingCurve(QEasingCurve.Linear)
        self._ring.valueChanged.connect(self._ring_step)

    def _ring_step(self,value):
        self._ring_progress=float(value)
        if QApplication.instance().property('liquid_reduce_motion'):
            self._ring.stop()
            self._ring_progress=1.0
        self.update()

    def enterEvent(self,event):
        super().enterEvent(event)
        if not QApplication.instance().property('liquid_reduce_motion'):
            self._ring.stop()
            self._ring_progress=0.0
            self._ring.start()

    def hideEvent(self,event):
        self._ring.stop()
        self._ring_progress=1.0
        super().hideEvent(event)

    def paint_icon(self,painter,rect):
        t=self._ring_progress
        angle=24*math.sin(t*math.tau*3)*(1-t)**2
        jump=-6*math.sin(math.pi*min(1.0,t/.7))**2
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(rect.center().x(),rect.top()+4+jump)
        painter.rotate(angle)
        super().paint_icon(painter,QRectF(-rect.width()/2,-4,rect.width(),rect.height()))
        painter.restore()


class GearButton(LiquidButton):
    def __init__(self,parent=None):
        super().__init__('',parent)
        self.setProperty('dockReveal',0.0)
        self.setProperty('dockCollapsedWidth',52)
        self._spin_progress=1.0
        self._spin=QVariantAnimation(self)
        self._spin.setDuration(650)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(1.0)
        self._spin.setEasingCurve(QEasingCurve.OutCubic)
        self._spin.valueChanged.connect(self._spin_step)

    def _spin_step(self,value):
        self._spin_progress=float(value)
        if QApplication.instance().property('liquid_reduce_motion'):
            self._spin.stop()
            self._spin_progress=1.0
        self.update()

    def enterEvent(self,event):
        super().enterEvent(event)
        if not QApplication.instance().property('liquid_reduce_motion'):
            self._spin.stop()
            self._spin_progress=0.0
            self._spin.start()

    def hideEvent(self,event):
        self._spin.stop()
        self._spin_progress=1.0
        super().hideEvent(event)

    def paint_icon(self,painter,rect):
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.translate(rect.center())
        painter.rotate(360*self._spin_progress if self._spin_progress<1 else 0)
        super().paint_icon(painter,QRectF(-rect.width()/2,-rect.height()/2,rect.width(),rect.height()))
        painter.restore()


class Notifications(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        self.entries=[]
        self.unread=0
        self.bell_frame=GlassPanel(window)
        self.settings_frame=GlassPanel(window)
        settings=self.main_settings=GearButton(self.settings_frame)
        settings.setProperty('dockItem',True)
        settings.setText('Settings')
        settings.setAccessibleName('Application settings')
        settings.setToolTip('')
        settings.setIcon(QIcon(theme_pixmap(':/icon/gear.svg',ColorThemeManager.instance().colors.text_primary,116)))
        settings.clicked.connect(lambda:window.bottom_navigation.navigate(4))
        settings.setGeometry(0,0,52,48)
        settings.setIconSize(QSize(29,29))
        settings.show()
        self.bell=BellButton(self.bell_frame)
        self.bell.setGeometry(0,0,52,48)
        self.bell.setIconSize(QSize(25,25))
        self.bell.setIcon(QIcon(str(Path(__file__).parent/'assets/bell.svg')))
        self.bell.setAccessibleName('Notifications')
        self.bell.setText('Notifications')
        self.bell.setToolTip('')
        self.bell.setProperty('dockItem',True)
        self.bell.clicked.connect(self.toggle)
        self.indicator=QLabel(self.bell)
        self.indicator.setFixedSize(10,10)
        self.indicator.move(35,7)
        self.indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.indicator.setStyleSheet('background:#ff453a;border:1px solid #ffaaa5;border-radius:5px;')
        self.indicator.hide()
        self.panel=GlassPanel(window)
        outer=QVBoxLayout(self.panel)
        outer.setContentsMargins(4,4,4,4)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('background:transparent;border:none;')
        body=QWidget()
        self.layout=QVBoxLayout(body)
        self.layout.setContentsMargins(14,14,14,14)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.panel.hide()
        self._corner_motions={}
        for button in (self.bell,self.main_settings):
            motion=QVariantAnimation(self)
            motion.setEasingCurve(QEasingCurve.OutCubic)
            motion.valueChanged.connect(lambda value,b=button:self._corner_step(b,value))
            self._corner_motions[button]=motion
        QApplication.instance().installEventFilter(self)
        ColorThemeManager.instance().theme_changed.connect(self.retheme)
        self.rebuild()

    def retheme(self):
        self.main_settings.setIcon(QIcon(theme_pixmap(':/icon/gear.svg',ColorThemeManager.instance().colors.text_primary,116)))
        self.bell.setIcon(QIcon(str(Path(__file__).parent/'assets/bell.svg')))
        self.rebuild()

    def add(self,title,message,action=None):
        entry=(title,str(message),action)
        if any(item[:2]==entry[:2] for item in self.entries):
            return
        self.entries.insert(0,entry)
        self.entries=self.entries[:30]
        self.unread+=1
        self.indicator.show()
        self.indicator.raise_()
        self.bell.setAccessibleDescription(f'{self.unread} unread notifications')
        self.rebuild()

    def rebuild(self):
        while self.layout.count():
            item=self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        heading=QLabel('Notifications')
        heading.setStyleSheet('font-size:17px;font-weight:600;background:transparent;')
        self.layout.addWidget(heading)
        for title,message,action in self.entries[:4]:
            label=QLabel(title+'\n'+message[:450])
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setStyleSheet('background:rgba(255,255,255,8);padding:9px;border-radius:10px;')
            self.layout.addWidget(label)
            if action:
                button=LiquidButton('View details')
                button.clicked.connect(lambda _,callback=action:callback())
                self.layout.addWidget(button)
        if not self.entries:
            self.layout.addWidget(QLabel('You’re all caught up.'))
        else:
            clear=LiquidButton('Clear notifications')
            clear.clicked.connect(self.clear)
            self.layout.addWidget(clear)

    def clear(self):
        self.entries.clear()
        self.unread=0
        self.indicator.hide()
        self.bell.setAccessibleDescription('No unread notifications')
        self.panel.hide()
        self.rebuild()

    def _corner_step(self,button,value):
        button.setProperty('dockReveal',float(value))
        self.position()
        button.update()

    def _reveal_corner(self,button,expanded):
        motion=self._corner_motions[button]
        motion.stop()
        motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else 240)
        motion.setStartValue(float(button.property('dockReveal')))
        motion.setEndValue(1.0 if expanded else 0.0)
        motion.start()

    def position(self):
        dock=self.window.bottom_navigation
        widths=[round(52+(button.fontMetrics().horizontalAdvance(button.text())+14)*float(button.property('dockReveal')))
                for button in (self.bell,self.main_settings)]
        pair_width=sum(widths)+8
        x=max(8,self.window.width()-pair_width-16)
        y=16 if dock.edge in ('top','left','right') else max(8,self.window.height()-64)
        if dock.edge=='right':
            x=16
        self.bell_frame.setGeometry(x,y,widths[0],48)
        self.bell.setGeometry(self.bell_frame.rect())
        self.settings_frame.setGeometry(x+widths[0]+8,y,widths[1],48)
        self.main_settings.setGeometry(self.settings_frame.rect())
        self.indicator.move(round(35-10*float(self.bell.property('dockReveal'))),7)
        self.bell_frame.show()
        self.settings_frame.show()
        self.bell_frame.raise_()
        self.settings_frame.raise_()

    def toggle(self):
        if self.panel.isVisible():
            self.panel.hide()
            return
        self.unread=0
        self.indicator.hide()
        self.bell.setAccessibleDescription('No unread notifications')
        height=min(540,self.layout.sizeHint().height()+20,self.window.height()-32)
        edge='bottom' if self.window.bottom_navigation.edge=='bottom' else 'top'
        reveal_panel(self.panel,self.window,self.bell,QSize(340,height),edge)

    def eventFilter(self,target,event):
        if target is self.window and event.type()==QEvent.Hide:
            for button,motion in self._corner_motions.items():
                motion.stop()
                button.setProperty('dockReveal',0.0)
        if target in (self.bell,self.main_settings):
            if event.type()==QEvent.ToolTip:
                return True
            if event.type() in (QEvent.Enter,QEvent.FocusIn):
                self._reveal_corner(target,True)
            elif event.type() in (QEvent.Leave,QEvent.FocusOut):
                self._reveal_corner(target,False)
        if self.panel.isVisible():
            if event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:
                self.panel.hide()
                return True
            if event.type()==QEvent.MouseButtonPress and hasattr(target,'parentWidget'):
                if target is not self.bell and target is not self.panel and not self.panel.isAncestorOf(target):
                    self.panel.hide()
        return False
