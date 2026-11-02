"""Window-wide stylesheet overlay for the liquid shell.

These rules used to be appended to the window stylesheet by
``LiquidExperience._style`` *after* the whole page tree existed. Every
``QWidget.setStyleSheet`` on the window re-polishes all descendants, so that
second application walked thousands of widgets on the startup path (~0.3 s).
The overlay is now composed into the single stylesheet MainWindow applies
before the pages are built; ``_style`` only restyles the navigation bar.
"""
from src.gui.theme.theme_manager import ColorThemeManager


def liquid_overlay_css(colors=None) -> str:
    """Form-control/scrollbar/slider rules for the current palette."""
    c = colors or ColorThemeManager.instance().colors
    return f'''
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background:{c.bg_secondary}; border:1px solid {c.border};
            border-radius:12px; padding:9px 12px; selection-background-color:{c.accent};
        }}
        QLineEdit:focus, QComboBox:focus {{ border:1px solid {c.accent}; }}
        QScrollBar:vertical {{ width:7px; background:transparent; margin:5px 0; }}
        QScrollBar::handle:vertical {{ background:{c.border}; border-radius:3px; min-height:30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        QSlider::groove:horizontal {{ height:5px; background:{c.border}; border-radius:2px; }}
        QSlider::handle:horizontal {{ width:17px; margin:-6px 0; border-radius:8px; background:{c.accent}; }}
    '''
