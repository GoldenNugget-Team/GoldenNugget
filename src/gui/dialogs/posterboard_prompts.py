"""GUI handlers for the PosterBoard import flows.

The PosterBoard tweak model is toolkit-free; these are the dialogs it used to
own. They are installed once at GUI startup and used only when a user imports
a wallpaper/template from the app.
"""

from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import QCoreApplication


def _parent():
    app = QtWidgets.QApplication.instance()
    return app.activeWindow() if app is not None else None


def prompt_legacy_convert(tendie_name: str, families: "list[str]") -> bool:
    """Ask how a legacy (pre-iOS 27) wallpaper should be imported.

    Returns True to convert, False to install the original files untouched.
    Dismissing the dialog (Escape) resolves to "Install as is", so the import is
    never silently converted and never dropped.
    """
    box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Icon.Question,
        QCoreApplication.translate("Nugget", "Legacy Wallpaper Format"),
        QCoreApplication.translate(
            "Nugget",
            "<b>{0}</b> uses the legacy {1} format.").format(
                tendie_name, ", ".join(sorted(set(families)))),
        parent=_parent())
    box.setInformativeText(QCoreApplication.translate(
        "Nugget",
        "iOS 27 only applies the depth effect to wallpapers in the modern format, "
        "so a legacy wallpaper is rewritten on import. Pick "
        "“Install as is” to push the original files untouched instead."))
    convert = box.addButton(
        QCoreApplication.translate("Nugget", "Convert (may break the wallpaper)"),
        QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton(
        QCoreApplication.translate("Nugget", "Install as is"),
        QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(convert)
    box.exec()
    return box.clickedButton() is convert


def show_warning(title: str, text: str) -> None:
    box = QtWidgets.QMessageBox(_parent())
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.exec()


def show_error(title: str, text: str) -> None:
    box = QtWidgets.QMessageBox(_parent())
    box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(text)
    box.exec()


def install() -> None:
    """Wire these dialogs into the PosterBoard import model."""
    from src.tweaks.posterboard import posterboard_tweak

    posterboard_tweak.install_ui(
        prompt_convert=prompt_legacy_convert,
        warning=show_warning,
        error=show_error,
    )
