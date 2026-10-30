import math
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, QMimeData, Signal, QVariantAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QLinearGradient, QRadialGradient, QDrag, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QPushButton, QWidget, QApplication, QStyleOptionButton, QStyle, QSlider, QCheckBox, QLabel
from awesomeui.controls import IOSSwitch as BaseSwitch
from src.gui.theme import ColorThemeManager
from .motion import animate


class GlassPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._frost = QPixmap()
        self.setObjectName('liquidPanel')
        self.setStyleSheet('QFrame#liquidPanel { background:transparent; border:none; }')

    def frost(self, bounds):
        if self.parentWidget() is None:
            return
        snapshot = self.parentWidget().grab(bounds).toImage()
        small = snapshot.scaled(max(1,bounds.width()//12),max(1,bounds.height()//12),
                                Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
        self._frost = QPixmap.fromImage(small.scaled(bounds.size(),Qt.IgnoreAspectRatio,Qt.SmoothTransformation))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        c = ColorThemeManager.instance().colors
        if not self._frost.isNull():
            clip = QPainterPath()
            clip.addRoundedRect(rect,24,24)
            p.save()
            p.setClipPath(clip)
            p.drawPixmap(self.rect(),self._frost)
            p.restore()
        fill = QColor(c.bg_secondary)
        fill.setAlpha(218 if not self._frost.isNull() else 238)
        p.setBrush(fill)
        edge = QLinearGradient(rect.topLeft(), rect.bottomRight())
        edge.setColorAt(0, QColor(255, 255, 255, 95))
        edge.setColorAt(.48, QColor(255, 255, 255, 16))
        edge.setColorAt(1, QColor(255, 255, 255, 42))
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(rect, 24, 24)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 21, 21)


def paint_dock_glass(p,shape,subtle=False):
    c=ColorThemeManager.instance().colors
    rect=shape.boundingRect()
    tint=QColor(c.bg_secondary)
    tint.setAlpha(225 if subtle else 195)
    p.fillPath(shape,tint)
    sheen=QLinearGradient(rect.topLeft(),rect.bottomLeft())
    sheen.setColorAt(0,QColor(255,255,255,24 if subtle else 42))
    sheen.setColorAt(.38,QColor(255,255,255,9))
    sheen.setColorAt(.65,QColor(255,255,255,2))
    sheen.setColorAt(1,QColor(255,255,255,8 if subtle else 18))
    p.fillPath(shape,sheen)
    rim=QLinearGradient(rect.topLeft(),rect.bottomRight())
    rim.setColorAt(0,QColor(255,255,255,78 if subtle else 140))
    rim.setColorAt(.35,QColor(255,255,255,30))
    rim.setColorAt(.7,QColor(255,255,255,12))
    rim.setColorAt(1,QColor(255,255,255,38 if subtle else 80))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(rim,1))
    p.drawPath(shape)


class LiquidSwitch(BaseSwitch):
    def __init__(self,checked=False,parent=None):
        super().__init__(checked,parent)
        from .sounds import UiSounds
        self.clicked.connect(UiSounds.instance().play_toggle)

    def setChecked(self, checked):
        super().setChecked(checked)
        surface=getattr(self,'_selection_surface',None)
        if surface is not None:
            surface.sync()

    ANIM_MS = 280

    def _animate_to(self, target):
        if getattr(self,'_selection_surface',None) is not None:
            self._anim.stop()
            self._set_progress(float(target))
            return
        self._anim.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else self.ANIM_MS)
        super()._animate_to(target)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .4)
        amount = self._progress
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height()/2, rect.height()/2)
        c=ColorThemeManager.instance().colors
        off=QColor(c.bg_tertiary)
        on=QColor(c.accent)
        tint=QColor(round(off.red()+(on.red()-off.red())*amount),
                    round(off.green()+(on.green()-off.green())*amount),
                    round(off.blue()+(on.blue()-off.blue())*amount),210)
        p.fillPath(path,tint)
        sheen=QLinearGradient(rect.topLeft(),rect.bottomLeft())
        sheen.setColorAt(0,QColor(255,255,255,48))
        sheen.setColorAt(.5,QColor(255,255,255,5))
        sheen.setColorAt(1,QColor(0,0,0,22))
        p.fillPath(path,sheen)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255,255,255,65),1))
        p.drawPath(path)
        knob=self.KNOB_SIZE-2
        inset=(self.height()-knob)/2
        x=inset+(self.width()-knob-2*inset)*amount
        thumb=QRectF(x,inset,knob,knob)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0,0,0,40))
        p.drawEllipse(thumb.translated(0,1.5))
        glass=QLinearGradient(thumb.topLeft(),thumb.bottomRight())
        glass.setColorAt(0,QColor(255,255,255,250))
        glass.setColorAt(.45,QColor(244,249,255,225))
        glass.setColorAt(1,QColor(208,222,239,200))
        p.setBrush(glass)
        p.setPen(QPen(QColor(255,255,255,220),1))
        p.drawEllipse(thumb)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255,255,255,180),1))
        p.drawArc(thumb.adjusted(3,2,-3,-3),35*16,110*16)
        if self.hasFocus():
            p.setPen(QPen(QColor(c.text_primary),1))
            p.drawRoundedRect(rect.adjusted(2,2,-2,-2),12,12)


