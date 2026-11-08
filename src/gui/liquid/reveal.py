from PySide6.QtCore import QEasingCurve, QObject, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsEffect, QWidget


class PageTransitionEffect(QGraphicsEffect):
    def __init__(self, parent):
        super().__init__(parent)
        self.amount = 0.0

    def draw(self, painter):
        painter.save()
        painter.setOpacity(0.15 + 0.85 * self.amount)
        painter.translate(0, 22 * (1 - self.amount))
        self.drawSource(painter)
        painter.restore()


class PageReveal(QObject):
    def __init__(self,target):
        super().__init__(target)
        self.target=target
        self.motion=QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.InOutCubic)
        self.motion.setDuration(560)
        self.motion.valueChanged.connect(self.step)
        self.motion.finished.connect(self._finish)
        self.effect = None

    def _finish(self):
        if self.effect is not None and self.target.graphicsEffect() is self.effect:
            self.target.setGraphicsEffect(None)
        self.effect = None
        self.target.clearMask()

    def cancel(self):
        self.motion.stop()
        self._finish()

    def start(self):
        self.cancel()
        if QApplication.instance().property('liquid_reduce_motion'):
            return
        self.effect = PageTransitionEffect(self.target)
        self.target.setGraphicsEffect(self.effect)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(1.0)
        self.step(0.0)
        self.motion.start()

    def step(self,value):
        if self.effect is not None:
            self.effect.amount = float(value)
            self.effect.update()


class DevicePeek(QWidget):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.progress=0.0
        self.motion=QVariantAnimation(self)
        self.motion.valueChanged.connect(self.step)
        self.motion.finished.connect(self._finish_reveal)
        self.hide_timer=QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(lambda:self.reveal(False))
        self.snapshot=None
        self.hide()

    def refresh_preview(self,*args):
        self.snapshot=self.window.ios_home._device_preview.grab()
        self.update()

    def peek(self,hold=False):
        if self.window.liquid.device.isVisible():
            return
        self.refresh_preview()
        self.reveal(True)
        self.hide_timer.stop()
        if not hold:
            self.hide_timer.start(2400)

    def dismiss(self):
        self.hide_timer.stop()
        self.motion.stop()
        self.progress=0.0
        self.hide()

    def _finish_reveal(self):
        if self.progress<=0:
            self.hide()

    def reveal(self,visible):
        if self.window.liquid.device.isVisible():
            self.dismiss()
            return
        button=self.window.liquid.device_button
        x=max(12,min(button.x()-20,self.window.width()-192))
        self.setGeometry(x,button.y()-278,180,278)
        self.show()
        self.raise_()
        self.motion.stop()
        reduced=QApplication.instance().property('liquid_reduce_motion')
        self.motion.setDuration(0 if reduced else (620 if visible else 400))
        self.motion.setStartValue(self.progress)
        self.motion.setEndValue(1.0 if visible else 0.0)
        self.motion.setEasingCurve(QEasingCurve.OutBack if visible else QEasingCurve.InOutCubic)
        self.motion.start()

    def step(self,value):
        self.progress=float(value)
        self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hole=QRectF(10,self.height()-23,self.width()-20,20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0,0,0,170))
        p.drawEllipse(hole)
        p.save()
        p.setClipRect(0,0,self.width(),self.height()-13)
        if self.snapshot and not self.snapshot.isNull():
            height=250
            y=self.height()-13-height*self.progress
            p.drawPixmap(18,round(y),144,height,self.snapshot)
        p.restore()
        lip=QLinearGradient(hole.topLeft(),hole.bottomLeft())
        lip.setColorAt(0,QColor(255,255,255,8))
        lip.setColorAt(1,QColor(255,255,255,60))
        p.setBrush(lip)
        p.drawRoundedRect(QRectF(12,self.height()-14,self.width()-24,7),4,4)
