from PySide6.QtCore import QEasingCurve, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QLabel


class FavoriteFeedbackLabel(QLabel):
    SWEEP_MS = 640
    HOLD_MS = 420

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_text = ''
        self._state_color = QColor('white')
        self._feedback_active = False
        self._favorited = False
        self._progress = 0.0
        self._motion = QVariantAnimation(self)
        self._motion.setDuration(self.SWEEP_MS)
        self._motion.setEasingCurve(QEasingCurve.InOutCubic)
        self._motion.setStartValue(0.0)
        self._motion.setEndValue(1.0)
        self._motion.valueChanged.connect(self._step)
        self._motion.finished.connect(self._sweep_finished)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self.cancel_feedback)

    def reserve_status_width(self):
        metrics = self.fontMetrics()
        self.setFixedWidth(max(metrics.horizontalAdvance(text) for text in
                               (self.tr('Enabled'), self.tr('Disabled'), self.tr('Favorited'))) + 12)

    def set_selection_state(self, text, color):
        self._state_text = text
        self._state_color = QColor(color)
        self.setStyleSheet(f'background:transparent;border:none;color:{self._state_color.name()};')
        self.setText(self.tr('Favorited') if self._feedback_active and self._favorited else text)
        self.update()

    def show_favorite_feedback(self, selected):
        self._motion.stop()
        self._hold.stop()
        self._favorited = bool(selected)
        self._feedback_active = True
        self._progress = 0.0
        self.setText(self.tr('Favorited') if selected else self._state_text)
        if QApplication.instance().property('liquid_reduce_motion'):
            self._progress = 1.0
            self._sweep_finished()
        else:
            self._motion.start()
        self.update()

    def _step(self, value):
        self._progress = float(value)
        self.update()

    def _sweep_finished(self):
        if self._favorited:
            self._hold.start(self.HOLD_MS)
        else:
            self.cancel_feedback()

    def cancel_feedback(self):
        self._motion.stop()
        self._hold.stop()
        self._feedback_active = False
        self.setText(self._state_text)
        self.update()

    def hideEvent(self, event):
        self.cancel_feedback()
        super().hideEvent(event)

    def paintEvent(self, event):
        if not self._feedback_active:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        metrics = self.fontMetrics()
        text = self.text()
        width = metrics.horizontalAdvance(text)
        left = (self.width() - width) / 2
        baseline = (self.height() - metrics.height()) / 2 + metrics.ascent()
        path = QPainterPath()
        path.addText(left, baseline, self.font(), text)
        band = max(12.0, width * .25)
        gold = QColor('#d6b967')
        gloss = QColor('#f4ead1')
        if self._favorited:
            x = left - band + (width + 2 * band) * self._progress
            gradient = QLinearGradient(x - band, 0, x + band, 0)
            gradient.setColorAt(0, gold)
            gradient.setColorAt(.5, gloss)
            gradient.setColorAt(1, gold)
        else:
            x = left + width + band - (width + 2 * band) * self._progress
            gradient = QLinearGradient(x - band, 0, x + band, 0)
            gradient.setColorAt(0, gold)
            gradient.setColorAt(.5, gloss)
            gradient.setColorAt(1, self._state_color)
        painter.fillPath(path, gradient)
