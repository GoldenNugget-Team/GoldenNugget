"""Theme-aware Qt controls; the host supplies a theme via configure_theme."""
from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtCore import (
    Signal as pyqtSignal,
)
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .theme import ColorThemeManager, connect_visible_theme, t, theme_pixmap


def _auto_retheme(widget):
    """Connect a widget's ``_retheme`` to the global theme_changed signal."""
    connect_visible_theme(widget)


class IOSSearchField(QLineEdit):
    """Local, case-insensitive list filter with a clear button."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(QCoreApplication.translate("ListSearch", "Search this list…"))
        self.setAccessibleName(self.placeholderText())
        self.setClearButtonEnabled(False)
        self.setFixedHeight(44)
        self.setTextMargins(34, 0, 38, 0)
        self._clear_button = QToolButton(self)
        self._clear_button.setFixedSize(36, 36)
        self._clear_button.setIconSize(QSize(18, 18))
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.setAccessibleName(QCoreApplication.translate("ListSearch", "Clear search"))
        self._clear_button.setToolTip(QCoreApplication.translate("ListSearch", "Clear search"))
        self._clear_button.clicked.connect(self._clear_search)
        self.textChanged.connect(lambda text: self._clear_button.setVisible(bool(text)))
        self._clear_button.hide()
        self._search_icon = QLabel(self)
        self._search_icon.setFixedSize(20, 20)
        self._search_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._search_icon.setStyleSheet("background: transparent; border: none; padding: 0;")
        self._retheme()
        _auto_retheme(self)

    def _clear_search(self):
        self.clear()
        self.setFocus(Qt.OtherFocusReason)

    def matches(self, *texts):
        haystack = " ".join(texts).casefold()
        return all(word in haystack for word in self.text().casefold().split())

    def _retheme(self):
        self.setStyleSheet(t("list_search"))
        colors = ColorThemeManager.instance().colors
        self._clear_button.setIcon(QIcon(theme_pixmap(
            ":/icon/x-lg.svg", colors.text_secondary, 18, self.devicePixelRatioF())))
        self._clear_button.setStyleSheet(t("search_clear_button"))
        self._search_icon.setPixmap(theme_pixmap(
            ":/icon/search.svg", ColorThemeManager.instance().colors.text_secondary,
            20, self.devicePixelRatioF()))
        self._search_icon.move(14, (self.height() - 20) // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._search_icon.move(14, (self.height() - 20) // 2)
        self._clear_button.move(self.width() - 44, (self.height() - 36) // 2)


class IOSSegmentedFilter(QWidget):
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setObjectName("iosSegmentedFilter")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(44)
        self._items = items
        self._index = 0
        self._group = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        for index, (title, data) in enumerate(items):
            button = QPushButton(title, self)
            button.setCheckable(True)
            button.setFixedHeight(34)
            button.setCursor(Qt.PointingHandCursor)
            self._group.addButton(button, index)
            layout.addWidget(button)
        self._group.button(0).setChecked(True)
        self._group.idClicked.connect(self.setCurrentIndex)
        self._retheme()
        _auto_retheme(self)

    def currentData(self):
        return self._items[self._index][1]

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, index):
        if index == self._index or not 0 <= index < len(self._items):
            return
        self._index = index
        self._group.button(index).setChecked(True)
        self.currentIndexChanged.emit(index)

    def _retheme(self):
        self.setStyleSheet(t("segmented_filter"))


class IOSSearchEmpty(QLabel):
    def __init__(self, parent=None):
        super().__init__(QCoreApplication.translate("ListSearch", "No matches found."), parent)
        self.setWordWrap(True)
        self.hide()
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("list_search_empty"))


class IOSSectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("iosSectionHeader")
        self.setProperty("cls", "iosSectionHeader")
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("section_header"))


class IOSCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("iosCard")
        self.setFrameShape(QFrame.StyledPanel)
        self._retheme()
        _auto_retheme(self)
        # Don't create a default layout - let the caller decide

    def _retheme(self):
        self.setStyleSheet(t("card"))


class IOSCollapsibleSection(QWidget):
    """A section header that expands/collapses the content block below it.

    Callers add their widgets to ``self.body_layout`` after construction (a
    tweak section is rendered straight from the registry, so the body is
    filled in right after this widget is created) and read back the resulting
    state through ``expanded`` / the ``toggled`` signal.
    """

    EXPANDED_CHEVRON = "\u25bc"    # down-pointing disclosure marker
    COLLAPSED_CHEVRON = "\u25b6"   # right-pointing disclosure marker

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("iosCollapsibleSection")
        self._title = title
        self._title_suffix = ""
        self._expanded = bool(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.header = QPushButton(self)
        self.header.setObjectName("iosCollapsibleHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setFocusPolicy(Qt.NoFocus)
        self.header.clicked.connect(self.toggle)
        layout.addWidget(self.header)

        self.body = QWidget(self)
        self.body.setObjectName("iosCollapsibleBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)

        # No toggled() emission here: the state was handed in by the caller.
        self.set_expanded(self._expanded)
        self._retheme()
        _auto_retheme(self)

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool):
        """Show/hide the body. Only emits ``toggled`` on an actual change."""
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self.header.setChecked(expanded)
        self._update_header_text()
        self.body.setVisible(expanded)
        if changed:
            self.toggled.emit(expanded)

    def set_title_suffix(self, suffix: str):
        """Append a compact status/count suffix to the section title."""
        self._title_suffix = str(suffix or "")
        self._update_header_text()

    def _update_header_text(self):
        self.header.setText(
            f"{self.EXPANDED_CHEVRON if self._expanded else self.COLLAPSED_CHEVRON}"
            f"  {self._title}{self._title_suffix}")

    def toggle(self):
        self.set_expanded(not self._expanded)

    def _retheme(self):
        self.header.setStyleSheet(t("collapsible_header"))


class IOSNavBar(QWidget):
    """Page identity, actions, and section navigation in one persistent header."""

    def __init__(self, title="", on_back=None, right_action=None,
                 window=None, parent=None):
        super().__init__(parent)
        self.setObjectName("iosNavBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._on_back = on_back or getattr(window, "_go_back", None)
        self._icon_path = None
        self._category_buttons = []
        self._right_btn = None
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.back_btn = QPushButton("‹", self)
        self.back_btn.setFixedSize(36, 36)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setToolTip(QCoreApplication.translate("Nugget", "Back"))
        self.back_btn.setAccessibleName(self.back_btn.toolTip())
        self.back_btn.clicked.connect(self._handle_back)
        row.addWidget(self.back_btn)
        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(32, 32)
        self.icon_lbl.hide()
        row.addWidget(self.icon_lbl)
        self.title_lbl = QLabel(title, self)
        self.title_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        row.addWidget(self.title_lbl, 1)
        self._right_box = QWidget(self)
        self._right_layout = QHBoxLayout(self._right_box)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._right_box)
        root.addLayout(row)
        self._categories = QScrollArea(self)
        self._categories.setWidgetResizable(True)
        self._categories.setFrameShape(QFrame.NoFrame)
        self._categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._categories.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._categories.setFixedHeight(44)
        self._category_content = QWidget()
        self._category_layout = QHBoxLayout(self._category_content)
        self._category_layout.setContentsMargins(0, 0, 0, 0)
        self._category_layout.setSpacing(6)
        self._categories.setWidget(self._category_content)
        self._categories.viewport().installEventFilter(self)
        self._category_content.installEventFilter(self)
        root.addWidget(self._categories)
        self._categories.hide()
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("nav_bar"))
        self.back_btn.setStyleSheet(t("nav_back_btn"))
        self.title_lbl.setStyleSheet(t("nav_title"))
        self._categories.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        if self._icon_path:
            self.icon_lbl.setPixmap(theme_pixmap(
                self._icon_path, ColorThemeManager.instance().colors.text_primary,
                28, self.devicePixelRatioF()))
        for button in self._category_buttons:
            button.setStyleSheet(t("nav_category"))
        if self._right_btn:
            self._right_btn.setStyleSheet(t("nav_right_btn"))

    def set_title(self, title):
        self.title_lbl.setText(title)

    def set_icon(self, resource_path):
        self._icon_path = resource_path
        self.icon_lbl.setVisible(bool(resource_path))
        self._retheme()

    def set_categories(self, categories):
        while self._category_layout.count():
            item = self._category_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._category_buttons = []
        self._categories.setVisible(len(categories) > 1)
        for title, callback in categories if len(categories) > 1 else []:
            button = QPushButton(title.replace("&", "&&"), self._category_content)
            button.setAccessibleName(title)
            button.installEventFilter(self)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(32)
            button.setStyleSheet(t("nav_category"))
            button.setFixedWidth(button.sizeHint().width())
            button.clicked.connect(
                lambda checked=False, b=button, cb=callback: self._jump(b, cb))
            self._category_layout.addWidget(button)
            self._category_buttons.append(button)
        self._category_layout.addStretch(1)
        width = sum(button.width() for button in self._category_buttons)
        width += max(0, len(self._category_buttons) - 1) * 6
        self._category_content.setMinimumWidth(width)
        self.setFixedHeight(108 if len(categories) > 1 else 64)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            bar = self._categories.horizontalScrollBar()
            if bar.maximum() > 0:
                pixels = event.pixelDelta()
                angles = event.angleDelta()
                delta = pixels.x() or pixels.y()
                if not delta:
                    delta = (angles.x() or angles.y()) / 120 * 64
                if delta:
                    bar.setValue(bar.value() - round(delta))
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _jump(self, selected, callback):
        for button in self._category_buttons:
            button.setChecked(button is selected)
        callback()

    def set_back_visible(self, visible):
        self.back_btn.setVisible(visible)

    def set_right_action(self, label_text, callback):
        self._clear_right()
        button = QPushButton(label_text, self)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet(t("nav_right_btn"))
        button.clicked.connect(callback)
        self._right_layout.addWidget(button)
        self._right_btn = button

    def clear_right_action(self):
        self._clear_right()

    def _clear_right(self):
        if self._right_btn is not None:
            self._right_layout.removeWidget(self._right_btn)
            self._right_btn.deleteLater()
            self._right_btn = None

    def _handle_back(self):
        if self._on_back:
            self._on_back()


class IOSValueRow(QPushButton):
    """Editable setting with a wrapping title and a separate visible value."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._title = title
        self.setObjectName("iosValueRow")
        self.setCursor(Qt.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("valueRowTitle")
        self.value_label = QLabel(self)
        self.value_label.setObjectName("valueRowValue")
        for label in (self.title_label, self.value_label):
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            text.addWidget(label)
        layout.addLayout(text, 1)
        arrow = QLabel("›", self)
        arrow.setObjectName("valueRowArrow")
        arrow.setFixedSize(20, 28)
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(arrow)
        self.set_display_value(QCoreApplication.translate("Nugget", "Not set"))
        self._retheme()
        _auto_retheme(self)

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(0, 56))

    def minimumSizeHint(self):
        return QSize(0, 56)

    def heightForWidth(self, width):
        return max(56, self.layout().totalHeightForWidth(width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def set_display_value(self, value):
        self.value_label.setText(str(value))
        self.setMinimumHeight(self.heightForWidth(self.width()))
        self.updateGeometry()
        self.setAccessibleName(f"{self._title}: {value}")

    def _retheme(self):
        self.setStyleSheet(t("value_row"))


class IOSSettingsRow(QPushButton):
    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("iosSettingsRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setText(f"{title}  ›")
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("settings_row"))


class IOSSettingsAction(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("settings_action"))


class IOSPrimaryButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("iosPrimaryButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("primary_button"))


class IOSDangerButton(QPushButton):
    """Red destructive CTA (Reset Tweaks / Remove Tweaks)."""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("iosDangerButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(50)
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("danger_button"))


class IOSSwitch(QPushButton):
    """iOS-style toggle switch: the track color fades while the knob slides.

    Track and knob are drawn in ``paintEvent`` (rather than a stylesheet plus a
    child ``QLabel``) so the knob can move on every animation frame without
    child-widget repaint artifacts. ``switch_progress`` runs 0.0 = off to
    1.0 = on and drives both the knob position and the track color.
    """

    TRACK_SIZE = QSize(51, 31)
    KNOB_SIZE = 27
    KNOB_INSET = 2
    ANIM_MS = 180
    KNOB_COLOR = QColor("#FFFFFF")

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self.TRACK_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

        self._progress = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"switch_progress", self)
        self._anim.setDuration(self.ANIM_MS)

        # set the state before connecting: building a page must not animate
        self.setChecked(checked)
        self.toggled.connect(self._on_toggled)
        _auto_retheme(self)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value):
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    switch_progress = Property(float, _get_progress, _set_progress)

    def _on_toggled(self, checked: bool):
        if not self.isVisible():
            # not on screen (page still being built): nothing to animate
            self._anim.stop()
            self._set_progress(1.0 if checked else 0.0)
            return
        self._animate_to(1.0 if checked else 0.0)

    def _animate_to(self, target: float):
        # restart from the current position, so rapid clicks blend instead of
        # snapping back to an end state
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if target > self._progress
            else QEasingCurve.Type.InOutCubic)
        self._anim.start()

    def _retheme(self):
        # a theme change must not animate: stop and snap to the current state
        self._anim.stop()
        self._set_progress(1.0 if self.isChecked() else 0.0)

    def paintEvent(self, event):
        c = ColorThemeManager.instance().colors
        p = self._progress
        off = QColor(c.border)
        # A selected switch is an active control, so it follows the user's
        # chosen accent instead of the semantic success green.
        on = QColor(c.accent)
        track = QColor(
            round(off.red() + (on.red() - off.red()) * p),
            round(off.green() + (on.green() - off.green()) * p),
            round(off.blue() + (on.blue() - off.blue()) * p),
        )

        knob = float(self.KNOB_SIZE)
        inset = self.KNOB_INSET
        travel = self.width() - knob - 2 * inset
        knob_x = inset + travel * p

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1.0 if self.isEnabled() else 0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(
            QRectF(0, 0, self.width(), self.height()),
            self.height() / 2.0, self.height() / 2.0)
        painter.setBrush(self.KNOB_COLOR)
        painter.drawRoundedRect(
            QRectF(knob_x, inset, knob, knob), knob / 2.0, knob / 2.0)
        painter.end()
