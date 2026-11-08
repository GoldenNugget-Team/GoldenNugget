"""Dialog for partial preset export.

Lets the user choose a subset of tweaks to include in an exported preset.
Tweaks are grouped by category so it is easy to, for example, export only the
SpringBoard tweaks, or only the Daemons, from a previously saved preset.
"""

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.tweaks.registry import SPECS_BY_ID, Section
from src.tweaks.tweak_names import TweakID


def _label_for(tweak_id: TweakID) -> str:
    """Human-readable (translated where possible) label for a tweak."""
    spec = SPECS_BY_ID.get(tweak_id)
    if spec is not None:
        return QCoreApplication.translate("Nugget", spec.title)
    labels = {
        TweakID.StatusBar: QCoreApplication.translate("Nugget", "Status Bar"),
        TweakID.Templates: QCoreApplication.translate("Nugget", "Templates"),
        TweakID.Daemons: QCoreApplication.translate("Nugget", "Daemons"),
        TweakID.ClearScreenTimeAgentPlist: QCoreApplication.translate(
            "Nugget", "Clear ScreenTimeAgent.plist file"),
    }
    return labels.get(tweak_id, tweak_id.name)


def tweaks_by_section() -> list[tuple[str, list[TweakID]]]:
    """Return tweak categories: (section_title, [TweakID, ...])."""
    grouped = []

    # Registry-driven tweaks, grouped by their Section.
    for section in Section:
        spec_ids = [spec.id for spec in SPECS_BY_ID.values()
                    if spec.section == section]
        grouped.append((QCoreApplication.translate("Nugget", section.value),
                        sorted(spec_ids, key=_label_for)))

    # The extra, registry-external tweaks.
    extras = [TweakID.StatusBar, TweakID.Templates, TweakID.Daemons,
              TweakID.ClearScreenTimeAgentPlist]
    grouped.append((QCoreApplication.translate("Nugget", "Other"), extras))

    return grouped


def _all_tweaks() -> set:
    return {tid for _, ids in tweaks_by_section() for tid in ids}


class PartialExportDialog(QDialog):
    """Checkbox list of tweak categories; returns the selected TweakIDs."""

    def __init__(self, selected: list = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate(
            "Nugget", "Partial Export"))
        self.setModal(True)
        self.resize(420, 520)

        available = _all_tweaks()
        if selected is None:
            selected = list(available)
        selected_set = set(selected) & available

        self._checkboxes = {}

        root = QVBoxLayout(self)

        hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "Choose which tweaks to include in the exported preset. "
            "Unchecked tweaks are left out."))
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)

        for section_title, tweak_ids in tweaks_by_section():
            if not tweak_ids:
                continue
            group = QGroupBox(section_title)
            outer = QVBoxLayout(group)

            select_all = QCheckBox(QCoreApplication.translate(
                "Nugget", "Select all in group"))
            select_all.setChecked(all(tid in selected_set for tid in tweak_ids))
            outer.addWidget(select_all)

            group_boxes = []
            for tid in tweak_ids:
                box = QCheckBox(_label_for(tid))
                box.setChecked(tid in selected_set)
                box.stateChanged.connect(
                    lambda _=False, s=select_all, gs=group_boxes:
                        self._sync_group_header(s, gs))
                self._checkboxes[tid] = box
                outer.addWidget(box)
                group_boxes.append(box)

            def _toggle_all(checked, gs=group_boxes):
                for b in gs:
                    b.setChecked(bool(checked))
            select_all.toggled.connect(_toggle_all)

            content_layout.addWidget(group)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            QCoreApplication.translate("Nugget", "Export"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _sync_group_header(self, select_all: QCheckBox, group_boxes: list):
        """Update the 'Select all in group' checkbox after an item toggles."""
        if group_boxes and all(b.isChecked() for b in group_boxes):
            select_all.blockSignals(True)
            select_all.setChecked(True)
            select_all.blockSignals(False)

    def selected_tweaks(self) -> list:
        """The TweakIDs the user chose to include."""
        return [tid for tid, box in self._checkboxes.items() if box.isChecked()]
