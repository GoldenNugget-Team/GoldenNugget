"""Read-only help for a registry tweak; opening it never changes selections."""
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import ColorThemeManager, t
from src.tweaks.registry import Kind


class TweakInfoDialog(QDialog):
    def __init__(self, spec, parent=None):
        super().__init__(parent)
        tr = lambda text: QCoreApplication.translate("Nugget", text)
        title = tr(spec.title)
        self.setWindowTitle(title)
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        scroll = QScrollArea(self)
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        self._content = content
        content.setObjectName("tweakInfoContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(14)

        def label(text, name="confirmRow"):
            widget = QLabel(text, content)
            widget.setTextFormat(Qt.PlainText)
            widget.setWordWrap(True)
            widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
            widget.setObjectName(name)
            body.addWidget(widget)

        label(title, "confirmTitle")
        label(tr("Intended effect"), "confirmTitle")
        label(tr(spec.description) if spec.description else
              tr("No detailed description is available for this tweak yet."))
        label(tr("Hidden settings can be ignored by your system version. "
                 "These descriptions explain intended effects, not a verified result on your device."), "confirmMuted")
        if spec.warning:
            label(tr("Before applying"), "confirmTitle")
            label(tr(spec.warning))
        requirements = []
        if spec.min_version:
            requirements.append(tr("Minimum system version: {0}").format(spec.min_version))
        if spec.max_version:
            requirements.append(tr("Maximum system version: {0}").format(spec.max_version))
        if spec.iphone_only:
            requirements.append(tr("iPhone only"))
        if spec.ipad_only:
            requirements.append(tr("iPad only"))
        label(tr("Compatibility"), "confirmTitle")
        label("\n".join(requirements) if requirements else
              tr("No additional version or device restrictions are listed for this tweak."))
        if spec.kind == Kind.NUMBER:
            label(tr("Allowed input: {0} – {1}").format(f"{spec.min_value:g}", f"{spec.max_value:g}"))
        label(tr("How to restore defaults"), "confirmTitle")
        from src.tweaks.tweak_classes import (
            DynamicIslandBorderWriteTest,
            ExperimentalBooleanPlistTweak,
            OptionalBundlePreferenceTweak,
            ResettableNumericPreferenceTweak,
            ReversibleBooleanPlistTweak,
        )
        from src.tweaks.tweaks import tweaks
        tweak = tweaks.get(spec.id)
        if isinstance(tweak, DynamicIslandBorderWriteTest):
            undo = tr("Turn off and apply again to remove the seven test settings. "
                      "The separate Disable Dynamic Island setting is not changed.")
        elif isinstance(tweak, ResettableNumericPreferenceTweak):
            undo = tr("Enter -1 and apply again to remove this setting.")
        elif isinstance(tweak, OptionalBundlePreferenceTweak):
            undo = tr("Clear the text and apply again to remove this setting.")
        elif isinstance(tweak, (ExperimentalBooleanPlistTweak, ReversibleBooleanPlistTweak)):
            undo = tr("Turn off and apply again to reverse this request. "
                      "This does not recover a previous custom value.")
        else:
            undo = tr("Turning this off stops it being included in the next apply. "
                      "To reset changes already on the device, open Apply, choose Restore Defaults, "
                      "and select the relevant page.")
        label(undo, "confirmMuted")
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        close = QPushButton(tr("Close"), self)
        close.setObjectName("cancelBtn")
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog"))
        self._scroll.setStyleSheet(t("tweak_info_scroll"))
