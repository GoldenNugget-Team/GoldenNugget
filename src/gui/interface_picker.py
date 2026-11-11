from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEvent,
    QSignalBlocker,
    Qt,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import ColorThemeManager, t


def _interface_preview(window, mode: str, dpr: float = 1.0) -> QPixmap:
    """Render the real Home and navigation without saving a preview choice.

    Temporarily change widget visibility with page signals suspended. Restore
    it synchronously before the event loop can repaint the live window.
    """
    if window is None or not hasattr(window, "ios_home"):
        return QPixmap()
    home = window.ios_home
    root = window.centralWidget()
    original_size = root.size()
    sidebar = mode == "sidebar"
    widgets = ((window.ui.sidebar, sidebar),
               (window.bottom_navigation, not sidebar),
               (home.cards_grid, not sidebar), (home.apply_btn, not sidebar),
               (window.ios_nav, False))
    previous = [(widget, not widget.isHidden()) for widget, _ in widgets]
    page = window.ios_pages.currentIndex()
    scrollbars = (home._scroll.verticalScrollBar(), home._scroll.horizontalScrollBar())
    scroll_positions = [bar.value() for bar in scrollbars]

    def settle_layout():
        # Visibility and responsive header changes invalidate nested layouts.
        # Flush geometry only: processEvents would also run device/background work.
        for _ in range(4):
            for widget in (root, *root.findChildren(QWidget)):
                widget.ensurePolished()
                if widget.layout() is not None:
                    widget.layout().activate()
            QCoreApplication.sendEvent(home._scroll, QEvent(QEvent.LayoutRequest))
            home._fit_header()
            home.cards_grid.reflow()

    try:
        with QSignalBlocker(window.ios_pages):
            window.ios_pages.setCurrentIndex(0)
        for widget, visible in widgets:
            widget.setVisible(visible)
        # Both alternatives use one desktop-sized canvas, regardless of the
        # live window's size. Resize the child surface, never the native window.
        root.resize(1440, 960)
        settle_layout()
        for bar in scrollbars:
            with QSignalBlocker(bar):
                bar.setValue(0)
        image = root.grab()
    finally:
        for widget, visible in previous:
            widget.setVisible(visible)
        with QSignalBlocker(window.ios_pages):
            window.ios_pages.setCurrentIndex(page)
        root.resize(original_size)
        settle_layout()
        for bar, position in zip(scrollbars, scroll_positions):
            with QSignalBlocker(bar):
                bar.setValue(position)
    preview = image.scaled(round(390 * dpr), round(260 * dpr),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    preview.setDevicePixelRatio(dpr)
    return preview


class InterfacePickerDialog(QDialog):
    """First launch: compare the real Home, with Modern recommended."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Choose Interface"))
        available = self.screen().availableGeometry().width()
        self.setFixedWidth(min(900, max(600, available - 48)))
        self.choice = None  # accepted legacy keys: "classic" | "ios"
        self._selected = "ios"
        self._preview_window = parent
        self._art = {}
        self._theme_labels = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)
        title = QLabel(QCoreApplication.translate("Nugget", "Welcome to GoldenNugget"))
        title.setStyleSheet(t("onboarding_title"))
        self._theme_labels.append((title, "onboarding_title"))
        title.setWordWrap(True)
        layout.addWidget(title)
        self._subtitle = QLabel(QCoreApplication.translate("Nugget", "Choose how you navigate your Home screen. You can change this later in Settings."))
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        choices = QHBoxLayout()
        choices.setSpacing(16)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, mode, name, description in (
            ("ios", "modern", QT_TRANSLATE_NOOP("Nugget", "Modern"),
             QT_TRANSLATE_NOOP("Nugget", "Your features on Home, with navigation at the bottom.")),
            ("classic", "sidebar", QT_TRANSLATE_NOOP("Nugget", "Sidebar"),
             QT_TRANSLATE_NOOP("Nugget", "Keep navigation in a sidebar beside your Home screen.")),
        ):
            card = QPushButton(self)
            card.setObjectName("interfaceChoice")
            card.setCheckable(True)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            card.setMinimumHeight(330)
            card.setAutoDefault(False)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setAccessibleName(QCoreApplication.translate("Nugget", name))
            self._group.addButton(card)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 16, 14, 16)
            card_layout.setSpacing(12)
            heading = QHBoxLayout()
            label = QLabel(QCoreApplication.translate("Nugget", name))
            label.setStyleSheet(t("onboarding_option_title"))
            self._theme_labels.append((label, "onboarding_option_title"))
            heading.addWidget(label)
            heading.addStretch()
            if key == "ios":
                badge = QLabel(QCoreApplication.translate("Nugget", "Recommended"))
                badge.setStyleSheet(t("onboarding_badge"))
                heading.addWidget(badge)
                self._recommended = badge
            card_layout.addLayout(heading)
            art = QLabel()
            art.setMinimumSize(0, 180)
            art.setAlignment(Qt.AlignmentFlag.AlignCenter)
            art.setStyleSheet(t("onboarding_preview"))
            card_layout.addWidget(art, 1)
            self._art[mode] = art
            desc = QLabel(QCoreApplication.translate("Nugget", description))
            desc.setWordWrap(True)
            desc.setStyleSheet(t("onboarding_description"))
            self._theme_labels.append((desc, "onboarding_description"))
            card_layout.addWidget(desc)
            # Labels are part of a single keyboard-accessible choice button.
            for child in card.findChildren(QLabel):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            card.clicked.connect(lambda checked=False, value=key: self._select(value))
            choices.addWidget(card, 1)
            if key == "ios":
                self._ios_frame = card
            else:
                self._classic_frame = card
        layout.addLayout(choices)
        footer = QHBoxLayout()
        footer.addStretch()
        self._continue = QPushButton(QCoreApplication.translate("Nugget", "Continue with Modern"))
        self._continue.setDefault(True)
        self._continue.clicked.connect(lambda: self._pick(self._selected))
        footer.addWidget(self._continue)
        layout.addLayout(footer)
        self._select("ios")
        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)

    def _select(self, choice):
        self._selected = choice
        self._ios_frame.setChecked(choice == "ios")
        self._classic_frame.setChecked(choice == "classic")
        self._continue.setText(QCoreApplication.translate("Nugget", "Continue with Modern") if choice == "ios"
                               else QCoreApplication.translate("Nugget", "Continue with Sidebar"))

    def _retheme(self):
        self.setStyleSheet(t("onboarding_dialog"))
        self._subtitle.setStyleSheet(t("onboarding_description"))
        for label, style in self._theme_labels:
            label.setStyleSheet(t(style))
        for card in (self._ios_frame, self._classic_frame):
            card.setStyleSheet(t("onboarding_choice"))
        self._recommended.setStyleSheet(t("onboarding_badge"))
        self._continue.setStyleSheet(t("onboarding_continue"))
        for mode, art in self._art.items():
            image = _interface_preview(self._preview_window, mode, self.devicePixelRatioF())
            if not image.isNull():
                # Card width can be smaller on compact displays.
                width = max(220, (self.width() - 56 - 16) // 2 - 28)
                art.setPixmap(image.scaled(round(width * self.devicePixelRatioF()),
                                          round(260 * self.devicePixelRatioF()),
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _pick(self, choice: str):
        self.choice = choice
        self.accept()


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
