"""Reusable preset banner widget.

Shows which preset is currently active (making presets explicit) and a
shortcut to open the preset manager. Used on both the classic and the
iOS-style home pages so the active state is always visible.
"""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from src.gui.theme import ColorThemeManager


class PresetBanner(QFrame):
    """A card that displays the active preset and a manage shortcut."""

    def __init__(self, ios_style: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("presetBanner")
        self.setFrameShape(QFrame.StyledPanel)
        self._ios_style = ios_style

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self.caption_lbl = QLabel(QCoreApplication.translate(
            "Nugget", "Active preset"))
        text_col.addWidget(self.caption_lbl)

        self.active_lbl = QLabel(QCoreApplication.translate("Nugget", "AutoSave"))
        text_col.addWidget(self.active_lbl)

        layout.addLayout(text_col, 1)

        self.manage_btn = QPushButton(QCoreApplication.translate("Nugget", "Manage"), self)
        self.manage_btn.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.manage_btn)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        if self._ios_style:
            self.setStyleSheet(f"""
                PresetBanner {{
                    background-color: {c.bg_secondary};
                    border-radius: 12px;
                    border: none;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                PresetBanner {{
                    background-color: {c.surface_hover};
                    border-radius: 10px;
                    border: none;
                }}
            """)
        self.caption_lbl.setStyleSheet(f"font-size: 12px; color: {c.text_secondary};")
        self.active_lbl.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {c.text_primary};")
        self.manage_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {c.accent};
                font-size: 15px;
                font-weight: 600;
                border: none;
                padding: 8px 12px;
            }}
            QPushButton:hover {{ color: {c.accent_hover}; }}
        """)

    def set_active_preset(self, name: str, autosave: bool = True):
        """Show ``name``, or a placeholder when no preset is loaded.

        With autosave off there is nothing behind the banner, so claiming
        "AutoSave" would be a lie — the tweaks on screen belong to no preset.
        """
        if name:
            self.active_lbl.setText(name)
        elif autosave:
            self.active_lbl.setText(QCoreApplication.translate("Nugget", "AutoSave"))
        else:
            self.active_lbl.setText(QCoreApplication.translate("Nugget", "Not Saved"))


class PresetWidget(QWidget):
    """Home-screen container: header + active-preset banner + manage action.

    Tapping *Manage* opens an animated popup (``PresetPopup``) that lists every
    preset, lets the user pick one and exposes the full action set (save, load,
    delete, export, partial export, import, open in Settings). ``on_manage`` is
    only used as a fallback when no window is available to own the popup.
    """

    def __init__(self, window=None, on_manage=None, ios_style: bool = True,
                 parent=None):
        super().__init__(parent)
        self.window = window
        self._on_manage = on_manage
        self._ios_style = ios_style
        self._popup = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._header = QLabel()
        layout.addWidget(self._header)

        self.banner = PresetBanner(ios_style=ios_style)
        self.banner.manage_btn.clicked.connect(self._on_manage_pressed)
        layout.addWidget(self.banner)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        if self._ios_style:
            self._header.setText(QCoreApplication.translate("Nugget", "PRESETS"))
            self._header.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {c.text_secondary};"
                "letter-spacing: 0.5px; padding-left: 4px;")
        else:
            self._header.setText(QCoreApplication.translate("Nugget", "Presets"))
            self._header.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {c.text_primary};")
        self.banner._retheme()

    def _on_manage_pressed(self):
        """Open the animated preset popup under the Manage button.

        Falls back to ``on_manage`` (navigate to the Settings page) when there
        is no window to own the popup, or when the popup cannot be created.
        """
        if self.window is not None and self._ios_style:
            try:
                from src.gui.ios.preset_menu import show_preset_popup
                if self._popup is not None:
                    try:
                        self._popup.close()
                    except RuntimeError:
                        # already destroyed by Qt when its parent went away
                        self._popup = None
                self._popup = show_preset_popup(
                    self.window, self.banner.manage_btn, parent=self.window)
                self._popup.closed.connect(self._forget_popup)
                return
            except Exception:
                # never let the banner break the home page: fall back
                self._popup = None
        if self._on_manage is not None:
            self._on_manage()

    def _forget_popup(self):
        popup, self._popup = self._popup, None
        if popup is not None:
            popup.deleteLater()

    def refresh(self):
        """Recompute and display the currently active preset."""
        name = self._current_preset_name()
        self.banner.set_active_preset(name, autosave=self._autosave_enabled())

    def active_preset_name(self) -> str:
        """Return the preset name currently represented by the banner."""
        name = self._current_preset_name()
        if name:
            return name
        return (QCoreApplication.translate("Nugget", "AutoSave")
                if self._autosave_enabled()
                else QCoreApplication.translate("Nugget", "Not Saved"))

    def _autosave_enabled(self) -> bool:
        if self.window is None:
            return True
        try:
            return bool(self.window.autosave_enabled())
        except Exception:
            return True

    def _current_preset_name(self) -> str:
        if self.window is None:
            return ""
        try:
            last = self.window.settings.value("last_loaded_preset", "", type=str)
        except Exception:
            last = ""
        if last:
            return last
        return ""
