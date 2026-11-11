"""Live preview of the status bar overrides on the top of an iPhone screen.

The Status Bar page edits a binary override struct (iOS 26 and below) or a
carrier-only archive (iOS 27+); an apply takes minutes and, on iOS 27, wipes
and restores the device. This preview draws what those settings will look
like before any of that happens: the Lock Screen (carrier on the left) and
the Home Screen (time on the left), each with the Dynamic Island, signal bars,
Wi-Fi and battery on the right.

Geometry follows an iPhone 15 Pro in points (393 pt wide, 54 pt status bar,
126x37 pt island at y=11), scaled to the widget.
"""
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QCoreApplication, QDate, QLocale, QRectF, QSize, Qt, QTime
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.gui.theme import ColorThemeManager
from src.tweaks.status_bar.status_setter import StatusBarItem

DEVICE_PT_W = 393.0
STATUS_BAR_PT_H = 54.0
CROP_PT_H = 92.0          # status bar + the top of the Lock Screen date
ISLAND = QRectF(133.5, 11.0, 126.0, 37.0)
MAX_BARS = 4
MAX_WIFI_BARS = 3

_WHITE = QColor(255, 255, 255)
_DIM = QColor(255, 255, 255, 90)
_BEZEL = QColor(0x1C, 0x1C, 0x1E)


@dataclass
class StatusBarPreviewState:
    carrier: str
    secondary_carrier: Optional[str] = None
    primary_badge: str = ""
    secondary_badge: str = ""
    bars: int = MAX_BARS
    secondary_bars: Optional[int] = None   # None: single SIM, no second row
    wifi_bars: Optional[int] = MAX_WIFI_BARS  # None: Wi-Fi icon hidden
    battery: Optional[int] = 100            # None: battery icon hidden
    battery_detail: str = ""
    time: str = ""
    show_cellular: bool = True


