"""Host theme bindings, independent of any application or settings store."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ThemeBindings:
    manager: Callable
    stylesheet: Callable
    pixmap: Callable
    connect: Callable

_bindings = None

def configure_theme(*, manager, stylesheet, pixmap, connect):
    global _bindings
    _bindings = ThemeBindings(manager, stylesheet, pixmap, connect)

def _theme():
    if _bindings is None:
        raise RuntimeError("Configure awesomeUI's host theme before creating themed controls")
    return _bindings

class ColorThemeManager:
    @staticmethod
    def instance():
        return _theme().manager()

def t(key):
    return _theme().stylesheet(key)

def theme_pixmap(*args, **kwargs):
    return _theme().pixmap(*args, **kwargs)

def connect_visible_theme(widget):
    return _theme().connect(widget)
