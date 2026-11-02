from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtCore import QCoreApplication, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractScrollArea, QComboBox, QLabel, QLineEdit,
    QTabWidget, QWidget,
)
from shiboken6 import isValid


@lru_cache(maxsize=2)
def _catalog_messages(folder):
    messages = []
    for path in sorted(Path(folder).glob('*.ts')):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        language = root.get('language', '').split('_')[0]
        for context in root.findall('context'):
            name = context.findtext('name', '')
            for message in context.findall('message'):
                source = message.findtext('source', '')
                translated = message.find('translation')
                text = ''
                if translated is not None and translated.get('type') not in ('unfinished', 'obsolete', 'vanished'):
                    text = translated.text or ''
                if source:
                    messages.append((name, source, language, text))
    return tuple(messages)


def collect_translatable_ui(app, folder, old_locale):
    lookup = {}
    language = old_locale.split('_')[0]
    for context, source, catalog_language, translated in _catalog_messages(folder):
        lookup.setdefault(source, set()).add((context, source))
        if translated and catalog_language == language:
            lookup.setdefault(translated, set()).add((context, source))
    bindings, scrolls = [], []
    objects = set()
    for window in app.topLevelWidgets():
        objects.add(window)
        objects.update(window.findChildren(QWidget))
        objects.update(window.findChildren(QAction))

    def bind(widget, key, value, setter):
        if not value or not isinstance(value, str):
            return
        remembered = getattr(widget, '_live_translation_sources', {})
        previous = remembered.get(key)
        if previous is not None and previous[2] == value:
            context, source = previous[:2]
        else:
            candidates = lookup.get(value, set())
            preferred = [pair for pair in candidates if pair[0] == 'Nugget']
            chosen = preferred or list(candidates)
            if len(chosen) != 1:
                return
            context, source = chosen[0]
        bindings.append((widget, key, context, source, setter))

    for widget in objects:
        if not isValid(widget):
            continue
        if isinstance(widget, (QLabel, QAbstractButton, QAction)) and not widget.property('liveTranslationExcluded'):
            bind(widget, 'text', widget.text(), widget.setText)
        if isinstance(widget, QWidget):
            for key in ('toolTip', 'accessibleName', 'accessibleDescription', 'windowTitle'):
                bind(widget, key, getattr(widget, key)(), getattr(widget, 'set' + key[0].upper() + key[1:]))
        if isinstance(widget, QLineEdit):
            bind(widget, 'placeholder', widget.placeholderText(), widget.setPlaceholderText)
        if isinstance(widget, QComboBox) and widget.property('liveTranslateItems'):
            for index in range(widget.count()):
                bind(widget, ('item', index), widget.itemText(index),
                     lambda text, widget=widget, index=index: widget.setItemText(index, text))
        if isinstance(widget, QWidget):
            for key in ('navigationTitle', 'categoryTitle'):
                bind(widget, key, widget.property(key),
                     lambda text, widget=widget, key=key: widget.setProperty(key, text))
            if hasattr(widget, 'set_display_value') and isinstance(getattr(widget, 'title', None), str):
                def set_title(text, widget=widget):
                    widget.title = text
                    widget.update()
                bind(widget, 'valueTitle', widget.title, set_title)
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                bind(widget, ('tab', index), widget.tabText(index),
                     lambda text, widget=widget, index=index: widget.setTabText(index, text))
        if isinstance(widget, QAbstractScrollArea):
            scrolls.append((widget.verticalScrollBar(), widget.verticalScrollBar().value()))
    return bindings, scrolls


def apply_translatable_ui(snapshot):
    bindings, scrolls = snapshot
    for widget, key, context, source, setter in bindings:
        if not isValid(widget):
            continue
        text = QCoreApplication.translate(context, source)
        blocker = QSignalBlocker(widget)
        setter(text)
        remembered = getattr(widget, '_live_translation_sources', {})
        remembered[key] = (context, source, text)
        widget._live_translation_sources = remembered
        del blocker
    for bar, value in scrolls:
        if isValid(bar):
            bar.setValue(value)
