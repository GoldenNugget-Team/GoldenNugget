"""Native window corner rounding, on the platforms that have it.

The app draws its own window frame (``src/gui/window_chrome.py``), and a corner
radius belongs to the frame — a frameless window has none, and Qt exposes no
API for it (``QWindow`` only offers ``setMask``). Two platforms do let an app
ask for the real thing, so the app asks there and keeps the mask everywhere
else:

* **macOS** — the ``NSWindow``'s content view is clipped by its layer
  (``cornerRadius`` + ``masksToBounds``). Because the clip happens in AppKit
  rather than on a bitmap, the corners are antialiased and the window keeps its
  **native drop shadow** — neither is possible with ``QWidget.setMask``, whose
  ``QRegion`` has one bit per pixel. A non-opaque window is required or the
  clipped corners would be filled with the window's background, so
  :func:`prepare_window` sets ``WA_TranslucentBackground``; Qt reads that
  attribute when it *creates* the native window, which is why it has to run at
  install time and not when the shape is applied.
* **Windows 11** — ``DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE)``.
  Windows 10 rejects the attribute, and that failure is exactly the signal the
  caller needs to keep using the mask.

Nothing here may take the app down over cosmetics, so every call is guarded and
reports success instead of raising; a failure just means "use the mask".

The native half cannot be exercised by the offline suite (it needs a real
desktop). ``tools/test_window_chrome.py`` pins the *selection*: native when it
reports success, mask when it fails or raises.
"""

import ctypes
import ctypes.util
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

log = logging.getLogger("GoldenNugget.native_corners")

MACOS = "macos"
WINDOWS = "windows"

#: DwmSetWindowAttribute attribute ids and preferences (dwmapi.h).
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_DONOTROUND = 1
_DWMWCP_ROUND = 2

_backend = None
_objc = None
_objc_ready = False
_dwmapi = None
_dwmapi_ready = False


# ---- platform detection ---------------------------------------------------

def backend() -> str:
    """``"macos"``, ``"windows"`` or ``""`` — probed once, then cached."""
    global _backend
    if _backend is None:
        _backend = _detect()
        log.debug("native corner rounding backend: %r", _backend or "none")
    return _backend


def _detect() -> str:
    """Which backend this *platform plugin* can serve, not just this OS.

    ``winId()`` is only a native handle under the real platform plugin. Under
    ``QT_QPA_PLATFORM=offscreen`` it is a made-up number, and handing that to
    ``objc_msgSend`` aborts the process inside AppKit — an Objective-C
    exception is not something Python can catch. So the plugin name is part of
    the check, and everything else falls back to the mask.
    """
    name = QGuiApplication.platformName() if QGuiApplication.instance() else ""
    if sys.platform == "darwin" and name == "cocoa":
        return MACOS if _objc_library() is not None else ""
    if sys.platform == "win32" and name == "windows":
        return WINDOWS if _dwmapi_library() is not None else ""
    return ""


def _objc_library():
    """libobjc, with the two entry points this module needs prepared."""
    global _objc, _objc_ready
    if _objc_ready:
        return _objc
    _objc_ready = True
    try:
        path = ctypes.util.find_library("objc")
        library = ctypes.cdll.LoadLibrary(path) if path else None
        if library is not None:
            library.sel_registerName.restype = ctypes.c_void_p
            library.sel_registerName.argtypes = [ctypes.c_char_p]
    except OSError as exc:  # pragma: no cover - depends on the host
        log.debug("libobjc unavailable: %s", exc)
        library = None
    _objc = library
    return _objc


def _dwmapi_library():
    global _dwmapi, _dwmapi_ready
    if _dwmapi_ready:
        return _dwmapi
    _dwmapi_ready = True
    try:
        _dwmapi = ctypes.WinDLL("dwmapi")
    except (OSError, AttributeError) as exc:  # pragma: no cover - Windows only
        log.debug("dwmapi unavailable: %s", exc)
        _dwmapi = None
    return _dwmapi


# ---- macOS ----------------------------------------------------------------

def _send(restype, argtypes, receiver, selector, *args):
    """``objc_msgSend`` with the prototype for *this* call.

    The prototypes matter: a stale ``restype`` turns a returned pointer into an
    ``int`` and the next call through that pointer crashes the process, so
    every call sets its own signature immediately before it is made.
    """
    library = _objc_library()
    function = library.objc_msgSend
    function.restype = restype
    function.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + list(argtypes)
    return function(ctypes.c_void_p(receiver),
                    library.sel_registerName(selector.encode()), *args)


def _macos_content_layer(window):
    """The ``CALayer`` of the window's content view, or None."""
    view = int(window.winId())
    if not view:
        return None
    ns_window = _send(ctypes.c_void_p, [], view, "window")
    if not ns_window:
        return None
    content = _send(ctypes.c_void_p, [], ns_window, "contentView")
    if not content:
        return None
    # wantsLayer has to be set before the view owns a layer to clip.
    _send(None, [ctypes.c_bool], content, "setWantsLayer:", True)
    return _send(ctypes.c_void_p, [], content, "layer") or None


def _macos_apply(window, radius) -> bool:
    layer = _macos_content_layer(window)
    if layer is None:
        return False
    _send(None, [ctypes.c_double], layer, "setCornerRadius:", float(radius))
    _send(None, [ctypes.c_bool], layer, "setMasksToBounds:", True)
    return True


# ---- Windows --------------------------------------------------------------

def _windows_apply(window, radius) -> bool:
    library = _dwmapi_library()
    if library is None:
        return False
    hwnd = int(window.winId())
    if not hwnd:
        return False
    preference = ctypes.c_int(_DWMWCP_ROUND if radius > 0
                              else _DWMWCP_DONOTROUND)
    result = library.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd),
        ctypes.c_uint(_DWMWA_WINDOW_CORNER_PREFERENCE),
        ctypes.byref(preference), ctypes.sizeof(preference))
    return result == 0


# ---- public API -----------------------------------------------------------

def prepare_window(window) -> bool:
    """Make the window able to show through its corners (macOS).

    Runs at install time, before the native window exists: Qt applies
    ``WA_TranslucentBackground`` while creating it, and setting the attribute
    later leaves the window opaque — the rounded corners would then be filled
    with the window's own background instead of the desktop.
    """
    if backend() != MACOS:
        return False
    try:
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not make the window translucent: %s", exc)
        return False
    return True


def apply(window, radius: int) -> bool:
    """Ask the OS to round *window*'s corners. False when it cannot."""
    if window.windowHandle() is None:
        # Nothing native exists yet (the chrome is applied while the window is
        # still being built). Report failure rather than forcing the platform
        # window into existence here — the next resize/show asks again.
        return False
    try:
        if backend() == MACOS:
            return _macos_apply(window, radius)
        if backend() == WINDOWS:
            return _windows_apply(window, radius)
    except Exception as exc:  # pragma: no cover - needs a real desktop
        log.warning("native corner rounding failed, falling back to a mask: %s",
                    exc)
    return False


def clear(window) -> None:
    """Drop the rounding (a zoomed window fills the work area square)."""
    try:
        if backend() == MACOS:
            _macos_apply(window, 0)
        elif backend() == WINDOWS:
            _windows_apply(window, 0)
    except Exception as exc:  # pragma: no cover - needs a real desktop
        log.debug("clearing native corners failed: %s", exc)
