from PySide6.QtCore import (
    Qt, QRectF, QTime, QDate, QTimer, QPropertyAnimation,
    QEasingCurve, Property,
)
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QFont, QPixmap, QLinearGradient,
)
from PySide6.QtWidgets import QWidget

_BEZEL = QColor(0x1C, 0x1C, 0x1E)
_SCREEN_BG = QColor(0x0B, 0x0B, 0x0C)
_DATE_TEXT = QColor(0xDD, 0xDD, 0xDE, 235)
_HOME_DIM = QColor(0x00, 0x00, 0x00, 62)
_ICON_BG = QColor(0x55, 0x55, 0x5A)
_DOCK_BG = QColor(0xFF, 0xFF, 0xFF, 46)
_HINT = QColor(0xFF, 0xFF, 0xFF, 150)

# Real iPhone 15 / 15 Pro display: 393x852 pt at @3x (1179x2556 native px).
DEVICE_PT_W = 393
DEVICE_PT_H = 852
DEVICE_SCALE = 3
_MAX_CA_EDGE = DEVICE_PT_H * DEVICE_SCALE


class PhoneFrame(QWidget):

    def __init__(self, parent=None, show_chrome=True):
        super().__init__(parent)
        self._pixmap = None
        self._placeholder = ""
        self._time = QTime.currentTime()
        self._date = QDate.currentDate()
        self._show_chrome = show_chrome

        self._ca_renderer = None
        self._ca_home_renderer = None
        self._ca_loop = 0.0
        self._ca_elapsed = 0.0
        self._ca_pixmap = None
        self._ca_transition = None
        self._ca_timer = QTimer(self)
        self._ca_timer.setInterval(33)
        self._ca_timer.timeout.connect(self._advance_ca)

        self._progress = 0.0
        self._drag_y = None
        self._drag_progress = 0.0
        self._anim = QPropertyAnimation(self, b"unlock_progress", self)
        self._anim.setDuration(420)

        self.setMinimumSize(120, 240)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def device_pixel_size(self):
        """Native screen pixel size of the represented iPhone (e.g. 1179x2556)."""
        return (DEVICE_PT_W * DEVICE_SCALE, DEVICE_PT_H * DEVICE_SCALE)

    def set_wallpaper(self, pixmap, live_clock: bool = True):
        self._stop_ca()
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
        else:
            self._pixmap = pixmap
        if live_clock:
            self._time = QTime.currentTime()
        self.update()

    def set_ca_scene(self, renderer, loop_seconds: float, home_renderer=None):
        self._stop_ca()
        self._pixmap = None
        self._ca_renderer = renderer
        self._ca_home_renderer = home_renderer
        self._ca_loop = float(loop_seconds or 0.0)
        self._ca_elapsed = 0.0
        self._ca_pixmap = None
        if renderer is not None:
            self._render_ca_frame()
            if self._ca_loop > 0.5 and not self._ca_timer.isActive():
                self._ca_timer.start()
        self.update()

    def set_ca_transition(self, renderer, transition):
        self._stop_ca()
        self._pixmap = None
        self._ca_renderer = renderer
        self._ca_transition = tuple(transition)
        self._ca_elapsed = 0.0
        self._ca_pixmap = None
        if renderer is not None:
            self._render_ca_frame()
        self.update()

    def _stop_ca(self):
        # Guard against multiple calls (e.g., from closeEvent and destructor)
        if self._ca_renderer is None and self._ca_timer.isActive():
            return
        self._ca_timer.stop()
        self._ca_renderer = None
        self._ca_home_renderer = None
        self._ca_loop = 0.0
        self._ca_transition = None
        self._ca_pixmap = None

    def _render_transition_frame(self, transition, progress: float):
        from_state, to_state = transition[0], transition[1]
        return self._ca_renderer.render_state_transition(
            from_state, to_state, max(0.0, min(1.0, progress)))

    def _render_ca_frame(self) -> float:
        if self._ca_renderer is None:
            return 0.0
        import time as _time
        started = _time.monotonic()
        if self._ca_transition:
            img = self._render_transition_frame(
                self._ca_transition, self._progress)
        else:
            renderer = self._ca_renderer
            if self._progress >= 1.0 and self._ca_home_renderer is not None:
                renderer = self._ca_home_renderer
            start = self._ca_elapsed
            if self._ca_loop > 0.5:
                start %= self._ca_loop
            img = renderer.render(start * 1000.0)
            self._ca_elapsed += self._ca_timer.interval() / 1000.0
        if img is not None and not img.isNull():
            long_edge = max(img.width(), img.height())
            if long_edge > _MAX_CA_EDGE:
                scale = _MAX_CA_EDGE / long_edge
                img = img.scaled(
                    max(1, int(img.width() * scale)),
                    max(1, int(img.height() * scale)),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            self._ca_pixmap = QPixmap.fromImage(img)
        return (_time.monotonic() - started) * 1000.0

    def _advance_ca(self):
        # Guard against being called after the timer has been stopped
        if self._ca_renderer is None:
            return
        took_ms = self._render_ca_frame()
        self.update()
        desired = 33
        if 30 < took_ms < 1000:
            desired = max(33, int(took_ms * 1.5))
        if self._ca_timer.isActive() and self._ca_timer.interval() != desired:
            self._ca_timer.stop()
            self._ca_timer.setInterval(desired)
            self._ca_timer.start()

    def set_placeholder(self, text: str = ""):
        self._placeholder = text
        self._pixmap = None
        self.update()

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value):
        self._progress = max(0.0, min(1.0, value))
        if self._ca_transition is not None:
            self._render_ca_frame()
        self.update()

    unlock_progress = Property(float, _get_progress, _set_progress)

    def _animate_to(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if target > self._progress
            else QEasingCurve.Type.InOutCubic)
        self._anim.start()

    def _screen_rect(self):
        w = self.width()
        h = self.height()
        inset_x = max(4.0, w * 0.028)
        inset_y = max(6.0, h * 0.03)
        return QRectF(inset_x, inset_y, w - 2 * inset_x, h - 2 * inset_y)

    def _clock_font(self, size_pt):
        f = QFont()
        f.setPointSizeF(size_pt)
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._anim.stop()
            self._drag_y = event.position().y()
            self._drag_progress = self._progress
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_y is None:
            super().mouseMoveEvent(event)
            return
        dy = event.position().y() - self._drag_y
        self._set_progress(self._drag_progress - dy / max(1.0, self.height()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_y is None:
            super().mouseReleaseEvent(event)
            return
        start_y = self._drag_y
        self._drag_y = None
        moved = abs(event.position().y() - start_y)
        if moved < 8:
            if self._progress >= 0.99:
                self._animate_to(0.0)
        elif self._progress > 0.33:
            self._animate_to(1.0)
        else:
            self._animate_to(0.0)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = QRectF(0, 0, self.width(), self.height())
        screen = self._screen_rect()
        radius = min(screen.width(), screen.height()) * 0.14

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, _BEZEL.lighter(116))
        gradient.setColorAt(0.5, _BEZEL)
        gradient.setColorAt(1.0, _BEZEL.darker(118))
        painter.fillRect(rect, gradient)

        clip = QPainterPath()
        clip.addRoundedRect(screen, radius, radius)
        painter.save()
        painter.setClipPath(clip)
        try:
            painter.fillRect(screen, _SCREEN_BG)
            if self._pixmap is not None or self._ca_pixmap is not None:
                self._paint_wallpaper(painter, screen)
            else:
                self._paint_placeholder(painter, screen)

            t = self._progress
            if t > 0.0:
                self._paint_home_screen(painter, screen, t)
            if self._show_chrome and t < 1.0:
                self._paint_lockscreen_chrome(painter, screen, t)
        finally:
            painter.restore()
        painter.end()

    def _paint_wallpaper(self, painter, screen: QRectF):
        pm = self._ca_pixmap if self._ca_pixmap is not None else self._pixmap
        scale = max(screen.width() / pm.width(), screen.height() / pm.height())
        w = pm.width() * scale
        h = pm.height() * scale
        target = QRectF(screen.center().x() - w / 2,
                        screen.center().y() - h / 2, w, h)
        painter.drawPixmap(target, pm, QRectF(pm.rect()))

    def _paint_placeholder(self, painter, screen: QRectF):
        if not self._placeholder:
            return
        f = self._clock_font(max(9.0, screen.width() * 0.032))
        painter.setFont(f)
        painter.setPen(QColor(0x8E, 0x8E, 0x93))
        painter.drawText(screen,
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         self._placeholder)

    def _paint_lockscreen_chrome(self, painter, screen: QRectF, t: float):
        lift = t * screen.height()
        painter.save()
        painter.setOpacity(max(0.0, 1.0 - t * 1.25))
        painter.translate(0.0, -lift)

        f_date = self._clock_font(max(10.0, screen.width() * 0.038))
        painter.setFont(f_date)
        painter.setPen(_DATE_TEXT)
        date_rect = QRectF(screen.left(), screen.top() + screen.height() * 0.030,
                           screen.width(), screen.height() * 0.06)
        painter.drawText(date_rect,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         self._date.toString("dddd, MMMM d").upper())

        f_time = self._clock_font(max(30.0, screen.width() * 0.155))
        painter.setFont(f_time)
        painter.setPen(Qt.white)
        time_rect = QRectF(screen.left(), date_rect.bottom() - screen.height() * 0.012,
                           screen.width(), screen.height() * 0.20)
        painter.drawText(time_rect,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         self._time.toString("H:mm"))

        if t < 0.5:
            f_hint = self._clock_font(max(9.0, screen.width() * 0.05))
            painter.setFont(f_hint)
            painter.setPen(_HINT)
            hint_rect = QRectF(screen.left(), screen.bottom() - screen.height() * 0.055,
                               screen.width(), screen.height() * 0.04)
            painter.drawText(hint_rect, Qt.AlignmentFlag.AlignHCenter, "\u2303")

        painter.restore()

    def _paint_home_screen(self, painter, screen: QRectF, t: float):
        painter.save()
        painter.fillRect(screen, _HOME_DIM)
        if t < 1.0:
            painter.setOpacity(t)

        scale = screen.width() / 390.0
        icon = 62 * scale
        gap = 24 * scale
        columns = 4
        rows = 3
        grid_w = columns * icon + (columns - 1) * gap
        x0 = screen.left() + (screen.width() - grid_w) / 2
        y0 = screen.top() + screen.height() * 0.34
        slide_in = (1.0 - t) * screen.height() * 0.06

        palette = [
            QColor(0xEA, 0x5D, 0x5D), QColor(0x5D, 0x9E, 0xEA), QColor(0x5D, 0xEA, 0x9E),
            QColor(0xEA, 0xCE, 0x5D), QColor(0xB0, 0x5D, 0xEA), QColor(0x5D, 0xEA, 0xEA),
            QColor(0xEA, 0x8D, 0x5D), QColor(0x8D, 0xEA, 0x5D), QColor(0xEA, 0x5D, 0xCE),
            QColor(0x5D, 0xC8, 0xEA), QColor(0xC8, 0xEA, 0x5D), QColor(0xEA, 0x5D, 0x8D),
        ]
        r = icon * 0.24

        painter.setPen(Qt.PenStyle.NoPen)
        idx = 0
        for row in range(rows):
            for col in range(columns):
                x = x0 + col * (icon + gap)
                y = y0 + row * (icon + gap) + slide_in
                painter.setBrush(palette[idx % len(palette)])
                painter.drawRoundedRect(QRectF(x, y, icon, icon), r, r)
                idx += 1

        dock = screen.width() * 0.82
        dock_x = screen.left() + (screen.width() - dock) / 2
        dock_y = screen.bottom() - screen.height() * 0.09 + slide_in * 0.4
        painter.setBrush(_DOCK_BG)
        painter.drawRoundedRect(QRectF(dock_x, dock_y, dock, icon * 1.15),
                                icon * 0.5, icon * 0.5)
        painter.setBrush(QColor(0x8A, 0x8A, 0x92))
        dock_gap = (dock - 4 * icon) / 5
        for i in range(4):
            x = dock_x + dock_gap + i * (icon + dock_gap)
            painter.drawRoundedRect(QRectF(x, dock_y + icon * 0.075,
                                           icon, icon), r, r)

        painter.restore()