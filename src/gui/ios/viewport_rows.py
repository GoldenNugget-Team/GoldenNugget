from bisect import bisect_left, bisect_right

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QTimer
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QWidget


class ViewportRows(QObject):
    def __init__(self, content):
        super().__init__(content)
        self._content = content
        self._rows = []
        self._scroll = None
        self._dirty = True
        self._indexed = []
        self._tops = []
        self._bounds = {}
        self._active = set()
        self._max_height = 0
        self._scrolling = False
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settled)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh)
        content.installEventFilter(self)

    def wrap(self, card):
        from src.gui.liquid.cards import prepare_card
        prepare_card(card)
        row = _ViewportRow(card, self)
        self._rows.append(row)
        self._dirty = True
        return row

    def clear(self):
        self._timer.stop()
        self._settle_timer.stop()
        self._scrolling = False
        self._rows.clear()
        self._indexed.clear()
        self._tops.clear()
        self._bounds.clear()
        self._active.clear()
        self._dirty = True

    def request(self, *_args):
        if not self._timer.isActive():
            self._timer.start(16)

    def invalidate(self, *_args):
        self._dirty = True
        self.request()

    def _scrolled(self, *_args):
        if not self._scrolling:
            for row in self._active:
                card = row._card
                motion = getattr(card, 'motion', None)
                if motion is not None:
                    motion.stop()
                    card.hover = 0.0
                    card.update()
                pointer = getattr(card, '_pointer_motion', None)
                if pointer is not None:
                    pointer.stop()
        self._scrolling = True
        self._settle_timer.start(90)
        self.request()

    def _settled(self):
        self._scrolling = False

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self.invalidate()
        return False

    def _build_index(self):
        indexed = []
        for row in self._rows:
            if row.isVisibleTo(self._content):
                top = row.mapTo(self._content, QPoint()).y()
                indexed.append((top, top + row.height(), row))
        indexed.sort(key=lambda item: item[0])
        self._indexed = indexed
        self._tops = [item[0] for item in indexed]
        self._bounds = {row: (top, bottom) for top, bottom, row in indexed}
        self._max_height = max((bottom - top for top, bottom, _ in indexed), default=0)
        self._dirty = False

    def _refresh(self):
        if self._scroll is None:
            parent = self._content.parentWidget()
            while parent is not None and not isinstance(parent, QScrollArea):
                parent = parent.parentWidget()
            if parent is None:
                return
            self._scroll = parent
            parent.verticalScrollBar().valueChanged.connect(self._scrolled)
            parent.verticalScrollBar().rangeChanged.connect(self.invalidate)
            parent.viewport().installEventFilter(self)
        viewport = self._scroll.viewport()
        if not self._content.isVisible():
            for row in self._active:
                row.display(False)
            self._active.clear()
            return
        if self._dirty:
            self._build_index()
        top = self._content.mapFrom(viewport, QPoint()).y()
        bottom = top + viewport.height()
        start = bisect_left(self._tops, top - 420 - self._max_height)
        end = bisect_right(self._tops, bottom + 420)
        desired = {row for y, last, row in self._indexed[start:end]
                   if last >= top - 420}
        for row in self._active - desired:
            bounds = self._bounds.get(row)
            if bounds is not None and bounds[1] >= top - 700 and bounds[0] <= bottom + 700:
                desired.add(row)
            else:
                row.display(False)
                if not row._card.isHidden():
                    desired.add(row)
        for row in desired - self._active:
            row.display(True)
        self._active = desired


class _ViewportRow(QWidget):
    def __init__(self, card, controller):
        super().__init__()
        self._card = card
        self._controller = controller
        self._height_cache = {}
        card.installEventFilter(self)
        for key in ("searchText", "sortTitle", "categoryTitle"):
            value = card.property(key)
            if isinstance(value, str):
                self.setProperty(key, value)
        self.setToolTip(card.toolTip())
        self.setAccessibleDescription(card.accessibleDescription())
        policy=QSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        card.setParent(self)
        card.hide()

    def sizeHint(self):
        return QSize(210,self.heightForWidth(max(210,self.width())))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self,width):
        key = (width, QApplication.instance().property('liquid_card_density'))
        if key in self._height_cache:
            return self._height_cache[key]
        layout=self._card.layout()
        height=layout.totalHeightForWidth(width) if layout is not None else -1
        floor=112 if QApplication.instance().property('liquid_card_density')=='compact'else 132
        if len(self._height_cache) >= 8:
            self._height_cache.clear()
        self._height_cache[key] = max(floor,height)
        return self._height_cache[key]

    def eventFilter(self, target, event):
        if target is self._card and event.type() == QEvent.LayoutRequest:
            self._height_cache.clear()
            self._controller.invalidate()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self._controller.invalidate()

    def hideEvent(self, event):
        self._card.hide()
        self._controller.invalidate()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._card.isVisible():
            self._fit()
        self._controller.invalidate()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._controller.invalidate()

    def _fit(self):
        self._card.setGeometry(self.rect())

    def display(self, shown):
        if shown:
            if self._card.isHidden():
                self._fit()
                self._card.show()
        elif not self._card.isHidden():
            focus = QApplication.focusWidget()
            if self.isVisible() and focus is not None and (focus is self._card or self._card.isAncestorOf(focus)):
                return
            self._card.hide()
