from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from .motion import animate


class SettingsExpansion(QWidget):
    def __init__(self, panel, origin):
        super().__init__(panel.parentWidget())
        self.setGeometry(panel.geometry())
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.snapshot = panel.grab()
        self.amount = 0.0
        self.origin = QPointF(
            max(0, min(origin.x(), self.width())),
            max(0, min(origin.y(), self.height())),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scale = .16 + .84 * self.amount
        painter.translate(self.origin)
        painter.scale(scale, scale)
        painter.translate(-self.origin)
        painter.drawPixmap(QRectF(self.rect()), self.snapshot, QRectF(self.snapshot.rect()))


def reveal_settings(panel, anchor, tiles):
    cancel = getattr(panel, '_finish_settings_reveal', None)
    if cancel:
        cancel()
    panel.show()
    panel.raise_()
    panel.layout().activate()
    for tile in tiles:
        tile.parentWidget().layout().activate()
        tile.layout().activate()
    if QApplication.instance().property('liquid_reduce_motion'):
        return

    origin = panel.mapFromGlobal(anchor.mapToGlobal(anchor.rect().center()))
    expansion = SettingsExpansion(panel, origin)
    panel.setMask(QRegion(QRect(-2, -2, 1, 1)))
    expansion.show()
    expansion.raise_()
    animation = None

    def finish():
        nonlocal animation
        panel._finish_settings_reveal = None
        if animation is not None:
            animation.stop()
            getattr(panel, '_liquid_animations', set()).discard(animation)
            animation.deleteLater()
            animation = None
        panel.clearMask()
        expansion.hide()
        expansion.deleteLater()

    def step(value):
        expansion.amount = float(value)
        expansion.update()

    panel._finish_settings_reveal = finish
    animation = animate(panel, 0.0, 1.0, step, duration=260,
                        easing=QEasingCurve.OutCubic, finished=finish)
