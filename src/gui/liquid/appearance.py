from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import ColorThemeManager


class GlassSlider(QSlider):
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setMinimumHeight(30)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .4)
        c=ColorThemeManager.instance().colors
        r=QRectF(12,self.height()/2-5,self.width()-24,10)
        p.setPen(QPen(QColor(255,255,255,45),1))
        p.setBrush(QColor(c.bg_tertiary))
        p.drawRoundedRect(r,5,5)
        progress=(self.value()-self.minimum())/max(1,self.maximum()-self.minimum())
        if self.invertedAppearance():
            progress=1-progress
        accent=QColor(c.accent)
        gradient=QLinearGradient(r.topLeft(),r.bottomLeft())
        gradient.setColorAt(0,accent.lighter(140))
        gradient.setColorAt(1,accent.darker(110))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(QRectF(r.x(),r.y(),r.width()*progress,r.height()),5,5)
        x=r.left()+r.width()*progress
        knob=QRectF(x-11,self.height()/2-11,22,22)
        p.setBrush(QColor(0,0,0,45))
        p.drawEllipse(knob.translated(0,2))
        glass=QLinearGradient(knob.topLeft(),knob.bottomRight())
        glass.setColorAt(0,QColor(255,255,255,245))
        glass.setColorAt(.4,QColor(241,249,255,210))
        glass.setColorAt(1,QColor(185,207,235,180))
        p.setPen(QPen(QColor(255,255,255,210),1))
        p.setBrush(glass)
        p.drawEllipse(knob)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255,255,255,190),1))
        p.drawArc(knob.adjusted(3,2,-3,-3),35*16,110*16)
        if self.hasFocus():
            p.setPen(QPen(accent,1))
            p.drawEllipse(knob.adjusted(-2,-2,2,2))

    def mousePressEvent(self,event):
        if event.button()!=Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.MouseFocusReason)
        self.setSliderDown(True)
        self._point(event)
        event.accept()

    def mouseMoveEvent(self,event):
        if self.isSliderDown():
            self._point(event)
        event.accept()

    def mouseReleaseEvent(self,event):
        self.setSliderDown(False)
        event.accept()

    def keyReleaseEvent(self,event):
        super().keyReleaseEvent(event)
        self.sliderReleased.emit()

    def _point(self,event):
        fraction=max(0,min(1,(event.position().x()-12)/max(1,self.width()-24)))
        if self.invertedAppearance():
            fraction=1-fraction
        self.setValue(round(self.minimum()+fraction*(self.maximum()-self.minimum())))


class GlassChoice(QWidget):
    changed=Signal(str)

    def __init__(self,choices,value,parent=None):
        super().__init__(parent)
        self.group=QButtonGroup(self)
        row=QHBoxLayout(self)
        row.setContentsMargins(4,4,4,4)
        row.setSpacing(3)
        self.choices=choices
        for key,label in choices:
            button=QPushButton(label,self)
            button.setCheckable(True)
            button.setChecked(key==value)
            button.setMinimumHeight(36)
            button.setCursor(Qt.PointingHandCursor)
            self.group.addButton(button)
            row.addWidget(button,1)
            button.clicked.connect(lambda _,v=key:self.changed.emit(v))
        ColorThemeManager.instance().theme_changed.connect(self.retheme)
        self.retheme()

    def retheme(self):
        c=ColorThemeManager.instance().colors
        self.setStyleSheet(f'QPushButton{{background:transparent;color:{c.text_secondary};border:none;border-radius:12px;padding:3px;font-size:12px;}} '
                          f'QPushButton:checked{{color:{c.text_primary};background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,45),stop:1 {c.bg_tertiary});border:1px solid rgba(255,255,255,90);}} '
                          'QPushButton:hover{background:rgba(255,255,255,20);} QPushButton:focus{border:1px solid rgba(255,255,255,150);}')
        self.update()

    def paintEvent(self,event):
        from .controls import paint_dock_glass
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path=QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),17,17)
        paint_dock_glass(p,path)


