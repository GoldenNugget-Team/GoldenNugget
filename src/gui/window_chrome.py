"""The app draws its own window frame.

The main window is frameless: the operating system paints no title bar next to
the app's surfaces, so the window's edge *is* the app's edge on macOS, Windows
and Linux alike. Everything the native frame used to provide is done here:

* **Window buttons** — close / minimize / zoom, drawn from the app's palette
  and floated in the window's top-left corner, where a title bar puts them.
  They stay above the page content, so they are visible in every mode
  (including the one with the navigation sidebar).
* **Rounded corners** — the window is clipped to a rounded rect
  (``rounded_region``), and the clip is dropped while maximized or full screen.

The corners are the one place where this cannot be done portably: a rounding
radius belongs to the window *frame*, a frameless window has none, and Qt
exposes no API for it. So the OS is asked first, through
``src/gui/native_corners.py`` — macOS clips the content view's layer (an
antialiased edge, and the native drop shadow survives) and Windows 11 rounds
through ``DwmSetWindowAttribute`` — and the mask below is the fallback for
everything else (Linux, Windows 10, a platform call that fails). The mask is
exact in shape but 1-bit, so that edge stays hard.
* **Moving** — the shared header (and the sidebar) drag the window; a double
  click zooms it.
* **Resizing** — the window edges and corners resize it, with the matching
  cursor. ``startSystemResize`` is tried first so the platform keeps its own
  resize loop where it has one; otherwise the geometry is driven directly.

Nothing here talks to a platform API: the same code path runs on every OS.
(That is also why the corners are a mask — see below.)

The surfaces that sit in the top-left corner must leave room for the buttons —
the header through ``LiquidNavBar.set_leading_inset`` and the sidebar through
``NavigationSidebar.set_top_inset``.

Offline regression suite: ``tools/test_window_chrome.py``.
"""

import math

from PySide6.QtCore import (QCoreApplication, QEvent, QObject, QPoint, QRect,
                            QRectF, Qt, QTimer)
from PySide6.QtGui import (QColor, QCursor, QImage, QPainter, QPen, QPolygon,
                           QRegion)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSlider,
                               QApplication, QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QScrollBar, QTabBar, QWidget)

from src.gui import native_corners
from src.gui.theme import ColorThemeManager, t
from src.version import App_Version

#: Radius of the window's corners (masked out of the rectangle).
CORNER_RADIUS = 10

#: Points per corner in the mask. ``QPainterPath.toFillPolygon`` flattens a
#: 10px arc to four vertices, which reads as a chamfer; sampling the arc
#: ourselves keeps every step well under a pixel.
CORNER_STEPS = 10

#: How close to an edge the pointer has to be to resize (px).
RESIZE_MARGIN = 5

#: Traffic-light buttons: diameter, gap and where the group starts.
BUTTON_SIZE = 14
BUTTON_GAP = 8
CONTROLS_LEFT = 16
CONTROLS_TOP = 10

#: Left space a top surface has to reserve for the buttons (left + width + air).
CONTROLS_INSET = 76

#: Right space the version label keeps from the window's right edge.
VERSION_RIGHT_INSET = 16

#: Height a surface anchored at the window's left edge (the sidebar) reserves.
TITLE_BAR_HEIGHT = 30

#: Room a page that starts at the window's top edge reserves for the buttons
#: (the home page has no shared header, so it pads its own content instead).
CONTENT_TOP_INSET = 34

#: The blank strip across the window's top that drags it, whatever page is
#: showing. Buttons and inputs inside it keep their own behaviour.
DRAG_STRIP_HEIGHT = 42

#: The widgets whose press stays a click, never a window drag.
_INTERACTIVE = (QAbstractButton, QAbstractSlider, QLineEdit, QAbstractItemView,
                QComboBox, QTabBar)

_CLOSE_COLOR = "#ff5f57"
_MINIMIZE_COLOR = "#febc2e"
_ZOOM_COLOR = "#28c840"
_INACTIVE_COLOR = "#4d4d4d"

#: How often the edge cursor is refreshed. Polling the pointer instead of
#: turning on mouse tracking for the whole widget tree keeps the app's mouse
#: overhead where it was — but the cursor still follows the window edges over
#: every page.
_CURSOR_POLL_MS = 120


