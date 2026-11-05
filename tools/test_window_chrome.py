#!/usr/bin/env python3
"""Offline test for the app-drawn window frame (no device, no desktop).

The frame is pure Qt, so the parts worth pinning are the ones that are easy to
get subtly wrong and impossible to notice from a screenshot:

* the window really is frameless and really does carry a rounded mask, and the
  mask is dropped while maximized / full screen (a mask on a maximized window
  clips its edges);
* the edge hit boxes map to the right cursors and the manual resize math
  respects the minimum size in every direction;
* a press on a control is never turned into a window drag, while a press on the
  blank strip above the content is — that contract is what keeps the buttons
  and the search box clickable;
* the name next to the buttons is only drawn when no header names the page;
* nothing calls ``QWidget.window()``: several pages keep their own
  ``self.window`` attribute, which shadows the Qt method, so that call raises
  ``TypeError: 'MainWindow' object is not callable`` — the module walks the
  parent chain instead (``_top_level``).

Run: python tools/test_window_chrome.py
"""
import ast
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_SANDBOX = tempfile.mkdtemp(prefix="gn_chrome_")
os.environ.setdefault("GOLDENNUGGET_PREFERENCES_DIR",
                      os.path.join(_SANDBOX, "preferences"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QMainWindow,
                               QPushButton, QWidget)

from src.gui import native_corners
from src.gui.window_chrome import (
    BUTTON_SIZE, CONTENT_TOP_INSET, CONTROLS_INSET, CONTROLS_LEFT, CONTROLS_TOP,
    CORNER_RADIUS, DRAG_STRIP_HEIGHT, RESIZE_MARGIN, TITLE_BAR_HEIGHT,
    _top_level, cursor_for_edges, install_window_chrome, rounded_region,
    window_controls_zoom,
)

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


class FakeHeader(QWidget):
    """Stands in for ``LiquidNavBar``: records the inset it is given."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.leading_inset = None

    def set_leading_inset(self, px):
        self.leading_inset = px


class FakeSidebar(QWidget):
    """Stands in for ``NavigationSidebar``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.top_inset = None

    def set_top_inset(self, px):
        self.top_inset = px


class FakePage(QWidget):
    """Stands in for a full-screen page (``IOSHomePage``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.top_inset = None

    def set_top_inset(self, px):
        self.top_inset = px


class FakeEvent:
    """The slice of ``QMouseEvent`` the chrome actually reads."""

    def __init__(self, point, global_point=None, button=Qt.MouseButton.LeftButton,
                 buttons=Qt.MouseButton.NoButton, kind=None):
        self._point = QPointF(point)
        self._global = QPointF(global_point if global_point is not None else point)
        self._button = button
        self._buttons = buttons
        self._kind = kind or QEvent.Type.MouseButtonPress

    def type(self):
        return self._kind

    def position(self):
        return self._point

    def globalPosition(self):
        return self._global

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons


def make_window():
    """A frameless window with the chrome installed over stub surfaces."""
    window = QMainWindow()
    window.setWindowTitle("GoldenNugget")
    window.setMinimumSize(320, 240)
    window.resize(900, 620)
    central = QWidget(window)
    window.setCentralWidget(central)
    header = FakeHeader(central)
    sidebar = FakeSidebar(central)
    page = FakePage(central)
    chrome = install_window_chrome(window, header, sidebar, pages=(page,))
    window.show()
    QApplication.processEvents()
    return window, chrome, header, sidebar, page


def test_cursor_mapping():
    print("cursor_for_edges")
    E = Qt.Edge
    C = Qt.CursorShape
    cases = {
        E.LeftEdge: C.SizeHorCursor,
        E.RightEdge: C.SizeHorCursor,
        E.TopEdge: C.SizeVerCursor,
        E.BottomEdge: C.SizeVerCursor,
        E.LeftEdge | E.TopEdge: C.SizeFDiagCursor,
        E.RightEdge | E.BottomEdge: C.SizeFDiagCursor,
        E.RightEdge | E.TopEdge: C.SizeBDiagCursor,
        E.LeftEdge | E.BottomEdge: C.SizeBDiagCursor,
    }
    for edges, expected in cases.items():
        label = "|".join(e.name for e in E if edges & e)
        check(f"{label} -> {expected.name}", cursor_for_edges(edges) == expected)
    check("no edges -> no cursor", cursor_for_edges(Qt.Edges()) is None)


def test_top_level():
    print("_top_level")
    window, _chrome, header, _sidebar, _page = make_window()
    nested = QLabel(header)
    check("walks to the window", _top_level(nested) is window)
    # The pitfall the helper exists for: a page that shadows `window`.
    shadowed = FakePage(window)
    shadowed.window = window
    check("works when a widget shadows .window", _top_level(shadowed) is window)
    check("a top-level widget is its own root", _top_level(window) is window)


def test_install():
    print("install_window_chrome")
    window, chrome, header, sidebar, page = make_window()
    check("window is frameless",
          bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint))
    check("chrome owns the three buttons",
          [b.isVisible() for b in (chrome.controls.close_btn,
                                   chrome.controls.minimize_btn,
                                   chrome.controls.zoom_btn)] == [True] * 3)
    check("header reserves the button row",
          header.leading_inset == CONTROLS_INSET, f"{header.leading_inset}px")
    check("sidebar reserves the title bar", sidebar.top_inset == TITLE_BAR_HEIGHT)
    check("full-screen pages reserve the title bar",
          page.top_inset == CONTENT_TOP_INSET)
    check("buttons sit in the top-left corner",
          chrome.controls.pos() == QPoint(CONTROLS_LEFT, CONTROLS_TOP),
          f"{chrome.controls.pos()}")
    check("the button row fits three buttons",
          chrome.controls.width() >= 3 * BUTTON_SIZE)
    check("title starts right of the buttons",
          chrome.title.x() > chrome.controls.x() + chrome.controls.width())
    check("title is mouse-transparent",
          chrome.title.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
    check("disabled install does nothing",
          install_window_chrome(QMainWindow(), enabled=False) is None)


def test_mask():
    print("rounded mask")
    window, chrome, *_ = make_window()
    mask = window.mask()
    width, height = window.width(), window.height()
    check("window is masked", not mask.isEmpty())
    check("corner is cut away",
          not mask.contains(QPoint(0, 0)) and
          not mask.contains(QPoint(width - 1, height - 1)))
    check("no row or column is clipped away",
          all(mask.contains(p) for p in (
              QPoint(0, height // 2), QPoint(width - 1, height // 2),
              QPoint(width // 2, 0), QPoint(width // 2, height - 1))),
          f"bbox {mask.boundingRect()}")
    check("most of the surface survives",
          mask.contains(QPoint(width // 2, height // 2)))

    window.isMaximized = lambda: True
    chrome._apply_shape()
    check("maximized window has no mask", window.mask().isEmpty())
    del window.isMaximized
    chrome._apply_shape()
    check("mask returns with the normal window", not window.mask().isEmpty())

    window.isFullScreen = lambda: True
    chrome._apply_shape()
    check("full-screen window has no mask", window.mask().isEmpty())
    del window.isFullScreen


def test_rounded_region():
    print("corner arc")
    rect = QRect(0, 0, 200, 150)
    region = rounded_region(rect.adjusted(0, 0, 1, 1))
    # Only the radius-sized corner square is cut. A chamfer (what
    # QPainterPath.toFillPolygon gives) drops the two pixels on the diagonal
    # either way; a sampled arc follows the circle to within half a pixel.
    check("pixel just outside the arc is cut",
          not region.contains(QPoint(2, 2)), "2,2")
    check("pixel just inside the arc is kept",
          region.contains(QPoint(4, 4)), "4,4")
    check("the arc centre is kept",
          region.contains(QPoint(CORNER_RADIUS, CORNER_RADIUS)))
    check("the cut stays inside the corner square",
          region.contains(QPoint(CORNER_RADIUS + 3, CORNER_RADIUS + 3)))
    check("straight edges reach the window border",
          all(region.contains(p) for p in (
              QPoint(0, 75), QPoint(199, 75), QPoint(100, 0), QPoint(100, 149))))
    check("all four corners are cut",
          not any(region.contains(p) for p in (
              QPoint(0, 0), QPoint(199, 0), QPoint(0, 149), QPoint(199, 149))))
    check("a radius bigger than the rect degrades to a rounded sliver",
          not rounded_region(QRect(0, 0, 8, 8)).isEmpty())
    check("zero radius is just the rect",
          rounded_region(rect, radius=0) == QRegion(rect))


def test_native_shape_selection():
    print("native rounding vs mask")
    window, chrome, *_ = make_window()
    real_apply, real_clear = native_corners.apply, native_corners.clear
    cleared = []
    native_corners.clear = lambda w: cleared.append(w)
    try:
        native_corners.apply = lambda w, radius: True
        chrome._apply_shape()
        check("a platform rounding needs no mask", window.mask().isEmpty())

        native_corners.apply = lambda w, radius: False
        chrome._apply_shape()
        check("no platform rounding -> mask", not window.mask().isEmpty())

        native_corners.apply = lambda w, radius: True
        chrome._zoomed = True
        chrome._apply_shape()
        check("zooming drops the native rounding", cleared == [window])
        check("zooming leaves no mask either", window.mask().isEmpty())

        chrome._zoomed = False
        chrome._apply_shape()
        check("un-zooming asks for the rounding again",
              window.mask().isEmpty() and cleared == [window])
        # The guarded wrapper itself must never raise, whatever the platform
        # state is (a half-created window, a plugin without a native handle).
        if native_corners.backend() == "":
            check("apply() without a native backend reports failure",
                  real_apply(window, CORNER_RADIUS) is False)
        else:
            check("apply() on a real desktop answers with a bool",
                  isinstance(real_apply(window, CORNER_RADIUS), bool))
    finally:
        native_corners.apply, native_corners.clear = real_apply, real_clear
        chrome._zoomed = False


def test_native_backend():
    print("native backend probe")
    check("a backend name is always a known string",
          native_corners.backend() in ("", native_corners.MACOS,
                                       native_corners.WINDOWS),
          repr(native_corners.backend()))
    window = QMainWindow()
    if sys.platform == "darwin" and native_corners.backend() == native_corners.MACOS:
        check("macOS windows are made translucent for the corner clip",
              native_corners.prepare_window(window) and
              window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    else:
        check("no translucency where the platform cannot round",
              native_corners.prepare_window(window) is False and
              not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))


def test_edges():
    print("edge hit boxes")
    window, chrome, *_ = make_window()
    rect = window.rect()
    cases = {
        "center": (QPoint(rect.width() // 2, rect.height() // 2), Qt.Edges()),
        "left": (QPoint(RESIZE_MARGIN, 100), Qt.Edge.LeftEdge),
        "right": (QPoint(rect.width() - 1 - RESIZE_MARGIN, 100),
                  Qt.Edge.RightEdge),
        "top": (QPoint(400, RESIZE_MARGIN), Qt.Edge.TopEdge),
        "bottom": (QPoint(400, rect.height() - 1 - RESIZE_MARGIN),
                   Qt.Edge.BottomEdge),
        "top-left": (QPoint(0, 0), Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
        "top-right": (QPoint(rect.width() - 1, 0),
                      Qt.Edge.RightEdge | Qt.Edge.TopEdge),
        "bottom-left": (QPoint(0, rect.height() - 1),
                        Qt.Edge.LeftEdge | Qt.Edge.BottomEdge),
        "bottom-right": (QPoint(rect.width() - 1, rect.height() - 1),
                         Qt.Edge.RightEdge | Qt.Edge.BottomEdge),
        "outside": (QPoint(-4, 100), Qt.Edges()),
    }
    for name, (point, expected) in cases.items():
        check(f"{name} -> {cursor_for_edges(expected) or 'none'}",
              chrome._edges_at(point) == expected)
    check("just inside the margin is not an edge",
          chrome._edges_at(QPoint(RESIZE_MARGIN + 2, 200)) == Qt.Edges())


def test_press_resize():
    print("press on an edge starts a resize")
    window, chrome, *_ = make_window()
    chrome._request_system_resize = lambda edges: False
    handled = chrome._press(window, FakeEvent(QPoint(2, 300)))
    check("press on the left edge is consumed", handled is True)
    check("resize grab recorded",
          chrome._resize_grab is not None and
          chrome._resize_grab[0] == Qt.Edge.LeftEdge)
    chrome._resize_grab = None

    chrome._request_system_resize = lambda edges: True
    handled = chrome._press(window, FakeEvent(QPoint(2, 300)))
    check("a platform resize loop needs no fallback grab",
          handled is True and chrome._resize_grab is None)

    chrome._request_system_resize = lambda edges: False
    check("a press in the middle starts no resize",
          chrome._press(window, FakeEvent(QPoint(400, 300))) is False and
          chrome._resize_grab is None)


def test_resize_math():
    print("manual resize geometry")
    window, chrome, *_ = make_window()
    window.setGeometry(100, 100, 800, 600)
    start = QRect(window.geometry())

    def drag(edges, delta):
        chrome._resize_grab = (edges, QPoint(0, 0), start)
        chrome._resize(delta)
        return QRect(window.geometry())

    grown = drag(Qt.Edge.RightEdge, QPoint(-40, 0))
    check("right edge shrinks the width",
          grown.width() == start.width() - 40 and grown.x() == start.x())
    grown = drag(Qt.Edge.BottomEdge, QPoint(0, 40))
    check("bottom edge grows the height",
          grown.height() == start.height() + 40 and grown.y() == start.y())
    grown = drag(Qt.Edge.LeftEdge, QPoint(40, 0))
    check("left edge moves the window",
          grown.x() == start.x() + 40 and grown.right() == start.right())
    grown = drag(Qt.Edge.TopEdge, QPoint(0, 40))
    check("top edge moves the window down",
          grown.y() == start.y() + 40 and grown.bottom() == start.bottom())

    # The minimum size is a hard stop: dragging the left edge past it must not
    # flip the geometry (a negative width) — it pins the edge instead.
    minimum = QPoint(320, 240)
    window.setMinimumSize(minimum.x(), minimum.y())
    pinned = drag(Qt.Edge.LeftEdge, QPoint(5000, 0))
    check("left resize stops at the minimum width",
          pinned.width() == minimum.x() and
          pinned.right() == start.right(), f"{pinned}")
    pinned = drag(Qt.Edge.TopEdge, QPoint(0, 5000))
    check("top resize stops at the minimum height",
          pinned.height() == minimum.y() and
          pinned.bottom() == start.bottom(), f"{pinned}")
    pinned = drag(Qt.Edge.RightEdge, QPoint(-5000, 0))
    check("right resize stops at the minimum width",
          pinned.width() == minimum.x(), f"{pinned}")
    pinned = drag(Qt.Edge.BottomEdge, QPoint(0, -5000))
    check("bottom resize stops at the minimum height",
          pinned.height() == minimum.y(), f"{pinned}")


def test_drag_targets():
    print("what counts as a title bar")
    window, chrome, header, sidebar, page = make_window()
    header.setGeometry(0, 0, 400, 60)
    sidebar.setGeometry(0, 60, 220, 500)
    label = QLabel("Home", header)
    label.setGeometry(120, 10, 60, 24)
    button = QPushButton("Apply", header)
    button.setGeometry(220, 10, 80, 30)
    field = QLineEdit(header)
    field.setGeometry(300, 10, 80, 26)

    check("the blank top strip drags the window",
          chrome._is_drag_target(page, QPoint(500, DRAG_STRIP_HEIGHT - 1)))
    check("below the strip nothing drags",
          not chrome._is_drag_target(page, QPoint(500, 200)))
    check("a header label drags", chrome._is_drag_target(label, QPoint(5, 5)))
    check("the header surface drags",
          chrome._is_drag_target(header, QPoint(10, 40)))
    check("the sidebar surface drags",
          chrome._is_drag_target(sidebar, QPoint(10, 200)))
    check("a button keeps its press",
          not chrome._is_drag_target(button, QPoint(5, 5)))
    check("an input keeps its press",
          not chrome._is_drag_target(field, QPoint(5, 5)))
    nested = QLabel(button)
    check("_accepts_press walks up to the control", chrome._accepts_press(nested))
    check("_accepts_press stops at the window", not chrome._accepts_press(page))

    # The strip zone is measured in WINDOW coordinates. The old check used
    # the pressed widget's local y, so the top half of any widget whose top
    # edge sits just below the strip (e.g. a card row at y=47) counted as
    # "the strip" and swallowed presses that belonged to the page.
    page_button = QPushButton("Deep", page)
    page_button.setGeometry(600, DRAG_STRIP_HEIGHT + 10, 80, 30)
    temp_label = QLabel(page_button)
    check("a top-half press on a widget below the strip is not a drag",
          not chrome._is_drag_target(temp_label, QPoint(5, 5)))
    # Pressing the actual strip over the page still drags wherever the page's
    # own deep containers happen to be.
    strip_leaf = QLabel(page)
    strip_leaf.setGeometry(340, 0, 60, 20)
    check("the strip over page content still drags",
          chrome._is_drag_target(strip_leaf, QPoint(5, 5)))

    check("double click on the strip zooms the window",
          chrome.eventFilter(page, FakeEvent(
              QPoint(500, 8),
              kind=QEvent.Type.MouseButtonDblClick)) is True and chrome._zoomed)
    chrome.toggle_zoom()
    QApplication.processEvents()


def test_drag_moves_window():
    print("dragging the strip moves the window")
    window, chrome, *_ = make_window()
    chrome._request_system_move = lambda: False
    start = QPoint(window.pos())
    origin = QPoint(500, 8)
    check("press on the strip starts a drag",
          chrome._press(window, FakeEvent(origin)) is False and
          chrome._move_grab is not None)
    chrome._move(window, FakeEvent(origin, buttons=Qt.MouseButton.LeftButton))
    check("a tiny move does nothing yet", window.pos() == start)
    moved = origin + QPoint(60, 40)
    chrome._move(window, FakeEvent(moved, buttons=Qt.MouseButton.LeftButton))
    check("the window follows the pointer",
          window.pos() == start + QPoint(60, 40), f"{window.pos()}")
    chrome._request_system_move = lambda: True
    chrome._press(window, FakeEvent(moved))
    chrome._move(window, FakeEvent(moved + QPoint(30, 30),
                                   buttons=Qt.MouseButton.LeftButton))
    check("a platform move loop takes over when available",
          chrome._move_grab is None)


def test_title_label():
    print("window name next to the buttons")
    window, chrome, header, *_ = make_window()
    QApplication.processEvents()
    # The header is the title bar on the pages that show one: the frosted strip
    # stands down beside it (it would blur the header and swallow its clicks).
    check("the strip stands down while the header is up", chrome._strip.isHidden())
    check("the version label yields to the header", chrome.version.isHidden())
    header.hide()
    QApplication.processEvents()
    check("shown when the header goes away", not chrome.title.isHidden())
    check("the strip comes back on headerless pages", not chrome._strip.isHidden())
    header.show()
    QApplication.processEvents()
    check("hidden again once the header is back", chrome.title.isHidden())
    header.hide()
    QApplication.processEvents()
    window.setWindowTitle("GoldenNugget Mobile")
    QApplication.processEvents()
    check("the label follows the window title",
          chrome.title.text() == "GoldenNugget Mobile" and
          not chrome.title.isHidden())
    # The strip comes back UNDER the chrome: a strip raised above the traffic
    # lights frosts them out and swallows their clicks (home page regression).
    check("the buttons float above the re-shown strip",
          window.children().index(chrome.controls) >
          window.children().index(chrome._strip))
    window.setWindowTitle("")
    QApplication.processEvents()
    check("an empty title is never drawn", chrome.title.isHidden())


def test_buttons():
    print("window buttons")
    window, chrome, *_ = make_window()
    before = QRect(window.geometry())
    screen = window.screen()
    area = screen.availableGeometry() if screen is not None else None
    chrome.controls.zoom_btn.click()
    QApplication.processEvents()
    check("zoom fills the screen's work area",
          area is None or window.geometry() == area,
          f"{window.geometry()} vs {area}")
    check("a zoomed window has no rounded mask", window.mask().isEmpty())
    check("edges are inert while zoomed",
          chrome._press(window, FakeEvent(QPoint(2, 300))) is False)
    chrome.controls.zoom_btn.click()
    QApplication.processEvents()
    check("zoom restores the previous geometry", window.geometry() == before,
          f"{window.geometry()} vs {before}")
    check("the mask comes back", not window.mask().isEmpty())
    check("window_controls_zoom matches the button",
          (window_controls_zoom(window), chrome._zoomed)[1])
    window_controls_zoom(window)
    chrome.controls.minimize_btn.click()
    QApplication.processEvents()
    check("minimize minimizes", window.isMinimized())
    window.showNormal()
    QApplication.processEvents()
    chrome.controls.close_btn.click()
    QApplication.processEvents()
    check("close closes", not window.isVisible())


def test_static_guards():
    print("static guards")
    path = os.path.join(os.path.dirname(__file__), "..", "src", "gui",
                        "window_chrome.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    offenders = [node.lineno for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "window"]
    check("never calls QWidget.window()", not offenders, f"lines {offenders}")
    check("uses the parent-chain helper instead", "_top_level(" in source)
    check("strings are translated directly",
          'QCoreApplication.translate("Nugget"' in source and "_tr(" not in source)


def main():
    QApplication.instance() or QApplication([])
    test_cursor_mapping()
    test_top_level()
    test_install()
    test_rounded_region()
    test_native_shape_selection()
    test_native_backend()
    test_mask()
    test_edges()
    test_press_resize()
    test_resize_math()
    test_drag_targets()
    test_drag_moves_window()
    test_title_label()
    test_buttons()
    test_static_guards()
    print(f"\n{PASS} checks passed")


if __name__ == "__main__":
    main()
