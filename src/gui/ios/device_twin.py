"""Digital twin: the selected tweaks drawn on a full Lock Screen and Home Screen.

Works on preset-shaped data (``{"TweakName": {"enabled": ..., "value": ...}}``)
so the same picture is available for the current selection, a saved preset and
a setup someone shared as a code. Only tweaks with a visible result are drawn;
the rest are counted so the preview never pretends to show everything.

It is a drawing, not a screenshot: geometry follows an iPhone 15 Pro in points
(393 x 852), wallpapers come from a .tendies preview when one is available, and
stock apps are stylised tiles.
"""
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP, QDate, QLocale, QPointF, QRectF, QSize, Qt, QTime
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient, QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.gui.ios.statusbar_preview import (
    DEVICE_PT_W, StatusBarPreviewState, paint_status_bar, preview_state,
)
from src.gui.theme import ColorThemeManager

CONTEXT = "DeviceTwin"
DEVICE_PT_H = 852.0
# Home-button iPhones still supported by iOS 26 (SE 2nd and 3rd generation).
_HOME_BUTTON_MODELS = frozenset({"iPhone12,8", "iPhone14,6"})


def _tr(text):
    return QCoreApplication.translate(CONTEXT, text)


@dataclass
class TwinApp:
    name: str
    color: str = "#888888"
    glyph: str = ""
    color2: str = ""                 # bottom of the background gradient
    image: Optional[str] = None      # icon theme PNG
    show_label: bool = True
    kind: str = ""                   # "clock" / "calendar" draw live faces


@dataclass
class TwinState:
    status: StatusBarPreviewState
    cutout: str = "island"           # island / notch / none
    home_button: bool = False
    footnote: str = ""
    supervised: bool = False
    glass_clock: bool = True
    glass_dock: bool = True
    glass_icons: bool = True
    search_button: bool = True
    seconds_hand: bool = True
    rtl: bool = False
    build_label: str = ""
    themed: list = field(default_factory=list)
    wallpaper: Optional[str] = None  # image file
    stock_icons: dict = field(default_factory=dict)  # app name -> icon PNG from the iPhone
    shown: list = field(default_factory=list)    # translated effect names
    not_shown: int = 0


# Tweaks the twin can draw, with the legend text for each.
VISIBLE = {
    "StatusBar": QT_TRANSLATE_NOOP("DeviceTwin", "Status bar overrides"),
    "HideDICompletely": QT_TRANSLATE_NOOP("DeviceTwin", "Dynamic Island turned off"),
    "LockScreenFootnote": QT_TRANSLATE_NOOP("DeviceTwin", "Lock Screen footnote"),
    "SBShowSupervisionTextOnLockScreen": QT_TRANSLATE_NOOP("DeviceTwin", "Supervision text"),
    "NoLiquidClock": QT_TRANSLATE_NOOP("DeviceTwin", "Solid Lock Screen clock"),
    "NoLiquidDock": QT_TRANSLATE_NOOP("DeviceTwin", "Solid Dock"),
    "UseFlatIconsEverywhere": QT_TRANSLATE_NOOP("DeviceTwin", "Flat icons"),
    "SBHideSearchAffordance": QT_TRANSLATE_NOOP("DeviceTwin", "Search button hidden"),
    "SBHomeScreenShowsSearchButton": QT_TRANSLATE_NOOP("DeviceTwin", "Search button hidden"),
    "DisableSecondsHand": QT_TRANSLATE_NOOP("DeviceTwin", "Clock icon without seconds hand"),
    "SBBuildNumber": QT_TRANSLATE_NOOP("DeviceTwin", "Build number in the status bar"),
    "RTL": QT_TRANSLATE_NOOP("DeviceTwin", "Right-to-left layout"),
    "IconThemes": QT_TRANSLATE_NOOP("DeviceTwin", "Custom icons"),
    "PosterBoard": QT_TRANSLATE_NOOP("DeviceTwin", "Wallpaper"),
}

def _cutout_for(model: str, version: str) -> tuple:
    from src.devicemanagement.device_capabilities import has_dynamic_island
    model = str(model or "")
    if model in _HOME_BUTTON_MODELS:
        return "none", True
    if has_dynamic_island(model) or not model.startswith("iPhone"):
        return "island", False
    return "notch", False


