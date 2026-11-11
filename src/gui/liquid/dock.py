import json
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QBitmap,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.ios.feature_icons import FEATURE_ICONS
from src.gui.theme import ColorThemeManager, theme_icon, theme_pixmap

from .controls import GlassPanel, LiquidBrand, LiquidButton, paint_dock_glass
from .placement import panel_rect, reveal_panel

ENTRIES = {
    'tweaks': ('Tweaks', 'toggles', 1),
    'daemons': ('Daemons', 'hdd', 3),
    'status': ('Status Bar', 'app-indicator', 5),
    'posterboard': ('PosterBoard', 'wallpaper', 2),
    'icons': ('Icon Themes', 'brush', 10),
    'passcode': ('Passcode Theme', 'lock', 11),
    'catalog': ('Community Catalog', 'globe', 13),
    'presets': ('Presets', 'folder', None),
    'templates': ('Templates','file-earmark-text',14),
    'apply': ('Apply Changes', 'check-circle', 6),
}
DEFAULT = ['tweaks','daemons','status','presets']
MAX_DOCK_ITEMS = 5
MIME='application/x-goldennugget-dock'


class DockDropSurface(QWidget):
    def __init__(self,dock):
        super().__init__(dock.window)
        self.dock=dock
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hide()

    def dragEnterEvent(self,event):
        self.dragMoveEvent(event)

    def dragMoveEvent(self,event):
        if not event.mimeData().hasFormat(MIME) or self.dock._drag_source is None:
            event.ignore()
            return
        if self.dock._preview_order is not None:
            self.dock._preview_order=None
            self.dock.position(animate_items=True)
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dropEvent(self,event):
        if not event.mimeData().hasFormat(MIME) or self.dock._drag_source is None:
            event.ignore()
            return
        self.dock._drag_drop_position=self.mapToGlobal(event.position().toPoint())
        self.dock._drag_committed=False
        event.setDropAction(Qt.MoveAction)
        event.accept()


