import logging
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Slot
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QApplication,
    QComboBox,
    QLineEdit,
)


class UiSounds(QObject):
    def __init__(self,app):
        super().__init__(app)
        self.effects={}
        self.enabled=True
        self._settings=None
        self._last_ui_hover_position=None
        self._hover_click_position=None
        self._native=False
        try:
            from PySide6.QtMultimedia import QSoundEffect  # pyright: ignore[reportMissingImports] (Essentials-only installs lack it; the except handles that)
        except ImportError:
            try:
                if sys.platform!='darwin':
                    raise ImportError('Native sound fallback is macOS-only')
                from AppKit import NSSound
                self._native=True
            except ImportError:
                logging.getLogger(__name__).warning('UI audio unavailable; continuing without sounds')
                return
        directory=Path(__file__).parent/'assets'/'sounds'
        for name in ('favorite','unfavorite','toggle','untoggle','ui_hover'):
            path=str(directory/(name+'.wav'))
            volume=.08 if name=='ui_hover' else .45 if name=='unfavorite' else .35
            if self._native:
                effect=NSSound.alloc().initWithContentsOfFile_byReference_(path,False)  # pyright: ignore[reportUndefinedVariable] (set on the darwin-only path above)
                if effect is None:
                    continue
                effect.setVolume_(volume)
            else:
                effect=QSoundEffect(self)
                effect.setVolume(volume)
                effect.setSource(QUrl.fromLocalFile(path))
            self.effects[name]=effect
        app.aboutToQuit.connect(self.stop)
        app.installEventFilter(self)

    @classmethod
    def instance(cls):
        app=QApplication.instance()
        sounds=getattr(app,'_liquid_sounds',None)
        if sounds is None:
            sounds=app._liquid_sounds=cls(app)
        return sounds

    def configure(self,settings):
        self._settings=settings
        self.enabled=settings.value('liquid/ui_sounds',True,type=bool)
        if not self.enabled:
            self.stop()

    @Slot(bool)
    def set_enabled(self,enabled):
        self.enabled=bool(enabled)
        if self._settings is not None:
            self._settings.setValue('liquid/ui_sounds',self.enabled)
            self._settings.sync()
        if not self.enabled:
            self.stop()

    def play(self,name):
        if not self.enabled:
            return
        if name!='ui_hover':
            if self._hover_click_position is None:
                self._hover_click_position=QCursor.pos()
        effect=self.effects.get(name)
        if effect is not None and (self._native or effect.isLoaded()):
            effect.stop()
            effect.play()

    def play_ui_hover(self,position):
        if not self.enabled:
            return
        if self._hover_click_position is not None:
            if position==self._hover_click_position:
                return
            self._hover_click_position=None
        if position==self._last_ui_hover_position:
            return
        effect=self.effects.get('ui_hover')
        if effect is None or (not self._native and not effect.isLoaded()):
            return
        if effect.isPlaying():
            return
        self._last_ui_hover_position=position
        if self._native:
            effect.setCurrentTime_(0.0)
        effect.play()

    def eventFilter(self,target,event):
        if not self.enabled:
            return False
        kind=event.type()
        if kind==QEvent.MouseButtonRelease:
            self._hover_click_position=event.globalPosition().toPoint()
        elif kind==QEvent.KeyRelease and isinstance(target,QAbstractButton) and event.key() in (Qt.Key_Space,Qt.Key_Return,Qt.Key_Enter):
            self._hover_click_position=QCursor.pos()
        if kind==QEvent.Enter:
            from .controls import LiquidCard
            ancestor=target
            main_window=None
            while ancestor is not None:
                if getattr(ancestor,'_selection_surface',None) is not None or ancestor.property('silentHoverAudio'):
                    return False
                if hasattr(ancestor,'ios_pages') and hasattr(ancestor,'ios_home'):
                    main_window=ancestor
                ancestor=ancestor.parent()
            if main_window is None:
                return False
            dock=getattr(main_window,'bottom_navigation',None)
            popup=getattr(dock,'popup',None)
            in_dock=any(surface is not None and (target is surface or surface.isAncestorOf(target))
                        for surface in (dock,popup))
            if main_window.ios_pages.currentWidget() is not main_window.ios_home and not in_dock:
                return False
            control=isinstance(target,(QAbstractButton,QLineEdit,QComboBox,QAbstractSlider))
            card=isinstance(target,LiquidCard)
            if (control or card) and target.isVisible() and target.isEnabled() and QApplication.mouseButtons()==Qt.NoButton:
                self.play_ui_hover(event.globalPosition().toPoint())
        return False

    @Slot()
    def stop(self):
        self._last_ui_hover_position=None
        self._hover_click_position=None
        for effect in self.effects.values():
            effect.stop()

    @Slot(bool)
    def play_favorite(self,checked):
        self.play('favorite' if checked else 'unfavorite')

    @Slot(bool)
    def play_toggle(self,checked):
        self.play('toggle' if checked else 'untoggle')
