from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.gui.theme import ColorThemeManager

from .controls import GlassPanel
from .motion import animate


class ValueEditor(GlassPanel):
    def __init__(self,window,anchor,dialog,title,on_save,example=None,fit_anchor=False):
        super().__init__(window)
        self.window=window
        self.anchor=anchor
        self.dialog=dialog
        self.fit_anchor=fit_anchor
        colors=ColorThemeManager.instance().colors
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout=QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)
        heading=QLabel(title)
        heading.setWordWrap(True)
        heading.setStyleSheet(f'background:transparent;color:{colors.text_primary};font-size:14px;font-weight:600;')
        layout.addWidget(heading)
        dialog.setParent(self,Qt.Widget)
        dialog.setModal(False)
        dialog.setMinimumWidth(0)
        dialog.setStyleSheet('QDialog{background:transparent;} QLineEdit{padding:7px;border-radius:10px;background:rgba(255,255,255,18);border:1px solid rgba(255,255,255,75);} QPushButton{padding:6px 12px;border-radius:10px;background:rgba(255,255,255,24);border:1px solid rgba(255,255,255,55);}')
        dialog.setStyleSheet(dialog.styleSheet()+f'QLineEdit,QPushButton{{color:{colors.text_primary};}}')
        action_style = (
            'QDialogButtonBox{button-layout:1;}'
            'QPushButton#valueEditorCancel,QPushButton#valueEditorOk{'
            'padding:7px 14px;border-radius:10px;font-size:12px;}'
            f'QPushButton#valueEditorCancel{{color:{colors.text_secondary};'
            'background:rgba(255,255,255,8);border:1px solid rgba(255,255,255,28);}'
            f'QPushButton#valueEditorOk{{color:{colors.text_primary};font-weight:600;'
            'background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,28),'
            'stop:1 rgba(255,255,255,12));border:1px solid rgba(255,255,255,80);}'
            'QPushButton#valueEditorCancel:hover,QPushButton#valueEditorOk:hover{'
            'background:rgba(255,255,255,32);border-color:rgba(255,255,255,135);}'
            'QPushButton#valueEditorCancel:pressed,QPushButton#valueEditorOk:pressed{'
            'background:rgba(255,255,255,16);border-color:rgba(255,255,255,65);}'
            'QPushButton#valueEditorCancel:focus,QPushButton#valueEditorOk:focus{'
            'border-color:rgba(255,255,255,190);}'
            'QPushButton#valueEditorOk:disabled{color:rgba(150,150,150,100);'
            'background:rgba(255,255,255,4);border-color:rgba(255,255,255,12);}')
        dialog.setStyleSheet(dialog.styleSheet()+action_style)
        for box in dialog.findChildren(QDialogButtonBox):
            box.setCenterButtons(True)
            box.setStyleSheet(action_style)
            box.layout().setSpacing(10)
            for role, name in ((QDialogButtonBox.Cancel, 'valueEditorCancel'),
                               (QDialogButtonBox.Ok, 'valueEditorOk')):
                button=box.button(role)
                if button is not None:
                    button.setObjectName(name)
                    button.setMinimumSize(88,36)
                    button.setMaximumWidth(144)
                    button.setAutoDefault(role==QDialogButtonBox.Ok)
                    button.setDefault(role==QDialogButtonBox.Ok)
        for button in dialog.findChildren(QPushButton):
            if button.objectName()=='valueEditorCancel':
                button.setMinimumSize(88,36)
        palette=dialog.input.palette()
        palette.setColor(QPalette.PlaceholderText,QColor(colors.text_secondary))
        dialog.input.setPalette(palette)
        dialog.layout().setContentsMargins(0,0,0,0)
        dialog.layout().setSpacing(8)
        if example is not None:
            hint=QLabel('App default: '+(str(example) if str(example) else 'Empty'))
            hint.setWordWrap(True)
            hint.setStyleSheet('background:transparent;font-size:11px;')
            layout.addWidget(hint)
            dialog.input.setPlaceholderText('Example: '+str(example))
        else:
            dialog.input.setPlaceholderText('Enter a value')
        layout.addWidget(dialog)
        dialog.accepted.connect(on_save)
        dialog.finished.connect(self.close)
        QApplication.instance().installEventFilter(self)
        self.open()

    def open(self):
        self.dialog.show()
        self.dialog.ensurePolished()
        card=self.anchor if self.fit_anchor else self.anchor.parentWidget()
        origin=card.mapTo(self.window,QPoint(0,0))
        width=min(max(card.width(),260 if self.fit_anchor else 0),self.window.width()-24)
        height=min(self.window.height()-24,max(card.height(),self.layout().totalHeightForWidth(width),self.layout().sizeHint().height()))
        x=max(12,min(origin.x(),self.window.width()-width-12))
        y=max(12,min(origin.y(),self.window.height()-height-12))
        self.setGeometry(x,y,width,height)
        self.show()
        self.raise_()
        def step(value):
            self.setMask(QRegion(QRect(0,0,self.width(),max(1,round(self.height()*float(value))))))
        step(0)
        animate(self,0.0,1.0,step,duration=220,finished=self.clearMask)
        self.dialog.input.setFocus(Qt.OtherFocusReason)
        self.dialog.input.selectAll()

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ColorThemeManager.instance().colors.bg_secondary))
        painter.drawRoundedRect(self.rect(),24,24)
        painter.end()
        super().paintEvent(event)

    def eventFilter(self,target,event):
        if self.isVisible() and event.type()==QEvent.Wheel and hasattr(target,'parentWidget'):
            inside = self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint()))
            if inside and target is not self and not self.isAncestorOf(target):
                return True
            if not inside:
                self.close()
        if self.isVisible() and event.type()==QEvent.MouseButtonPress:
            if hasattr(target,'parentWidget') and target is not self and not self.isAncestorOf(target):
                self.close()
        elif self.isVisible() and event.type()==QEvent.KeyPress and event.key()==Qt.Key_Escape:
            self.close()
            return True
        if target is self.window and event.type() in (QEvent.Resize,QEvent.Hide):
            self.close()
        return False

    def closeEvent(self,event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