class LiquidDock(GlassPanel):
    def __init__(self,window,parent=None):
        super().__init__(window)
        self._ready=False
        self._drag_source=None
        self._drag_cancelled=False
        self._drag_slots={}
        self._drag_drop_position=None
        self._drag_committed=False
        self.window=window
        self._drop_surface=DockDropSurface(self)
        from .dock_hint import DockHint
        self.hover_hint=DockHint(window)
        self.edge=window.settings.value('liquid/dock_edge','bottom')
        if self.edge not in ('top','bottom','left','right'):
            self.edge='bottom'
        self.setAcceptDrops(True)
        self.popup=GlassPanel(window)
        self.popup.hide()
        self.popup_layout=QVBoxLayout(self.popup)
        self.popup_layout.setContentsMargins(10,10,10,10)
        self.popup_layout.setSpacing(6)
        self.popup_area=QScrollArea()
        self.popup_area.setWidgetResizable(True)
        self.popup_area.setFrameShape(QScrollArea.NoFrame)
        self.popup_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.popup_area.setStyleSheet('background:transparent;border:none;')
        self.popup_body=QWidget()
        self.popup_column=QVBoxLayout(self.popup_body)
        self.popup_column.setContentsMargins(2,2,2,2)
        self.popup_column.setSpacing(5)
        self.popup_area.setWidget(self.popup_body)
        self.popup_layout.addWidget(self.popup_area)
        self.brand=LiquidBrand(self)
        self.brand.setToolTip('Workspace')
        self.brand.clicked.connect(self.activate_brand)
        try:
            saved=json.loads(window.settings.value('liquid/dock_items',json.dumps(DEFAULT)))
        except (ValueError,TypeError):
            saved=DEFAULT
        self.order=list(dict.fromkeys(k for k in saved if k in ENTRIES))[:MAX_DOCK_ITEMS]
        if not window.settings.value('liquid/presets_movable',False,type=bool):
            if 'presets' not in self.order and len(self.order) < MAX_DOCK_ITEMS:
                self.order.append('presets')
            self.save_order()
            window.settings.setValue('liquid/presets_movable',True)
        self.save_order()
        self.buttons={}
        for key,(name,icon,page) in ENTRIES.items():
            button=self.make_button(name,key=key,parent=self)
            if key=='presets':
                button.clicked.connect(self.open_presets)
            else:
                button.clicked.connect(lambda _,p=page:self.navigate(p))
            button.setIcon(self.entry_icon(key))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos,k=key:self.configure_item(k))
            self.buttons[key]=button
        self.presets=self.buttons['presets']
        self.more=self.make_button('More',parent=self)
        self.more.setIcon(QIcon(str(Path(__file__).parent/'assets/more.svg')))
        self.more.setAccessibleName('More')
        self.more.setProperty('dockReveal',0.0)
        self.more.setToolTip('More')
        self.more.clicked.connect(self.open_more)
        self.settings_button=self.make_button('App Settings',parent=self)
        self.settings_button.setProperty('dockReveal',0.0)
        self.settings_button.setIcon(theme_icon(':/icon/gear.svg','#dce0e8'))
        self.settings_button.setAccessibleName('App Settings')
        self.settings_button.clicked.connect(lambda:window.liquid.open_settings())
        self._utility_motions={}
        for button in (self.more,self.settings_button):
            motion=QVariantAnimation(self)
            motion.setEasingCurve(QEasingCurve.OutCubic)
            motion.valueChanged.connect(lambda value,b=button:self._utility_step(b,value))
            self._utility_motions[button]=motion
        self._flight_active=False
        self._expanded=True
        self._amount=1.0
        self._drag_source=None
        self._preview_order=None
        self._button_motion={}
        self._motion=QVariantAnimation(self)
        self._motion.setEasingCurve(QEasingCurve.InOutCubic)
        self._motion.valueChanged.connect(self._step)
        self._collapse_timer=QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(1100)
        self._collapse_timer.timeout.connect(self._collapse_if_idle)
        self._ready=True
        window.installEventFilter(self)
        window.ios_pages.currentChanged.connect(self.sync)
        ColorThemeManager.instance().theme_changed.connect(self.retheme)
        QTimer.singleShot(0,self.position)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shape=QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5),24,24)
        paint_dock_glass(p,shape,subtle=True)
        color=QColor(ColorThemeManager.instance().colors.text_secondary)
        color.setAlpha(28)
        p.setPen(QPen(color,1))
        vertical=self.edge in ('left','right')
        visible=[button for button in self._items() if not button.isHidden()]
        boundaries=[visible[0]] if visible else []
        if self.more in visible and self.more not in boundaries:
            boundaries.append(self.more)
        for button in boundaries:
            if button.isHidden():
                continue
            if vertical:
                y=button.y()-2
                p.drawLine(16,y,self.width()-16,y)
            else:
                x=button.x()-2
                p.drawLine(x,16,x,self.height()-16)
        p.end()

    def make_button(self,text,parent=None,key=''):
        button=LiquidButton(text,parent,key=key)
        button.setProperty('dockItem',True)
        button.setProperty('menuItem',parent is not self)
        button.setMinimumSize(0,0)
        button.setIconSize(QSize(26,26) if key else QSize(19,19))
        if parent is not self:
            button.setIconSize(QSize(26,26))
        button.setStyleSheet('QPushButton#liquidButton{background:transparent;border:none;padding:4px 10px;font-size:13px;font-weight:500;}')
        if parent is not self:
            button.setStyleSheet('QPushButton#liquidButton{background:transparent;border:none;padding:8px 12px;font-size:15px;font-weight:500;}')
        button.installEventFilter(self)
        button.dragStarted.connect(self.begin_drag)
        button.dragFinished.connect(self.finish_drag)
        return button

    def entry_icon(self,key):
        name,icon,_=ENTRIES[key]
        colors=ColorThemeManager.instance().colors
        return theme_icon(FEATURE_ICONS.get(name,':/icon/'+icon+'.svg'),
                          colors.text_primary)

    def menu_icon(self,resource_path,color='#dce0e8'):
        reference=theme_pixmap(':/icon/globe.svg','#dce0e8',104)
        source=theme_pixmap(resource_path,color,104)
        if source.isNull() or reference.isNull():
            return QIcon(source)
        def ink(pixmap):
            return QRegion(QBitmap.fromImage(pixmap.toImage().createAlphaMask())).boundingRect()
        bounds=ink(source)
        reference_bounds=ink(reference)
        if bounds.isEmpty() or reference_bounds.isEmpty():
            return QIcon(source)
        extent=max(reference_bounds.width(),reference_bounds.height())
        cropped=source.copy(bounds).scaled(extent,extent,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        normalized=QPixmap(104,104)
        normalized.fill(Qt.transparent)
        painter=QPainter(normalized)
        painter.drawPixmap((104-cropped.width())//2,(104-cropped.height())//2,cropped)
        painter.end()
        return QIcon(normalized)

    def _utility_step(self,button,value):
        button.setProperty('dockReveal',float(value))
        self.position()
        button.update()

    def _reveal_utility(self,button,expanded):
        motion=self._utility_motions[button]
        motion.stop()
        motion.setDuration(0 if QApplication.instance().property('liquid_reduce_motion') else 240)
        motion.setStartValue(float(button.property('dockReveal')))
        motion.setEndValue(1.0 if expanded else 0.0)
        motion.start()

    def retheme(self):
        for key,button in self.buttons.items():
            button.setIcon(self.entry_icon(key))
        self._layout_key=None
        self.position()
        self.update()

    def _step(self,value):
        self._amount=float(value)
        self.position()

    def _items(self):
        order=self._preview_order if self._preview_order is not None else self.order
        return [self.buttons[key] for key in order]+[self.more,self.settings_button]

    def position(self,animate_items=False):
        key=(self.window.size(),self.edge,round(self._amount,4),
             tuple(round(float(button.property('dockReveal')),4) for button in (self.more,self.settings_button)),
             tuple(self.order),tuple(self._preview_order or ()),
             tuple(button.text() for button in self._items()))
        if not animate_items and getattr(self,'_layout_key',None)==key:
            return
        self._layout_key=key
        vertical=self.edge in ('left','right')
        bounds=self.window.rect().adjusted(12,12,-12,-12)
        items=self._items()
        available=bounds.height()-64 if vertical else bounds.width()-200
        visible=[]
        total=0
        for button in items:
            if button.key and ENTRIES[button.key][0] in getattr(self,'_hidden_features',set()):
                continue
            if vertical:
                extent=40
            elif button in (self.more,self.settings_button):
                extra=max(56,button.fontMetrics().horizontalAdvance(button.text())+14)
                extent=round(38+extra*float(button.property('dockReveal')))
            else:
                extent=max(86,button.sizeHint().width()+4)
            if button in (self.more,self.settings_button) or total+extent+100<available:
                visible.append((button,extent))
                total+=extent+3
        for button in self.buttons.values():
            button.setVisible(any(button is item[0] for item in visible))
        for button in (self.more,self.settings_button):
            button.show()
        amount=self._amount
        expanded_width=64 if vertical else 180+total+8
        expanded_height=min(bounds.height(),64+total) if vertical else 56
        retained_width=sum(extent+3 for button,extent in visible
                           if button in (self.buttons['tweaks'],self.buttons['daemons']))
        closed_width=64 if vertical else 62+retained_width+8
        closed_height=144 if vertical else 56
        width=round(closed_width+(expanded_width-closed_width)*amount)
        height=round(closed_height+(expanded_height-closed_height)*amount)
        x=bounds.right()-width+1 if self.edge=='right'else bounds.left()
        y=bounds.bottom()-height+1 if self.edge=='bottom'else bounds.top()
        self.setGeometry(x,y,min(width,bounds.right()-x+1),min(height,bounds.height()))
        self.brand.compact=vertical
        self.brand.reveal=amount
        self.brand.setGeometry(4,3,50 if vertical else round(50+114*amount),48)
        self.brand.update()
        cursor=58 if vertical else round(62+114*amount)
        for button,extent in visible:
            retained=button in (self.buttons['tweaks'],self.buttons['daemons'])
            button.setVisible(amount>.01 or retained)
            button.setProperty('menuItem',False)
            button.setProperty('iconOnly',vertical)
            button.setToolTip(button.accessibleName() or button.text())
            target=QRect(7,cursor,50,extent) if vertical else QRect(cursor,7,extent,42)
            if animate_items and button.geometry()!=target:
                motion=self._button_motion.get(button)
                if motion is None:
                    motion=QVariantAnimation(button)
                    motion.setEasingCurve(QEasingCurve.OutCubic)
                    motion.setDuration(340)
                    motion.valueChanged.connect(button.setGeometry)
                    self._button_motion[button]=motion
                motion.stop()
                motion.setStartValue(button.geometry())
                motion.setEndValue(target)
                motion.start()
            elif not animate_items:
                motion=self._button_motion.get(button)
                if motion is None or motion.state()!=QVariantAnimation.Running:
                    button.setGeometry(target)
            cursor+=extent+3
        self.brand.setVisible(True)
        self.raise_()
        liquid=getattr(self.window,'liquid',None)
        if liquid is not None:
            liquid.notifications.position()
        self.update()
        if self.popup.isVisible():
            self.position_popup()

    def eventFilter(self,watched,event):
        if not getattr(self,'_ready',False):
            return False
        kind=event.type()
        if self._drag_source is not None and kind==QEvent.KeyPress and event.key()==Qt.Key_Escape:
            self._drag_cancelled=True
        if self._drag_source is not None:
            if kind==QEvent.MouseButtonRelease:
                self._drag_drop_position=event.globalPosition().toPoint()
            elif kind==QEvent.Drop and isinstance(watched,QWidget):
                self._drag_drop_position=watched.mapToGlobal(event.position().toPoint())
        if watched in (self.more,self.settings_button) and self.edge in ('top','bottom'):
            if kind in (QEvent.Enter,QEvent.FocusIn):
                self._reveal_utility(watched,True)
            elif kind in (QEvent.Leave,QEvent.FocusOut):
                self._reveal_utility(watched,False)
        if watched is self.window and kind in (QEvent.Resize,QEvent.Show):
            self._drop_surface.setGeometry(self.window.rect())
            self.hover_hint.dismiss(immediate=True)
            self.position()
        if watched is self.window and kind in (QEvent.WindowDeactivate,QEvent.Hide):
            self.hover_hint.dismiss(immediate=True)
        if watched.parent() is self and watched.property('dockItem'):
            if kind in (QEvent.Enter,QEvent.FocusIn) and self.edge in ('left','right'):
                self.hover_hint.reveal(watched,self.edge)
            elif kind in (QEvent.Leave,QEvent.FocusOut,QEvent.MouseButtonPress,QEvent.Hide):
                self.hover_hint.dismiss()
            elif kind==QEvent.ToolTip and self.edge in ('left','right'):
                return True
        if kind in (QEvent.DragEnter,QEvent.DragMove,QEvent.Drop) and event.mimeData().hasFormat(MIME):
            if watched in self.buttons.values() and watched.parentWidget() is self:
                self._drag_at(watched.mapTo(self,event.position().toPoint()))
                event.setDropAction(Qt.MoveAction)
                event.accept()
                if kind==QEvent.Drop:
                    self.commit_drag()
                return True
        if kind==QEvent.DragLeave and watched in self.buttons.values():
            QTimer.singleShot(0,self.cancel_preview_outside)
        return False

    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(MIME):
            if self._drag_source is None:
                self.begin_drag(bytes(event.mimeData().data(MIME)).decode())
            event.acceptProposedAction()

    def dragMoveEvent(self,event):
        self._drag_at(event.position().toPoint())
        event.acceptProposedAction()

    def dragLeaveEvent(self,event):
        self._preview_order=None
        self.position(animate_items=True)
        event.accept()

    def dropEvent(self,event):
        if event.mimeData().hasFormat(MIME):
            self._drag_at(event.position().toPoint())
            self.commit_drag()
            event.setDropAction(Qt.MoveAction)
            event.accept()

    def begin_drag(self,source):
        self.hover_hint.dismiss(immediate=True)
        self._collapse_timer.stop()
        self._drag_source=source
        self.buttons[source].setProperty('dragGhost',True)
        self.buttons[source].update()
        self._drag_cancelled=False
        self._drag_drop_position=None
        self._drag_committed=False
        self._drag_slots={key:QRect(self.buttons[key].geometry()) for key in self.order
                          if self.buttons[key].isVisible()}
        QApplication.instance().installEventFilter(self)
        self._preview_order=None
        self.set_expanded(True)
        self._drop_surface.setGeometry(self.window.rect())
        self._drop_surface.show()
        self._drop_surface.raise_()
        self.raise_()

    def _drag_at(self,point):
        source=self._drag_source
        if source not in ENTRIES:
            return
        target=next((key for key,rect in self._drag_slots.items() if rect.contains(point)),None)
        order=self.order.copy()
        if source not in order:
            if len(order) >= MAX_DOCK_ITEMS:
                self._preview_order = None
                return
            vertical=self.edge in ('left','right')
            coordinate=point.y() if vertical else point.x()
            before=next((key for key,rect in self._drag_slots.items()
                         if coordinate<(rect.center().y() if vertical else rect.center().x())),None)
            order.insert(order.index(before) if before is not None else len(order),source)
        elif target is not None and target!=source:
            start,end=order.index(source),order.index(target)
            order[start],order[end]=order[end],order[start]
        if order!=self._preview_order:
            self._preview_order=order
            self.position(animate_items=True)

    def cancel_preview_outside(self):
        from PySide6.QtGui import QCursor
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._preview_order=None
            self.position(animate_items=True)

    def commit_drag(self):
        self._drag_committed=True
        if self._preview_order is not None and len(self._preview_order) <= MAX_DOCK_ITEMS:
            self.order=self._preview_order.copy()
            self.save_order()
        self._preview_order=None
        self.position(animate_items=True)

    def finish_drag(self,source,accepted):
        from PySide6.QtGui import QCursor
        QApplication.instance().removeEventFilter(self)
        self._drop_surface.hide()
        drop_position=self._drag_drop_position if self._drag_drop_position is not None else QCursor.pos()
        outside=not self.rect().contains(self.mapFromGlobal(drop_position))
        remove=outside and not self._drag_committed and not self._drag_cancelled and source in self.order
        self.buttons[source].setProperty('dragGhost',False)
        snapshot=self.buttons[source].grab() if remove else None
        self.buttons[source].update()
        origin=self.window.mapFromGlobal(drop_position)
        self._drag_source=None
        self._preview_order=None
        if remove:
            self.order.remove(source)
            self.save_order()
            self.popup.hide()
        self.position(animate_items=True)
        if remove:
            from .dock_flight import DockFlight
            self._return_flight=DockFlight(self,snapshot,origin)
        if self._drag_committed:
            QTimer.singleShot(0,self._refresh_more)
        self._collapse_timer.start()

    def save_order(self):
        self.window.settings.setValue('liquid/dock_items',json.dumps(self.order))

    def configure_item(self,key):
        menu=QMenu(self)
        action=menu.addAction('Move to More'if key in self.order else 'Pin to dock')
        action.setEnabled(len(self.order)>1 if key in self.order else len(self.order)<MAX_DOCK_ITEMS)
        action.triggered.connect(lambda:self._move_item(key,key not in self.order))
        menu.exec(self.buttons[key].mapToGlobal(self.buttons[key].rect().center()))

    def _move_item(self,key,pinned):
        if key not in ENTRIES or (pinned and key not in self.order and len(self.order)>=MAX_DOCK_ITEMS):
            return
        if pinned and key not in self.order:
            self.order.append(key)
        elif not pinned and len(self.order)>1:
            self.order.remove(key)
        self.save_order()
        self.popup.hide()
        self.position(animate_items=True)

    def position_popup(self):
        anchor=getattr(self,'_popup_anchor',self.more)
        self.popup.setGeometry(panel_rect(self.window,anchor,QSize(300,self._popup_height),self.edge))

    def _clear_popup(self,title):
        while self.popup_column.count():
            item=self.popup_column.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        heading=QLabel(title)
        heading.setStyleSheet('font-size:15px;font-weight:600;background:transparent;padding:4px;')
        self.popup_column.addWidget(heading)

    def _show_popup(self,anchor):
        self._popup_anchor=anchor
        self._popup_height=min(520,self.popup_column.sizeHint().height()+24)
        reveal_panel(self.popup,self.window,anchor,QSize(300,self._popup_height),self.edge)

    def open_more(self):
        if self.popup.isVisible() and getattr(self,'_panel','')=='more':
            self.popup.hide()
            return
        self.set_expanded(True)
        self.window.liquid.settings.hide()
        self._panel='more'
        self._populate_more()
        self._show_popup(self.more)

    def _refresh_more(self):
        if not self.popup.isVisible() or getattr(self,'_panel','')!='more':
            return
        self._populate_more()
        self.popup_column.activate()
        self._popup_height=min(520,self.popup_column.sizeHint().height()+24)
        self.position_popup()

    def _populate_more(self):
        self._clear_popup('More')
        for name,icon,color,url in [('Discord','discord','#5865f2','https://discord.gg/F7ssrHjdgK'),('GitHub','github','#edf1f7','https://github.com/GoldenNugget-Team/GoldenNugget')]:
            button=self.make_button(name)
            button.setMinimumHeight(48)
            button.setIcon(self.menu_icon(':/icon/'+icon+'.svg',color))
            button.setProperty('external',True)
            button.clicked.connect(lambda _,u=url:QDesktopServices.openUrl(QUrl(u)))
            self.popup_column.addWidget(button)
        for key in ['templates', *(key for key in ENTRIES if key != 'templates')]:
            name,icon,page = ENTRIES[key]
            if name in getattr(self,'_hidden_features',set()):
                continue
            if key in self.order and self.buttons[key].isVisible():
                continue
            button=self.make_button(name,key=key)
            button.setMinimumHeight(48)
            button.setIcon(self.entry_icon(key))
            if key=='presets':
                button.clicked.connect(self.open_presets)
            else:
                button.clicked.connect(lambda _,p=page:self.navigate(p))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos,k=key:self._move_item(k,True))
            self.popup_column.addWidget(button)

    def open_presets(self):
        if self.popup.isVisible()and getattr(self,'_panel','')=='presets':
            self.popup.hide()
            return
        self.window.liquid.settings.hide()
        self._panel='presets'
        self._clear_popup('Your presets')
        try:
            icons=json.loads(self.window.settings.value('liquid/preset_icons','{}'))
        except (ValueError,TypeError):
            icons={}
        names=self.window.preset_manager.list_presets()
        if not names:
            self.popup_column.addWidget(QLabel('Save a preset to keep a configuration here.'))
        for name in names:
            button=self.make_button(icons.get(name,'📁')+'  '+name)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda _,n=name:self.window.liquid.load_preset(n))
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos,n=name:self.preset_icon(n))
            self.popup_column.addWidget(button)
        manage=self.make_button('Manage all presets →')
        manage.setMinimumHeight(38)
        manage.clicked.connect(lambda:self.navigate(12))
        self.popup_column.addWidget(manage)
        self._show_popup(self.presets if self.presets.isVisible() else self.more)

    def preset_icon(self,name):
        menu=QMenu(self.popup)
        for icon,label in [('🐶','Dog'),('🐱','Cat'),('📁','Folder'),('⭐','Star'),('🎮','Game'),('⚡','Lightning')]:
            menu.addAction(icon+' '+label,lambda n=name,i=icon:self._save_icon(n,i))
        menu.exec(self.popup.mapToGlobal(self.popup.rect().center()))

    def _save_icon(self,name,icon):
        try:
            icons=json.loads(self.window.settings.value('liquid/preset_icons','{}'))
        except (ValueError,TypeError):
            icons={}
        icons[name]=icon
        self.window.settings.setValue('liquid/preset_icons',json.dumps(icons))
        self.popup.hide()
        self.open_presets()

    def navigate(self,page):
        if any(index==page and name in getattr(self,'_hidden_features',set())
               for name,_,index in ENTRIES.values()):
            return
        self.popup.hide()
        liquid=getattr(self.window,'liquid',None)
        if liquid is not None:
            liquid.settings.hide()
        if self.window.ios_pages.currentIndex()==page:
            return
        self.window.show_ios_page(page)
        self.sync()

    def set_hidden_features(self,features):
        self._hidden_features=set(features)
        self._layout_key=None
        self.position()

    def sync(self,*args):
        index=self.window.ios_pages.currentIndex()
        for key,button in self.buttons.items():
            button.setProperty('selected',ENTRIES[key][2]==index)
            button.setAccessibleDescription('Selected'if ENTRIES[key][2]==index else '')
            button.update()

    def activate_brand(self):
        if not self._expanded:
            self.set_expanded(True)
            self._collapse_timer.start(3500)
        else:
            self.navigate(0)

    def enterEvent(self,event):
        self._collapse_timer.stop()
        self.set_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self,event):
        self._collapse_timer.start()
        super().leaveEvent(event)

    def operation_active(self):
        return (self._flight_active or self.window.apply_in_progress
                or getattr(self.window,'_cache_restore_in_progress',False)
                or getattr(self.window,'_operation_result_visible',False))

    def update_operation(self):
        if self.operation_active():
            self._collapse_timer.stop()
            self.set_expanded(True)

    def _collapse_if_idle(self):
        if self.operation_active():
            return
        if not self.window.settings.value('liquid/collapse_idle',True,type=bool):
            return
        settings=getattr(getattr(self.window,'liquid',None),'settings',None)
        if not self.underMouse()and not self.popup.isVisible()and not(settings and settings.isVisible())and not self._drag_source:
            self.set_expanded(False)

    def set_expanded(self,value):
        if not value and self.operation_active():
            return
        if value==self._expanded:
            return
        self._expanded=value
        self._motion.stop()
        self._motion.setDuration(0 if self.window.settings.value('liquid/reduce_motion',False,type=bool)else 220)
        self._motion.setStartValue(self._amount)
        self._motion.setEndValue(1.0 if value else 0.0)
        self._motion.start()

    def set_edge(self,edge):
        self.popup.hide()
        self._motion.stop()
        self.edge=edge
        self.window.settings.setValue('liquid/dock_edge',edge)
        self.position()
        if hasattr(self.window,'liquid'):
            self.window.liquid.reserve_dock_space()
            self.window.liquid.position_device()
            if self.window.liquid.settings.isVisible():
                self.window.liquid.settings.reposition()
