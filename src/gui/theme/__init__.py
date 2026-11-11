from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBitmap, QColor, QIcon, QImage, QPainter, QPixmap, QRegion

from src.gui.theme.accent_picker import AccentPicker
from src.gui.theme.colors import ACCENT_PRESETS, DARK
from src.gui.theme.styles import FONT_FAMILY, STYLES
from src.gui.theme.theme_manager import ColorThemeManager


def t(style_key: str) -> str:
    """Render a named stylesheet template with the current theme colors."""
    payload = dict(ColorThemeManager.instance().colors.__dict__)
    payload["font_family"] = FONT_FAMILY
    return STYLES[style_key].format_map(payload)


def themed_stylesheet(style_key: str, **extra) -> str:
    """Render a stylesheet template with the current colors plus runtime
    extras (e.g. a generated caret image path passed as ``caret=...``)."""
    payload = dict(ColorThemeManager.instance().colors.__dict__)
    payload["font_family"] = FONT_FAMILY
    payload.update(extra)
    return STYLES[style_key].format_map(payload)


@lru_cache(maxsize=256)
def theme_icon(resource_path: str, color_hex: str) -> QIcon:
    """Tint monochrome SVGs while preserving supplied raster artwork."""
    if resource_path.startswith(':/icon/features/') and resource_path.lower().endswith('.png'):
        return QIcon(theme_pixmap(resource_path, color_hex, 64))
    if not resource_path.lower().endswith('.svg'):
        return QIcon(resource_path)
    img = QImage(resource_path)
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(img.rect(), QColor(color_hex))
    painter.end()
    return QIcon(QPixmap.fromImage(img))


@lru_cache(maxsize=128)
def theme_pixmap(resource_path: str, color_hex: str, size: int,
                 dpr: float = 1.0) -> QPixmap:
    """Fit artwork to *size* logical pixels, tinting only monochrome SVGs.

    Unlike ``theme_icon`` the icon is scaled by the SVG engine *before* the
    tint is applied, so icons with a small viewBox (11x11, 16x16) stay crisp
    when blown up to home-tile size. ``dpr`` renders extra device pixels on
    HiDPI screens and sets the pixmap's device pixel ratio accordingly.
    """
    scale = max(1.0, float(dpr))
    logical = int(round(size))
    phys = int(round(size * scale))
    pm = QPixmap(phys, phys)
    pm.setDevicePixelRatio(scale)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    if not resource_path.lower().endswith('.svg'):
        source = resource_path
        if resource_path.startswith(':/icon/features/'):
            artwork = Path(__file__).resolve().parents[2] / 'qt' / resource_path[2:]
            if artwork.is_file():
                source = str(artwork)
        image = QImage(source)
        if not image.isNull():
            if resource_path.startswith(':/icon/features/'):
                bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
                if not bounds.isEmpty():
                    image = image.copy(bounds.adjusted(-2, -2, 2, 2).intersected(image.rect()))
            factor = logical / max(image.width(), image.height())
            width, height = image.width() * factor, image.height() * factor
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(QRectF((logical - width) / 2, (logical - height) / 2, width, height), image)
        painter.end()
        return pm
    src = QIcon(resource_path).pixmap(QSize(logical, logical))
    painter.drawPixmap(QRect(0, 0, logical, logical), src)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(QRect(0, 0, logical, logical), QColor(color_hex))
    painter.end()
    return pm


__all__ = [
    "ColorThemeManager", "DARK", "ACCENT_PRESETS", "STYLES", "FONT_FAMILY",
    "AccentPicker", "t", "themed_stylesheet", "theme_icon", "theme_pixmap",
]
