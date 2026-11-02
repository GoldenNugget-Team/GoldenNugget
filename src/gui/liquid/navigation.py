import time
from PySide6.QtCore import Qt, QEvent, QSize, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QApplication
from src.gui.theme import ColorThemeManager
from .controls import GlassPanel, LiquidButton


class LiquidNavBar(GlassPanel):
    """Shared page header, painted as one surface with the window.

    It used to be a floating glass card: rounded, translucent, and inset from
    the page edge by the ``iosNavWrap`` margins. The header now fills with the
    same background the pages use and only marks its lower edge with a hairline
    divider, so the title bar reads as part of the window instead of a panel
    sitting on top of it. The glass panel base is kept for the rest of the
    widget tree (``GlassPanel`` supplies the transparent-background setup).
    """

    def __init__(self,title='',parent=None,on_back=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self.update)
        self._category_buttons=[]
        self._right_btn=None
        root=QVBoxLayout(self)
        root.setContentsMargins(14,9,14,9)
        root.setSpacing(5)
        row=QHBoxLayout()
        row.setSpacing(12)
        self.back_btn=LiquidButton('‹')
        self.back_btn.setFixedSize(40,40)
        self.back_btn.setAccessibleName('Back')
        if on_back:
            self.back_btn.clicked.connect(on_back)
        row.addWidget(self.back_btn)
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

    def set_back_visible(self,visible):
        self.back_btn.setVisible(visible)

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