def _clamp(value, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return high


def preview_state(manager, ios27: bool, now: Optional[QTime] = None) -> StatusBarPreviewState:
    """Turn the StatusBar tweak into what the device would show.

    Overrides only apply while the master switch is on. On iOS 27 only the
    cellular entry (carrier, badge, bars) survives; time, battery, Wi-Fi and
    icon visibility stay stock there, so the preview keeps them stock too.
    """
    now = now or QTime.currentTime()
    state = StatusBarPreviewState(
        carrier=QCoreApplication.translate("Nugget", "Carrier"),
        time=now.toString("H:mm"),
    )
    if not getattr(manager, "enabled", False):
        return state

    def overridden(name):
        try:
            return bool(getattr(manager, name)())
        except Exception:
            return False

    if overridden("is_carrier_overridden"):
        state.carrier = manager.get_carrier_override()
    if overridden("is_primary_service_badge_overridden"):
        state.primary_badge = manager.get_primary_service_badge_override()
    if overridden("is_gsm_signal_strength_bars_overridden"):
        state.bars = _clamp(manager.get_gsm_signal_strength_bars_override(), 0, MAX_BARS)
    secondary = overridden("is_secondary_carrier_overridden")
    if secondary:
        state.secondary_carrier = manager.get_secondary_carrier_override()
    if overridden("is_secondary_service_badge_overridden"):
        state.secondary_badge = manager.get_secondary_service_badge_override()
        secondary = True
    if overridden("is_secondary_gsm_signal_strength_bars_overridden"):
        state.secondary_bars = _clamp(
            manager.get_secondary_gsm_signal_strength_bars_override(), 0, MAX_BARS)
    elif secondary:
        state.secondary_bars = MAX_BARS

    if ios27:
        return state

    def hidden(item):
        try:
            return manager.is_item_overridden(item) and not manager.get_item_override(item)
        except Exception:
            return False

    if overridden("is_time_overridden"):
        state.time = manager.get_time_override()
    if overridden("is_battery_capacity_overridden"):
        state.battery = _clamp(manager.get_battery_capacity_override(), 0, 100)
    if overridden("is_battery_detail_overridden"):
        state.battery_detail = manager.get_battery_detail_override()
    if overridden("is_wifi_signal_strength_bars_overridden"):
        state.wifi_bars = _clamp(manager.get_wifi_signal_strength_bars_override(), 0, MAX_WIFI_BARS)
    if hidden(StatusBarItem.CellularDataNetworkStatusBarItem):
        state.wifi_bars = None
    if hidden(StatusBarItem.MainBatteryStatusBarItem):
        state.battery = None
    if hidden(StatusBarItem.CellularServiceStatusBarItem):
        state.show_cellular = False
    return state


def _font(px: float, weight=QFont.Weight.DemiBold) -> QFont:
    font = QFont()
    font.setPixelSize(max(1, round(px)))
    font.setWeight(weight)
    return font


def _elide(text: str, font: QFont, width: float) -> str:
    return QFontMetricsF(font).elidedText(text, Qt.TextElideMode.ElideRight, max(0.0, width))


def _paint_bars(p: QPainter, x: float, bottom: float, s: float, filled: int, height: float) -> float:
    """Four signal bars growing left to right; returns the drawn width."""
    bar_w, gap = 3.0 * s, 1.5 * s
    for i in range(MAX_BARS):
        h = height * (0.35 + 0.65 * i / (MAX_BARS - 1))
        p.setBrush(_WHITE if i < filled else _DIM)
        p.drawRoundedRect(QRectF(x + i * (bar_w + gap), bottom - h, bar_w, h), 0.8 * s, 0.8 * s)
    return MAX_BARS * bar_w + (MAX_BARS - 1) * gap


WIFI_W = 17.0  # pt, the iOS glyph is about 17 x 12


def _paint_wifi(p: QPainter, x: float, bottom: float, s: float, filled: int) -> float:
    """Wi-Fi fan of three arcs plus the dot; returns the drawn width."""
    w = WIFI_W * s
    big = w / 2 / 0.7071  # a 90-degree fan this wide
    cx = x + w / 2
    for i in range(MAX_WIFI_BARS):
        radius = big * (i + 1) / MAX_WIFI_BARS
        path = QPainterPath()
        rect = QRectF(cx - radius, bottom - radius, 2 * radius, 2 * radius)
        path.moveTo(cx, bottom)
        path.arcTo(rect, 45, 90)
        path.closeSubpath()
        if i:
            inner = big * i / MAX_WIFI_BARS + 1.4 * s
            cut = QPainterPath()
            cut.moveTo(cx, bottom)
            cut.arcTo(QRectF(cx - inner, bottom - inner, 2 * inner, 2 * inner), 45, 90)
            cut.closeSubpath()
            path = path.subtracted(cut)
        p.setBrush(_WHITE if i < filled else _DIM)
        p.drawPath(path)
    return w


def _paint_battery(p: QPainter, x: float, mid: float, s: float, level: int) -> float:
    w, h = 25.0 * s, 12.0 * s
    body = QRectF(x, mid - h / 2, w, h)
    p.setPen(QPen(_DIM, 1.0 * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body.adjusted(0.5 * s, 0.5 * s, -0.5 * s, -0.5 * s), 3.5 * s, 3.5 * s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_DIM)
    p.drawRoundedRect(QRectF(body.right() + 1.0 * s, mid - 2.0 * s, 1.5 * s, 4.0 * s), 0.7 * s, 0.7 * s)
    inner = body.adjusted(2.0 * s, 2.0 * s, -2.0 * s, -2.0 * s)
    inner.setWidth(inner.width() * max(0, min(100, level)) / 100.0)
    p.setBrush(QColor(0xFF, 0x3B, 0x30) if level <= 20 else _WHITE)
    p.drawRoundedRect(inner, 1.8 * s, 1.8 * s)
    return w + 2.5 * s


def paint_status_bar(p: QPainter, screen: QRectF, state: StatusBarPreviewState, lock_screen: bool,
                     cutout: str = "island"):
    """Draw the status bar along the top of ``screen`` (a full-width device screen).

    ``cutout`` is the hardware at the top centre: ``"island"`` (Dynamic
    Island), ``"notch"`` or ``"none"`` (island turned off, or no cutout). The
    side zones keep the island's geometry in every case.
    """
    s = screen.width() / DEVICE_PT_W
    island = QRectF(screen.left() + ISLAND.left() * s, screen.top() + ISLAND.top() * s,
                    ISLAND.width() * s, ISLAND.height() * s)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0))
    if cutout == "island":
        p.drawRoundedRect(island, island.height() / 2, island.height() / 2)
    elif cutout == "notch":
        notch = QRectF(screen.center().x() - 81 * s, screen.top() - 8 * s, 162 * s, 40 * s)
        p.drawRoundedRect(notch, 20 * s, 20 * s)

    mid = island.center().y()
    # Left side: carrier on the Lock Screen, time on the Home Screen.
    left = QRectF(screen.left() + 16 * s, island.top(), island.left() - screen.left() - 26 * s, island.height())
    p.setPen(_WHITE)
    if lock_screen:
        lines = [state.carrier] if state.show_cellular else []
        if state.show_cellular and state.secondary_carrier is not None:
            lines.append(state.secondary_carrier)
        if lines:
            font = _font((15.0 if len(lines) == 1 else 12.0) * s)
            p.setFont(font)
            text = "\n".join(_elide(line, font, left.width()) for line in lines)
            p.drawText(left, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, text)
    else:
        font = _font(17.0 * s)
        p.setFont(font)
        p.drawText(left, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
                   _elide(state.time, font, left.width()))

    # Right side: [badge] bars, Wi-Fi, [detail] battery, centred in the zone.
    p.setPen(Qt.PenStyle.NoPen)
    zone_left, zone_right = island.right() + 8 * s, screen.right() - 12 * s
    badge_font = _font(9.5 * s, QFont.Weight.Bold)
    detail_font = _font(12.0 * s)
    rows = [(state.primary_badge, state.bars)]
    if state.secondary_bars is not None:
        rows.append((state.secondary_badge, state.secondary_bars))
    badge_w = max((QFontMetricsF(badge_font).horizontalAdvance(b) + 5 * s for b, _ in rows if b), default=0.0)
    bars_w = (badge_w + 2 * s if badge_w else 0) + (4 * 3.0 + 3 * 1.5) * s
    pieces = []
    if state.show_cellular:
        pieces.append(("cell", bars_w))
    if state.wifi_bars is not None:
        pieces.append(("wifi", WIFI_W * s))
    if state.battery_detail and state.battery is not None:
        pieces.append(("detail", QFontMetricsF(detail_font).horizontalAdvance(state.battery_detail)))
    if state.battery is not None:
        pieces.append(("battery", 27.5 * s))
    gap = 5.0 * s
    total = sum(w for _, w in pieces) + gap * max(0, len(pieces) - 1)
    x = zone_left + max(0.0, (zone_right - zone_left - total) / 2)
    for kind, width in pieces:
        if kind == "cell":
            row_h = 11.5 * s if len(rows) == 1 else 5.5 * s
            for index, (badge, bars) in enumerate(rows):
                bottom = mid + row_h / 2 if len(rows) == 1 else mid - 0.7 * s + index * (row_h + 1.4 * s)
                bx = x
                if badge_w:
                    if badge:
                        p.setFont(badge_font)
                        p.setPen(_WHITE)
                        p.drawText(QRectF(bx, bottom - row_h - 1 * s, badge_w, row_h + 2 * s),
                                   Qt.AlignmentFlag.AlignCenter, badge)
                        p.setPen(Qt.PenStyle.NoPen)
                    bx += badge_w + 2 * s
                _paint_bars(p, bx, bottom, s, bars, row_h)
        elif kind == "wifi":
            _paint_wifi(p, x, mid + 6.0 * s, s, state.wifi_bars)
        elif kind == "detail":
            p.setFont(detail_font)
            p.setPen(_WHITE)
            p.drawText(QRectF(x, island.top(), width + 1, island.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, state.battery_detail)
            p.setPen(Qt.PenStyle.NoPen)
        elif kind == "battery":
            _paint_battery(p, x, mid, s, state.battery)
        x += width + gap
    p.restore()


class StatusBarPreview(QWidget):
    """Two cropped iPhone screen tops: Lock Screen and Home Screen."""

    GAP = 16
    LABEL_H = 24
    MAX_SCALE = 1.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = StatusBarPreviewState(
            carrier=QCoreApplication.translate("Nugget", "Carrier"),
            time=QTime.currentTime().toString("H:mm"))
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setAccessibleName(QCoreApplication.translate("Nugget", "Status bar preview"))

    def set_state(self, state: StatusBarPreviewState):
        self._state = state
        self.update()

    def state(self) -> StatusBarPreviewState:
        return self._state

    def _scale(self, width: int) -> float:
        crop_w = (width - self.GAP) / 2
        return max(0.4, min(self.MAX_SCALE, crop_w / DEVICE_PT_W))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(CROP_PT_H * self._scale(width)) + self.LABEL_H

    def sizeHint(self):
        return QSize(2 * int(DEVICE_PT_W) + self.GAP, self.heightForWidth(2 * int(DEVICE_PT_W) + self.GAP))

    def minimumSizeHint(self):
        return QSize(320, self.heightForWidth(320))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        s = self._scale(self.width())
        crop_w, crop_h = DEVICE_PT_W * s, CROP_PT_H * s
        x0 = (self.width() - (2 * crop_w + self.GAP)) / 2
        colors = ColorThemeManager.instance().colors
        titles = (QCoreApplication.translate("Nugget", "Lock Screen"),
                  QCoreApplication.translate("Nugget", "Home Screen"))
        for index, lock in enumerate((True, False)):
            crop = QRectF(x0 + index * (crop_w + self.GAP), 0, crop_w, crop_h)
            self._paint_crop(p, crop, s, lock)
            p.setPen(QColor(colors.text_secondary))
            p.setFont(_font(12, QFont.Weight.Medium))
            p.drawText(QRectF(crop.left(), crop.bottom() + 4, crop.width(), self.LABEL_H - 4),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, titles[index])
        p.end()

    def _paint_crop(self, p: QPainter, crop: QRectF, s: float, lock: bool):
        bezel = 6.0 * s
        radius = 47.0 * s
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(crop.left(), crop.top(), crop.width(), crop.height() + radius),
                             radius + bezel, radius + bezel)
        p.save()
        p.setClipRect(crop)
        p.fillPath(outer, _BEZEL)
        screen = QRectF(crop.left() + bezel, crop.top() + bezel,
                        crop.width() - 2 * bezel, crop.height() + radius)
        inner = QPainterPath()
        inner.addRoundedRect(screen, radius, radius)
        wallpaper = QLinearGradient(screen.topLeft(), screen.bottomRight())
        wallpaper.setColorAt(0.0, QColor(0x2B, 0x3A, 0x67))
        wallpaper.setColorAt(1.0, QColor(0x6A, 0x3E, 0x7C))
        p.fillPath(inner, wallpaper)
        p.setClipPath(inner, Qt.ClipOperation.IntersectClip)
        paint_status_bar(p, screen, self._state, lock)
        if lock:
            # The top of the Lock Screen date, so the crop reads as a Lock Screen.
            p.setPen(QColor(255, 255, 255, 220))
            p.setFont(_font(15.0 * s))
            p.drawText(QRectF(screen.left(), screen.top() + 60 * s, screen.width(), 22 * s),
                       Qt.AlignmentFlag.AlignHCenter,
                       QLocale().toString(QDate.currentDate(), "dddd, d MMMM"))
        p.restore()
