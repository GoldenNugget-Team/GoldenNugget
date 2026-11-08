from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
)
from shiboken6 import delete


class ControlGrid(QLayout):
    def __init__(self, max_columns=None):
        super().__init__()
        self.max_columns = max_columns
        self.items = []
        self._measurements = {}
        self._height_hints = {}
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(12)

    def invalidate(self):
        self._measurements = {}
        self._height_hints = {}
        super().invalidate()

    def addItem(self, item):
        self.items.append(item)
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        item = self.items.pop(index) if 0 <= index < len(self.items) else None
        self.invalidate()
        return item

    def expandingDirections(self):
        return Qt.Horizontal

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        key=(width,QApplication.instance().property('liquid_card_density'))
        if key not in self._height_hints:
            self._height_hints[key]=self.arrange(QRect(0, 0, width, 0), False)
        return self._height_hints[key]

    def minimumSize(self):
        return QSize(210, 0)

    def sizeHint(self):
        return QSize(960, self.heightForWidth(960))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, True)

    def arrange(self, rect, apply):
        visible = [item for item in self.items if not item.widget().isHidden()]
        compact=QApplication.instance().property('liquid_card_density')=='compact'
        columns=max(1,min(max(1,len(visible)),4 if compact else 3,(rect.width()+self.spacing())//(235 if compact else 280)))
        if self.max_columns is not None:
            columns=min(columns,self.max_columns)
        width=max(1,(rect.width()-(columns-1)*self.spacing())//columns)
        y = rect.y()
        for start in range(0, len(visible), columns):
            row = visible[start:start + columns]
            height=max(self.card_height(item.widget(),width,compact) for item in row)
            if apply:
                for column, item in enumerate(row):
                    item.setGeometry(QRect(rect.x() + column * (width + self.spacing()), y, width, height))
            y += height + self.spacing()
        return max(0, y - rect.y() - self.spacing())

    def card_height(self,widget,width,compact):
        card=getattr(widget,'_card',widget)
        floor=72 if card.property('liquidCompactCard') else 112 if compact else 132
        layout=card.layout()
        if layout is None:
            return floor
        key=(id(card),width,compact)
        if key not in self._measurements:
            if card is not widget and not card.property('liquidCompactCard') and widget.hasHeightForWidth():
                height=widget.heightForWidth(width)
            else:
                height=layout.totalHeightForWidth(width)
            self._measurements[key]=max(floor,height)
        return self._measurements[key]


def prepare_card(card):
    if card.property('liquidControlCard'):
        return
    old = card.layout()
    if old is None:
        return
    card.setProperty('liquidControlCard', True)
    parts = []
    while old.count():
        parts.append(old.takeAt(0))
    delete(old)
    root = QVBoxLayout(card)
    root.setContentsMargins(16, 15, 16, 14)
    root.setSpacing(10)
    header = QHBoxLayout()
    header.setSpacing(7)
    text = parts.pop(0) if parts else None
    descriptions = []
    if text and text.layout():
        body = text.layout()
        title = body.takeAt(0)
        if title:
            header.addItem(title)
            header.setStretch(0, 1)
        while body.count():
            descriptions.append(body.takeAt(0))
        delete(body)
    elif text:
        header.addItem(text)
        header.setStretch(0, 1)
    badges, actions, switches, editors = [], [], [], []
    for part in parts:
        widget = part.widget()
        if widget is None:
            continue
        if isinstance(widget, QLabel) and widget.text() == 'NEW':
            badges.append(part)
            widget.setFixedSize(34, 18)
            widget.setStyleSheet('color:#ffb9c3;background:#6e293b;border-radius:6px;font-size:9px;font-weight:700;')
        elif widget.property('liquidValueEntry'):
            editors.append(part)
        elif widget.accessibleName().startswith(('About ', 'Favorite: ')) or widget.__class__.__name__=='FavoriteButton':
            header.addItem(part)
        elif 'switch' in widget.__class__.__name__.lower():
            switches.append(part)
        else:
            actions.append(part)
    for part in badges:
        header.addItem(part)
    root.addLayout(header)
    for part in descriptions:
        root.addItem(part)
    root.addStretch(1)
    for part in editors:
        root.addItem(part)
    footer = QHBoxLayout()
    footer.setSpacing(7)
    for part in actions:
        footer.addItem(part)
    footer.addStretch(1)
    for part in switches:
        footer.addItem(part)
    root.addLayout(footer)
    card.setMinimumWidth(0)
    configure_card(card)
    card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


def configure_card(card):
    compact=QApplication.instance().property('liquid_card_density')=='compact'
    margin=10 if compact else 12
    card.layout().setContentsMargins(margin,9,margin,9)
    card.layout().setSpacing(6 if compact else 9)
    card.setMinimumHeight(72 if card.property('liquidCompactCard') else 112 if compact else 132)