def _effective(name, entry, version, model) -> bool:
    """Selected and able to run on this device (incompatible tweaks do nothing)."""
    from src.controllers.risk_assessment import is_selected
    from src.gui.ios.compat import compatibility_reasons
    from src.tweaks.tweak_names import TweakID
    if not is_selected(name, entry):
        return False
    if not version:
        return True
    try:
        return not compatibility_reasons(TweakID[name], version, model)
    except KeyError:
        return True


def _status_state(entry, version) -> StatusBarPreviewState:
    from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
    from src.controllers.preset_manager import PresetManager
    tweak = StatusBarTweak()
    if isinstance(entry, dict):
        PresetManager.__new__(PresetManager)._apply_status_bar(tweak, entry)
    ios27 = False
    try:
        ios27 = int(str(version).split(".")[0]) >= 27
    except ValueError:
        pass
    return preview_state(tweak, ios27)


def build_state(tweaks_data, version="", model="", build="", wallpaper=None) -> TwinState:
    """What the device would look like with ``tweaks_data`` applied."""
    from src.controllers.risk_assessment import is_selected
    data = tweaks_data or {}
    on = {name for name, entry in data.items() if _effective(name, entry, version, model)}
    cutout, home_button = _cutout_for(model, version)
    state = TwinState(status=_status_state(data.get("StatusBar"), version),
                      cutout=cutout, home_button=home_button)
    if "HideDICompletely" in on and cutout == "island":
        state.cutout = "none"
    if "LockScreenFootnote" in on:
        state.footnote = str(data["LockScreenFootnote"].get("value") or "")
    state.supervised = "SBShowSupervisionTextOnLockScreen" in on
    state.glass_clock = "NoLiquidClock" not in on
    state.glass_dock = "NoLiquidDock" not in on
    state.glass_icons = "UseFlatIconsEverywhere" not in on
    state.search_button = not {"SBHideSearchAffordance", "SBHomeScreenShowsSearchButton"}.intersection(on)
    state.seconds_hand = "DisableSecondsHand" not in on
    state.rtl = "RTL" in on
    if "SBBuildNumber" in on:
        state.build_label = build or _tr("Build")
    for theme in (data.get("IconThemes") or {}).get("themes", []) if "IconThemes" in on else []:
        if isinstance(theme, dict):
            label = str(theme.get("display_name") or "")
            state.themed.append(TwinApp(label, image=theme.get("icon_path") or None,
                                        show_label=bool(label)))
    if wallpaper:
        state.wallpaper = wallpaper
        on.add("PosterBoard")
    stock = _status_state(None, version)
    stock.time = state.status.time
    if "StatusBar" in on and state.status == stock:
        on.discard("StatusBar")   # switched on without any override
    shown = [name for name in VISIBLE if name in on]
    state.shown = [_tr(VISIBLE[name]) for name in shown]
    state.not_shown = sum(1 for name, entry in data.items()
                          if name not in VISIBLE and is_selected(name, entry))
    return state


def current_wallpaper() -> Optional[str]:
    """Preview image of the first queued PosterBoard wallpaper, if it can be made."""
    try:
        from src.gui.preview.tendie_preview import extract_tendie_preview
        from src.tweaks.tweaks import tweaks, TweakID
        board = tweaks.get(TweakID.PosterBoard)
        for item in getattr(board, "tendies", [])[:1]:
            if getattr(item, "path", None):
                return extract_tendie_preview(item.path)
    except Exception:
        return None
    return None


# --- painting -------------------------------------------------------------

