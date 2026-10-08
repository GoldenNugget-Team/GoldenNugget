from PySide6.QtCore import (
    Qt, QCoreApplication, Signal as pyqtSignal, QSize, QRectF,
    QPropertyAnimation, QEasingCurve, Property,
)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QDialog, QDialogButtonBox, QLineEdit, QSpinBox,
    QDoubleSpinBox, QVBoxLayout,
)

from src.gui.theme import t, ColorThemeManager


def _auto_retheme(widget):
    """Connect a widget's ``_retheme`` to the global theme_changed signal."""
    ColorThemeManager.instance().theme_changed.connect(widget._retheme)


class TextInputDialog(QDialog):
    """iOS-style text input dialog."""
    def __init__(self, title: str, current_value: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.input = QLineEdit()
        self.input.setText(current_value)
        self.input.setPlaceholderText(QCoreApplication.translate("TextInputDialog", "Enter value..."))
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet(t("text_input_dialog"))
        layout.addWidget(buttons)

    def _retheme(self):
        self.setStyleSheet(t("text_input_dialog"))

    def get_value(self) -> str:
        return self.input.text()


def decimals_for_step(step) -> int:
    """Decimal places needed to express ``step`` (0.5 -> 1, 1 -> 0, 0.25 -> 2)."""
    try:
        text = f"{float(step):.6f}".rstrip("0")
    except (TypeError, ValueError):
        return 0
    if text.endswith("."):
        return 0
    return len(text.split(".", 1)[1])


class NumberInputDialog(QDialog):
    """iOS-style number input dialog.

    ``step`` picks the widget: an integral step keeps the integer spin box
    (every existing numeric tweak), a finer one switches to a decimal box so
    values like 0.5 are expressible. ``get_value`` returns an int in the
    integral case and a float otherwise.
    """
    def __init__(self, title: str, current_value: int = 0, min_val: int = 0, max_val: int = 999,
                 parent=None, step: float = 1.0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self._retheme()

        self._decimals = decimals_for_step(step)
        self._integral = self._decimals == 0

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        if self._integral:
            self.spin = QSpinBox()
            self.spin.setRange(int(min_val), int(max_val))
            self.spin.setValue(int(current_value))
            self.spin.setButtonSymbols(QSpinBox.NoButtons)
        else:
            self.spin = QDoubleSpinBox()
            self.spin.setDecimals(self._decimals)
            self.spin.setSingleStep(abs(float(step)))
            self.spin.setRange(float(min_val), float(max_val))
            self.spin.setValue(float(current_value))
            self.spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        c = ColorThemeManager.instance().colors
        self.spin.setStyleSheet(f"""
            QSpinBox, QDoubleSpinBox {{
                background-color: {c.bg_input};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 15px;
                padding: 12px 16px;
            }}
        """)
        layout.addWidget(self.spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; font-size: 15px; }}
            QPushButton {{
                background-color: {c.accent};
                border-radius: 10px;
                color: {c.text_inverse};
                font-size: 15px;
                font-weight: 600;
                padding: 12px 24px;
                border: none;
                min-width: 80px;
            }}
            QPushButton:hover {{ background-color: {c.accent_hover}; }}
        """)

    def get_value(self):
        value = self.spin.value()
        return int(value) if self._integral else round(float(value), self._decimals)


class IOSSummaryDialog(QDialog):
    """iOS-style confirm dialog listing what an action will do.

    Built for the pre-apply summary: takes a title, a list of ``lines`` and an
    optional muted footer note, then offers Cancel / a themed confirm button.
    ``exec()`` returns ``QDialog.Accepted`` when the user confirms.

    An optional ``extra_button`` (e.g. "Update Cache") renders as an
    additional themed button that returns ``extra_result`` (default 2) so the
    caller can branch on it without closing with a plain confirm.
    """
    def __init__(self, title: str, lines: list[str], muted: str = "",
                 confirm_text: str = "", extra_button: str = "",
                 extra_result: int = 2, parent=None, details_callback=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setMinimumHeight(140)
        self._retheme()
        _auto_retheme(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title_lbl = QLabel(title, self)
        title_lbl.setObjectName("confirmTitle")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        for line in lines:
            row_lbl = QLabel(line, self)
            row_lbl.setObjectName("confirmRow")
            row_lbl.setWordWrap(True)
            layout.addWidget(row_lbl)

        if muted:
            muted_lbl = QLabel(muted, self)
            muted_lbl.setObjectName("confirmMuted")
            muted_lbl.setWordWrap(True)
            layout.addWidget(muted_lbl)

        layout.addStretch()

        if details_callback is not None:
            details_btn = QPushButton(QCoreApplication.translate("ApplyPreview", "View changes"), self)
            details_btn.setObjectName("cancelBtn")
            details_btn.setCursor(Qt.PointingHandCursor)
            details_btn.clicked.connect(lambda: details_callback(self))
            layout.addWidget(details_btn)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addStretch()
        if extra_button:
            extra_btn = QPushButton(extra_button, self)
            extra_btn.setObjectName("cancelBtn")
            extra_btn.setCursor(Qt.PointingHandCursor)
            extra_btn.clicked.connect(lambda: self.done(extra_result))
            buttons.addWidget(extra_btn)
        cancel_btn = QPushButton(QCoreApplication.translate("IOSSummaryDialog", "Cancel"), self)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.confirm_btn = QPushButton(
            confirm_text or QCoreApplication.translate("IOSSummaryDialog", "Confirm"), self)
        self.confirm_btn.setObjectName("confirmBtn")
        self.confirm_btn.setCursor(Qt.PointingHandCursor)
        self.confirm_btn.clicked.connect(self.accept)
        self.confirm_btn.setDefault(True)
        buttons.addWidget(self.confirm_btn)
        layout.addLayout(buttons)

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog"))


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

    EXPANDED_CHEVRON = "\u25be"    # small down triangle
    COLLAPSED_CHEVRON = "\u25b8"   # small right triangle

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("iosCollapsibleSection")
        self._title = title
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
        self.header.setText(
            f"{self.EXPANDED_CHEVRON if expanded else self.COLLAPSED_CHEVRON}"
            f"  {self._title}")
        self.body.setVisible(expanded)
        if changed:
            self.toggled.emit(expanded)

    def toggle(self):
        self.set_expanded(not self._expanded)

    def _retheme(self):
        self.header.setStyleSheet(t("collapsible_header"))


class IOSNavBar(QWidget):
    """Reusable navigation header."""
    def __init__(self, title: str = "", on_back=None, right_action=None,
                 window=None, parent=None):
        super().__init__(parent)
        self.setObjectName("iosNavBar")
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._on_back = on_back or (window._go_back if hasattr(window, "_go_back") else None)
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(t("nav_bar"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        self._left_pad = QWidget(self)
        self._left_pad.setFixedWidth(90)
        layout.addWidget(self._left_pad)

        self.back_btn = QPushButton(QCoreApplication.translate("Nugget", "←  Back"), self)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet(t("nav_back_btn"))
        self.back_btn.clicked.connect(self._handle_back)
        layout.addWidget(self.back_btn)

        self.title_lbl = QLabel(title, self)
        self.title_lbl.setAlignment(Qt.AlignCenter)
        self.title_lbl.setStyleSheet(t("nav_title"))
        layout.addWidget(self.title_lbl, 1)

        self._right_box = QWidget(self)
        self._right_layout = QHBoxLayout(self._right_box)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.setSpacing(0)
        layout.addWidget(self._right_box)
        self._right_btn = None
        self._left_pad.setVisible(False)
        _auto_retheme(self)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(t("nav_bar"))
        self.back_btn.setStyleSheet(t("nav_back_btn"))
        self.title_lbl.setStyleSheet(t("nav_title"))
        if self._right_btn:
            self._right_btn.setStyleSheet(t("nav_right_btn"))

    def set_title(self, title: str):
        self.title_lbl.setText(title)

    def set_back_visible(self, visible: bool):
        self.back_btn.setVisible(visible)
        self._left_pad.setVisible(not visible)

    def set_right_action(self, label_text: str, callback):
        self._clear_right()
        c = ColorThemeManager.instance().colors
        btn = QPushButton(label_text, self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(t("nav_right_btn"))
        btn.clicked.connect(callback)
        self._right_layout.addWidget(btn)
        self._right_btn = btn

    def clear_right_action(self):
        self._clear_right()

    def _clear_right(self):
        if self._right_btn is not None:
            self._right_layout.removeWidget(self._right_btn)
            self._right_btn.setParent(None)
            self._right_btn.deleteLater()
            self._right_btn = None

    def _handle_back(self):
        if self._on_back:
            self._on_back()


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
        on = QColor(c.success)
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
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(
            QRectF(0, 0, self.width(), self.height()),
            self.height() / 2.0, self.height() / 2.0)
        painter.setBrush(self.KNOB_COLOR)
        painter.drawRoundedRect(
            QRectF(knob_x, inset, knob, knob), knob / 2.0, knob / 2.0)
        painter.end()


class IOSValueLabel(QLabel):
    """Label showing current value in parentheses"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._retheme()
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("value_label"))
