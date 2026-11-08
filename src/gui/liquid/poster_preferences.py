from copy import deepcopy

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel

from src.gui.ios.components import NumberInputDialog, TextInputDialog
from src.gui.theme import ColorThemeManager
from src.gui.widgets import IOSCard, IOSSwitch
from src.tweaks.posterboard.device_overrides import OPTIONS, option_key
from src.tweaks.posterboard.preference_controls import (
    CLOCK_FONT_IDENTIFIERS,
    POSTER_PRESETS,
    number_limits,
)
from src.tweaks.registry import Kind
from src.tweaks.tweaks import tweaks

from .cards import prepare_card
from .choice_editor import ChoiceDialog
from .controls import LiquidButton
from .selection_card import bind_selection_card
from .value_editor import ValueEditor
from .value_entry import GlassValueEntry


def render_poster_flag(content,spec,target):
    tweak=tweaks[spec.id]
    master=content._tweak_switches[spec.id]
    card=IOSCard()
    row=QHBoxLayout(card)
    title=QLabel(spec.title+' - Requested state')
    title.setWordWrap(True)
    title.setStyleSheet(f'font-size:15px;color:{ColorThemeManager.instance().colors.text_primary};')
    content._switch_labels.append(title)
    row.addWidget(title,1)
    entry=GlassValueEntry(spec.title)
    entry.set_display_value('Enabled' if tweak.value else 'Disabled')
    entry.setEnabled(master.isChecked())
    master.toggled.connect(entry.setEnabled)
    row.addWidget(entry)
    prepare_card(card)
    def edit():
        dialog=ChoiceDialog([('Disabled',False,True,None),('Enabled',True,True,None)],tweak.value)
        def save():
            if not entry.isEnabled():
                return
            value=dialog.get_value()
            tweak.set_value(value,toggle_enabled=False)
            entry.set_display_value('Enabled' if value else 'Disabled')
        old=getattr(content,'_value_editor_panel',None)
        if old is not None:
            from shiboken6 import isValid
            if isValid(old):
                old.close()
        content._value_editor_panel=ValueEditor(content.window,entry,dialog,spec.title,save)
    entry.clicked.connect(edit)
    target.addWidget(card)
    content._search_rows.append((card,spec.id,spec.title+' Requested state',spec.key,True))


