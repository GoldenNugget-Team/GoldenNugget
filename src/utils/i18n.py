"""Qt-free translation seam for the backend.

Backend modules keep calling::

    QCoreApplication.translate("Nugget", "text")
    QCoreApplication.tr("text")

``pyside6-lupdate`` extracts translations by looking for those exact call
shapes, so the names must not change. This module provides a tiny stand-in
``QCoreApplication`` with the same static API; it does **not** import Qt.

Who translates?
    The GUI installs the real Qt translator once at startup::

        from PySide6.QtCore import QCoreApplication as _Qt
        from src.utils import i18n
        i18n.install_translate(_Qt.translate)

    Until that happens (CLI, headless tools, early startup) the source string
    is returned unchanged, i.e. English. When Qt happens to be loaded already
    (a GUI process, or a test that imported PySide6) its translator is used
    automatically, so no caller has to care.

``QT_TRANSLATE_NOOP`` is kept under its Qt name for the same extraction
reason; at runtime it simply returns *text*.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

TranslateFn = Callable[..., str]

_translate: Optional[TranslateFn] = None


def install_translate(fn: Optional[TranslateFn]) -> None:
    """Install (or clear, with ``None``) the runtime translation function."""
    global _translate
    _translate = fn


def _loaded_qt_translate() -> Optional[TranslateFn]:
    """Qt's ``translate`` **if some other module already imported Qt**.

    Deliberately does not import anything: the backend must stay runnable with
    no PySide6 installed. When the GUI is around (or a test loaded Qt itself)
    Qt is already in ``sys.modules``, and using its translator keeps backend
    strings translated even if nobody called :func:`install_translate`.
    """
    qtcore = sys.modules.get("PySide6.QtCore")
    if qtcore is None:
        return None
    return getattr(getattr(qtcore, "QCoreApplication", None), "translate", None)


def translate(context: str, text: str, disambiguation: str = None, n: int = -1) -> str:
    fn = _translate or _loaded_qt_translate()
    if fn is None:
        return text
    try:
        return fn(context, text, disambiguation, n)
    except Exception:
        # A translation backend must never take the app down.
        return text


def QT_TRANSLATE_NOOP(context: str, text: str) -> str:  # noqa: N802 - Qt name
    """Marker kept for ``pyside6-lupdate``; returns the source string."""
    return text


class QCoreApplication:  # noqa: N801 - deliberately mirrors the Qt class name
    """Static translation API compatible with ``PySide6.QtCore.QCoreApplication``.

    Only the translation surface is provided: the backend never needs a Qt
    application object.
    """

    @staticmethod
    def translate(context: str, text: str, disambiguation: str = None, n: int = -1) -> str:
        return translate(context, text, disambiguation, n)

    @staticmethod
    def tr(text: str, disambiguation: str = None, n: int = -1) -> str:
        # QCoreApplication.tr uses its own class name as translation context.
        return translate("QCoreApplication", text, disambiguation, n)
