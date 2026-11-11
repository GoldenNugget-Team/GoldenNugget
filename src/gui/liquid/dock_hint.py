from PySide6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from src.gui.theme import ColorThemeManager


class DockHint(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        font = self.font()
        font.setPixelSize(13)
        font.setWeight(QFont.Medium)
        self.setFont(font)
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._step)
        self._animation.finished.connect(self._finished)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(45)
        self._hover_timer.timeout.connect(self._begin_reveal)
        self.hide()

    def reveal(self, button, edge):
        self._animation.stop()
        self._hover_timer.stop()
        if getattr(self, '_button', None) is not button:
            self._progress = 0.0
        self._button = button
        self._text = button.accessibleName() or button.text() or button.toolTip()
        self._edge = edge
        self._dock = button.parentWidget()
        width = min(self.parentWidget().width() - 24, self.fontMetrics().horizontalAdvance(self._text) + 52)
        self._full_width = max(80, width)
        anchor = button.mapTo(self.parentWidget(), QPoint(0, 0))
        dock_origin = self._dock.mapTo(self.parentWidget(), QPoint(0, 0))
        self._seam = dock_origin.x() + self._dock.width() - 1 if edge == 'left' else dock_origin.x() + 1
        available = self.parentWidget().width() - self._seam - 8 if edge == 'left' else self._seam - 8
        self._full_width = max(1, min(self._full_width, available))
        self._top = max(8, min(anchor.y() + (button.height() - 40) // 2,
                               self.parentWidget().height() - 48))
        self._step(self._progress)
        if QApplication.instance().property('liquid_reduce_motion'):
            self._begin_reveal()
        else:
            self._hover_timer.start()

    def _begin_reveal(self):
        self.show()
        self.raise_()
        self.stackUnder(self._dock)
        self._run(1.0)

    def dismiss(self, immediate=False):
        self._hover_timer.stop()
        if immediate:
            self._animation.stop()
            self._progress = 0.0
            self.hide()
        elif self.isVisible():
            self._run(0.0)

    def _run(self, end):
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(end)
        reduced = QApplication.instance().property('liquid_reduce_motion')
        curve = QEasingCurve(QEasingCurve.OutBack if end else QEasingCurve.InOutCubic)
        curve.setOvershoot(0.28)
        self._animation.setEasingCurve(curve)
        self._animation.setDuration(0 if reduced else 330 if end else 150)
        self._animation.start()

    def _step(self, value):
        self._progress = max(0.0, float(value))
        width = max(1, round(self._full_width * self._progress))
        x = self._seam if self._edge == 'left' else self._seam - width
        self.setGeometry(x, self._top, width, 40)
        self.update()

    def _finished(self):
        if self._progress == 0:
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = ColorThemeManager.instance().colors
        from .controls import paint_dock_glass
        bounds = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        # Extend the dock-facing rounded corners under the dock, leaving an
        # open joining edge and the same glass rim as the dock itself.
        bounds.adjust(-24 if self._edge == 'left' else 0, 0,
                      24 if self._edge == 'right' else 0, 0)
        shape = QPainterPath()
        shape.addRoundedRect(bounds, 16, 16)
        paint_dock_glass(painter, shape)
        glow = QLinearGradient(bounds.topLeft(), bounds.bottomLeft())
        glow.setColorAt(0, QColor(255, 255, 255, 38))
        glow.setColorAt(0.45, QColor(255, 255, 255, 9))
        glow.setColorAt(1, QColor(255, 255, 255, 2))
        painter.fillPath(shape, glow)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(glow, 1))
        painter.drawPath(shape)
        progress = min(1.0, self._progress)
        offset = round((1 - progress) * (-8 if self._edge == 'left' else 8))
        if self._edge == 'right':
            offset += self.width() - self._full_width
        painter.translate(offset, 0)
        painter.setOpacity(max(0.0, min(1.0, (progress - 0.15) / 0.85)))
        painter.setPen(QColor(colors.text_primary))
        text_rect = QRectF(18, 0, max(0, self._full_width - 36), self.height())
        text = self.fontMetrics().elidedText(self._text, Qt.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
