from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from src.gui.theme.colors import ACCENT_PRESETS
from src.gui.theme.theme_manager import ColorThemeManager

# Tooltip names, declared for lupdate; translated where the tooltip is set.
_ACCENT_NAMES = {
    "blue": QT_TRANSLATE_NOOP("Nugget", "Blue"),
    "purple": QT_TRANSLATE_NOOP("Nugget", "Purple"),
    "pink": QT_TRANSLATE_NOOP("Nugget", "Pink"),
    "red": QT_TRANSLATE_NOOP("Nugget", "Red"),
    "orange": QT_TRANSLATE_NOOP("Nugget", "Orange"),
    "yellow": QT_TRANSLATE_NOOP("Nugget", "Yellow"),
    "green": QT_TRANSLATE_NOOP("Nugget", "Green"),
    "teal": QT_TRANSLATE_NOOP("Nugget", "Teal"),
}


class AccentPicker(QWidget):
    """Row of colored circles for choosing the accent color."""

    accent_changed = Signal(str)

    _SIZE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tm = ColorThemeManager.instance()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._buttons: dict[str, QPushButton] = {}

        for name in ACCENT_PRESETS:
            btn = QPushButton(self)
            btn.setFixedSize(self._SIZE, self._SIZE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, n=name: self._on_click(n))
            btn.setToolTip(QCoreApplication.translate(
                "Nugget", _ACCENT_NAMES.get(name, name.capitalize())))
            self._buttons[name] = btn
            layout.addWidget(btn)
        layout.addStretch()

        self._tm.theme_changed.connect(self._retheme)
        self._retheme()

    def _on_click(self, name: str):
        self._tm.set_accent(name)
        self._highlight_selected()
        self.accent_changed.emit(name)

    def _highlight_selected(self):
        self._retheme()

    def _retheme(self):
        from src.gui.theme import themed_stylesheet
        for name, btn in self._buttons.items():
            btn.setChecked(name == self._tm.accent_name)
            btn.setStyleSheet(themed_stylesheet('accent_swatch', swatch=ACCENT_PRESETS[name][0]))