def render_poster_preferences(content, spec, target):
    tweak=tweaks[spec.id]
    master=content._tweak_switches[spec.id]
    fields={}
    archive=spec.kind==Kind.POSTER_ARCHIVE

    def store(key,value,used=True):
        values=deepcopy(tweak.value)
        if archive:
            if used:
                values[key]=value
            else:
                values.pop(key,None)
        else:
            values.setdefault('none',deepcopy(spec.value['none']))[key]=value
        tweak.set_value(values,toggle_enabled=False)

    def current(key,default):
        values=tweak.value if archive else tweak.value.get('none',{})
        return values.get(key,default)

    def display(value):
        if type(value) is bool:
            return 'On' if value else 'Off'
        if type(value) in (int,float):
            return f'{value:g}'
        return str(value) or 'Not set'

    def open_editor(entry,dialog,title,save):
        old=getattr(content,'_value_editor_panel',None)
        if old is not None:
            from shiboken6 import isValid
            if isValid(old):
                old.close()
        content._value_editor_panel=ValueEditor(content.window,entry,dialog,title,save)

    def add_field(group,key,title,default,limits=None):
        card=IOSCard()
        row=QHBoxLayout(card)
        label=QLabel(title)
        label.setWordWrap(True)
        label.setStyleSheet(f'font-size:15px;color:{ColorThemeManager.instance().colors.text_primary};')
        content._switch_labels.append(label)
        row.addWidget(label,1)
        entry=GlassValueEntry(title)
        entry.set_display_value(display(current(key,default)))
        entry.setToolTip(key)
        row.addWidget(entry)
        selected=key in tweak.value if archive else bool(current(key,default)) if type(default) is bool else True
        switch=IOSSwitch(selected)
        switch.setAccessibleName('Use '+title)
        row.addWidget(switch)
        prepare_card(card)
        bind_selection_card(card,switch)
        card.setEnabled(master.isChecked())
        master.toggled.connect(card.setEnabled)
        entry.setEnabled(selected)
        fields[key]=(switch,entry)
        def used(checked):
            if archive:
                store(key,current(key,default),checked)
                if checked:
                    entry.set_display_value(display(current(key,default)))
            elif type(default) is bool:
                store(key,checked)
                entry.set_display_value(display(checked))
            else:
                store(key,current(key,default) if checked else default)
            entry.setEnabled(checked)
        switch.toggled.connect(used)
        if not archive and type(default) is bool:
            entry.hide()
        def edit():
            if not entry.isEnabled():
                return
            value=current(key,default)
            if type(default) is bool:
                dialog=ChoiceDialog([('Off',False,True,None),('On',True,True,None)],value)
            elif key=='Clock:timeFontConfiguration.timeFontIdentifier':
                choices=[(font.removeprefix('PRTimeFontIdentifier'),font,True,None) for font in CLOCK_FONT_IDENTIFIERS]
                dialog=ChoiceDialog(choices,value)
            elif type(default) in (int,float):
                lower,upper,step=limits or number_limits(key.split(':',1)[-1],default)
                dialog=NumberInputDialog(title,value,lower,upper,step=step)
            else:
                dialog=TextInputDialog(title,str(value))
            def save():
                if not entry.isEnabled():
                    return
                value=dialog.get_value()
                if type(default) is float:
                    value=float(value)
                store(key,value)
                entry.set_display_value(display(value))
            open_editor(entry,dialog,title,save)
        entry.clicked.connect(edit)
        target.addWidget(card)
        content._search_rows.append((card,spec.id,group+' '+title,key,True))

    if archive:
        toolbar=IOSCard()
        buttons=QHBoxLayout(toolbar)
        preset_title=QLabel('Wallpaper presets')
        preset_title.setStyleSheet(f'font-size:15px;color:{ColorThemeManager.instance().colors.text_primary};')
        content._switch_labels.append(preset_title)
        buttons.addWidget(preset_title,1)
        preset_entry=GlassValueEntry('Wallpaper preset')
        preset_entry.set_display_value('Choose preset')
        buttons.addWidget(preset_entry)
        prepare_card(toolbar)
        toolbar.setEnabled(master.isChecked())
        master.toggled.connect(toolbar.setEnabled)
        def preset(name):
            for key,value in POSTER_PRESETS[name].items():
                switch,entry=fields[key]
                switch.setChecked(True)
                store(key,value)
                entry.set_display_value(display(value))
        def choose_preset():
            dialog=ChoiceDialog([(name,name,True,None) for name in POSTER_PRESETS])
            def save():
                name=dialog.get_value()
                if master.isChecked():
                    preset(name)
                    preset_entry.set_display_value(name)
            open_editor(preset_entry,dialog,'Wallpaper preset',save)
        preset_entry.clicked.connect(choose_preset)
        target.addWidget(toolbar)
        content._search_rows.append((toolbar,spec.id,'Wallpaper presets','still compact clock',True))
        tint_card=IOSCard()
        tint_row=QHBoxLayout(tint_card)
        tint_title=QLabel('Icon tint color')
        tint_title.setStyleSheet(f'font-size:15px;color:{ColorThemeManager.instance().colors.text_primary};')
        content._switch_labels.append(tint_title)
        tint_row.addWidget(tint_title,1)
        tint=LiquidButton('Icon tint color')
        tint.setProperty('liquidValueEntry',True)
        tint.setStyleSheet(f'color:{ColorThemeManager.instance().colors.text_primary};background:transparent;font-size:12px;')
        tint_row.addWidget(tint)
        tint_keys=tuple('Home Screen:customizationConfiguration._tintColorStyle.'+field
                        for field in ('_hue','_saturation','_alpha'))
        color_switch=IOSSwitch(any(key in tweak.value for key in tint_keys))
        color_switch.setAccessibleName('Use icon tint color')
        tint_row.addWidget(color_switch)
        prepare_card(tint_card)
        bind_selection_card(tint_card,color_switch)
        tint_card.setEnabled(master.isChecked())
        master.toggled.connect(tint_card.setEnabled)
        tint.setEnabled(color_switch.isChecked())
        def use_color(checked):
            for key in tint_keys:
                switch,entry=fields[key]
                switch.setChecked(checked)
                if not checked:
                    store(key,None,False)
                    entry.set_display_value('Not set')
            tint.setEnabled(checked)
            if not checked:
                tint.setIcon(QIcon())
                tint.setText('Not set')
        color_switch.toggled.connect(use_color)
        content._poster_color_controls=(color_switch,tint)
        def pick_color():
            prefix='Home Screen:customizationConfiguration._tintColorStyle.'
            seed=QColor.fromHsvF(float(current(prefix+'_hue',.5)),float(current(prefix+'_saturation',1.0)),1.0,float(current(prefix+'_alpha',1.0)))
            from .color_editor import ColorPickerDialog
            dialog=ColorPickerDialog(seed,allow_brightness=False)
            def save():
                if not tint.isEnabled():
                    return
                color=dialog.get_value()
                if color is None:
                    color_switch.setChecked(False)
                    for field in ('_hue','_saturation','_alpha'):
                        key=prefix+field
                        switch,entry=fields[key]
                        switch.setChecked(False)
                        store(key,None,False)
                        entry.set_display_value('Not set')
                    tint.setIcon(QIcon())
                    tint.setText('Not set')
                    return
                swatch=QPixmap(20,20)
                swatch.fill(color)
                tint.setIcon(QIcon(swatch))
                tint.setText(color.name())
                for field,value in (('_hue',max(0,color.hsvHueF())),('_saturation',color.hsvSaturationF()),('_alpha',color.alphaF())):
                    key=prefix+field
                    switch,entry=fields[key]
                    switch.setChecked(True)
                    store(key,float(value))
                    entry.set_display_value(display(value))
            open_editor(tint,dialog,'Icon tint color',save)
            dialog.input.setPlaceholderText('#RRGGBB')
        tint.clicked.connect(pick_color)
        target.addWidget(tint_card)
        content._search_rows.append((tint_card,spec.id,'Icon tint color','hue saturation alpha',True))
        for group,path,title,default in OPTIONS:
            add_field(group,option_key(group,path),title if title.startswith(group) else group+' - '+title,default)
    else:
        titles={
            'SBWallpaperHasVideoKey':'Has video','SBWallpaperMagnifyEnabledKey':'Magnification',
            'SBWallpaperParallaxFactorKey':'Parallax factor','SBWallpaperPortraitKey':'Portrait',
            'SBWallpaperStillTimeInVideoKey':'Video still time','SBWallpaperSupportsCroppingKey':'Cropping',
            'SBWallpaperZoomScaleKey':'Zoom scale','kSBProceduralWallpaperHomeUserSetKey':'Procedural wallpaper user set',
        }
        for key,default in spec.value['none'].items():
            limits=(.01,100,.01) if key=='SBWallpaperZoomScaleKey' else (0,100,.1) if key=='SBWallpaperParallaxFactorKey' else (0,86400,.1)
            add_field(spec.title,key,titles[key],default,limits)
    content._poster_preference_fields=getattr(content,'_poster_preference_fields',{})
    content._poster_preference_fields[spec.id]=fields
