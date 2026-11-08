"""Factories for registry-backed tweak rows, separate from page rebuild/search."""
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from src.gui.ios.components import IOSCard, IOSSwitch, IOSValueRow, decimals_for_step
from src.gui.theme import t
from src.tweaks.registry import SPECS_BY_ID, Kind
from src.tweaks.tweaks import TweakID, tweaks


def _fmt_number(value) -> str:
    """Render a numeric tweak value compactly (5, 0.5, 1)."""
    try:
        return f'{float(value):g}'
    except (TypeError, ValueError):
        return str(value)


class TweakRowFactory:
    def __init__(self, page, root_layout, compatible):
        self.page, self.root_layout, self.compatible = page, root_layout, compatible

    def render(self, spec, target):
        from src.gui.ios.feature_news import control_title
        title = control_title(QCoreApplication.translate("Nugget", spec.title))
        description = QCoreApplication.translate("Nugget", spec.description) if spec.description else ""
        if spec.kind == Kind.SWITCH:
            self.make_switch(spec.id, title, description, target)
        elif spec.kind == Kind.TEXT:
            self.make_text_input(spec.id, title, description, target)
        elif spec.kind == Kind.NUMBER:
            self.make_number_input(spec.id, title, spec.min_value, spec.max_value,
                                   description, spec.step, target)
        else:
            raise ValueError(f"Unknown tweak control kind: {spec.kind}")

    def description_label(self, description):
        label = QLabel(description)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        label.setProperty('tweakDescription', True)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.page._switch_labels.append(label)
        label.setStyleSheet(t("tweak_row_description"))
        return label

    def add_value_description(self, row, description):
        if description:
            row.layout().itemAt(0).layout().insertWidget(1, self.description_label(description))
            row.setAccessibleDescription(description)

    def make_switch(self, tweak_id: TweakID, title: str, description: str='', target: QVBoxLayout=None):
        if tweak_id not in tweaks:
            return
        tweak = tweaks[tweak_id]
        card = IOSCard()
        if tweak_id == TweakID.ForceSolariumFallback:
            self.page.force_solarium_fallback_card = card
        if not self.compatible(tweak_id):
            card.hide()
        row_layout = QHBoxLayout(card)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(12)
        label = QLabel(title)
        label.setWordWrap(True)
        label.setStyleSheet(t("tweak_row_label"))
        self.page._switch_labels.append(label)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addWidget(label)
        if description:
            text_layout.addWidget(self.description_label(description))
        row_layout.addLayout(text_layout, 1)
        switch = IOSSwitch(tweak.enabled)
        spec = SPECS_BY_ID.get(tweak_id)
        if tweak_id == TweakID.DisableSystemAperture:

            def select_aperture(checked):
                if checked:
                    from src.gui.dialogs.confirmation import ask_confirmation
                    if not ask_confirmation(self.page, QCoreApplication.translate("IOSSectionContent", 'Test Dynamic Island availability?'), QCoreApplication.translate("IOSSectionContent", 'This may change Dynamic Island, the status bar and Live Activities. Removing the black background is not confirmed. Test this with Disable Dynamic Island switched off. Turn off and apply again to undo.'), QCoreApplication.translate("IOSSectionContent", 'Enable experiment'), destructive=True):
                        switch.setChecked(False)
                        return
                tweak.set_enabled(checked)
            switch.toggled.connect(select_aperture)
        elif spec is not None and spec.experimental:

            def select_experiment(checked):
                if checked and spec.warning:
                    from src.gui.dialogs.confirmation import ask_confirmation
                    if not ask_confirmation(self.page, title, QCoreApplication.translate('Nugget', spec.warning), QCoreApplication.translate("IOSSectionContent", 'Enable experiment'), destructive=True):
                        switch.setChecked(False)
                        return
                tweak.set_enabled(checked)
                if checked and spec.exclusive_with is not None:
                    peer = tweaks.get(spec.exclusive_with)
                    if peer is not None:
                        peer.set_enabled(False)
                    peer_switch = self.page._tweak_switches.get(spec.exclusive_with)
                    if peer_switch is not None:
                        peer_switch.setChecked(False)
            switch.toggled.connect(select_experiment)
        else:
            switch.toggled.connect(lambda checked: tweak.set_enabled(checked))
        if spec is not None and spec.unavailable_reason:
            switch.setEnabled(tweak.enabled)
            switch.toggled.connect(lambda checked, control=switch: control.setEnabled(checked))
            switch.setToolTip(spec.unavailable_reason)
        self.page._tweak_switches[tweak_id] = switch
        from src.gui.ios.feature_news import add_new_badge
        add_new_badge(row_layout, 'tweak:' + tweak_id.name, card)
        row_layout.addWidget(switch)
        row_layout.addWidget(self.page._make_favorite_button(tweak_id, title))
        row_layout.addWidget(self.page._make_info_button(tweak_id, title))
        if description:
            label.setToolTip(description)
            switch.setToolTip(description)
            card.setToolTip(description)
        (target or self.root_layout).addWidget(card)
        self.page._search_rows.append((card, tweak_id, title, description, self.compatible(tweak_id)))

    def make_text_input(self, tweak_id: TweakID, title: str, description: str='', target: QVBoxLayout=None):
        if tweak_id not in tweaks:
            return
        if not self.compatible(tweak_id):
            return
        tweak = tweaks[tweak_id]
        card = IOSCard()
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 8, 14, 8)
        card_layout.setSpacing(10)
        row = IOSValueRow(title)
        self.add_value_description(row, description)
        if description:
            row.setToolTip(description)
        current = ''
        if getattr(tweak, 'value', None) is not None:
            current = str(tweak.value)
            spec = SPECS_BY_ID.get(tweak_id)
            empty_label = 'No app override' if spec is not None and spec.bundle_identifier else 'Empty'
            row.set_display_value(current if current else QCoreApplication.translate('Nugget', empty_label))
        row.clicked.connect(lambda: self.page._show_text_input_dialog(tweak_id, title, current, row))
        from src.gui.ios.feature_news import add_new_badge
        add_new_badge(row.layout(), 'tweak:' + tweak_id.name, row, index=row.layout().count() - 1)
        card_layout.addWidget(row, 1)
        card_layout.addWidget(self.page._make_favorite_button(tweak_id, title))
        card_layout.addWidget(self.page._make_info_button(tweak_id, title))
        (target or self.root_layout).addWidget(card)
        self.page._search_rows.append((card, tweak_id, title, description, True))

    def make_number_input(self, tweak_id: TweakID, title: str, min_val: int=0, max_val: int=999, description: str='', step: float=1.0, target: QVBoxLayout=None):
        if tweak_id not in tweaks:
            return
        if not self.compatible(tweak_id):
            return
        tweak = tweaks[tweak_id]
        card = IOSCard()
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 8, 14, 8)
        card_layout.setSpacing(10)
        row = IOSValueRow(title)
        self.add_value_description(row, description)
        if description:
            row.setToolTip(f'{description}\n\n' + QCoreApplication.translate('Nugget', 'Range: {0} – {1}').format(_fmt_number(min_val), _fmt_number(max_val)))
        decimals = decimals_for_step(step)
        current = 0
        if getattr(tweak, 'value', None) is not None:
            current = int(tweak.value) if decimals == 0 else float(tweak.value)
            row.set_display_value(_fmt_number(current))
        spec = SPECS_BY_ID.get(tweak_id)
        if spec is not None and spec.reset_value is not None and (current == spec.reset_value):
            row.set_display_value(QCoreApplication.translate("IOSSectionContent", 'Remove override'))
        if spec is not None and spec.unavailable_reason:
            row.set_display_value(QCoreApplication.translate("IOSSectionContent", 'Unavailable — needs verification'))
            row.setAccessibleDescription(spec.unavailable_reason)
            row.setEnabled(False)
        else:
            row.clicked.connect(lambda: self.page._show_number_input_dialog(tweak_id, title, current, row, min_val, max_val, step))
        from src.gui.ios.feature_news import add_new_badge
        add_new_badge(row.layout(), 'tweak:' + tweak_id.name, row, index=row.layout().count() - 1)
        card_layout.addWidget(row, 1)
        card_layout.addWidget(self.page._make_favorite_button(tweak_id, title))
        card_layout.addWidget(self.page._make_info_button(tweak_id, title))
        (target or self.root_layout).addWidget(card)
        self.page._search_rows.append((card, tweak_id, title, description, True))
