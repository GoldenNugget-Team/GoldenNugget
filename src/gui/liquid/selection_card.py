from PySide6.QtCore import QEasingCurve, QEvent, Qt, QVariantAnimation, Slot
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QWidget,
)
from shiboken6 import isValid


class SelectionCard(QWidget):
    """Input-transparent selection outline, driven by the card's real switch."""
    def __init__(self, card, switch):
        super().__init__(card)
        self.card = card
        self.switch = switch
        self.selected = switch.isChecked()
        self.progress = 1.0
        self.pressed = None
        self.press_active = False
        self.favorite_animation = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.motion = QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.Linear)
        self.motion.valueChanged.connect(self._step)
        switch.toggled.connect(self.sync)
        switch.installEventFilter(self)
        card.installEventFilter(self)
        from .controls import FavoriteButton
        for favorite in card.findChildren(FavoriteButton):
            favorite.toggled.connect(self.favorite_changed)
        for child in card.findChildren(QWidget):
            if child is not self and not self._interactive(child):
                child.installEventFilter(self)
        card.setCursor(Qt.PointingHandCursor)
        card.setFocusPolicy(Qt.StrongFocus)
        labels=card.findChildren(QLabel)
        card.setAccessibleName(switch.accessibleName() or (labels[0].text() if labels else 'Toggle setting'))
        card.setAccessibleDescription('Enabled' if self.selected else 'Disabled')
        self.setGeometry(card.rect())
        self.show()
        self.raise_()

    def _interactive(self, target):
        while target is not None and target is not self.card:
            if isinstance(target, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QAbstractSlider)):
                return True
            if isinstance(target, QLabel):
                flags=target.textInteractionFlags()
                if flags & (Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard) or '<a ' in target.text().lower():
                    return True
            target = target.parentWidget()
        return False

    def _step(self, value):
        self.progress = float(value)
        self.update()

    def favorite_changed(self, checked):
        self.animate_border(favorite=True,reverse=not checked)
        label = getattr(self, 'action_label', None)
        if label is not None and hasattr(label, 'show_favorite_feedback'):
            label.show_favorite_feedback(checked)

    def animate_border(self, favorite=False, reverse=False):
        self.favorite_animation=favorite
        self.reverse_animation=reverse
        self.motion.stop()
        self.progress=1.0
        if not QApplication.instance().property('liquid_reduce_motion'):
            self.progress=0.0
            self.motion.setDuration(360 if reverse else 480)
            self.motion.setStartValue(0.0)
            self.motion.setEndValue(1.0)
            self.motion.start()
        self.update()

    def sync(self, *_):
        if not isValid(self.switch):
            return
        selected = self.switch.isChecked()
        changed = selected != self.selected
        if not changed:
            return
        self.selected = selected
        self.card.setAccessibleDescription('Enabled' if selected else 'Disabled')
        update_label=getattr(self,'update_action_label',None)
        if update_label is not None:
            update_label()
        if changed:
            self.animate_border()
        self.update()

    @Slot()
    def update_action_label(self):
        label=getattr(self,'action_label',None)
        if label is None or not isValid(label) or not isValid(self.switch):
            return
        from src.gui.theme import ColorThemeManager
        colors=ColorThemeManager.instance().colors
        checked=self.switch.isChecked()
        state=(checked,colors.text_primary,colors.text_secondary)
        if getattr(label,'_selection_style_state',None)==state:
            return
        label._selection_style_state=state
        if hasattr(label, 'set_selection_state'):
            label.set_selection_state('Enabled' if checked else 'Disabled',
                                      colors.text_primary if checked else colors.text_secondary)
            return
        label.setText('Enabled' if checked else 'Disabled')
        label.setStyleSheet('background:transparent;border:none;color:'+(
            colors.text_primary if checked else colors.text_secondary)+';')

    def eventFilter(self, target, event):
        kind = event.type()
        if target is self.switch:
            # Preset and device refreshes intentionally block switch signals.
            if kind in (QEvent.Paint, QEvent.Show, QEvent.EnabledChange):
                self.sync()
            return False
        if target is self.card:
            if kind == QEvent.Resize:
                self.setGeometry(self.card.rect())
                self.raise_()
            elif kind == QEvent.Hide:
                self.motion.stop()
                self.progress = 1.0
                self.pressed = None
                self.press_active = False
        if kind not in (QEvent.KeyPress, QEvent.MouseButtonPress,
                        QEvent.MouseButtonDblClick, QEvent.MouseButtonRelease):
            return False
        if self._interactive(target):
            return False
        if target is self.card and kind==QEvent.KeyPress and event.key() in (Qt.Key_Space,Qt.Key_Return):
            if self.switch.isEnabled() and not event.isAutoRepeat():
                self.switch.click()
            return True
        if kind in (QEvent.MouseButtonPress,QEvent.MouseButtonDblClick) and event.button() == Qt.LeftButton:
            if self.switch.isEnabled():
                self.pressed = target.mapTo(self.card, event.position().toPoint())
                self.press_active=True
                self.update()
                return True
        elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self.pressed is not None:
                point = target.mapTo(self.card, event.position().toPoint())
                click = self.card.rect().contains(point) and (
                    point-self.pressed).manhattanLength() < QApplication.startDragDistance()
                self.pressed = None
                self.press_active=False
                if click and self.switch.isEnabled():
                    self.animate_border()
                    self.update()
                    self.switch.click()
                self.update()
                return True
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtCore import QRectF
        bounds = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        shape = QPainterPath()
        shape.addRoundedRect(bounds, 16, 16)
        painter.setBrush(Qt.NoBrush)
        if self.press_active:
            painter.fillPath(shape,QColor(255,255,255,12))
            painter.setPen(QPen(QColor(255,255,255,200),1.5))
            painter.drawPath(shape)
        if self.selected:
            painter.fillPath(shape,QColor(255,255,255,5))
        painter.setPen(QPen(QColor(245,247,250,95) if self.selected else QColor(180,187,198,30), 1))
        painter.drawPath(shape)
        if self.progress < 1:
            fade=1-self.progress
            gold=self.favorite_animation
            base=(214,185,103) if gold else (255,255,255)
            bright=(224,200,137) if gold else (255,255,255)
            painter.setPen(QPen(QColor(*base,round((100 if gold else 160)*fade*fade)),1.5))
            painter.drawPath(shape)
            direction=-1 if getattr(self,'reverse_animation',False) else 1
            wave=QConicalGradient(bounds.center(),90-360*self.progress*direction)
            wave.setColorAt(0,QColor(*base,0))
            wave.setColorAt(.68,QColor(*base,0))
            wave.setColorAt(.88,QColor(*bright,round((180 if gold else 230)*fade)))
            wave.setColorAt(.94,QColor(*base,round(65*fade)))
            wave.setColorAt(1,QColor(*base,0))
            painter.setPen(QPen(wave,4))
            painter.drawPath(shape)
            painter.setPen(QPen(wave,1.4))
            painter.drawPath(shape)
            if not gold:
                return
            band=max(60,bounds.width()*.25)
            travel=1-self.progress if getattr(self,'reverse_animation',False) else self.progress
            x=-band+(bounds.width()+2*band)*travel
            sweep=QLinearGradient(x-band,0,x+band,bounds.height()*.3)
            sweep.setColorAt(0,QColor(214,185,103,0))
            sweep.setColorAt(.35,QColor(181,151,74,12))
            sweep.setColorAt(.5,QColor(224,200,137,32))
            sweep.setColorAt(.7,QColor(181,151,74,10))
            sweep.setColorAt(1,QColor(214,185,103,0))
            painter.fillPath(shape,sweep)


