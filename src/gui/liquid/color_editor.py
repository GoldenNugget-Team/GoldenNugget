from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from src.gui.theme import ColorThemeManager

from .appearance import GlassSlider
from .circle_palette import ColorWheel


class ColorPickerDialog(QDialog):
    def __init__(self,color,parent=None,*,allow_brightness=True):
        super().__init__(parent)
        self._color=QColor(color)
        self._allow_brightness=allow_brightness
        self._reset_requested=False
        layout=QVBoxLayout(self)
        row=QHBoxLayout()
        row.setSpacing(12)
        self.wheel=ColorWheel()
        self.wheel.setAccessibleName('Color hue and saturation')
        row.addWidget(self.wheel)
        fields=QVBoxLayout()
        self.input=QLineEdit()
        self.input.setMinimumWidth(0)
        self.input.setAccessibleName('Color hexadecimal value')
        self.input.setValidator(QRegularExpressionValidator(QRegularExpression('#[0-9a-fA-F]{6}'),self.input))
        fields.addWidget(QLabel('Hex color'))
        fields.addWidget(self.input)
        self.alpha=GlassSlider(Qt.Horizontal)
        self.alpha.setRange(0,100)
        self.alpha.setAccessibleName('Color opacity')
        self.alpha_label=QLabel('Opacity')
        fields.addWidget(self.alpha_label)
        fields.addWidget(self.alpha)
        self.brightness=GlassSlider(Qt.Horizontal)
        self.brightness.setRange(0,100)
        self.brightness.setAccessibleName('Color brightness')
        if allow_brightness:
            fields.addWidget(QLabel('Brightness'))
            fields.addWidget(self.brightness)
        else:
            self.brightness.setParent(self)
            self.brightness.hide()
        row.addLayout(fields,1)
        layout.addLayout(row)
        swatches=QHBoxLayout()
        swatches.setSpacing(8)
        colors=('#ffffff','#f06464','#f0bc57','#67c6a1','#6c9df2')
        if allow_brightness:
            colors=('#111111',)+colors
        for value in colors:
            swatch=QPushButton()
            swatch.setFixedSize(22,22)
            swatch.setToolTip(value)
            swatch.setAccessibleName('Select color '+value)
            swatch.setStyleSheet(f'background:{value};border:1px solid rgba(255,255,255,70);border-radius:11px;padding:0;')
            swatch.clicked.connect(lambda _,value=value:self.select(QColor(value)))
            swatches.addWidget(swatch)
        swatches.addStretch()
        layout.addLayout(swatches)
        self.reset_button=QPushButton('Reset value')
        self.reset_button.setObjectName('valueEditorCancel')
        self.reset_button.setToolTip('Remove the pending color override')
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(self.reset_value)
        layout.addWidget(self.reset_button,0,Qt.AlignLeft)
        actions=QDialogButtonBox(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self._ok=actions.button(QDialogButtonBox.Ok)
        self.wheel.changed.connect(self._from_wheel)
        self.alpha.valueChanged.connect(self._from_wheel)
        self.brightness.valueChanged.connect(self._from_wheel)
        self.input.textChanged.connect(self._from_hex)
        text_color=ColorThemeManager.instance().colors.text_secondary
        for label in self.findChildren(QLabel):
            label.setStyleSheet(f'color:{text_color};background:transparent;font-size:12px;')
        self.select(self._color)

    def select(self,color):
        alpha=self._color.alphaF()
        self._color=QColor(color)
        self._color.setAlphaF(alpha)
        if not self._allow_brightness:
            self._color=QColor.fromHsvF(max(0,self._color.hsvHueF()),self._color.hsvSaturationF(),1,alpha)
        self.wheel.hue=max(0,self._color.hsvHueF())
        self.wheel.saturation=self._color.hsvSaturationF()
        for control,value in ((self.alpha,round(alpha*100)),(self.brightness,round(self._color.valueF()*100))):
            with QSignalBlocker(control):
                control.setValue(value)
        with QSignalBlocker(self.input):
            self.input.setText(self._color.name())
        self._ok.setEnabled(True)
        self.alpha_label.setText(f'Opacity {self.alpha.value()}%')
        self.wheel.update()

    def _from_wheel(self,*_args):
        self._color=QColor.fromHsvF(self.wheel.hue,self.wheel.saturation,
                                  self.brightness.value()/100 if self._allow_brightness else 1,
                                  self.alpha.value()/100)
        with QSignalBlocker(self.input):
            self.input.setText(self._color.name())
        self._ok.setEnabled(True)
        self.alpha_label.setText(f'Opacity {self.alpha.value()}%')

    def _from_hex(self,text):
        valid=self.input.hasAcceptableInput()
        self._ok.setEnabled(valid)
        if valid:
            self.select(QColor(text))

    def accept(self):
        if self.input.hasAcceptableInput():
            super().accept()

    def reset_value(self):
        self._reset_requested=True
        super().accept()

    def get_value(self):
        if self._reset_requested:
            return None
        if not self.input.hasAcceptableInput():
            raise ValueError('Enter a six-digit hexadecimal color.')
        return QColor(self._color)
