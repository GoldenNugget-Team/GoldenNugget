from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion

from .motion import animate


def panel_rect(window, anchor, size, edge):
    bounds=window.rect().adjusted(12,12,-12,-12)
    origin=QRect(anchor.mapTo(window,QPoint(0,0)),anchor.size())
    width=min(size.width(),bounds.width())
    height=min(size.height(),bounds.height())
    if edge=='top':
        x,y=origin.left(),origin.bottom()+8
        height=min(height,max(80,bounds.bottom()-y))
    elif edge=='left':
        x,y=origin.right()+8,origin.top()
        width=min(width,max(120,bounds.right()-x))
    elif edge=='right':
        x,y=origin.left()-width-8,origin.top()
    else:
        x,y=origin.left(),origin.top()-height-8
        height=min(height,max(80,origin.top()-bounds.top()-8))
        y=origin.top()-height-8
    x=max(bounds.left(),min(x,bounds.right()-width+1))
    y=max(bounds.top(),min(y,bounds.bottom()-height+1))
    return QRect(x,y,width,height)


def reveal_panel(panel,window,anchor,size,edge):
    for animation in list(getattr(panel,'_liquid_animations',())):
        animation.stop()
        animation.deleteLater()
    if hasattr(panel,'_liquid_animations'):
        panel._liquid_animations.clear()
    panel.hide()
    end=panel_rect(window,anchor,size,edge)
    panel.setGeometry(end)
    panel.frost(end)
    panel.show()
    panel.raise_()
    def step(value):
        amount=max(1,round((panel.width() if edge in ('left','right')else panel.height())*float(value)))
        if edge=='left':
            clip=QRect(0,0,amount,panel.height())
        elif edge=='right':
            clip=QRect(panel.width()-amount,0,amount,panel.height())
        elif edge=='top':
            clip=QRect(0,0,panel.width(),amount)
        else:
            clip=QRect(0,panel.height()-amount,panel.width(),amount)
        panel.setMask(QRegion(clip))
    step(0)
    animate(panel,0.0,1.0,step,duration=220,finished=panel.clearMask)


def sheet_rect(window,anchor,size):
    origin=QRect(anchor.mapTo(window,QPoint(0,0)),anchor.size())
    width=min(size.width(),window.width()-24)
    height=min(size.height(),max(120,origin.top()-12))
    x=max(12,min(origin.center().x()-width//2,window.width()-width-12))
    return QRect(x,origin.top()-height+3,width,height)


def reveal_sheet(panel,window,anchor,size,*,duration=540,extend_from_button=False):
    from PySide6.QtWidgets import QGraphicsEffect
    class EjectEffect(QGraphicsEffect):
        def __init__(self,parent):
            super().__init__(parent)
            self.amount=0.0

        def draw(self,painter):
            painter.save()
            painter.setOpacity(.15+.85*self.amount)
            if extend_from_button:
                height=anchor.height()+(panel.height()-anchor.height())*self.amount
                painter.setClipRect(0,round(panel.height()-height),panel.width(),round(height))
                painter.translate(0,14*(1-self.amount))
                self.drawSource(painter)
                painter.restore()
                return
            painter.translate(panel.width()/2,panel.height())
            painter.translate(0,18*(1-self.amount))
            painter.scale(.975+.025*self.amount,.95+.05*self.amount)
            painter.translate(-panel.width()/2,-panel.height())
            self.drawSource(painter)
            painter.restore()

    for animation in list(getattr(panel,'_liquid_animations',())):
        animation.stop()
        animation.deleteLater()
    getattr(panel,'_liquid_animations',set()).clear()
    panel.hide()
    panel.clearMask()
    panel.setGeometry(sheet_rect(window,anchor,size))
    effect=EjectEffect(panel)
    panel.setGraphicsEffect(effect)
    panel.show()
    panel.raise_()
    def step(value):
        effect.amount=float(value)
        panel._flow=float(value)
        effect.update()
        panel.update()
    from PySide6.QtCore import QEasingCurve
    animate(panel,0.0,1.0,step,duration=duration,easing=QEasingCurve.InOutCubic,
            finished=lambda:panel.setGraphicsEffect(None))
