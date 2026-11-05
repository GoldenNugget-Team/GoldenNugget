import time
from PySide6.QtCore import Qt, QCoreApplication, QEvent, QPoint, QSize, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QApplication
from src.gui.theme import ColorThemeManager, theme_pixmap
from src.gui.window_chrome import CONTROLS_LEFT, CONTROLS_TOP, BUTTON_SIZE, _top_level
from .controls import GlassPanel, LiquidButton

# Ensure resources are registered (icons used below)
try:
    from src.qt import resources_rc  # noqa: F401
except Exception:
    resources_rc = None


class BackCapsule(LiquidButton):
    """Header's back button: a pill with a chevron icon and the word "Back".

    It floats over the header's left edge, right below the app-drawn window
    buttons (close / minimize / zoom), and refits its width to the label on
    every change so live translation cannot clip the word.
    """

    labelFitted=Signal(int)

    def __init__(self,parent=None):
        super().__init__('',parent)
        self.setIconSize(QSize(14,14))
        self.setFixedHeight(30)
        self.setStyleSheet('QPushButton#liquidButton { background:transparent; border:none; padding:3px 12px; font-size:14px; font-weight:600; }')

    def fit_to_label(self):
        width=max(80,self.sizeHint().width())
        if width!=self.width():
            self.setFixedWidth(width)
        self.labelFitted.emit(self.width())

    def setText(self,text):
        super().setText(text)
        self.fit_to_label()


