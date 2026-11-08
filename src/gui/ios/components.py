from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QLocale,
    QPropertyAnimation,
    QRectF,
    QRegularExpression,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtCore import (
    Signal as pyqtSignal,
)
from PySide6.QtGui import (
    QColor,
    QDoubleValidator,
    QIcon,
    QIntValidator,
    QPainter,
    QRegularExpressionValidator,
    QValidator,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
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

from src.gui.theme import ColorThemeManager, t, theme_pixmap
from src.gui.widgets import (
    IOSCard,
    IOSCollapsibleSection,
    IOSDangerButton,
    IOSNavBar,
    IOSPrimaryButton,
    IOSSearchEmpty,
    IOSSearchField,
    IOSSectionHeader,
    IOSSegmentedFilter,
    IOSSettingsAction,
    IOSSettingsRow,
    IOSSwitch,
    IOSValueRow,
    _auto_retheme,
)


class TextInputDialog(QDialog):
    """iOS-style text input dialog."""
    def __init__(self, title: str, current_value: str = "", parent=None, *,
                 bundle_identifier=False, pattern: str = None, placeholder: str = None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.input = QLineEdit()
        self.input.setText(current_value)
        if bundle_identifier:
            from src.tweaks.preference_validation import BUNDLE_IDENTIFIER_PATTERN
            self.input.setMaxLength(255)
            self.input.setValidator(QRegularExpressionValidator(
                QRegularExpression(BUNDLE_IDENTIFIER_PATTERN), self.input))
        elif pattern:
            self.input.setValidator(QRegularExpressionValidator(
                QRegularExpression(pattern), self.input))
        self.input.setAccessibleName(title)
        self.input.setPlaceholderText(
            placeholder or QCoreApplication.translate("TextInputDialog", "Enter value..."))
        layout.addWidget(self.input)
        if bundle_identifier:
            self.input.setPlaceholderText("com.example.app")
            hint = QLabel(self.tr("Leave empty to remove this app override."))
            hint.setWordWrap(True)
            layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.setStyleSheet(t("text_input_dialog"))
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self.input.textChanged.connect(self._update_input_state)
        self._update_input_state()
        layout.addWidget(buttons)

    def _update_input_state(self):
        self._ok_button.setEnabled(self.input.hasAcceptableInput())

    def accept(self):
        if self.input.hasAcceptableInput():
            super().accept()

    def _retheme(self):
        self.setStyleSheet(t("text_input_dialog"))

    def showEvent(self, event):
        super().showEvent(event)
        self.input.setFocus(Qt.OtherFocusReason)

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


def compact_number_text(value, locale, decimals):
    if float(value) == 0:
        return locale.toString(0)
    text = locale.toString(float(value), 'f', decimals)
    if locale.decimalPoint() in text:
        text = text.rstrip(locale.zeroDigit()).rstrip(locale.decimalPoint())
    return text


class NumericEntryValidator(QValidator):
    def __init__(self, range_validator, integral, parent):
        super().__init__(parent)
        self.range_validator = range_validator
        self.integral = integral

    def validate(self, text, position):
        allowed = '0123456789-+' if self.integral else '0123456789.-+'
        if any(character not in allowed for character in text):
            return QValidator.Invalid, text, position
        return self.range_validator.validate(text, position)


class NumberInputDialog(QDialog):
    """Number entry with integer or decimal validation based on the step."""

    def __init__(self, title: str, current_value: int = 0, min_val: int = 0, max_val: int = 999,
                 parent=None, step: float = 1.0):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self._retheme()
        self._decimals = decimals_for_step(step)
        self._integral = self._decimals == 0

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        self.input = QLineEdit(self)
        self.input.setAccessibleName(title)
        locale=QLocale.c()
        locale.setNumberOptions(QLocale.RejectGroupSeparator)
        self.input.setLocale(locale)
        self.input.setInputMethodHints(Qt.ImhFormattedNumbersOnly | Qt.ImhNoPredictiveText)
        self.input.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if self._integral:
            validator = QIntValidator(int(min_val), int(max_val), self.input)
            text = self.input.locale().toString(int(current_value))
        else:
            validator = QDoubleValidator(float(min_val), float(max_val), self._decimals, self.input)
            validator.setNotation(QDoubleValidator.StandardNotation)
            text = compact_number_text(current_value, self.input.locale(), self._decimals)
        validator.setLocale(self.input.locale())
        self._number_validator = NumericEntryValidator(validator, self._integral, self.input)
        self.input.setValidator(self._number_validator)
        self.input.setText(text)
        layout.addWidget(self.input)
        if not self._integral:
            hint = QLabel(QCoreApplication.translate("Nugget", "Range: {0} – {1} · Step: {2}").format(
                compact_number_text(min_val, self.input.locale(), self._decimals),
                compact_number_text(max_val, self.input.locale(), self._decimals),
                compact_number_text(step, self.input.locale(), self._decimals)))
            hint.setWordWrap(True)
            hint.setStyleSheet(t("home_subtitle"))
            layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self.input.textChanged.connect(self._update_input_state)
        self._update_input_state()
        layout.addWidget(buttons)

    def _update_input_state(self):
        self._ok_button.setEnabled(self.input.hasAcceptableInput())

    def _retheme(self):
        self.setStyleSheet(t("text_input_dialog"))

    def showEvent(self, event):
        super().showEvent(event)
        self.input.setFocus(Qt.OtherFocusReason)
        self.input.selectAll()

    def accept(self):
        if self.input.hasAcceptableInput():
            super().accept()

    def get_value(self):
        locale = self.input.locale()
        value, valid = (locale.toInt(self.input.text()) if self._integral
                        else locale.toDouble(self.input.text()))
        if not valid or not self.input.hasAcceptableInput():
            raise ValueError("Enter a number within the allowed range.")
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
                 extra_result: int = 2, parent=None, details_callback=None,
                 header_widget=None, acknowledge_text: str = "", preview_callback=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(140)
        _auto_retheme(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title_lbl = QLabel(title, self)
        title_lbl.setObjectName("confirmTitle")
        title_lbl.setWordWrap(True)
        header = QHBoxLayout()
        self._summary_icon = QLabel(self)
        self._summary_icon.setFixedSize(36, 36)
        header.addWidget(self._summary_icon)
        header.addWidget(title_lbl, 1)
        layout.addLayout(header)
        if header_widget is not None:
            header_widget.setParent(self)
            layout.addWidget(header_widget)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        summary = IOSCard()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(12)
        for line in lines:
            row_lbl = QLabel(line, self)
            row_lbl.setObjectName("confirmRow")
            row_lbl.setWordWrap(True)
            summary_layout.addWidget(row_lbl)
        scroll.setWidget(summary)
        scroll.setMinimumHeight(140)
        scroll.setMaximumHeight(320)
        layout.addWidget(scroll, 1)

        if muted:
            muted_lbl = QLabel(muted, self)
            muted_lbl.setObjectName("confirmMuted")
            muted_lbl.setWordWrap(True)
            layout.addWidget(muted_lbl)

        layout.addStretch()

        secondary = QHBoxLayout()
        secondary.setSpacing(12)
        for text, callback in ((QCoreApplication.translate("ApplyPreview", "View changes"), details_callback),
                               (QCoreApplication.translate("DeviceTwin", "Preview on iPhone"), preview_callback)):
            if callback is None:
                continue
            button = QPushButton(text, self)
            button.setObjectName("cancelBtn")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, cb=callback: cb(self))
            secondary.addWidget(button)
        if secondary.count():
            layout.addLayout(secondary)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
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
        # A checkbox the user must tick before confirming (e.g. high risk).
        self.acknowledge = None
        if acknowledge_text:
            from PySide6.QtWidgets import QCheckBox
            self.acknowledge = QCheckBox(acknowledge_text, self)
            self.confirm_btn.setEnabled(False)
            self.confirm_btn.setDefault(False)
            cancel_btn.setDefault(True)
            self.acknowledge.toggled.connect(self.confirm_btn.setEnabled)
            layout.addWidget(self.acknowledge)
        layout.addLayout(buttons)
        for button in self.findChildren(QPushButton):
            button.setMinimumHeight(48)
        self._retheme()

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog") + t("summary_dialog"))
        from src.gui.ios.feature_icons import FEATURE_ICONS
        self._summary_icon.setPixmap(theme_pixmap(
            FEATURE_ICONS["Tweaks"], ColorThemeManager.instance().colors.text_primary,
            36, self.devicePixelRatioF()))
