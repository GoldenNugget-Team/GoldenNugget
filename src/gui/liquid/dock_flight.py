import math

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from .motion import animate


class DockFlight(QWidget):
    def __init__(self, dock, snapshot, origin):
        super().__init__(dock.window)
        self.dock = dock
        self.snapshot = snapshot
        self.origin = origin
        self.amount = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(dock.window.rect())
        self.show()
        self.raise_()
        animate(self, 0.0, 1.0, self.step, duration=580, finished=self.deleteLater)

    def step(self, value):
        self.amount = float(value)
        self.update()

    def paintEvent(self, event):
        target = self.dock.more.mapTo(self.parentWidget(), self.dock.more.rect().center())
        t = self.amount
        center = self.origin * (1-t) + target * t
        width = self.snapshot.width() / self.snapshot.devicePixelRatio() * (1-.8*t)
        height = self.snapshot.height() / self.snapshot.devicePixelRatio() * (1-.8*t)
        rect = QRectF(center.x()-width/2, center.y()-height/2-math.sin(t*math.pi)*42, width, height)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(1-t*t)
        painter.drawPixmap(rect, self.snapshot, QRectF(self.snapshot.rect()))
