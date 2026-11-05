from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QFrame

from src.gui.theme import ColorThemeManager, t


class HomeWidgetPickerDialog(QDialog):
    """First-launch dialog: pick the home top-bar widget.

    ``choice`` is ``"storage"`` or ``"presets"`` once the user picks an option.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Choose Home Widget"))
        self.setFixedWidth(420)
        self.choice = None  # "storage" | "presets"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel(QCoreApplication.translate("Nugget", "Customize your Home screen"))
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._subtitle = QLabel(QCoreApplication.translate(
            "Nugget", "Which widget should appear next to the device picker?"))
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        layout.addSpacing(8)

        self._storage_frame = QFrame()
        sf_lay = QVBoxLayout(self._storage_frame)
        sf_lay.setContentsMargins(16, 12, 16, 12)
        sf_title = QLabel(QCoreApplication.translate("Nugget", "Device Storage"))
        sf_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        self._sf_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Shows the connected iPhone's used and free space."))
        self._sf_desc.setWordWrap(True)
        sf_lay.addWidget(sf_title)
        sf_lay.addWidget(self._sf_desc)
        self._storage_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._storage_frame.mousePressEvent = lambda e: self._pick("storage")
        layout.addWidget(self._storage_frame)

        self._presets_frame = QFrame()
        pf_lay = QVBoxLayout(self._presets_frame)
        pf_lay.setContentsMargins(16, 12, 16, 12)
        pf_title = QLabel(QCoreApplication.translate("Nugget", "Presets"))
        pf_title.setStyleSheet("font-size: 16px; font-weight: 600; border: none;")
        self._pf_desc = QLabel(QCoreApplication.translate(
            "Nugget", "Shows the active preset and opens the preset manager."))
        self._pf_desc.setWordWrap(True)
        pf_lay.addWidget(pf_title)
        pf_lay.addWidget(self._pf_desc)
        self._presets_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self._presets_frame.mousePressEvent = lambda e: self._pick("presets")
        layout.addWidget(self._presets_frame)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; background: transparent; }}
        """)
        self._subtitle.setStyleSheet(f"color: {c.text_secondary}; font-size: 14px;")
        self._storage_frame.setStyleSheet(f"""
            QFrame {{ background-color: {c.surface_hover}; border-radius: 12px; }}
            QFrame:hover {{ background-color: {c.border}; }}
        """)
        self._sf_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; border: none;")
        self._presets_frame.setStyleSheet(f"""
            QFrame {{ background-color: {c.surface_hover}; border-radius: 12px; }}
            QFrame:hover {{ background-color: {c.border}; }}
        """)
        self._pf_desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; border: none;")

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()