# (name, gradient top, gradient bottom, pictogram) -- stand-ins drawn in
# code below, not Apple artwork.
_STOCK = (
    (QT_TRANSLATE_NOOP("DeviceTwin", "FaceTime"), "#5EE07A", "#1FB84A", "facetime"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Calendar"), "#FFFFFF", "#FFFFFF", "calendar"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Photos"), "#FFFFFF", "#F2F2F7", "photos"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Camera"), "#D8D8DD", "#8E8E93", "camera"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Mail"), "#5AC8FA", "#1A73F0", "mail"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Notes"), "#FFFFFF", "#F7F7F7", "notes"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Reminders"), "#FFFFFF", "#F7F7F7", "reminders"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Clock"), "#000000", "#000000", "clock"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Weather"), "#5AAEFA", "#1C5BD4", "weather"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Maps"), "#F4F1E6", "#D9EDCF", "maps"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Music"), "#FF6378", "#F7223C", "music"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Settings"), "#D1D1D6", "#8E8E93", "settings"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "App Store"), "#1BC9FB", "#1871E8", "appstore"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Wallet"), "#2C2C2E", "#000000", "wallet"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Health"), "#FFFFFF", "#F7F7F7", "health"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Files"), "#FFFFFF", "#F2F2F7", "files"),
)
_DOCK = (
    (QT_TRANSLATE_NOOP("DeviceTwin", "Phone"), "#5EE07A", "#1FB84A", "phone"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Safari"), "#FFFFFF", "#E5E5EA", "safari"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Messages"), "#5EE07A", "#1FB84A", "messages"),
    (QT_TRANSLATE_NOOP("DeviceTwin", "Music"), "#FF6378", "#F7223C", "music"),
)


def _font(px, weight=QFont.Weight.DemiBold):
    font = QFont()
    font.setPixelSize(max(1, round(px)))
    font.setWeight(weight)
    return font


def _app(entry, icons=None):
    name, top, bottom, kind = entry
    return TwinApp(name, top, color2=bottom, kind=kind, image=(icons or {}).get(name))


# --- pictograms -----------------------------------------------------------
# Each draws into a unit square (the painter is scaled to the icon), so the
# shapes stay crisp at any preview size.

def _stroke(p, color, width):
    p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _fill(p, color):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))


def _poly(*points):
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    return path


def _pict_facetime(p):
    _fill(p, "#FFFFFF")
    p.drawRoundedRect(QRectF(0.17, 0.32, 0.42, 0.36), 0.08, 0.08)
    p.drawPath(_poly((0.62, 0.47), (0.83, 0.33), (0.83, 0.67), (0.62, 0.53)))


def _pict_photos(p):
    colors = ("#F9C21B", "#F68B1F", "#EE3E37", "#C2378F", "#7E57C2", "#2A8FD8", "#3DB54A", "#A5CD39")
    p.setPen(Qt.PenStyle.NoPen)
    for index, color in enumerate(colors):
        p.save()
        p.translate(0.5, 0.5)
        p.rotate(index * 45)
        petal = QColor(color)
        petal.setAlpha(215)
        p.setBrush(petal)
        p.drawRoundedRect(QRectF(-0.085, -0.37, 0.17, 0.3), 0.085, 0.085)
        p.restore()


def _pict_camera(p):
    _fill(p, "#2C2C2E")
    p.drawRoundedRect(QRectF(0.36, 0.25, 0.28, 0.12), 0.04, 0.04)
    p.drawRoundedRect(QRectF(0.14, 0.31, 0.72, 0.45), 0.1, 0.1)
    _fill(p, "#636366")
    p.drawEllipse(QPointF(0.5, 0.535), 0.165, 0.165)
    _fill(p, "#0B0B0D")
    p.drawEllipse(QPointF(0.5, 0.535), 0.115, 0.115)
    _fill(p, "#5A6B8C")
    p.drawEllipse(QPointF(0.47, 0.505), 0.035, 0.035)
    _fill(p, "#FFD60A")
    p.drawEllipse(QPointF(0.76, 0.39), 0.025, 0.025)


def _pict_mail(p):
    _fill(p, "#FFFFFF")
    p.drawRoundedRect(QRectF(0.17, 0.29, 0.66, 0.44), 0.06, 0.06)
    _stroke(p, "#2F8CF5", 0.035)
    path = QPainterPath(QPointF(0.2, 0.33))
    path.lineTo(0.5, 0.55)
    path.lineTo(0.8, 0.33)
    p.drawPath(path)


def _pict_notes(p):
    band = QLinearGradient(0, 0, 0, 0.27)
    band.setColorAt(0, QColor("#FFE45C"))
    band.setColorAt(1, QColor("#FFC800"))
    p.fillRect(QRectF(0, 0, 1, 0.27), band)
    _stroke(p, "#C7C7CC", 0.022)
    for y in (0.45, 0.6, 0.75):
        p.drawLine(QPointF(0.14, y), QPointF(0.86, y))


def _pict_reminders(p):
    for y, color in ((0.3, "#0A84FF"), (0.5, "#FF3B30"), (0.7, "#FF9500")):
        _fill(p, color)
        p.drawEllipse(QPointF(0.25, y), 0.07, 0.07)
        _fill(p, "#FFFFFF")
        p.drawEllipse(QPointF(0.25, y), 0.035, 0.035)
        _stroke(p, "#D1D1D6", 0.035)
        p.drawLine(QPointF(0.42, y), QPointF(0.82, y))


