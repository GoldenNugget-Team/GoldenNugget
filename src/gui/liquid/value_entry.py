from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy

from src.gui.theme import ColorThemeManager, theme_pixmap


class GlassValueEntry(QPushButton):
    def __init__(self,title,parent=None):
        super().__init__(parent)
        self.title=title
        self.value='Not set'
        self.setProperty('liquidValueEntry',True)
        self.setMinimumWidth(0)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet('background:transparent;border:none;')
        self.set_display_value(self.value)
        ColorThemeManager.instance().theme_changed.connect(self.update)

    def sizeHint(self):
        return QSize(140,36)

    def minimumSizeHint(self):
        return QSize(80,36)

    def set_display_value(self,value):
        self.value=str(value)
        self.setAccessibleName(f'{self.title}, editable value: {self.value}')
        self.setToolTip(self.value)
        self.update()

    def paintEvent(self,event):
        c=ColorThemeManager.instance().colors
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .45)
        r=QRectF(self.rect()).adjusted(.5,.5,-.5,-.5)
        p.setPen(QPen(QColor(c.accent if self.hasFocus() else c.border),1))
        p.setBrush(QColor(c.bg_tertiary))
        p.drawRoundedRect(r,10,10)
        icon=theme_pixmap(':/icon/edit-value.svg',c.text_secondary,20,self.devicePixelRatioF())
        p.drawPixmap(QRectF(10,8,20,20),icon,QRectF(icon.rect()))
        p.setFont(self.font())
        p.setPen(QColor(c.text_primary))
        text=self.fontMetrics().elidedText('Value: '+self.value,Qt.ElideRight,max(0,self.width()-50))
        p.drawText(QRectF(38,0,max(0,self.width()-48),self.height()),Qt.AlignVCenter,text)
