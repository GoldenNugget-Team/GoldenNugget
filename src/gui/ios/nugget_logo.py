from math import sin

from PySide6.QtCore import QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel


class NuggetLogo(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(88, 88)
        self.setAccessibleName(self.tr("GoldenNugget"))
        self.setPixmap(QPixmap(":/credits/big_nugget.png"))
        self._sparkle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._twinkle)

    def _twinkle(self):
        self._sparkle += 0.16
        self.update()

    def enterEvent(self, event):
        self._timer.start()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._timer.stop()
        self.update()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        mascot = self.pixmap()
        if mascot is None or mascot.isNull():
            return
        painter.drawPixmap(QRectF(self.rect()), mascot, QRectF(mascot.rect()))
        if self._timer.isActive():
            for i, (x, y) in enumerate(((17, 12), (70, 25), (64, 5))):
                strength = max(0.0, sin(self._sparkle + i * 2))
                radius = 1 + strength * 3
                painter.setPen(QPen(QColor(255, 225, 111, int(220 * strength)), 1.4))
                center = QPointF(x, y)
                painter.drawLine(center + QPointF(-radius, 0), center + QPointF(radius, 0))
                painter.drawLine(center + QPointF(0, -radius), center + QPointF(0, radius))
