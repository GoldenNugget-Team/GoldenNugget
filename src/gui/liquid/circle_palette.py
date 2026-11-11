import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from src.gui.theme import ColorThemeManager

from .appearance import GlassSlider


class ColorWheel(QWidget):
    changed=Signal(float,float)
    committed=Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedSize(112,112)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Accent color wheel')
        self.setToolTip('Drag to select hue and saturation')
        self.hue=0.0
        self.saturation=0.0
        self._gradient=None

    def gradient(self):
        ratio=self.devicePixelRatioF()
        if self._gradient is not None and self._gradient.devicePixelRatioF()==ratio:
            return self._gradient
        self._gradient=QPixmap(round(self.width()*ratio),round(self.height()*ratio))
        self._gradient.setDevicePixelRatio(ratio)
        self._gradient.fill(Qt.transparent)
        painter=QPainter(self._gradient)
        painter.setRenderHint(QPainter.Antialiasing)
        center=QPointF(self.rect().center())
        radius=self.width()/2-6
        rect=QRectF(center.x()-radius,center.y()-radius,radius*2,radius*2)
        hue=QConicalGradient(center,0)
        for index in range(7):
            hue.setColorAt(index/6,QColor.fromHsvF((index%6)/6,1,1))
        painter.setPen(Qt.NoPen)
        painter.setBrush(hue)
        painter.drawEllipse(rect)
        saturation=QRadialGradient(center,radius)
        saturation.setColorAt(0,QColor(255,255,255))
        saturation.setColorAt(1,QColor(255,255,255,0))
        painter.setBrush(saturation)
        painter.drawEllipse(rect)
        painter.end()
        return self._gradient

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0,0,self.gradient())
        center=QPointF(self.rect().center())
        radius=self.width()/2-6
        angle=self.hue*math.tau
        point=center+QPointF(math.cos(angle),-math.sin(angle))*radius*self.saturation
        painter.setBrush(QColor.fromHsvF(self.hue,self.saturation,1))
        painter.setPen(QPen(QColor('#202024'),4))
        painter.drawEllipse(point,6,6)
        painter.setPen(QPen(QColor('white'),2))
        painter.drawEllipse(point,6,6)

    def pick(self,point):
        delta=point-QPointF(self.rect().center())
        self.hue=(math.atan2(-delta.y(),delta.x())/math.tau)%1
        self.saturation=min(1,math.hypot(delta.x(),delta.y())/(self.width()/2-6))
        self.changed.emit(self.hue,self.saturation)
        self.update()

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.setFocus()
            self.pick(event.position())

    def mouseMoveEvent(self,event):
        if event.buttons()&Qt.LeftButton:
            self.pick(event.position())

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.pick(event.position())
            self.committed.emit()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Left,Qt.Key_Right):
            self.hue=(self.hue+(-1 if event.key()==Qt.Key_Left else 1)/180)%1
        elif event.key() in (Qt.Key_Up,Qt.Key_Down):
            self.saturation=max(0,min(1,self.saturation+(.02 if event.key()==Qt.Key_Up else -.02)))
        else:
            return super().keyPressEvent(event)
        self.changed.emit(self.hue,self.saturation)
        self.update()

    def keyReleaseEvent(self,event):
        if event.key() in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Up,Qt.Key_Down):
            self.committed.emit()
        else:
            super().keyReleaseEvent(event)


class CirclePalette(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        layout=QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)
        self.wheel=ColorWheel()
        self.wheel.changed.connect(self.preview_wheel)
        self.wheel.committed.connect(self.commit_wheel)
        layout.addWidget(self.wheel)
        fields=QVBoxLayout()
        fields.setSpacing(6)
        layout.addLayout(fields,1)
        self.brightness=GlassSlider(Qt.Horizontal)
        self.brightness.setRange(0,100)
        self.brightness.setAccessibleName('Accent brightness')
        self.brightness.setToolTip('Brightness')
        self.brightness.valueChanged.connect(self.brightness_changed)
        self.brightness.sliderReleased.connect(self.commit_wheel)
        fields.addWidget(QLabel('Brightness'))
        fields.addWidget(self.brightness)
        self.hex=QLineEdit(ColorThemeManager.instance().colors.accent)
        self.hex.setAccessibleName('Custom accent color')
        self.hex.setPlaceholderText('#RRGGBB')
        self.hex.editingFinished.connect(self.apply_hex)
        self.hex.setMinimumWidth(0)
        self.hex.setMaximumWidth(160)
        fields.addWidget(self.hex)
        ColorThemeManager.instance().theme_changed.connect(self.sync)
        self.sync()

    def sync(self):
        color=QColor(ColorThemeManager.instance().colors.accent)
        self.hex.setText(color.name())
        if color.hsvHueF()>=0:
            self.wheel.hue=color.hsvHueF()
        self.wheel.saturation=color.hsvSaturationF()
        self.brightness.blockSignals(True)
        self.brightness.setValue(round(color.valueF()*100))
        self.brightness.blockSignals(False)
        self.wheel.update()

    def preview_wheel(self,hue,saturation):
        self.hex.setText(QColor.fromHsvF(hue,saturation,self.brightness.value()/100).name())

    def commit_wheel(self):
        self.select(QColor.fromHsvF(self.wheel.hue,self.wheel.saturation,self.brightness.value()/100).name())

    def brightness_changed(self,value):
        self.preview_wheel(self.wheel.hue,self.wheel.saturation)
        if not self.brightness.isSliderDown():
            self.commit_wheel()

    def select(self,value):
        manager=ColorThemeManager.instance()
        if QColor(manager.colors.accent).name()!=value:
            manager.set_custom_accent(value)

    def apply_hex(self):
        color=QColor(self.hex.text())
        if color.isValid():
            self.select(color.name())
        else:
            self.sync()