def _top_level(widget):
    """The window *widget* belongs to.

    ``QWidget.window()`` cannot be used here: several pages keep their own
    ``self.window`` reference, which shadows the Qt method on the wrapped
    widget. Walking the parent chain avoids that collision.
    """
    while widget is not None:
        parent = widget.parentWidget()
        if parent is None:
            return widget
        widget = parent
    return None


def rounded_region(rect: QRect, radius: int = CORNER_RADIUS,
                   steps: int = CORNER_STEPS) -> QRegion:
    """A :class:`QRegion` of *rect* with its corners cut along a real arc.

    ``QWidget.setMask`` takes a 1-bit region, so there is no antialiasing to be
    had — but the shape itself must follow the arc: a ``QPainterPath``
    flattened by Qt turns a 10px corner into a four-vertex chamfer, which is
    the difference between "rounded" and "cut". The arc is sampled here
    instead, one vertex every few degrees.

    True native rounding (antialiased, with the window shadow) is not reachable
    from Qt: the radius belongs to the window frame a frameless window does not
    have. See the module docstring.
    """
    left, top = rect.left(), rect.top()
    right, bottom = rect.right(), rect.bottom()
    r = max(0.0, min(float(radius), rect.width() / 2.0, rect.height() / 2.0))
    if r <= 0:
        return QRegion(rect)
    corners = (
        (left + r, top + r, 180.0, 270.0),      # top-left
        (right - r, top + r, 270.0, 360.0),     # top-right
        (right - r, bottom - r, 0.0, 90.0),     # bottom-right
        (left + r, bottom - r, 90.0, 180.0),    # bottom-left
    )
    points = []
    for cx, cy, start, end in corners:
        for step in range(steps + 1):
            angle = math.radians(start + (end - start) * step / steps)
            points.append(QPoint(round(cx + r * math.cos(angle)),
                                 round(cy + r * math.sin(angle))))
    return QRegion(QPolygon(points))


def cursor_for_edges(edges) -> Qt.CursorShape | None:
    """The resize cursor for a set of ``Qt.Edges`` (None when not on an edge)."""
    if not edges:
        return None
    left = bool(edges & Qt.Edge.LeftEdge)
    right = bool(edges & Qt.Edge.RightEdge)
    top = bool(edges & Qt.Edge.TopEdge)
    bottom = bool(edges & Qt.Edge.BottomEdge)
    if left:
        return Qt.CursorShape.SizeFDiagCursor if top else \
            Qt.CursorShape.SizeBDiagCursor if bottom else \
            Qt.CursorShape.SizeHorCursor
    if right:
        return Qt.CursorShape.SizeBDiagCursor if top else \
            Qt.CursorShape.SizeFDiagCursor if bottom else \
            Qt.CursorShape.SizeHorCursor
    if top or bottom:
        return Qt.CursorShape.SizeVerCursor
    return None