def _pict_weather(p):
    _fill(p, "#FFD60A")
    p.drawEllipse(QPointF(0.4, 0.38), 0.16, 0.16)
    cloud = QPainterPath()
    cloud.addEllipse(QPointF(0.44, 0.62), 0.13, 0.13)
    cloud.addEllipse(QPointF(0.61, 0.55), 0.16, 0.16)
    cloud.addEllipse(QPointF(0.76, 0.65), 0.1, 0.1)
    cloud.addRoundedRect(QRectF(0.31, 0.6, 0.55, 0.15), 0.075, 0.075)
    cloud.setFillRule(Qt.FillRule.WindingFill)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(cloud)


def _pict_maps(p):
    _fill(p, "#A8D98F")
    p.drawRoundedRect(QRectF(-0.1, -0.1, 0.45, 0.42), 0.1, 0.1)
    _fill(p, "#8CCBF5")
    p.drawRoundedRect(QRectF(0.62, 0.64, 0.5, 0.5), 0.12, 0.12)
    _stroke(p, "#FFFFFF", 0.16)
    p.drawLine(QPointF(-0.05, 1.05), QPointF(1.05, -0.05))
    _stroke(p, "#FFCC33", 0.03)
    p.drawLine(QPointF(-0.05, 1.05), QPointF(1.05, -0.05))
    p.setPen(QPen(QColor("#FFFFFF"), 0.04, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor("#0A84FF"))
    p.drawPath(_poly((0.5, 0.3), (0.67, 0.7), (0.5, 0.61), (0.33, 0.7)))


def _pict_music(p):
    _fill(p, "#FFFFFF")
    p.drawPath(_poly((0.4, 0.3), (0.74, 0.22), (0.74, 0.32), (0.4, 0.4)))
    p.drawRect(QRectF(0.4, 0.3, 0.05, 0.4))
    p.drawRect(QRectF(0.69, 0.22, 0.05, 0.4))
    for x, y in ((0.35, 0.7), (0.64, 0.62)):
        p.save()
        p.translate(x, y)
        p.rotate(-20)
        p.drawEllipse(QPointF(0, 0), 0.1, 0.075)
        p.restore()


def _pict_settings(p):
    p.setPen(Qt.PenStyle.NoPen)
    gear = QPainterPath()
    gear.addEllipse(QPointF(0.5, 0.5), 0.29, 0.29)
    tooth = QPainterPath()
    tooth.addRoundedRect(QRectF(-0.05, -0.38, 0.1, 0.14), 0.02, 0.02)
    for index in range(12):
        gear.addPath(QTransform().translate(0.5, 0.5).rotate(index * 30).map(tooth))
    gear.setFillRule(Qt.FillRule.WindingFill)
    p.setBrush(QColor("#3A3A3C"))
    p.drawPath(gear)
    p.setBrush(QColor("#B8B8BD"))
    p.drawEllipse(QPointF(0.5, 0.5), 0.19, 0.19)
    p.setBrush(QColor("#3A3A3C"))
    p.drawEllipse(QPointF(0.5, 0.5), 0.07, 0.07)


def _pict_appstore(p):
    _stroke(p, "#FFFFFF", 0.075)
    p.drawLine(QPointF(0.56, 0.23), QPointF(0.31, 0.7))
    p.drawLine(QPointF(0.44, 0.23), QPointF(0.69, 0.7))
    p.drawLine(QPointF(0.24, 0.58), QPointF(0.76, 0.58))


def _pict_wallet(p):
    colors = ("#0A84FF", "#30D158", "#FFD60A", "#FF9F0A", "#FF453A")
    for index, color in enumerate(colors):
        _fill(p, color)
        p.drawRoundedRect(QRectF(0.17, 0.22 + index * 0.065, 0.66, 0.2), 0.05, 0.05)
    _fill(p, "#48484A")
    p.drawRoundedRect(QRectF(0.13, 0.5, 0.74, 0.3), 0.07, 0.07)


def _pict_health(p):
    heart = QPainterPath(QPointF(0.5, 0.78))
    heart.cubicTo(0.16, 0.56, 0.15, 0.3, 0.33, 0.26)
    heart.cubicTo(0.42, 0.24, 0.48, 0.3, 0.5, 0.35)
    heart.cubicTo(0.52, 0.3, 0.58, 0.24, 0.67, 0.26)
    heart.cubicTo(0.85, 0.3, 0.84, 0.56, 0.5, 0.78)
    gradient = QLinearGradient(0, 0.25, 0, 0.8)
    gradient.setColorAt(0, QColor("#FF6482"))
    gradient.setColorAt(1, QColor("#FF2D55"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawPath(heart)


def _pict_files(p):
    _fill(p, "#3D9BF5")
    p.drawRoundedRect(QRectF(0.15, 0.27, 0.32, 0.16), 0.05, 0.05)
    body = QLinearGradient(0, 0.33, 0, 0.78)
    body.setColorAt(0, QColor("#62B8FF"))
    body.setColorAt(1, QColor("#1D8BF1"))
    p.setBrush(body)
    p.drawRoundedRect(QRectF(0.15, 0.34, 0.7, 0.44), 0.07, 0.07)


def _pict_phone(p):
    # handset drawn level (handle up, cups down), then turned so the earpiece
    # sits top-left and the mouthpiece bottom-right
    handset = QPainterPath(QPointF(-0.34, 0.13))
    handset.lineTo(-0.34, 0.0)
    handset.cubicTo(-0.34, -0.22, 0.34, -0.22, 0.34, 0.0)
    handset.lineTo(0.34, 0.13)
    handset.lineTo(0.15, 0.13)
    handset.lineTo(0.15, 0.04)
    handset.cubicTo(0.15, -0.07, -0.15, -0.07, -0.15, 0.04)
    handset.lineTo(-0.15, 0.13)
    handset.closeSubpath()
    p.save()
    p.translate(0.5, 0.5)
    p.rotate(225)
    p.translate(0, 0.02)
    p.setPen(QPen(QColor("#FFFFFF"), 0.06, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(handset)
    p.restore()


def _pict_safari(p):
    disc = QLinearGradient(0, 0.12, 0, 0.88)
    disc.setColorAt(0, QColor("#4FC3F7"))
    disc.setColorAt(1, QColor("#1565E0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(disc)
    p.drawEllipse(QPointF(0.5, 0.5), 0.39, 0.39)
    _stroke(p, "#FFFFFF", 0.012)
    import math
    for index in range(24):
        a = math.radians(index * 15)
        inner = 0.3 if index % 2 else 0.27
        p.drawLine(QPointF(0.5 + math.sin(a) * inner, 0.5 - math.cos(a) * inner),
                   QPointF(0.5 + math.sin(a) * 0.34, 0.5 - math.cos(a) * 0.34))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FF3B30"))
    p.drawPath(_poly((0.5, 0.5), (0.45, 0.45), (0.72, 0.28), (0.55, 0.55)))
    p.setBrush(QColor("#FFFFFF"))
    p.drawPath(_poly((0.5, 0.5), (0.55, 0.55), (0.28, 0.72), (0.45, 0.45)))


def _pict_messages(p):
    _fill(p, "#FFFFFF")
    p.drawEllipse(QPointF(0.5, 0.47), 0.33, 0.27)
    tail = QPainterPath(QPointF(0.28, 0.6))
    tail.quadTo(0.27, 0.72, 0.18, 0.78)
    tail.quadTo(0.35, 0.78, 0.45, 0.69)
    tail.closeSubpath()
    p.drawPath(tail)


_PICTOGRAMS = {
    "facetime": _pict_facetime, "photos": _pict_photos, "camera": _pict_camera,
    "mail": _pict_mail, "notes": _pict_notes, "reminders": _pict_reminders,
    "weather": _pict_weather, "maps": _pict_maps, "music": _pict_music,
    "settings": _pict_settings, "appstore": _pict_appstore, "wallet": _pict_wallet,
    "health": _pict_health, "files": _pict_files, "phone": _pict_phone,
    "safari": _pict_safari, "messages": _pict_messages,
}


def _paint_wallpaper(p, screen, state, images):
    image = images.get(state.wallpaper) if state.wallpaper else None
    if image is not None and not image.isNull():
        scaled = image.scaled(screen.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QPointF(screen.center().x() - scaled.width() / 2,
                            screen.center().y() - scaled.height() / 2), scaled)
        return
    gradient = QLinearGradient(screen.topLeft(), screen.bottomRight())
    gradient.setColorAt(0.0, QColor(0x2B, 0x3A, 0x67))
    gradient.setColorAt(0.55, QColor(0x5B, 0x3F, 0x84))
    gradient.setColorAt(1.0, QColor(0xC0, 0x5A, 0x7A))
    p.fillRect(screen, gradient)


def _glass(p, rect, radius, s, strong=True):
    """Liquid Glass approximation: translucent fill, bright rim, top highlight."""
    p.setPen(QPen(QColor(255, 255, 255, 120 if strong else 70), 1.0 * s))
    p.setBrush(QColor(255, 255, 255, 46 if strong else 30))
    p.drawRoundedRect(rect, radius, radius)
    shine = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    shine.setColorAt(0.0, QColor(255, 255, 255, 70))
    shine.setColorAt(0.45, QColor(255, 255, 255, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shine)
    p.drawRoundedRect(rect, radius, radius)


def _paint_icon(p, rect, app, s, glass, images, seconds_hand=True, now=None):
    radius = rect.width() * 0.225
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    image = images.get(app.image) if app.image else None
    if image is not None and not image.isNull():
        p.drawImage(rect, image)
    else:
        if app.color2:
            background = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            background.setColorAt(0, QColor(app.color))
            background.setColorAt(1, QColor(app.color2))
            p.fillPath(path, background)
        else:
            p.fillPath(path, QColor(app.color))
        light = QColor(app.color).lightness() > 200
        ink = QColor(0x1C, 0x1C, 0x1E) if light else QColor(255, 255, 255)
        if app.kind == "clock":
            _paint_clock_face(p, rect, s, seconds_hand, now or QTime.currentTime())
        elif app.kind == "calendar":
            p.setPen(QColor(0xFF, 0x3B, 0x30))
            p.setFont(_font(rect.height() * 0.17, QFont.Weight.Bold))
            p.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.08, rect.width(), rect.height() * 0.22),
                       Qt.AlignmentFlag.AlignCenter, QLocale().toString(QDate.currentDate(), "ddd").upper())
            p.setPen(ink)
            p.setFont(_font(rect.height() * 0.5, QFont.Weight.Normal))
            p.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.28, rect.width(), rect.height() * 0.62),
                       Qt.AlignmentFlag.AlignCenter, str(QDate.currentDate().day()))
        elif app.kind in _PICTOGRAMS:
            p.save()
            p.translate(rect.topLeft())
            p.scale(rect.width(), rect.height())
            _PICTOGRAMS[app.kind](p)
            p.restore()
        else:
            p.setPen(ink)
            p.setFont(_font(rect.height() * 0.46, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, app.glyph)
    if glass:
        shine = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        shine.setColorAt(0.0, QColor(255, 255, 255, 95))
        shine.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillPath(path, shine)
    p.restore()
    if glass:
        p.setPen(QPen(QColor(255, 255, 255, 110), 0.9 * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


def _paint_clock_face(p, rect, s, seconds_hand, now):
    import math
    c = rect.center()
    r = rect.width() * 0.42
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(c, r, r)
    p.setPen(QPen(QColor(0x1C, 0x1C, 0x1E), 0.8 * s))
    for i in range(12):
        a = math.radians(i * 30)
        p.drawLine(QPointF(c.x() + math.sin(a) * r * 0.82, c.y() - math.cos(a) * r * 0.82),
                   QPointF(c.x() + math.sin(a) * r * 0.95, c.y() - math.cos(a) * r * 0.95))

    def hand(angle, length, width, color):
        a = math.radians(angle)
        p.setPen(QPen(QColor(color), width * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(c, QPointF(c.x() + math.sin(a) * r * length, c.y() - math.cos(a) * r * length))

    hand((now.hour() % 12 + now.minute() / 60) * 30, 0.5, 2.6, "#1C1C1E")
    hand(now.minute() * 6, 0.75, 2.0, "#1C1C1E")
    if seconds_hand:
        hand(now.second() * 6, 0.85, 0.9, "#FF9500")


def _paint_frame(p, rect, s, state):
    """Phone body; returns the screen rect."""
    body = QPainterPath()
    body.addRoundedRect(rect, 60 * s, 60 * s)
    p.fillPath(body, QColor(0x2C, 0x2C, 0x2E))
    inner = QPainterPath()
    inner.addRoundedRect(rect.adjusted(2 * s, 2 * s, -2 * s, -2 * s), 58 * s, 58 * s)
    p.fillPath(inner, QColor(0x0B, 0x0B, 0x0C))
    bezel = 10 * s
    if state.home_button:
        screen = QRectF(rect.left() + bezel * 1.6, rect.top() + 88 * s,
                        rect.width() - bezel * 3.2, rect.height() - 176 * s)
        p.setPen(QPen(QColor(0x5A, 0x5A, 0x5E), 2 * s))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(rect.center().x(), rect.bottom() - 44 * s), 26 * s, 26 * s)
        return screen, 0.0
    return rect.adjusted(bezel, bezel, -bezel, -bezel), 50 * s


def paint_lock_screen(p, screen, s, state, images):
    _paint_wallpaper(p, screen, state, images)
    paint_status_bar(p, screen, state.status, True, cutout=state.cutout)
    date = QLocale().toString(QDate.currentDate(), "dddd, d MMMM")
    p.setPen(QColor(255, 255, 255, 225))
    p.setFont(_font(17 * s))
    p.drawText(QRectF(screen.left(), screen.top() + 66 * s, screen.width(), 24 * s),
               Qt.AlignmentFlag.AlignCenter, date)
    clock_rect = QRectF(screen.left(), screen.top() + 84 * s, screen.width(), 112 * s)
    time = QTime.currentTime().toString("H:mm")
    font = _font(100 * s, QFont.Weight.Bold)
    if state.glass_clock:
        path = QPainterPath()
        metrics = QFontMetricsF(font)
        width = metrics.horizontalAdvance(time)
        path.addText(QPointF(clock_rect.center().x() - width / 2, clock_rect.bottom() - 18 * s), font, time)
        fill = QLinearGradient(clock_rect.topLeft(), clock_rect.bottomLeft())
        fill.setColorAt(0.0, QColor(255, 255, 255, 150))
        fill.setColorAt(1.0, QColor(255, 255, 255, 60))
        p.setPen(QPen(QColor(255, 255, 255, 210), 1.4 * s))
        p.setBrush(fill)
        p.drawPath(path)
    else:
        p.setPen(QColor(255, 255, 255))
        p.setFont(font)
        p.drawText(clock_rect, Qt.AlignmentFlag.AlignCenter, time)

    bottom = screen.bottom() - (34 * s if not state.home_button else 12 * s)
    lines = []
    if state.supervised:
        lines.append(_tr("This iPhone is supervised and managed."))
    if state.footnote:
        lines.append(state.footnote)
    if lines:
        p.setPen(QColor(255, 255, 255, 230))
        p.setFont(_font(12 * s, QFont.Weight.Medium))
        text_rect = QRectF(screen.left() + 70 * s, bottom - 96 * s, screen.width() - 140 * s, 40 * s)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
                   | Qt.TextFlag.TextWordWrap, "\n".join(lines))
    if not state.home_button:
        for cx in (screen.left() + 64 * s, screen.right() - 64 * s):
            circle = QRectF(cx - 25 * s, bottom - 62 * s, 50 * s, 50 * s)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawEllipse(circle)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRoundedRect(QRectF(screen.center().x() - 67 * s, screen.bottom() - 13 * s, 134 * s, 5 * s),
                          2.5 * s, 2.5 * s)


def paint_home_screen(p, screen, s, state, images):
    _paint_wallpaper(p, screen, state, images)
    status = state.status
    if state.build_label:
        status = StatusBarPreviewState(**{**status.__dict__, "time": state.build_label})
    paint_status_bar(p, screen, status, False, cutout=state.cutout)
    apps = [_app(entry, state.stock_icons) for entry in _STOCK] + list(state.themed)
    apps = apps[:24]
    icon = 62 * s
    margin = 27 * s
    gap = (screen.width() - 2 * margin - 4 * icon) / 3
    top = screen.top() + 72 * s
    label_font = _font(11.5 * s, QFont.Weight.Medium)
    for index, app in enumerate(apps):
        row, col = divmod(index, 4)
        if state.rtl:
            col = 3 - col
        rect = QRectF(screen.left() + margin + col * (icon + gap), top + row * 94 * s, icon, icon)
        _paint_icon(p, rect, app, s, state.glass_icons, images, state.seconds_hand)
        if app.show_label:
            p.setPen(QColor(255, 255, 255))
            p.setFont(label_font)
            name = _tr(app.name) if app.kind or not app.image else app.name
            p.drawText(QRectF(rect.left() - gap / 2, rect.bottom() + 4 * s, icon + gap, 16 * s),
                       Qt.AlignmentFlag.AlignHCenter,
                       QFontMetricsF(label_font).elidedText(name, Qt.TextElideMode.ElideRight, icon + gap))

    dock_h = 92 * s
    dock = QRectF(screen.left() + 12 * s, screen.bottom() - dock_h - (20 * s if not state.home_button else 6 * s),
                  screen.width() - 24 * s, dock_h)
    if state.search_button:
        # hugs its label like the iOS pill: magnifier + text, slim padding
        font = _font(13 * s, QFont.Weight.DemiBold)
        label = _tr("Search")
        text_w = QFontMetricsF(font).horizontalAdvance(label)
        glyph, pad, space = 10 * s, 10 * s, 4 * s
        width = pad + glyph + space + text_w + pad
        pill = QRectF(screen.center().x() - width / 2, dock.top() - 36 * s, width, 26 * s)
        p.setPen(QPen(QColor(255, 255, 255, 60), 0.6 * s))
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        ink = QColor(255, 255, 255, 235)
        lens = QPointF(pill.left() + pad + glyph * 0.42, pill.center().y() - glyph * 0.08)
        p.setPen(QPen(ink, 1.5 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(lens, glyph * 0.34, glyph * 0.34)
        p.drawLine(QPointF(lens.x() + glyph * 0.25, lens.y() + glyph * 0.25),
                   QPointF(pill.left() + pad + glyph, lens.y() + glyph * 0.58))
        p.setPen(ink)
        p.setFont(font)
        p.drawText(QRectF(pill.left() + pad + glyph + space, pill.top(), text_w + 1, pill.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
    if state.glass_dock:
        _glass(p, dock, 34 * s, s)
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0x3A, 0x3A, 0x3C, 215))
        p.drawRoundedRect(dock, 34 * s, 34 * s)
    dock_apps = [_app(entry, state.stock_icons) for entry in _DOCK]
    if state.rtl:
        dock_apps.reverse()
    step = (dock.width() - 4 * icon) / 5
    for index, app in enumerate(dock_apps):
        rect = QRectF(dock.left() + step + index * (icon + step), dock.center().y() - icon / 2, icon, icon)
        _paint_icon(p, rect, app, s, state.glass_icons, images, state.seconds_hand)
    if not state.home_button:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRoundedRect(QRectF(screen.center().x() - 67 * s, screen.bottom() - 13 * s, 134 * s, 5 * s),
                          2.5 * s, 2.5 * s)


class DeviceTwinView(QWidget):
    """Lock Screen and Home Screen side by side, each in a full phone frame."""

    GAP = 28
    LABEL_H = 26

    def __init__(self, state: TwinState, parent=None):
        super().__init__(parent)
        self._images = {}
        self.set_state(state)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setSizePolicy(policy)
        self.setAccessibleName(_tr("iPhone preview"))

    def set_state(self, state: TwinState):
        self.state = state
        self._images = {}
        for path in [state.wallpaper, *state.stock_icons.values()] + [app.image for app in state.themed]:
            if path and path not in self._images:
                self._images[path] = QImage(path)
        self.update()

    def sizeHint(self):
        return QSize(640, 700)

    def minimumSizeHint(self):
        return QSize(360, 420)

    def _phone_rect(self, index):
        frame_w = DEVICE_PT_W + 20
        frame_h = DEVICE_PT_H + 20
        avail_h = self.height() - self.LABEL_H
        scale = min((self.width() - self.GAP) / (2 * frame_w), avail_h / frame_h)
        w, h = frame_w * scale, frame_h * scale
        x0 = (self.width() - (2 * w + self.GAP)) / 2
        return QRectF(x0 + index * (w + self.GAP), 0, w, h), scale

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        colors = ColorThemeManager.instance().colors
        titles = (QCoreApplication.translate("Nugget", "Lock Screen"),
                  QCoreApplication.translate("Nugget", "Home Screen"))
        for index, painter in enumerate((paint_lock_screen, paint_home_screen)):
            rect, s = self._phone_rect(index)
            screen, radius = _paint_frame(p, rect, s, self.state)
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(screen, radius, radius)
            p.setClipPath(clip)
            painter(p, screen, s, self.state, self._images)
            p.restore()
            p.setPen(QColor(colors.text_secondary))
            p.setFont(_font(13, QFont.Weight.Medium))
            p.drawText(QRectF(rect.left(), rect.bottom() + 6, rect.width(), self.LABEL_H - 6),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, titles[index])
        p.end()
