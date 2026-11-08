"""GUI warning for a tweak flagged by the remote HotLoad safety rules.

The rule matching itself lives in ``src.controllers.hotload`` (backend); only
the confirmation dialog is Qt.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox


def confirm_flagged(rule: dict, parent=None) -> bool:
    """Show the warning for a flagged tweak. Returns True (Continue Anyway)
    to allow, or False (Cancel) to block."""
    tweak = rule.get("tweak", "this tweak")
    reason = rule.get("reason")
    if reason:
        reason_txt = str(reason)
    else:
        reason_txt = QCoreApplication.translate(
            "Nugget", "This feature is currently flagged as dangerous or broken.")
    text = (QCoreApplication.translate(
                "Nugget", "GoldenNugget safety rules have flagged \"{0}\" as currently dangerous or broken.").format(tweak)
            + f"\n\n{reason_txt}\n\n"
            + QCoreApplication.translate(
                "Nugget", "It is recommended not to enable it. Do you still want to enable it?"))
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(QCoreApplication.translate("Nugget", "Disabled Feature Warning"))
    box.setText(text)
    continue_btn = box.addButton(
        QCoreApplication.translate("Nugget", "Continue Anyway"),
        QMessageBox.ButtonRole.AcceptRole)
    cancel_btn = box.addButton(
        QCoreApplication.translate("Nugget", "Cancel"),
        QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel_btn)
    box.exec()
    return box.clickedButton() is continue_btn
