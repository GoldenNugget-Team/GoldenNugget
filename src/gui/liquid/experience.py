import math
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from src.gui.theme import ColorThemeManager

from .controls import GlassPanel, LiquidButton, LiquidDangerButton, PulseOverlay
from .motion import animate
from .panels import DeviceDrawer, PhoneRender, RestoreDrawer, WorkspaceSettings
from .reveal import DevicePeek, PageReveal


class UpdateBorder(GlassPanel):
    def __init__(self,window):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.phase=0
        self.timer=QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        self.hide()

    def tick(self):
        self.phase+=.12
        self.update()

    def showEvent(self,event):
        self.timer.start()

    def hideEvent(self,event):
        self.timer.stop()

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        for width,alpha in [(12,8),(6,20),(2,110)]:
            p.setPen(QPen(QColor(233,189,105,round(alpha*(.75+.25*math.sin(self.phase)))),width))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(7,7,-7,-7),20,20)


class LiquidExperience(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window
        QApplication.instance().setProperty("liquid_card_density",window.settings.value("liquid/card_density","comfortable"))
        self.home=window.ios_home
        self.last_device=''
        self.update_shown=False
        self.device=DeviceDrawer(window)
        self.settings=WorkspaceSettings(window)
        self.restore=RestoreDrawer(window)
        from .notifications import Notifications
        self.notifications=Notifications(window)
        self.border=UpdateBorder(window)
        self.device_button=LiquidButton('Device',window)
        self.device_button.setIcon(QIcon(str(Path(__file__).parent/'assets/usb.svg')))
        self.device_button.clicked.connect(self.device.toggle)
        self.peek=DevicePeek(window)
        self.home._device_preview.preview_changed.connect(self.peek.refresh_preview)
        self.device_button.installEventFilter(self)
        self.device_button.setToolTip('Device information and connection')
        self.device_button.setProperty('solidSurface',True)
        self._clean_home()
        self._style()
        self.reserve_dock_space()
        self.poll=QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()
        QApplication.instance().installEventFilter(self)
        window.ios_pages.currentChanged.connect(self.page_transition)
        ColorThemeManager.instance().theme_changed.connect(self._style)
        window.settings.setValue('ui/interface_choice_done',True)
        QTimer.singleShot(0,self.refresh)

    def _clean_home(self):
        home=self.home
        for widget in [home._branding,home._device_area,home.control_tabs,home.cards_grid,
                       home.catalog_card,home.update_notice,home.community_links]:
            widget.hide()
        home.status_lbl.hide()
        content=home._scroll.widget()
        layout=content.layout()
        layout.removeWidget(home.support_panel)
        layout.insertWidget(max(0,layout.count()-1),home.support_panel)
        home.support_panel.title.setText('Developers')
        home.cards_grid.setMinimumHeight(260)
        home.catalog_card.setMinimumHeight(58)
        home.cards_grid.show()
        home.catalog_card.show()
        layout.removeWidget(home.cards_grid)
        layout.insertWidget(0,home.cards_grid)
        layout.removeWidget(home.catalog_card)
        layout.insertWidget(0,home.catalog_card)
        home.apply_btn.setText('Apply Changes')
        home.apply_btn.setProperty('homeAction',True)
        home.apply_btn.setProperty('silentHoverAudio',True)
        home.apply_btn.setProperty('actionIcon',':/icon/check-circle.svg')
        home.apply_btn.setProperty('iconOnlyAction',False)
        home.apply_btn.setAccessibleName('Apply Changes')
        home.apply_btn.setToolTip('Apply Changes')
        home.apply_btn.set_action_footer('')
        home.apply_btn.setFocusPolicy(Qt.TabFocus)
        home.apply_btn.clicked.disconnect(home.open_apply_classic)
        home.apply_btn.clicked.connect(self.restore.activate)
        self.window.ios_apply.set_status_only(True)
        self.restore_button=LiquidDangerButton('Restore Changes')
        self.restore_button.setProperty('homeAction',True)
        self.restore_button.setProperty('silentHoverAudio',True)
        self.restore_button.setProperty('actionIcon',':/icon/arrow-clockwise.svg')
        self.restore_button.setProperty('iconOnlyAction',False)
        self.restore_button.setAccessibleName('Restore Changes')
        self.restore_button.setToolTip('Restore Changes')
        self.restore_button.setFocusPolicy(Qt.TabFocus)
        self.restore_button.setFixedHeight(40)
        from .restore_changes_panel import RestoreChangesPanel
        self.restore_changes_panel=RestoreChangesPanel(self.window)
        self.restore_button.clicked.connect(lambda:self.restore_changes_panel.activate(self.restore_button))
        for index in range(layout.count()):
            row=layout.itemAt(index).layout()
            if row and row.indexOf(home.apply_btn)>=0:
                layout.insertWidget(index+1,self.restore_button)
                break
        home.apply_btn.setFixedHeight(48)
        home.apply_btn.show()
        home.apply_btn.bind_scroll_area(home._scroll)
        self.restore_button.bind_scroll_area(home._scroll)
        home._device_preview.show()
        home.device_combo.show()
        home.device_software.show()
        home.device_details.show()
        home._branding.setMaximumHeight(0)
        home._device_area.setMaximumHeight(0)

    def _style(self):
        c=ColorThemeManager.instance().colors
        if not hasattr(self,"_base_style"):
            self._base_style=self.window.styleSheet()
        self.window.setStyleSheet(self._base_style+f'''
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background:{c.bg_secondary}; border:1px solid {c.border};
                border-radius:12px; padding:9px 12px; selection-background-color:{c.accent};
            }}
            QLineEdit:focus, QComboBox:focus {{ border:1px solid {c.accent}; }}
            QScrollBar:vertical {{ width:7px; background:transparent; margin:5px 0; }}
            QScrollBar::handle:vertical {{ background:{c.border}; border-radius:3px; min-height:30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QSlider::groove:horizontal {{ height:5px; background:{c.border}; border-radius:2px; }}
            QSlider::handle:horizontal {{ width:17px; margin:-6px 0; border-radius:8px; background:{c.accent}; }}
        ''')
        nav=self.window.ios_nav
        nav.setStyleSheet(f'background:{c.bg_secondary};border-radius:20px;')
        for button in getattr(nav,'_category_buttons',[]):
            button.setStyleSheet(f'QPushButton{{border:none;border-radius:13px;padding:6px 12px;color:{c.text_secondary};background:transparent;}} QPushButton:hover,QPushButton:checked{{color:{c.text_primary};background:{c.bg_tertiary};}}')

    def set_card_density(self,value):
        from .cards import ControlGrid, configure_card
        self.window.settings.setValue('liquid/card_density',value)
        QApplication.instance().setProperty('liquid_card_density',value)
        for card in self.window.findChildren(GlassPanel):
            if card.property('liquidControlCard'):
                configure_card(card)
        for grid in self.window.findChildren(ControlGrid):
            grid.invalidate()
            parent=grid.parentWidget()
            if parent:
                parent.updateGeometry()
                if parent.layout():
                    parent.layout().invalidate()
        self.window.ios_pages.updateGeometry()

    def position_device(self):
        edge=self.window.bottom_navigation.edge
        right=self.window.settings.value('liquid/device_edge','left')=='right'
        if edge=='left':
            right=True
        elif edge=='right':
            right=False
        y=self.window.height()-(126 if edge=='bottom'and not right else 74)
        width=min(max(138,self.device_button.fontMetrics().horizontalAdvance(self.device_button.text())+62),max(138,self.window.width()-48))
        rect=QRect(self.window.width()-width-24 if right else 24,y,width,46)
        if self.device_button.geometry()!=rect:
            self.device_button.setGeometry(rect)

    def reserve_dock_space(self):
        dock=self.window.bottom_navigation
        left=82 if dock.edge=='left'else 10
        right=82 if dock.edge=='right'else 10
        top=78 if dock.edge=='top'else 6
        bottom=76 if dock.edge=='bottom'else 20
        self.window.body_row.setContentsMargins(left,top,right,bottom)
        dock.position()

    def eventFilter(self,target,event):
        kind=event.type()
        panel=getattr(self,'restore_changes_panel',None)
        if panel is not None and panel.isVisible():
            if kind==QEvent.MouseButtonPress and isinstance(target,QWidget):
                point=event.globalPosition().toPoint()
                inside=panel.rect().contains(panel.mapFromGlobal(point))
                opener=self.restore_button.rect().contains(self.restore_button.mapFromGlobal(point))
                if not inside and not opener:
                    panel.hide()
            elif target is self.window and kind==QEvent.Resize:
                panel.reposition()
        if kind==QEvent.MouseButtonPress and self.device.isVisible() and isinstance(target,QWidget):
            point=event.globalPosition().toPoint()
            inside=self.device.rect().contains(self.device.mapFromGlobal(point))
            opener=self.device_button.rect().contains(self.device_button.mapFromGlobal(point))
            if not inside and not opener:
                self.device.hide()
        if kind==QEvent.MouseButtonPress and self.restore.isVisible() and isinstance(target,QWidget):
            point=event.globalPosition().toPoint()
            inside=self.restore.rect().contains(self.restore.mapFromGlobal(point))
            anchor=self.home.apply_btn
            opener=anchor.rect().contains(anchor.mapFromGlobal(point))
            if not inside and not opener:
                self.restore.hide()
        if target is self.device_button:
            if kind==QEvent.Enter and self.last_device and not self.device.isVisible():
                self.peek.peek(hold=True)
            elif kind==QEvent.Leave:
                self.peek.hide_timer.start(500)
        if kind==QEvent.KeyPress and event.key()==Qt.Key_Escape:
            panels=[self.window.bottom_navigation.popup,self.settings,self.device,self.restore,self.restore_changes_panel]
            if any(panel.isVisible() for panel in panels):
                for panel in panels:
                    panel.hide()
                return True
        if target is self.window and kind in (QEvent.Resize,QEvent.Show):
            self.position_device()
            self.device_button.raise_()
            self.border.setGeometry(self.window.rect())
            if self.restore.isVisible():
                self.restore.reposition()
            if self.settings.isVisible():
                self.settings.reposition()
            if self.device.isVisible():
                self.device.reposition()
        if kind==QEvent.MouseButtonPress and isinstance(target,QAbstractButton):
            text=(target.accessibleName()+' '+target.toolTip()).lower()
            star='favorite'in text
            if not star:
                PulseOverlay(target,event.position())
        if kind==QEvent.Show and isinstance(target,QDialog) and target.__class__.__name__ in ('TextInputDialog','NumberInputDialog'):
            if not self.window.settings.value('liquid/reduce_motion',False,type=bool):
                end=target.geometry()
                start=QRect(end.center().x()-80,end.center().y()-35,160,70)
                animate(target,start,end,target.setGeometry,duration=340)
        if kind==QEvent.FocusIn and isinstance(target,(QLineEdit,QComboBox)):
            PulseOverlay(target)
        if kind==QEvent.MouseButtonPress and target is self.window:
            self.window.bottom_navigation.popup.hide()
        return False

    def open_settings(self):
        self.window.bottom_navigation.popup.hide()
        self.window.bottom_navigation.set_expanded(True)
        self.settings.toggle()

    def page_transition(self,*args):
        self.window._stop_page_slide()
        if not hasattr(self,'_page_reveal'):
            self._page_reveal=PageReveal(self.window.ios_pages)
        if self.window.ios_pages.currentIndex()==0:
            self._page_reveal.cancel()
            return
        self._page_reveal.start()

    def _style_categories(self):
        c=ColorThemeManager.instance().colors
        for button in getattr(self.window.ios_nav,'_category_buttons',[]):
            button.setStyleSheet(f'QPushButton{{border:none;border-radius:13px;padding:6px 12px;color:{c.text_secondary};background:transparent;}} QPushButton:hover,QPushButton:checked{{color:{c.text_primary};background:{c.bg_tertiary};}}')

    def clear_passed_category(self):
        nav=self.window.ios_nav
        import time
        if time.monotonic()-getattr(nav,"_selection_started",0)<.5:
            return
        selected=next((button for button in nav._category_buttons if button.property('selected')),None)
        if selected is None:
            return
        page=self.window.ios_pages.currentWidget()
        watch=getattr(self,'_category_watch',None)
        if watch is None or watch[0] is not selected or watch[1] is not page:
            targets=list(self.window._page_section_targets(page))
            from PySide6.QtWidgets import QScrollArea
            self._category_watch=None
            for label,target in targets:
                if label.replace('&','&&')!=selected.text():
                    continue
                for area in page.findChildren(QScrollArea):
                    body=area.widget()
                    if body is not None and body.isAncestorOf(target):
                        headers=tuple(item for _,item in targets if body.isAncestorOf(item))
                        self._category_watch=(selected,page,area,body,target,headers)
                        break
                break
            watch=self._category_watch
        if watch is None:
            return
        from shiboken6 import isValid
        _,_,area,body,target,headers=watch
        if not all(isValid(item) for item in (area,body,target)):
            self._category_watch=None
            return
        top=target.mapTo(body,QPoint()).y()
        later=[item.mapTo(body,QPoint()).y() for item in headers if isValid(item)
               and item.mapTo(body,QPoint()).y()>top]
        bottom=min(later) if later else body.height()
        position=area.verticalScrollBar().value()
        if position<top-40 or position>=bottom-12:
            selected.setProperty('selected',False)
            selected.update()

    def refresh(self):
        if not self.window.isVisible() or self.window.isMinimized():
            return
        self.clear_passed_category()
        dm=self.window.device_manager
        uid=dm.get_current_device_udid() or ''
        model=dm.get_current_device_model() if uid else ''
        from pymobiledevice3.irecv_devices import IRECV_DEVICES
        name=next((item.display_name for item in IRECV_DEVICES if item.product_type==model),model)
        self.device_button.setText(name or ('Device' if uid else 'Connect device'))
        self.position_device()
        self.device.refresh()
        self.restore.refresh()
        if uid and uid!=self.last_device:
            self.arrival()
        if self.last_device and not uid and not self.window.bottom_navigation.operation_active():
            self.notifications.add('Device disconnected','Reconnect your device to apply changes.')
        self.last_device=uid
        self.notifications.position()
        self.home.update_notice.hide()
        self.home.status_lbl.hide()
        self.home.device_connection.hide()
        if self.home._update_available is True and not self.update_shown:
            self.update_shown=True
            self.show_update()

    def arrival(self):
        if not self.device.isVisible():
            self.peek.peek()

    def show_update(self):
        self.notifications.add('Update available','A new GoldenNugget version is available.',
                               self.home._show_update_info)

    def load_preset(self, name):
        import json
        from pathlib import Path

        from src.gui.dialogs.confirmation import ask_confirmation
        from src.gui.ios.compat import compatibility_reasons
        from src.gui.ios.preset_menu import load_preset_flow
        from src.tweaks.registry import SPECS
        from src.tweaks.tweaks import tweaks
        pm=self.window.preset_manager
        try:
            data=json.loads(Path(pm.get_preset_path(name)).read_text()).get('tweaks',{})
        except (OSError,ValueError,AttributeError):
            return
        self.clear_passed_category()
        dm=self.window.device_manager
        version=dm.get_current_device_version() or ''
        model=dm.get_current_device_model() or ''
        unsupported=[spec.id for spec in SPECS
                     if isinstance(data.get(spec.id.name),dict)
                     and data[spec.id.name].get('enabled')
                     and compatibility_reasons(spec.id,version,model)]
        if unsupported:
            device=dm.get_current_device_name() or model or 'this device'
            if not ask_confirmation(self.window,'Preset compatibility',
                    f'This preset contains controls unsupported on {device}. '
                    'Load it with those controls turned off?',confirm_text='Skip unsupported controls'):
                return
        if not load_preset_flow(self.window,self.window,pm,name,restart=False):
            return
        for key in unsupported:
            if key in tweaks:
                tweaks[key].set_enabled(False)
        self.window._save_autosave_preset()
        for page in [self.window.ios_tweaks,self.window.ios_springboard,
                     self.window.ios_internal,self.window.ios_liquidglass]:
            page.rebuild()
        self.window.ios_daemons.refresh_from_tweaks()
        self.window.ios_home.refresh_preset_widget()
        self.window.bottom_navigation.popup.hide()