def bind_selection_card(card, switch, *, favorite_feedback=False):
    card._selection_surface = SelectionCard(card, switch)
    switch._selection_surface = card._selection_surface
    from PySide6.QtGui import QFont

    from src.gui.theme import ColorThemeManager
    if favorite_feedback:
        from .favorite_feedback import FavoriteFeedbackLabel
        label = FavoriteFeedbackLabel(card)
    else:
        label=QLabel(card)
    font=QFont('Inter Variable')
    font.setPixelSize(12)
    font.setWeight(QFont.Medium)
    label.setFont(font)
    label.setAlignment(Qt.AlignCenter)
    label.setMinimumWidth(62)
    if favorite_feedback:
        label.reserve_status_width()
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    label.setProperty('selectionActionLabel',True)
    card._selection_surface.action_label=label
    ColorThemeManager.instance().theme_changed.connect(card._selection_surface.update_action_label)
    def replace(layout):
        for index in range(layout.count()):
            item=layout.itemAt(index)
            if item.widget() is switch:
                layout.insertWidget(index,label)
                return True
            if item.layout() is not None and replace(item.layout()):
                return True
        return False
    replace(card.layout())
    card._selection_surface.update_action_label()
    switch.setFocusPolicy(Qt.NoFocus)
    switch.hide()