class LiquidNavBar(GlassPanel):
    """Shared page header, painted as one surface with the window.

    It used to be a floating glass card: rounded, translucent, and inset from
    the page edge by the ``iosNavWrap`` margins. The header now fills with the
    same background the pages use and only marks its lower edge with a hairline
    divider, so the title bar reads as part of the window instead of a panel
    sitting on top of it. The glass panel base is kept for the rest of the
    widget tree (``GlassPanel`` supplies the transparent-background setup).
    """

    #: Left margin of the header content (the window's edge inset).
    LEADING_MARGIN = 14

    #: The back capsule sits directly below the app-drawn window buttons
    #: (close / minimize / zoom, see ``src/gui/window_chrome.py``).
    BACK_GAP = 2

    #: Air between the back capsule and the header's own content (title row).
    BACK_TRAIL = 12

    def __init__(self,title='',parent=None,on_back=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self.update)
        self._category_buttons=[]
        self._right_btn=None
        self._controls_inset=0
        root=QVBoxLayout(self)
        root.setContentsMargins(self.LEADING_MARGIN,9,14,9)
        root.setSpacing(5)
        row=QHBoxLayout()
        row.setSpacing(12)
        self.back_btn=BackCapsule(self)
        self._configure_back_capsule()
        if on_back:
            self.back_btn.clicked.connect(on_back)
        self.icon_lbl=QLabel()
        self.icon_lbl.setFixedSize(28,28)
        row.addWidget(self.icon_lbl)
        self.title_lbl=QLabel(title)
        self.title_lbl.setStyleSheet('font-size:22px;font-weight:650;background:transparent;')
        row.addWidget(self.title_lbl,1)
        self._right_layout=QHBoxLayout()
        row.addLayout(self._right_layout)
        root.addLayout(row)
        self._categories=QScrollArea()
        self._categories.setWidgetResizable(True)
        self._categories.setFrameShape(QScrollArea.NoFrame)
        self._categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._categories.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._categories.setFixedHeight(36)
        self._categories.setStyleSheet('background:transparent;border:none;')
        self._category_content=QWidget()
        self._category_layout=QHBoxLayout(self._category_content)
        self._category_layout.setContentsMargins(0,0,0,0)
        self._category_layout.setSpacing(4)
        self._categories.setWidget(self._category_content)
        self._categories.viewport().installEventFilter(self)
        self._category_content.installEventFilter(self)
        root.addWidget(self._categories)
        self._scroll_animation=QVariantAnimation(self)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation.valueChanged.connect(lambda value:self._categories.horizontalScrollBar().setValue(round(value)))
        self.setFixedHeight(62)

    def _configure_back_capsule(self):
        """Geometry + content of the back capsule under the window buttons."""
        button=self.back_btn
        colors=ColorThemeManager.instance().colors
        button.setIcon(QIcon(theme_pixmap(':/icon/chevron.left.svg',
                                          colors.text_primary,12,
                                          self.devicePixelRatioF())))
        label=QCoreApplication.translate('Nugget','Back')
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.labelFitted.connect(self._apply_leading_margins)
        button.setText(label)   # also fits the button width
        self._reposition_back_capsule()

    def _back_capsule_spot(self):
        """Where the back capsule belongs, in *this header's* coordinates.

        ``move()`` on the capsule takes parent-relative coordinates, while the
        traffic lights are placed by ``WindowChrome`` in **window** ones — the
        two only agree while the header itself sits in the window's top-left
        corner, and that is exactly what stopped being true: the shared header
        used to live inside the page's centred column (so on any window wider
        than ``IOS_CONTENT_MAX_WIDTH`` it started ~300px to the right, and the
        capsule slid with it) and it shifts right again when the sidebar
        opens. The spot is therefore mapped, never assumed — the same lesson
        as ``PresetPopup._panel_pos``.

        The buttons' column wins whenever the header actually starts at the
        window's left edge; when it does not (a sidebar beside it) the capsule
        keeps a small air gap from the header's own edge instead, so it can
        never hang over the neighbouring surface. Vertically it is clamped the
        same way: under the buttons when there is room, otherwise just inside
        the header.
        """
        window=_top_level(self)
        if window is None:
            return QPoint(CONTROLS_LEFT,CONTROLS_TOP+BUTTON_SIZE+self.BACK_GAP)
        # The window's origin seen from this header (negative while the header
        # is inset: the floating dock reserves (10, 6) on ``body_row``, a
        # sidebar the content's width), so adding it turns a window point into
        # a local one.
        origin=self.mapFrom(window,QPoint(0,0))
        x=max(CONTROLS_LEFT,4-origin.x())
        y=max(CONTROLS_TOP+BUTTON_SIZE+self.BACK_GAP,6-origin.y())
        return QPoint(x+origin.x(),y+origin.y())

    def _reposition_back_capsule(self):
        """Keep the capsule under the buttons; the header moves, the pill stays."""
        self.back_btn.move(self._back_capsule_spot())

    def showEvent(self,event):
        # First shown: the header is in the window's tree by now, so the spot
        # computed at construction time is finally the real one.
        super().showEvent(event)
        self._reposition_back_capsule()

    def moveEvent(self,event):
        # The sidebar opening / closing, or a layout change on the way up,
        # repositions this header without resizing it.
        super().moveEvent(event)
        self._reposition_back_capsule()

    def resizeEvent(self,event):
        # A window resize (including the zoom button) moves and resizes the
        # header — the capsule has to follow it, not slide away from the
        # buttons.
        super().resizeEvent(event)
        self._reposition_back_capsule()

    def set_leading_inset(self,px):
        """Reserve room on the left for the window's own buttons.

        The back capsule floats *below* the app-drawn traffic lights and
        claims its own room on the left edge; the title row (which shares its
        vertical band with the buttons) still starts after them (see
        ``src/gui/window_chrome.py``).
        """
        root=self.layout()
        if root is None:
            return
        self._controls_inset=max(0,int(px))
        self._apply_leading_margins()

    def _apply_leading_margins(self,*_fitted):
        """Keep the title row clear of the window buttons AND the capsule."""
        root=self.layout()
        if root is None:
            return
        margins=root.contentsMargins()
        leading=self.LEADING_MARGIN+self._controls_inset
        if self.back_btn.isVisibleTo(self):
            leading=max(leading,self.back_btn.x()+self.back_btn.width()+self.BACK_TRAIL)
        root.setContentsMargins(leading,margins.top(),margins.right(),margins.bottom())

    def set_back_visible(self,visible):
        self.back_btn.setVisible(visible)
        self._reposition_back_capsule()
        self._apply_leading_margins()

    def paintEvent(self,event):
        # One surface with the window: same background as the pages, no glass,
        # no rounded box. A single hairline marks where the header ends.
        p=QPainter(self)
        c=ColorThemeManager.instance().colors
        p.fillRect(self.rect(),QColor(c.bg_primary))
        p.setPen(QPen(QColor(c.divider),1))
        y=self.height()-1
        p.drawLine(0,y,self.width(),y)

    def _retheme(self):
        # Colours are read live in paintEvent; a repaint is all that is needed.
        self.update()

    def set_title(self,title):
        self.title_lbl.setText(title)

    def set_icon(self,path):
        self.icon_lbl.setVisible(bool(path))
        if path:
            self.icon_lbl.setPixmap(QPixmap(path).scaled(28,28,Qt.KeepAspectRatio,Qt.SmoothTransformation))

    def set_categories(self,categories):
        while self._category_layout.count():
            item=self._category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._category_buttons=[]
        self._categories.setVisible(len(categories)>1)
        for title,callback in categories if len(categories)>1 else []:
            button=LiquidButton(title.replace('&','&&'))
            button.setMinimumHeight(32)
            button.setFixedHeight(32)
            button.setFixedWidth(button.sizeHint().width()+10)
            button.clicked.connect(lambda _,b=button,cb=callback:self._jump(b,cb))
            button.installEventFilter(self)
            self._category_layout.addWidget(button)
            self._category_buttons.append(button)
        self._category_layout.addStretch()
        self.setFixedHeight(103 if len(categories)>1 else 62)

    def _jump(self,selected,callback):
        self._selection_started=time.monotonic()
        for button in self._category_buttons:
            button.setProperty('selected',button is selected)
            button.update()
        callback()

    def eventFilter(self,target,event):
        if event.type()==QEvent.Wheel:
            bar=self._categories.horizontalScrollBar()
            delta=event.pixelDelta().x() or event.pixelDelta().y()
            if not delta:
                delta=(event.angleDelta().x()or event.angleDelta().y())/120*90
            if bar.maximum()>0 and delta:
                end=max(0,min(bar.maximum(),bar.value()-round(delta)))
                self._scroll_animation.stop()
                self._scroll_animation.setDuration(0 if QApplication.instance().property('liquid_reduce_motion')else 180)
                self._scroll_animation.setStartValue(bar.value())
                self._scroll_animation.setEndValue(end)
                self._scroll_animation.start()
                return True
        return super().eventFilter(target,event)

    def set_right_action(self,text,callback):
        self.clear_right_action()
        self._right_btn=LiquidButton(text)
        self._right_btn.clicked.connect(callback)
        self._right_layout.addWidget(self._right_btn)

    def clear_right_action(self):
        if self._right_btn:
            self._right_layout.removeWidget(self._right_btn)
            self._right_btn.hide()
            self._right_btn.deleteLater()
            self._right_btn=None