class LiquidButton(QPushButton):
    reorderRequested = Signal(str, str)
    dragStarted = Signal(str)
    dragFinished = Signal(str, bool)

    def __init__(self, text='', parent=None, *, key=''):
        super().__init__(text, parent)
        self.key = key
        self.hover = 0.0
        self.wave = 0.0
        self._dock_pointer = QPointF(.5,.5)
        self.setMouseTracking(True)
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(360)
        self._hover_animation.setEasingCurve(QEasingCurve.OutBack)
        self._hover_animation.valueChanged.connect(self._set_hover)
        self._press = None
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setIconSize(QSize(23,23))
        self.setAcceptDrops(bool(key))
        self.setObjectName('liquidButton')
        self.setStyleSheet('QPushButton#liquidButton { background:transparent; border:none; padding:10px 14px; font-weight:600; }')

    def set_wave(self,value):
        self.wave=value
        self.update()

    def _set_hover(self, value):
        self.hover = float(value)
        self.update()

    def _hover_to(self, target):
        self._hover_animation.setDuration(0 if QApplication.instance().property("liquid_reduce_motion") else 220)
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self.hover)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def enterEvent(self, event):
        if self.property('dockItem'):
            self._track_dock_pointer(event.position())
        self._hover_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def _track_dock_pointer(self,position):
        self._dock_pointer=QPointF(max(0,min(1,position.x()/max(1,self.width()))),
                                  max(0,min(1,position.y()/max(1,self.height()))))
        self.update()

    def mouseMoveEvent(self, event):
        if self.property('dockItem'):
            self._track_dock_pointer(event.position())
        if self.key and event.buttons() & Qt.LeftButton and self._press is not None and (event.position().toPoint()-self._press).manhattanLength()>12:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData('application/x-goldennugget-dock', self.key.encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(self._press)
            self._press = None
            self.setProperty('dragGhost',True)
            self.update()
            self.dragStarted.emit(self.key)
            try:
                result=drag.exec(Qt.MoveAction)
                self.dragFinished.emit(self.key,result==Qt.MoveAction)
            finally:
                self.setProperty('dragGhost',False)
                self.setDown(False)
                self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._press=None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-goldennugget-dock'):
            event.acceptProposedAction()

    def dropEvent(self, event):
        source = bytes(event.mimeData().data('application/x-goldennugget-dock')).decode()
        self.reorderRequested.emit(source, self.key)
        event.acceptProposedAction()

    def paint_icon(self,painter,rect):
        self.icon().paint(painter,rect.toRect())

    def paintEvent(self, event):
        if self.property('dragGhost'):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = ColorThemeManager.instance().colors
        amount=max(0.0,self.hover+self.wave)
        inset=3-2*amount
        r=QRectF(self.rect()).adjusted(inset,inset,-inset,-inset)
        selected=self.isChecked() or bool(self.property('selected'))
        fill=QColor(c.accent) if selected else QColor(255,255,255)
        dock=bool(self.property("dockItem"))
        fill.setAlpha(min(100, round(45 if selected else (0 if dock else 7)+16*amount)))
        if dock and not self.property('menuItem') and selected:
            fill=QColor(255,255,255,24)
        if self.property('solidSurface'):
            fill=QColor(c.bg_secondary)
            fill.setAlpha(255)
        p.setBrush(fill)
        edge=QLinearGradient(r.topLeft(),r.bottomRight())
        edge.setColorAt(0,QColor(255,255,255,round(35+60*min(1,amount))))
        edge.setColorAt(.5,QColor(255,255,255,12))
        edge.setColorAt(1,QColor(255,255,255,35))
        p.setPen(Qt.NoPen if dock else QPen(edge,1))
        p.drawRoundedRect(r,18,18)
        if dock and not self.property('menuItem') and selected:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255,255,255,38),1))
            p.drawRoundedRect(r,18,18)
        hover=max(0,min(1,self.hover))
        if dock and hover>0:
            pointer=QPointF(self._dock_pointer.x()*self.width(),self._dock_pointer.y()*self.height())
            shape=QPainterPath()
            glass=r.adjusted(-1.5*hover*(1-self._dock_pointer.x()),
                             -1.5*hover*(1-self._dock_pointer.y()),
                             1.5*hover*self._dock_pointer.x(),
                             1.5*hover*self._dock_pointer.y())
            shape.addRoundedRect(glass,18,18)
            radius=max(32,min(85,self.width()*.65))
            glow=QRadialGradient(pointer,radius)
            light=QColor(255,255,255,round(52*hover))
            glow.setColorAt(0,light)
            tint=QColor(c.text_primary) if not self.property('menuItem') else QColor(c.accent)
            tint.setAlpha(round(18*hover))
            glow.setColorAt(.48,tint)
            glow.setColorAt(1,QColor(0,0,0,0))
            p.fillPath(shape,glow)
            rim=QRadialGradient(pointer,radius)
            rim.setColorAt(0,QColor(255,255,255,round(135*hover)))
            rim.setColorAt(1,QColor(255,255,255,0))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(rim,1))
            p.drawPath(shape)
        p.save()
        follow=hover if dock and not QApplication.instance().property('liquid_reduce_motion') else 0
        p.translate(self.width()/2+(self._dock_pointer.x()-.5)*3*follow,
                    self.height()/2-2*amount+(self._dock_pointer.y()-.5)*3*follow)
        scale=1+.035*amount-(.025 if self.isDown()else 0)
        p.scale(scale,scale)
        p.translate(-self.width()/2,-self.height()/2)
        if self.property('dockReveal') is not None and not self.property('iconOnly'):
            reveal=float(self.property('dockReveal'))
            size=self.iconSize().width()
            collapsed=float(self.property('dockCollapsedWidth') or 38)
            x=round((collapsed-size)/2+(12-(collapsed-size)/2)*reveal)
            self.paint_icon(p,QRectF(x,(self.height()-size)//2,size,size))
            left=max(38,size+21)
            p.setClipRect(QRectF(left,0,max(0,min(self.width()-left-5,self.width()-collapsed)),self.height()))
            p.setFont(self.font())
            p.setPen(QColor(c.text_primary))
            p.drawText(QRectF(left,0,max(0,self.width()-left-5),self.height()),Qt.AlignLeft|Qt.AlignVCenter,self.text())
        elif self.property('iconOnly'):
            size=self.iconSize()
            self.paint_icon(p,QRectF((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height()))
        elif self.property('menuItem'):
            left=14
            if not self.icon().isNull():
                icon_size=self.iconSize().width()
                self.icon().paint(p,14,(self.height()-icon_size)//2,icon_size,icon_size)
                left=24+icon_size
            p.setFont(self.font())
            p.setPen(QColor(c.text_primary))
            p.drawText(QRectF(left,0,self.width()-left-30,self.height()),Qt.AlignLeft|Qt.AlignVCenter,self.text().replace('&&','&'))
        else:
            option=QStyleOptionButton()
            self.initStyleOption(option)
            self.style().drawControl(QStyle.CE_PushButtonLabel,option,p,self)
        p.restore()
        if self.property('external'):
            p.setPen(QPen(QColor(c.text_secondary),1.5))
            x,y=self.width()-18,self.height()/2-4
            p.drawLine(QPointF(x-5,y+7),QPointF(x+2,y))
            p.drawLine(QPointF(x-4,y),QPointF(x+2,y))
            p.drawLine(QPointF(x+2,y),QPointF(x+2,y+6))


class PulseOverlay(QWidget):
    def __init__(self, target, origin=None, star=False):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(target.rect())
        self.origin = origin or QPointF(target.rect().center())
        self.star = star
        self.progress = 0.0
        self.show()
        animate(self, 0.0, 1.0, self._step, duration=650 if star else 440,
                finished=self.deleteLater)

    def _step(self, value):
        self.progress = float(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 14, 14)
        p.setClipPath(path)
        color = QColor('#efc674') if self.star else QColor(ColorThemeManager.instance().colors.accent)
        color.setAlpha(round(65*(1-self.progress)))
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        radius = max(self.width(),self.height())*self.progress
        p.drawEllipse(self.origin, radius, radius)
        if self.star:
            p.save()
            p.translate(self.width()/2,self.height()/2-math.sin(self.progress*math.pi)*7)
            p.rotate(self.progress*180)
            star = QPainterPath()
            for i in range(10):
                a = -math.pi/2+i*math.pi/5
                radius = 10 if i%2==0 else 4
                point=QPointF(math.cos(a)*radius,math.sin(a)*radius)
                if i==0:
                    star.moveTo(point)
                else:
                    star.lineTo(point)
            star.closeSubpath()
            p.setOpacity(1-self.progress)
            p.setBrush(QColor('#f8d47c'))
            p.drawPath(star)
            p.restore()
            p.setPen(QPen(QColor('#f8d47c'), 1.5))
            for i in range(6):
                angle = i*math.pi/3 + self.progress*1.8
                center = self.origin+QPointF(math.cos(angle)*radius*.65, math.sin(angle)*radius*.65)
                p.drawLine(center+QPointF(-3,0),center+QPointF(3,0))
                p.drawLine(center+QPointF(0,-3),center+QPointF(0,3))


class LiquidBrand(LiquidButton):
    def __init__(self,parent=None):
        super().__init__('GoldenNugget',parent)
        self.setMinimumSize(0,0)
        self.compact=False
        self.reveal=1.0
        self.phase=0.0
        self.setAccessibleName('GoldenNugget')
        from ..slogans import launch_slogan
        self._slogan=launch_slogan()
        self.setAccessibleDescription(self._slogan)
        self.shimmer=QVariantAnimation(self)
        self.shimmer.setDuration(1800)
        self.shimmer.setStartValue(0.0)
        self.shimmer.setEndValue(1.0)
        self.shimmer.setLoopCount(-1)
        self.shimmer.valueChanged.connect(self._shimmer)
        self.logo=QPixmap(':/credits/big_nugget.png')

    def _shimmer(self,value):
        self.phase=float(value)
        self.update()

    def enterEvent(self,event):
        super().enterEvent(event)
        if not QApplication.instance().property('liquid_reduce_motion'):
            self.shimmer.start()

    def leaveEvent(self,event):
        self.shimmer.stop()
        super().leaveEvent(event)

    def hideEvent(self,event):
        self.shimmer.stop()
        self._hover_animation.stop()
        self.hover=0.0
        super().hideEvent(event)

    def paintEvent(self,event):
        from PySide6.QtGui import QFont
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)
        gradient=QLinearGradient(-self.width()+self.phase*self.width()*2,0,
                                 self.phase*self.width()*2,self.height())
        for stop,color in ((0,'#91602D'),(.35,'#C99744'),(.55,'#FFE4A0'),
                           (.8,'#C99744'),(1,'#91602D')):
            gradient.setColorAt(stop,QColor(color))
        hover=max(0.0,min(1.0,self.hover))
        if hover:
            p.setOpacity(hover*.18)
            p.setBrush(gradient)
            p.drawRoundedRect(QRectF(2,3,46,42),13,13)
            p.setOpacity(1.0)
        fitted=self.logo.size().scaled(38,38,Qt.KeepAspectRatio)
        x=(50-fitted.width())/2
        y=(48-fitted.height())/2
        p.drawPixmap(QRectF(x,y,fitted.width(),fitted.height()),self.logo,QRectF(self.logo.rect()))
        if self.compact:
            return
        p.setOpacity(self.reveal)
        title_font=QFont('Inter Variable')
        title_font.setPixelSize(15)
        title_font.setWeight(QFont.Bold)
        slogan_font=QFont('Inter Variable')
        slogan_font.setPixelSize(10)
        p.setPen(QColor('#BC8B45'))
        p.setFont(title_font)
        label=self.text() if self.text()!='GN'else 'GoldenNugget'
        title_rect=QRectF(44,5,120,22)
        slogan_rect=QRectF(44,26,120,22)
        p.drawText(title_rect,Qt.AlignVCenter,label)
        slogan_font.setPixelSize(9)
        p.setFont(slogan_font)
        p.setPen(QColor('#B08B58'))
        p.drawText(slogan_rect,Qt.AlignLeft|Qt.AlignTop|Qt.TextWordWrap,self._slogan)
        if hover:
            p.setOpacity(self.reveal*hover)
            p.setPen(QPen(gradient,1))
            for font,rect,(text,wrap) in (
                    (title_font,title_rect,(label,False)),
                    (slogan_font,slogan_rect,(self._slogan,True))):
                p.setFont(font)
                p.drawText(rect,(Qt.AlignLeft|Qt.AlignTop|Qt.TextWordWrap)
                           if wrap else Qt.AlignVCenter,text)


class ActionStretchSurface(QWidget):
    MARGIN = 36

    def __init__(self, button):
        super().__init__(button.window())
        self.button = button
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        button.destroyed.connect(self.deleteLater)

    def sync(self):
        from PySide6.QtCore import QPoint
        origin = self.button.mapTo(self.parentWidget(), QPoint())
        self.setGeometry(origin.x()-self.MARGIN, origin.y()-self.MARGIN,
                         self.button.width()+2*self.MARGIN, self.button.height()+2*self.MARGIN)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.translate(self.MARGIN, self.MARGIN)
        self.button.paint_home_action(painter)


class LiquidActionButton(LiquidButton):
    danger=False

    def __init__(self,text='',parent=None):
        super().__init__(text,parent)
        self.pointer=QPointF(.5,.5)
        self.setMouseTracking(True)
        self.pointer_motion=QVariantAnimation(self)
        self.pointer_motion.setDuration(150)
        self.pointer_motion.setEasingCurve(QEasingCurve.OutCubic)
        self.pointer_motion.valueChanged.connect(self._pointer_step)
        self._stretch_surface = None
        self._action_footer = ''
        self._scroll_bars = []
        self._scroll_hover_suspended = False
        self._scroll_pointer = None

    def showEvent(self, event):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                self.bind_scroll_area(parent)
            parent = parent.parentWidget()
        super().showEvent(event)

    def bind_scroll_area(self, scroll):
        for bar in (scroll.verticalScrollBar(), scroll.horizontalScrollBar()):
            if bar not in self._scroll_bars:
                bar.valueChanged.connect(self._cancel_scroll_hover)
                self._scroll_bars.append(bar)

    def _cancel_scroll_hover(self, *_args):
        self.pointer_motion.stop()
        self._hover_animation.stop()
        self._scroll_hover_suspended = True
        self._scroll_pointer = QCursor.pos()
        self.pointer = QPointF(.5, .5)
        self.hover = 0.0
        if self._stretch_surface is not None:
            self._stretch_surface.hide()
        self.update()

    def wheelEvent(self, event):
        self._cancel_scroll_hover()
        super().wheelEvent(event)

    def set_action_footer(self, text):
        self._action_footer = text
        self.setAccessibleDescription(text)
        self.update()
        if self._stretch_surface is not None:
            self._stretch_surface.update()

    def _set_hover(self, value):
        super()._set_hover(value)
        if self._stretch_surface is not None:
            self._stretch_surface.sync()
            if (self.hover <= 0 or self._scroll_hover_suspended
                    or QApplication.instance().property('liquid_reduce_motion')):
                self._stretch_surface.hide()
            elif self.isVisible() and self._stretch_surface.isHidden():
                self._stretch_surface.show()
                self._stretch_surface.raise_()

    def hideEvent(self, event):
        if self._stretch_surface is not None:
            self._stretch_surface.hide()
        self.pointer_motion.stop()
        self._hover_animation.stop()
        self.hover = 0.0
        super().hideEvent(event)

    def _hover_to(self, target):
        if target and self._scroll_hover_suspended:
            return
        if not self.property('homeAction'):
            return super()._hover_to(target)
        if target and not QApplication.instance().property('liquid_reduce_motion'):
            if self._stretch_surface is None:
                self._stretch_surface = ActionStretchSurface(self)
            self._stretch_surface.sync()
            self._stretch_surface.show()
            self._stretch_surface.raise_()
        self._hover_animation.stop()
        self._hover_animation.setDuration(
            0 if QApplication.instance().property('liquid_reduce_motion') else 320 if target else 250)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_animation.setStartValue(self.hover)
        self._hover_animation.setEndValue(float(target))
        self._hover_animation.start()

    def _pointer_step(self,value):
        self.pointer=QPointF(value)
        self.update()
        if self._stretch_surface is not None:
            self._stretch_surface.sync()

    def mouseMoveEvent(self,event):
        if self._scroll_hover_suspended:
            if (event.globalPosition().toPoint() == self._scroll_pointer
                    or not self.rect().contains(event.position().toPoint())):
                super().mouseMoveEvent(event)
                return
            self._scroll_hover_suspended = False
            self._hover_to(1.0)
        self.pointer_motion.stop()
        self.pointer_motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else 110)
        self.pointer_motion.setStartValue(self.pointer)
        self.pointer_motion.setEndValue(QPointF(max(0,min(1,event.position().x()/max(1,self.width()))),
                                               max(0,min(1,event.position().y()/max(1,self.height())))))
        self.pointer_motion.start()
        super().mouseMoveEvent(event)

    def paint_home_action(self, painter=None):
        from PySide6.QtGui import QFont, QRadialGradient
        c=ColorThemeManager.instance().colors
        p=painter if painter is not None else QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .4)
        hover=max(0,min(1,self.hover)) if self.isEnabled() else 0
        rect=QRectF(self.rect()).adjusted(4,4,-4,-4)
        pointer=QPointF(self.pointer.x()*self.width(),self.pointer.y()*self.height())
        accent=QColor('#ec748b') if self.danger else QColor(c.accent)
        radius=min(90,max(34,self.width()*.18))
        shape=QPainterPath()
        corner=15
        def side(start,end,normal):
            dx,dy=end.x()-start.x(),end.y()-start.y()
            length=math.hypot(dx,dy)
            if length<=0:
                return
            ux,uy=dx/length,dy/length
            center=max(0,min(length,(pointer.x()-start.x())*ux+(pointer.y()-start.y())*uy))
            reach=min(radius,length/2)
            center=max(reach,min(length-reach,center))
            if reach<1 or hover<=0:
                shape.lineTo(end)
                return
            distance=abs((pointer.x()-start.x())*normal.x()+(pointer.y()-start.y())*normal.y())
            influence=max(0.0,1-distance/24)**2
            bulge=32*hover*influence if painter is not None else 0
            before=start+QPointF(ux*(center-reach),uy*(center-reach))
            peak=start+QPointF(ux*center,uy*center)+normal*bulge
            after=start+QPointF(ux*(center+reach),uy*(center+reach))
            tangent=QPointF(ux*reach*.55,uy*reach*.55)
            shape.lineTo(before)
            shape.cubicTo(before+tangent,peak-tangent,peak)
            shape.cubicTo(peak+tangent,after-tangent,after)
            shape.lineTo(end)
        shape.moveTo(rect.left()+corner,rect.top())
        side(QPointF(rect.left()+corner,rect.top()),QPointF(rect.right()-corner,rect.top()),QPointF(0,-1))
        shape.quadTo(rect.right(),rect.top(),rect.right(),rect.top()+corner)
        side(QPointF(rect.right(),rect.top()+corner),QPointF(rect.right(),rect.bottom()-corner),QPointF(1,0))
        shape.quadTo(rect.right(),rect.bottom(),rect.right()-corner,rect.bottom())
        side(QPointF(rect.right()-corner,rect.bottom()),QPointF(rect.left()+corner,rect.bottom()),QPointF(0,1))
        shape.quadTo(rect.left(),rect.bottom(),rect.left(),rect.bottom()-corner)
        side(QPointF(rect.left(),rect.bottom()-corner),QPointF(rect.left(),rect.top()+corner),QPointF(-1,0))
        shape.quadTo(rect.left(),rect.top(),rect.left()+corner,rect.top())
        shape.closeSubpath()
        p.fillPath(shape,QColor(c.bg_secondary))
        fill=QColor(accent)
        fill.setAlpha(12+round(12*hover))
        p.fillPath(shape,fill)
        glow=QRadialGradient(pointer,radius)
        bright=QColor(accent)
        bright.setAlpha(round(45*hover))
        glow.setColorAt(0,bright)
        glow.setColorAt(1,QColor(0,0,0,0))
        p.fillPath(shape,glow)
        edge=QRadialGradient(pointer,radius)
        bright.setAlpha(round(190*hover))
        edge.setColorAt(0,bright)
        edge.setColorAt(1,QColor(255,255,255,24))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(edge,1.2))
        p.drawPath(shape)
        p.setPen(QColor(c.text_primary))
        p.setFont(QFont('Inter Variable',12,QFont.DemiBold))
        from PySide6.QtGui import QFontMetricsF
        from src.gui.theme import theme_pixmap
        title_rect=QRectF(rect)
        if self._action_footer:
            title_rect.setHeight(22)
        title_rect.translate(0,1 if self.isDown() else 0)
        icon_path=self.property('actionIcon')
        icon_size=18 if icon_path else 0
        icon_only=bool(self.property('iconOnlyAction'))
        gap=7 if icon_path and not icon_only else 0
        text_width=max(0,title_rect.width()-icon_size-gap-20)
        title='' if icon_only else QFontMetricsF(p.font()).elidedText(self.text(),Qt.ElideRight,int(text_width))
        group_width=QFontMetricsF(p.font()).horizontalAdvance(title)+icon_size+gap
        left=title_rect.center().x()-group_width/2
        if icon_path:
            key=(icon_path,c.text_primary,self.devicePixelRatioF())
            if getattr(self,'_action_icon_key',None)!=key:
                self._action_icon_key=key
                self._action_icon=theme_pixmap(icon_path,c.text_primary,icon_size,self.devicePixelRatioF())
            p.drawPixmap(QRectF(left,title_rect.center().y()-icon_size/2,icon_size,icon_size),
                         self._action_icon,QRectF(self._action_icon.rect()))
        p.drawText(QRectF(left+icon_size+gap,title_rect.top(),group_width-icon_size-gap,title_rect.height()),
                   Qt.AlignVCenter | Qt.AlignLeft,title)
        if self._action_footer:
            font=QFont('Inter Variable')
            font.setPixelSize(11)
            p.setFont(font)
            p.setPen(QColor(c.text_secondary))
            footer_rect=QRectF(rect.left()+10,rect.bottom()-14,rect.width()-20,12)
            footer=QFontMetricsF(font).elidedText(self._action_footer,Qt.ElideRight,int(footer_rect.width()))
            p.drawText(footer_rect,Qt.AlignCenter,footer)

    def paintEvent(self,event):
        if self.property("homeAction"):
            if self._stretch_surface is not None and self._stretch_surface.isVisible():
                return
            self.paint_home_action()
            return
        from PySide6.QtGui import QFont, QRadialGradient
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .4)
        r=QRectF(self.rect()).adjusted(1,1,-1,-1)
        base=QColor('#9d3447') if self.danger else QColor(ColorThemeManager.instance().colors.accent)
        fill=QLinearGradient(r.topLeft(),r.bottomRight())
        fill.setColorAt(0,base.darker(145))
        fill.setColorAt(.55,base.darker(110))
        fill.setColorAt(1,base.darker(165))
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r,17,17)
        light=QRadialGradient(QPointF(r.left()+self.pointer.x()*r.width(),r.top()),max(90,r.width()*.42))
        light.setColorAt(0,QColor(255,255,255,round(12+25*self.hover)))
        light.setColorAt(1,QColor(255,255,255,0))
        p.setBrush(light)
        p.drawRoundedRect(r,17,17)
        p.setPen(QColor('#faf8ff'))
        p.setFont(QFont('Inter Variable',12,QFont.DemiBold))
        p.drawText(r.adjusted(12,0,-12,0),Qt.AlignCenter,self.text().replace('&',''))
        if self.hasFocus():
            p.setPen(QPen(QColor(255,255,255,95),1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(4,4,-4,-4),13,13)


class LiquidDangerButton(LiquidActionButton):
    danger=True


class MagnifyingArtwork(QLabel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.amount=0.0
        self.focus=QPointF(.5,.5)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self,event):
        image=self.pixmap()
        if image is None or image.isNull():
            return
        p=QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        amount=0 if QApplication.instance().property('liquid_reduce_motion') else self.amount
        center=QPointF(self.width()/2,self.height()/2)
        p.translate(center)
        scale=1+.025*amount
        p.scale(scale,scale)
        p.translate(-center)
        p.drawPixmap(self.rect(),image)
        if self.amount>0:
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            p.setOpacity(.12*self.amount)
            p.drawPixmap(self.rect(),image)


class GlassCheckBox(QCheckBox):
    def __init__(self,text='',parent=None):
        super().__init__(text,parent)
        from .sounds import UiSounds
        self.clicked.connect(UiSounds.instance().play_toggle)
        self.amount=0.0
        self.motion=QVariantAnimation(self)
        self.motion.setDuration(180)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.motion.valueChanged.connect(self.step)
        self.toggled.connect(self.transition)
        self.setMinimumHeight(32)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text())+56,32)

    def step(self,value):
        self.amount=float(value)
        self.update()

    def transition(self,checked):
        self.motion.stop()
        self.motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else 180)
        self.motion.setStartValue(self.amount)
        self.motion.setEndValue(1.0 if checked else 0.0)
        self.motion.start()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c=ColorThemeManager.instance().colors
        track=QRectF(1,(self.height()-22)/2,38,22)
        fill=QColor(c.accent if self.isChecked() else c.bg_tertiary)
        p.setBrush(fill)
        p.setPen(QPen(QColor(255,255,255,65),1))
        p.drawRoundedRect(track,11,11)
        p.setBrush(QColor('#fafafa'))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(track.x()+3+16*self.amount,track.y()+3,16,16))
        p.setPen(QColor(c.text_primary))
        p.setFont(self.font())
        p.drawText(QRectF(50,0,self.width()-50,self.height()),Qt.AlignVCenter,self.text())
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(c.accent),1))
            p.drawRoundedRect(track.adjusted(-1,-1,1,1),12,12)