class ColorField(QWidget):
    changed=Signal(str)
    finished=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        color=QColor(ColorThemeManager.instance().colors.accent)
        self.hue=max(0,color.hsvHueF())
        self.saturation=color.hsvSaturationF()
        self.brightness=color.valueF()
        self.setFixedHeight(100)
        self.setCursor(Qt.CrossCursor)
        self.setAccessibleName('Accent saturation and brightness')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r=QRectF(self.rect()).adjusted(1,1,-1,-1)
        gradient=QLinearGradient(r.topLeft(),r.topRight())
        gradient.setColorAt(0,QColor('white'))
        gradient.setColorAt(1,QColor.fromHsvF(self.hue,1,1))
        p.setPen(Qt.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(r,12,12)
        shade=QLinearGradient(r.topLeft(),r.bottomLeft())
        shade.setColorAt(0,QColor(0,0,0,0))
        shade.setColorAt(1,QColor('black'))
        p.setBrush(shade)
        p.drawRoundedRect(r,12,12)
        p.setPen(QPen(QColor('white'),2))
        p.setBrush(QColor.fromHsvF(self.hue,self.saturation,self.brightness))
        p.drawEllipse(QPointF(2+self.saturation*(self.width()-4),2+(1-self.brightness)*(self.height()-4)),5,5)

    def mousePressEvent(self,event):
        self._point(event)

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.LeftButton:
            self._point(event)

    def mouseReleaseEvent(self,event):
        self.finished.emit()

    def _point(self,event):
        self.saturation=max(0,min(1,event.position().x()/self.width()))
        self.brightness=max(0,min(1,1-event.position().y()/self.height()))
        self.changed.emit(QColor.fromHsvF(self.hue,self.saturation,self.brightness).name())
        self.update()


class ColorSwatch(QPushButton):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.color = QColor(value)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('Accent ' + value)
        self.setToolTip(value)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(QPen(QColor(255, 255, 255, 145 if self.underMouse() else 85), 1))
        p.setBrush(self.color)
        p.drawEllipse(rect)
        if self.hasFocus() or self.isChecked():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ColorThemeManager.instance().colors.text_primary), 1))
            p.drawEllipse(rect.adjusted(-2, -2, 2, 2))


class InlinePalette(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        column=QVBoxLayout(self)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(5)
        self.field=ColorField()
        column.addWidget(self.field)
        hue=self.hue=GlassSlider()
        hue.setAccessibleName('Accent hue')
        hue.setRange(0,359)
        hue.setValue(round(self.field.hue*359))
        hue.valueChanged.connect(self.change_hue)
        column.addWidget(hue)
        colors=QHBoxLayout()
        for value in ['#d5ad68','#758bff','#b18ae8','#e586b5','#5bc4ae','#ec835f']:
            button=ColorSwatch(value)
            button.clicked.connect(lambda _,v=value:self.select(v))
            colors.addWidget(button)
        colors.addStretch()
        column.addLayout(colors)
        self.hex=QLineEdit(ColorThemeManager.instance().colors.accent)
        self.hex.setAccessibleName('Accent hex color')
        self.hex.setPlaceholderText('#RRGGBB')
        self.hex.editingFinished.connect(self.apply_hex)
        column.addWidget(self.hex)
        self.pending=None
        self.field.changed.connect(self.queue)
        self.field.finished.connect(self.commit)
        self.hue.sliderReleased.connect(self.commit)

    def queue(self,value):
        self.pending=value
        self.hex.setText(value)


    def commit(self):
        if self.pending:
            ColorThemeManager.instance().set_custom_accent(self.pending)
            self.pending=None

    def apply_hex(self):
        color=QColor(self.hex.text())
        if color.isValid():
            self.select(color.name())
        else:
            self.hex.setText(ColorThemeManager.instance().colors.accent)

    def select(self,value):
        color=QColor(value)
        self.field.hue=max(0,color.hsvHueF())
        self.field.saturation=color.hsvSaturationF()
        self.field.brightness=color.valueF()
        self.hue.blockSignals(True)
        self.hue.setValue(round(self.field.hue*359))
        self.hue.blockSignals(False)
        self.queue(value)
        self.commit()
        self.field.update()

    def change_hue(self,value):
        self.field.hue=value/359
        self.field.changed.emit(QColor.fromHsvF(self.field.hue,self.field.saturation,self.field.brightness).name())
        self.field.update()