class WindowButton(QAbstractButton):
    """One traffic-light button, painted by the app.

    A filled circle in the classic colour; hovering reveals the action glyph,
    and the whole group greys out while the window is in the background.
    """

    def __init__(self, color, glyph, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._glyph = glyph
        self.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event):
        # The glyph only appears on hover, so the circle has to repaint on
        # enter/leave as well as on a press.
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isActiveWindow()
        color = QColor(self._color) if active else QColor(_INACTIVE_COLOR)
        if active and self.underMouse():
            color = color.lighter(118)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(0.5, 0.5, BUTTON_SIZE - 1, BUTTON_SIZE - 1))
        if not (active and self.underMouse()):
            return
        pen = QPen(QColor(0, 0, 0, 150), 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = BUTTON_SIZE / 2
        half = BUTTON_SIZE / 4.6
        if self._glyph == "close":
            painter.drawLine(int(center - half), int(center - half),
                             int(center + half), int(center + half))
            painter.drawLine(int(center + half), int(center - half),
                             int(center - half), int(center + half))
        elif self._glyph == "minimize":
            painter.drawLine(int(center - half), int(center),
                             int(center + half), int(center))
        else:  # zoom
            painter.drawLine(int(center - half), int(center),
                             int(center + half), int(center))
            painter.drawLine(int(center), int(center - half),
                             int(center), int(center + half))


class WindowControls(QWidget):
    """The window's own title-bar buttons, bound to *window*."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(BUTTON_GAP)
        self.close_btn = WindowButton(_CLOSE_COLOR, "close", self)
        self.minimize_btn = WindowButton(_MINIMIZE_COLOR, "minimize", self)
        self.zoom_btn = WindowButton(_ZOOM_COLOR, "zoom", self)
        for button in (self.close_btn, self.minimize_btn, self.zoom_btn):
            row.addWidget(button)
        width = 3 * BUTTON_SIZE + 2 * BUTTON_GAP
        self.setFixedSize(width, BUTTON_SIZE)
        self.close_btn.setToolTip(QCoreApplication.translate("Nugget", "Close"))
        self.minimize_btn.setToolTip(
            QCoreApplication.translate("Nugget", "Minimize"))
        self.zoom_btn.setToolTip(QCoreApplication.translate("Nugget", "Zoom"))
        self.close_btn.clicked.connect(window.close)
        self.minimize_btn.clicked.connect(window.showMinimized)
        self.zoom_btn.clicked.connect(lambda: window_controls_zoom(window))


class _TitleStrip(QWidget):
    """A frosted title-bar zone laid over the window's top strip.

    It draws a blurred read of whatever page content flows underneath (the
    backdrop is re-grabbed whenever something repaints in the strip) and it
    blocks every pointer event: nothing behind the title bar is clickable or
    scrollable any more. The strip itself rejects presses to the chrome —
    the same `_press`/`_move` path as any other drag surface — so the top
    resize edge keeps working and the rest of the strip moves the window.
    """

    _BLUR_FACTOR = 8  # backdrop downscale; the upscale is the blur

    def __init__(self, window, chrome):
        super().__init__(window)
        self._chrome = chrome
        self._backdrop = None
        self._dirty = True
        self._painting = False
        self.setFixedHeight(DRAG_STRIP_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def invalidate(self):
        if self._painting:
            return  # the backdrop grab itself repaints the page behind
        self._dirty = True
        self.update()

    def refresh_geometry(self, width):
        self.resize(max(0, width), DRAG_STRIP_HEIGHT)

    # ---- pointer (all swallowed here, used as drag gestures for the chrome)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._chrome._press(self, event)
        event.accept()  # never fall through to the page behind

    def mouseMoveEvent(self, event):
        self._chrome._move(self, event)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._chrome._resize_grab = None
        self._chrome._move_grab = None
        self._chrome._move_dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self._chrome._is_drag_target(self, self._chrome._local(self, event)):
            window_controls_zoom(self._chrome._window)
        event.accept()

    def wheelEvent(self, event):
        event.accept()  # the strip is not a scroll surface for the page

    # ---- painting --------------------------------------------------------

    def paintEvent(self, event):
        # The backdrop grab below repaints page content, its Paint events hit
        # the app filter and would call invalidate() again — muted meanwhile,
        # otherwise the strip repaints forever.
        self._painting = True
        try:
            self._dirty = False
            self._rebuild_backdrop()
        finally:
            self._painting = False
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(self.rect(), self._backdrop)
        theme = ColorThemeManager.instance()
        tint = QColor(theme.c("bg_primary"))
        tint.setAlphaF(0.62)
        painter.fillRect(self.rect(), tint)
        edge = QColor(theme.c("divider"))
        edge.setAlphaF(0.65)
        painter.setPen(edge)
        painter.drawLine(0, self.height() - 1, self.width() - 1, self.height() - 1)
        painter.end()

    def _rebuild_backdrop(self):
        """Blur a fresh grab of the page content under the strip.

        The chrome widgets (buttons, title, version) are window children, not
        part of the central widget, so the grab sees the page alone and the
        blurred read is what the strip shows *behind* its own tint.
        """
        self._dirty = False
        window = self._chrome._window
        width, height = self.width(), self.height()
        shell = window.centralWidget()
        self._backdrop = None
        if shell is None or width < 8 or height < 4:
            return
        grab = shell.grab(QRect(0, 0, int(width * self.devicePixelRatioF()) or width, height))
        if grab.isNull():
            return
        small = grab.toImage().scaled(
            max(1, width // self._BLUR_FACTOR),
            max(1, height // self._BLUR_FACTOR),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._backdrop = QImage(small)


def window_controls_zoom(window):
    """Toggle the window between zoomed and normal.

    The chrome implements the zoom itself (see ``WindowChrome.toggle_zoom``),
    so a frameless window never covers the taskbar on Windows and behaves the
    same on every desktop. A window without chrome falls back to the platform.
    """
    chrome = getattr(window, "window_chrome", None)
    if isinstance(chrome, WindowChrome):
        chrome.toggle_zoom()
    elif window.isMaximized():
        window.showNormal()
    else:
        window.showMaximized()


class WindowChrome(QObject):
    """Frameless chrome for one top-level window.

    *header* and *sidebar* are the surfaces the window can be dragged by; they
    are also the surfaces that get the button room reserved.
    """

    def __init__(self, window, header=None, sidebar=None, pages=()):
        super().__init__(window)
        self._window = window
        self._header = header
        self._sidebar = sidebar
        self._resize_grab = None
        self._move_grab = None
        self._move_dragging = False
        self._cursor_widget = None
        self._cursor_backup = None
        self._zoomed = False
        self._pre_zoom_geometry = None

        flags = window.windowFlags()
        window.setWindowFlags(flags | Qt.WindowType.FramelessWindowHint)
        # macOS has to be told before the native window exists that it may show
        # through the corners (see native_corners).
        native_corners.prepare_window(window)

        self.controls = WindowControls(window)
        # The window's name, drawn next to the buttons where a title bar would
        # put it. It is only shown while the shared header is hidden (the home
        # page is full screen), otherwise the header already names the page.
        self.title = QLabel(window.windowTitle(), window)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title.setStyleSheet(t("window_title"))
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.title.adjustSize()

        # The app version, pinned to the top-right corner where a native title
        # bar sometimes shows a build tag. Same transparency deal as the title:
        # the top strip must keep dragging and resizing underneath it.
        self.version = QLabel(App_Version, window)
        self.version.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.version.setStyleSheet(t("window_version"))
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.version.adjustSize()

        # The frosted strip above every page: draws the blurred page that
        # flows underneath and keeps the content behind the title bar
        # unclickable. It sits under the buttons/title/version but over
        # everything the app stacks on the window.
        self._strip = _TitleStrip(window, self)

        if header is not None and hasattr(header, "set_leading_inset"):
            header.set_leading_inset(CONTROLS_INSET)
        if sidebar is not None and hasattr(sidebar, "set_top_inset"):
            sidebar.set_top_inset(TITLE_BAR_HEIGHT)
        for page in pages:
            # Pages without the shared header reach the window's top edge, so
            # they make room for the buttons themselves.
            if hasattr(page, "set_top_inset"):
                page.set_top_inset(CONTENT_TOP_INSET)

        window.installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        # The edge cursor follows the pointer over every page without turning
        # on mouse tracking across the widget tree.
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(_CURSOR_POLL_MS)
        self._cursor_timer.timeout.connect(self._poll_cursor)
        self._cursor_timer.start()

        self._relayout()

    # ---- zoom ------------------------------------------------------------

    def toggle_zoom(self):
        """Fill the screen's work area, or go back to the previous geometry.

        Deliberately not ``showMaximized``: a maximized frameless window covers
        the taskbar on Windows, and a native maximize also re-creates the
        window's decorations on some desktops. Filling the available geometry
        is the same thing on every OS.
        """
        window = self._window
        if self._zoomed:
            self._zoomed = False
            if self._pre_zoom_geometry is not None:
                window.setGeometry(self._pre_zoom_geometry)
            self._apply_shape()
            return
        screen = window.screen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            window.showMaximized()
            return
        self._pre_zoom_geometry = window.geometry()
        self._zoomed = True
        window.setGeometry(area)
        self._apply_shape()

    # ---- window events ---------------------------------------------------

    def eventFilter(self, watched, event):
        if watched is self._window:
            etype = event.type()
            if etype == QEvent.Type.WindowTitleChange:
                self.title.setText(self._window.windowTitle())
                self.title.adjustSize()
                self._relayout()
            elif etype in (QEvent.Type.Resize, QEvent.Type.Show,
                           QEvent.Type.WindowStateChange):
                self._relayout()
            return False
        if not isinstance(watched, QWidget) or _top_level(watched) is not self._window:
            return False
        etype = event.type()
        # A child widget gets ShowToParent/HideToParent, not Show/Hide — the
        # header is hidden and shown by the page switch, so both kinds count.
        if watched is self._header and etype in (
                QEvent.Type.Show, QEvent.Type.ShowToParent,
                QEvent.Type.Hide, QEvent.Type.HideToParent):
            self._sync_title()
            return False
        if etype == QEvent.Type.Paint and watched is not self._strip:
            # Whatever repaints inside the strip makes the blurred backdrop
            # stale (a page redraw, a drawer sliding under it, a popup) — one
            # extra strip-sized grab per frame at most, coalesced by update().
            rect = watched.rect().translated(
                watched.mapTo(self._window, watched.rect().topLeft()))
            if rect.y() < DRAG_STRIP_HEIGHT:
                self._strip.invalidate()
        if etype == QEvent.Type.MouseButtonPress:
            return self._press(watched, event)
        if etype == QEvent.Type.MouseMove:
            return self._move(watched, event)
        if etype == QEvent.Type.MouseButtonRelease:
            self._resize_grab = None
            self._move_grab = None
            self._move_dragging = False
            return False
        if etype == QEvent.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton and \
                    self._is_drag_target(watched, self._local(watched, event)):
                window_controls_zoom(self._window)
                return True
        return False

    def _relayout(self):
        """Re-place the buttons and re-cut the window's rounded corners."""
        self._strip.refresh_geometry(self._window.width())
        self._strip.raise_()
        self.controls.move(CONTROLS_LEFT, CONTROLS_TOP)
        self.controls.raise_()
        # The name sits centred over the window's top strip (where a native
        # title bar would draw it); it is re-centred on every resize.
        self.title.move((self._window.width() - self.title.width()) // 2,
                        CONTROLS_TOP + (BUTTON_SIZE - self.title.height()) // 2)
        self.title.raise_()
        self.version.move(self._window.width() - self.version.width()
                          - VERSION_RIGHT_INSET,
                          CONTROLS_TOP + (BUTTON_SIZE - self.version.height()) // 2)
        self.version.raise_()
        self._sync_title()
        self._apply_shape()

    def _sync_title(self):
        """Show the window name only while no header names the page."""
        header = self._header
        header_names_page = header is not None and header.isVisible()
        # The shared header is the title bar on the pages that show one: it
        # already reserves room for the buttons (set_leading_inset), so the
        # frosted strip stands down instead of blurring it and swallowing its
        # clicks. The home page has no header, so there the strip — and the
        # window name and version label pinned to its corners — stay as they
        # always were.
        self.title.setVisible(not header_names_page and
                              bool(self.title.text()))
        self.version.setVisible(not header_names_page)
        self._strip.setVisible(not header_names_page)
        if not header_names_page:
            # Re-showing the strip must not float it over its own chrome:
            # re-raise in the _relayout order (strip below buttons/name).
            self._strip.raise_()
            self.controls.raise_()
            self.title.raise_()
            self.version.raise_()

    def _retheme(self):
        self.title.setStyleSheet(t("window_title"))
        self.title.adjustSize()
        self.version.setStyleSheet(t("window_version"))
        self.version.adjustSize()
        self._strip.invalidate()
        self._relayout()

    def _apply_shape(self):
        window = self._window
        if self._zoomed or window.isMaximized() or window.isFullScreen():
            native_corners.clear(window)
            if window.mask():
                window.clearMask()
            return
        # Ask the OS first: its clip is antialiased and keeps the window's drop
        # shadow, which a 1-bit mask can never do. Only macOS and Windows 11
        # answer, and on Windows 10 the call fails — then the mask takes over.
        if native_corners.apply(window, CORNER_RADIUS):
            if window.mask():
                window.clearMask()
            return
        rect = window.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        # A region counts a pixel as inside when its *centre* is, so the shape
        # has to reach one pixel past the window or the last row and column
        # would be clipped away (Qt clamps the mask to the widget anyway).
        window.setMask(rounded_region(rect.adjusted(0, 0, 1, 1)))

    # ---- pointer ---------------------------------------------------------

    def _local(self, widget, event) -> QPoint:
        return widget.mapTo(self._window, event.position().toPoint())

    def _edges_at(self, point: QPoint):
        rect = self._window.rect()
        if not rect.contains(point):
            return Qt.Edges()
        edges = Qt.Edges()
        if point.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= rect.width() - 1 - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if point.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= rect.height() - 1 - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _press(self, watched, event):
        # A press always begins a new gesture. A release outside the window
        # never reaches this filter, so a stale grab has to be dropped here or
        # the next move would keep dragging from the old anchor.
        self._resize_grab = None
        self._move_grab = None
        self._move_dragging = False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self._zoomed or self._window.isMaximized() or \
                self._window.isFullScreen():
            return False
        if isinstance(watched, QScrollBar):
            return False  # the scrollbar owns its edge strip
        point = self._local(watched, event)
        edges = self._edges_at(point)
        if edges:
            if not self._request_system_resize(edges):
                self._resize_grab = (edges, event.globalPosition().toPoint(),
                                     self._window.geometry())
            return True
        if self._is_drag_target(watched, point):
            self._move_grab = (event.globalPosition().toPoint(),
                               self._window.pos())
            self._move_dragging = False
        return False

    def _request_system_move(self) -> bool:
        """Let the platform move the window; False when it has no such loop.

        ``startSystemMove`` hands the drag to the window manager, which is what
        keeps snapping and edge docking working. Not every platform plugin
        implements it (this macOS box returns False), so the caller always has
        the manual fallback.
        """
        handle = self._window.windowHandle()
        return bool(handle is not None and handle.startSystemMove())

    def _request_system_resize(self, edges) -> bool:
        """Let the platform resize the window (see ``_request_system_move``)."""
        handle = self._window.windowHandle()
        return bool(handle is not None and handle.startSystemResize(edges))

    def _move(self, watched, event):
        if self._resize_grab is not None:
            self._resize(event.globalPosition().toPoint())
            return True
        if self._move_grab is not None:
            return self._drag(event)
        return False

    def _drag(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._move_grab = None
            self._move_dragging = False
            return False
        start_global, start_pos = self._move_grab
        delta = event.globalPosition().toPoint() - start_global
        if not self._move_dragging:
            if delta.manhattanLength() < QApplication.startDragDistance():
                return False
            self._move_dragging = True
            if self._request_system_move():
                self._move_grab = None
                return True
        self._window.move(start_pos + delta)
        return True

    def _resize(self, current: QPoint):
        edges, start_global, start_geometry = self._resize_grab
        delta = current - start_global
        geometry = QRect(start_geometry)
        minimum = self._window.minimumSize()
        if edges & Qt.Edge.LeftEdge:
            left = min(geometry.left() + delta.x(),
                       geometry.right() - minimum.width() + 1)
            geometry.setLeft(left)
        elif edges & Qt.Edge.RightEdge:
            geometry.setRight(max(geometry.right() + delta.x(),
                                  geometry.left() + minimum.width() - 1))
        if edges & Qt.Edge.TopEdge:
            top = min(geometry.top() + delta.y(),
                      geometry.bottom() - minimum.height() + 1)
            geometry.setTop(top)
        elif edges & Qt.Edge.BottomEdge:
            geometry.setBottom(max(geometry.bottom() + delta.y(),
                                   geometry.top() + minimum.height() - 1))
        if geometry != self._window.geometry():
            self._window.setGeometry(geometry)

    def _is_drag_target(self, widget, point=None) -> bool:
        """True when a press here should move the window.

        Two places act as the title bar: the blank strip across the window's
        top (which is what the home page shows above its content, and what the
        header shows around its title) and the chrome surfaces themselves.
        Anything that accepts a press — a button, a scrollbar, an input — keeps
        it, so no control is ever swallowed by a drag.
        """
        strip = None
        if point is not None:
            strip = 0 <= widget.mapTo(self._window, point).y() <= DRAG_STRIP_HEIGHT
        if strip:
            # One seamless strip: the zone never splits on what happens to
            # sit under the pointer. Only a control that lives in the strip
            # itself keeps its press — the walk starts at the pressed widget
            # and stops at the first ancestor whose top edge falls below the
            # strip (pixels of such a control can never be in the strip). A
            # deep page container buried under interactive ancestors no
            # longer carves the zone into holes.
            walk = widget
            while walk is not None and walk is not self._window:
                if isinstance(walk, _INTERACTIVE):
                    return False
                if walk is not widget and \
                        walk.mapTo(self._window, walk.rect().topLeft()).y() > DRAG_STRIP_HEIGHT:
                    break
                walk = walk.parentWidget()
            return True
        if self._accepts_press(widget):
            return False
        for surface in (self._header, self._sidebar):
            if surface is None:
                continue
            walk = widget
            while walk is not None and walk is not surface:
                if not isinstance(walk, QLabel):
                    break
                walk = walk.parentWidget()
            if walk is surface:
                return True
        return False

    def _accepts_press(self, widget) -> bool:
        """True when *widget* (or a parent below the window) handles clicks."""
        walk = widget
        while walk is not None and walk is not self._window:
            if isinstance(walk, _INTERACTIVE):
                return True
            walk = walk.parentWidget()
        return False

    # ---- edge cursor -----------------------------------------------------

    def _poll_cursor(self):
        window = self._window
        if not window.isVisible() or not window.isActiveWindow() or \
                self._zoomed or window.isMaximized() or window.isFullScreen() or \
                QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        self._keep_raised()
        position = QCursor.pos()
        widget = QApplication.widgetAt(position)
        if widget is None or _top_level(widget) is not window:
            self._set_edge_cursor(None, None)
            return
        self._set_edge_cursor(widget, self._edges_at(window.mapFromGlobal(position)))

    def _set_edge_cursor(self, widget, edges):
        shape = cursor_for_edges(edges)
        if isinstance(widget, QScrollBar):
            widget, shape = None, None
        if self._cursor_widget is not None and \
                (self._cursor_widget is not widget or shape is None):
            self._restore_cursor()
        if widget is None or shape is None or self._cursor_widget is widget:
            return
        self._cursor_backup = widget.cursor()
        widget.setCursor(shape)
        self._cursor_widget = widget

    def _keep_raised(self):
        """Float the chrome over whatever the app stacks on the window.

        The liquid surfaces (drawers, dock, workspace panel, popups) are built
        after the chrome, so as window children they start ABOVE the buttons,
        the title and the version label — and their scroll bars can cross the
        top strip. The chrome is meant to stay visible in every mode (buttons
        are raised again on every relayout), so whenever the topmost window
        child is not one of ours, raise the chrome back over it. The check is
        cheap enough for the 120 ms cursor poll.
        """
        ours = (self.controls, self.title, self.version, self._strip)
        for child in reversed(self._window.children()):
            if isinstance(child, QWidget):
                if child in ours:
                    return
                self._relayout()
                return

    def _restore_cursor(self):
        widget, backup = self._cursor_widget, self._cursor_backup
        self._cursor_widget = None
        self._cursor_backup = None
        if widget is None:
            return
        try:
            if backup is None:
                widget.unsetCursor()
            else:
                widget.setCursor(backup)
        except RuntimeError:
            pass  # the page was rebuilt while the pointer sat on its edge


def install_window_chrome(window, header=None, sidebar=None, pages=(),
                          enabled: bool = True):
    """Give *window* the app's own frame instead of the OS one.

    Returns the :class:`WindowChrome` (or None when disabled). *header* and
    *sidebar* are the surfaces that can drag the window (and that reserve room
    for the buttons); *pages* are the pages that reach the window's top edge
    and therefore pad their own content.
    """
    if not enabled:
        return None
    chrome = WindowChrome(window, header=header, sidebar=sidebar, pages=pages)
    # The free helpers (``window_controls_zoom``) find the chrome this way.
    window.window_chrome = chrome
    return chrome