class LiquidCard(GlassPanel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.hover=0.0
        self._glass_pointer=QPointF(.5,.5)
        self.motion=QVariantAnimation(self)
        self.motion.setDuration(280)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.motion.valueChanged.connect(self.step)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def hideEvent(self,event):
        self.motion.stop()
        pointer_motion=getattr(self,'_pointer_motion',None)
        if pointer_motion is not None:
            pointer_motion.stop()
        self.step(0.0)
        super().hideEvent(event)

    def _retheme(self):
        self.update()

    def step(self,value):
        self.hover=float(value)
        artwork=getattr(self,'_home_artwork_motion',None)
        if artwork is not None:
            artwork.amount=self.hover
            artwork.update()
        self.update()

    def enterEvent(self,event):
        if self._scroll_active():
            self._scroll_hover_deferred = True
            return super().enterEvent(event)
        if self.property("liquidControlCard") or self.__class__.__name__=="_TileCard":
            self.shift(1.0)
        super().enterEvent(event)

    def mouseMoveEvent(self,event):
        if self._scroll_active():
            self._scroll_hover_deferred = True
            return super().mouseMoveEvent(event)
        if getattr(self, '_scroll_hover_deferred', False):
            self._scroll_hover_deferred = False
            self.shift(1.0)
        target=QPointF(max(0,min(1,event.position().x()/max(1,self.width()))),
                       max(0,min(1,event.position().y()/max(1,self.height()))))
        if not hasattr(self,'_pointer_motion'):
            self._pointer_motion=QVariantAnimation(self)
            self._pointer_motion.setEasingCurve(QEasingCurve.OutCubic)
            self._pointer_motion.valueChanged.connect(self._move_reflection)
        motion=self._pointer_motion
        motion.stop()
        motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else 140)
        motion.setStartValue(self._glass_pointer)
        motion.setEndValue(target)
        motion.start()
        super().mouseMoveEvent(event)

    def _move_reflection(self,value):
        self._glass_pointer=value
        artwork=getattr(self,'_home_artwork_motion',None)
        if artwork is not None:
            artwork.focus=self._glass_pointer
            artwork.update()
        if self.property('liquidCatalog') or self.property('liquidHomeCard'):
            self.update()

    def leaveEvent(self,event):
        self._scroll_hover_deferred = False
        if self.hover > 0 or self.motion.state() == QVariantAnimation.Running:
            self.shift(0.0)
        super().leaveEvent(event)

    def _scroll_active(self):
        controller = getattr(self.parentWidget(), '_controller', None)
        return bool(getattr(controller, '_scrolling', False))

    def shift(self,value):
        self.motion.stop()
        self.motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion')else 260)
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.motion.setStartValue(self.hover)
        self.motion.setEndValue(value)
        self.motion.start()

    def paintEvent(self,event):
        if self.property('liquidCatalog') or self.property('liquidHomeCard'):
            p=QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            rect=QRectF(self.rect()).adjusted(2,2,-2,-2)
            shape=QPainterPath()
            shape.addRoundedRect(rect,22,22)
            paint_dock_glass(p,shape)
            pointer=QPointF(self._glass_pointer.x()*self.width(),self._glass_pointer.y()*self.height())
            hover=max(0,min(1,self.hover))
            radius=min(220,max(100,self.width()*.9))
            reflection=QRadialGradient(pointer,radius)
            reflection.setColorAt(0,QColor(255,255,255,round(60*hover)))
            accent=QColor(ColorThemeManager.instance().colors.accent)
            accent.setAlpha(round(24*hover))
            reflection.setColorAt(.45,accent)
            reflection.setColorAt(1,QColor(255,255,255,0))
            p.fillPath(shape,reflection)
            rim=QRadialGradient(pointer,radius)
            rim.setColorAt(0,QColor(255,255,255,round(160*hover)))
            rim.setColorAt(1,QColor(255,255,255,0))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(rim,1.2))
            p.drawPath(shape)
            if self.property('liquidHomeCard'):
                inset=rect.adjusted(3,3,-3,-3)
                edge=QLinearGradient(inset.topLeft(),inset.bottomRight())
                edge.setColorAt(0,QColor(255,255,255,38))
                edge.setColorAt(.4,QColor(255,255,255,0))
                edge.setColorAt(1,QColor(255,255,255,14))
                p.setPen(QPen(edge,1))
                p.drawRoundedRect(inset,19,19)
            return
        if not self.property('liquidControlCard'):
            super().paintEvent(event)
            return
        c=ColorThemeManager.instance().colors
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        fill=QColor(c.bg_secondary)
        fill=fill.lighter(round(100+5*self.hover))
        p.setBrush(fill)
        edge=QColor(c.text_secondary)
        edge.setAlpha(round(35+18*self.hover))
        p.setPen(QPen(edge,1))
        p.drawRoundedRect(rect,16,16)


class FavoriteButton(QPushButton):
    def __init__(self,parent=None):
        super().__init__(parent)
        from .sounds import UiSounds
        self.clicked.connect(UiSounds.instance().play_favorite)

    def paintEvent(self,event):
        if self.isChecked():
            p=QPainter(self)
            glow=QRadialGradient(QPointF(self.rect().center()),self.width()*.48)
            color=QColor('#d6b967')
            color.setAlpha(40)
            glow.setColorAt(0,color)
            color.setAlpha(0)
            glow.setColorAt(1,color)
            p.fillRect(self.rect(),glow)
            p.end()
        super().paintEvent(event)
