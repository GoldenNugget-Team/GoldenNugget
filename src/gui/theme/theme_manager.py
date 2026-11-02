from PySide6.QtCore import QObject, Signal, QEvent, Qt
from PySide6.QtGui import QColor, QPalette, QGuiApplication

from src.gui.theme.colors import ThemeColors, DARK, ACCENT_PRESETS
from src.utils.settings import Settings


class ColorThemeManager(QObject):
    """Manages the persisted accent color for the single application palette.

    Singleton accessed via ``ColorThemeManager.instance()``.
    Emits ``theme_changed`` whenever the accent (or the resulting palette)
    changes so connected widgets can re-render their stylesheets.
    """

    theme_changed = Signal()

    _inst = None

    def __init__(self, parent=None):
        super().__init__(parent)
        # Same keys the old QSettings store used, but persisted in the app's
        # own data folder (src.utils.settings reads the legacy plist once).
        self._settings = Settings("GoldenNugget")
        self._accent_name = self._settings.value("accent_color", "blue")
        self._custom_accent = self._settings.value('liquid/custom_accent', '#cfa55d')
        if self._accent_name not in ACCENT_PRESETS and self._accent_name != 'custom':
            self._accent_name = 'blue'
        self._colors = self._build_colors()
        self._revision = 0
        self._pinned_app = None

    @classmethod
    def instance(cls) -> "ColorThemeManager":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    # ---- current palette ------------------------------------------------

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def accent_name(self) -> str:
        return self._accent_name

    def c(self, slot: str) -> str:
        """Shortcut: return the hex value for *slot* from the palette."""
        return getattr(self._colors, slot)

    # ---- switching -------------------------------------------------------

    def set_accent(self, name: str):
        if name not in ACCENT_PRESETS:
            return
        if name == self._accent_name:
            return
        self._accent_name = name
        self._settings.setValue("accent_color", name)
        self._publish_colors()

    def set_custom_accent(self, value: str):
        color = QColor(value)
        if not color.isValid():
            return
        if self._accent_name == 'custom' and self._custom_accent == color.name():
            return
        self._custom_accent = color.name()
        self._accent_name = 'custom'
        self._settings.set_many({'liquid/custom_accent': self._custom_accent,
                                 'accent_color': 'custom'})
        self._publish_colors()

    def _publish_colors(self):
        self._settings.sync()
        self._colors = self._build_colors()
        self._revision += 1
        self.apply_to_app()
        self.theme_changed.emit()

    # ---- keeping the OS out ----------------------------------------------

    def apply_to_app(self, app=None):
        """Apply the palette and pin Qt's colour scheme to dark.

        The app never follows the OS appearance. Without the pin, Qt hands
        native parts (Windows/macOS title bars, system dialogs) to the OS
        scheme and re-resolves the palette when the OS switches between
        light and dark. Pinning keeps them dark; if a platform still reports
        a different scheme, the palette and pin are applied again.
        """
        app = app or self._pinned_app or QGuiApplication.instance()
        if app is None:
            return
        hints = app.styleHints()
        if hasattr(hints, "setColorScheme"):  # Qt 6.8+
            hints.setColorScheme(self._qt_scheme())
        app.setPalette(self.build_palette())
        if self._pinned_app is not app:
            self._pinned_app = app
            if hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(self._on_system_scheme)

    def _qt_scheme(self):
        return Qt.ColorScheme.Dark

    def _on_system_scheme(self, scheme):
        # Only the live singleton answers; a replaced manager (tests, reloads)
        # must not fight it over the scheme.
        if ColorThemeManager._inst is self and scheme != self._qt_scheme():
            self.apply_to_app()

    # ---- QPalette for Fusion style ---------------------------------------

    def build_palette(self) -> QPalette:
        pal = QPalette()
        c = self._colors
        roles = {
            QPalette.ColorRole.Window: c.bg_primary,
            QPalette.ColorRole.WindowText: c.text_primary,
            QPalette.ColorRole.Base: c.bg_input,
            QPalette.ColorRole.AlternateBase: c.bg_tertiary,
            QPalette.ColorRole.ToolTipBase: c.bg_elevated,
            QPalette.ColorRole.ToolTipText: c.text_primary,
            QPalette.ColorRole.Text: c.text_primary,
            QPalette.ColorRole.Button: c.bg_secondary,
            QPalette.ColorRole.ButtonText: c.text_primary,
            QPalette.ColorRole.BrightText: c.error,
            QPalette.ColorRole.Link: c.accent,
            QPalette.ColorRole.LinkVisited: c.accent_pressed,
            QPalette.ColorRole.Highlight: c.selection,
            QPalette.ColorRole.HighlightedText: c.text_inverse,
            QPalette.ColorRole.PlaceholderText: c.text_secondary,
            QPalette.ColorRole.Light: c.bg_elevated,
            QPalette.ColorRole.Midlight: c.bg_tertiary,
            QPalette.ColorRole.Dark: c.border,
            QPalette.ColorRole.Mid: c.divider,
            QPalette.ColorRole.Shadow: c.border,
            QPalette.ColorRole.Accent: c.accent,
        }
        # Apply every role to inactive windows too: default Qt roles otherwise
        # leave pale text or dark native controls behind when focus changes.
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                      QPalette.ColorGroup.Disabled):
            for role, value in roles.items():
                pal.setColor(group, role, QColor(value))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                     QPalette.ColorRole.ButtonText, QPalette.ColorRole.PlaceholderText,
                     QPalette.ColorRole.HighlightedText):
            pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.text_disabled))
        pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(c.bg_tertiary))
        return pal

    # ---- helpers ---------------------------------------------------------

    def _build_colors(self) -> ThemeColors:
        if self._accent_name == 'custom':
            color = QColor(self._custom_accent)
            accent, hover, pressed = color.name(), color.lighter(115).name(), color.darker(115).name()
        else:
            accent, hover, pressed = ACCENT_PRESETS[self._accent_name]
        return DARK.with_accent(accent, hover, pressed)

    def accent_hex(self) -> str:
        """Return the current accent as a ``"#rrggbb"`` string."""
        return self._colors.accent

    def accent_rgb(self) -> tuple:
        q = QColor(self._colors.accent)
        return (q.red(), q.green(), q.blue())


class _VisibleThemeConnection(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self._widget = widget
        self._dirty = False
        widget.installEventFilter(self)
        ColorThemeManager.instance().theme_changed.connect(self._apply)

    def _apply(self):
        if not self._widget.isVisible():
            self._dirty = True
            return
        self._dirty = False
        self._widget._retheme()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show and self._dirty:
            self._apply()
        return super().eventFilter(watched, event)


def connect_visible_theme(widget):
    _VisibleThemeConnection(widget)
