from PySide6.QtCore import QCoreApplication, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.gui.ios.compat import device_family, is_tweak_compatible
from src.gui.ios.components import (
    IOSSearchEmpty,
    IOSSearchField,
    IOSSectionHeader,
    IOSSegmentedFilter,
    IOSValueRow,
    LiquidCard,
    LiquidSwitch,
    NumberInputDialog,
    TextInputDialog,
)
from src.gui.ios.tweak_categories import (
    BOTTOM_TWEAK_CATEGORIES,
    SPRINGBOARD_GROUPS,
    TWEAK_CATEGORY_ORDER,
    tweak_category,
)
from src.gui.theme import ColorThemeManager, t, theme_icon, theme_pixmap
from src.tweaks.hidden import current_hidden_feature_names
from src.tweaks.registry import (
    SECTION_FEATURES,
    SPECS_BY_ID,
    SPECS_BY_SECTION,
    Kind,
    Section,
)
from src.tweaks.tweak_loader import load_plist_tweaks
from src.tweaks.tweaks import TweakID, tweaks

# Feature (page) name -> registry Section it maps to in the iOS tweaks UI.
# A HotLoad-hidden feature loses its whole section here (and the Sidebar/Home
# entries), so its tweaks are never even shown.
_SECTION_FEATURES = SECTION_FEATURES


def _hidden_feature_names() -> set:
    """Names of HotLoad-hidden features for the current setup, as a set."""
    return current_hidden_feature_names()


def _fmt_number(value) -> str:
    """Render a numeric tweak value compactly (5, 0.5, 1)."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _hidden_sections() -> set:
    """Registry Sections whose feature is hidden, so we skip rendering them."""
    hidden = _hidden_feature_names()
    return {s for s, feat in _SECTION_FEATURES.items() if feat in hidden}


class IOSSectionContent(QWidget):
    """iOS-style tweak controls for one or more registry sections.

    Can be reused inside any scroll area or page.
    """

    def __init__(self, window, sections=None, parent=None):
        super().__init__(parent)
        self.window = window
        self.sections = sections
        self._switch_labels = []
        self._tweak_switches = {}
        self._solarium_visible: bool = None
        from src.controllers.favorites import TweakFavorites
        self._favorites = TweakFavorites.instance()

        # Load tweaks (idempotent) so the sections below actually populate
        load_plist_tweaks()

        # persistent root layout: keeps only a rebuildable inner widget
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.search = IOSSearchField(self)
        self.search.setPlaceholderText(QCoreApplication.translate("Nugget", "Search tweaks…"))
        self.search.setAccessibleName(self.search.placeholderText())
        self.filter_control = IOSSegmentedFilter([
            (QCoreApplication.translate("Nugget", "All"), "all"),
            (QCoreApplication.translate("Nugget", "Enabled"), "enabled"),
            (QCoreApplication.translate("Nugget", "Disabled"), "disabled"),
            (QCoreApplication.translate("Nugget", "Favorites"), "favorites"),
        ], self)
        self.filter_control.setAccessibleName(QCoreApplication.translate("Nugget", "Tweak filter"))
        self._search_row = search_row = QHBoxLayout()
        search_row.setContentsMargins(16, 16, 16, 0)
        search_row.setSpacing(8)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.filter_control)
        root.addLayout(search_row)
        self._description_note = QLabel(self.tr("Descriptions show intended effects. Check ? for compatibility and cautions."), self)
        self._description_note.setContentsMargins(20, 6, 16, 0)
        self._description_note.setWordWrap(True)
        root.addWidget(self._description_note)
        self._loading_label = QLabel(self.tr("Loading controls…"), self)
        self._loading_label.setContentsMargins(20, 8, 16, 0)
        self._loading_label.hide()
        root.addWidget(self._loading_label)
        self._inner = None
        self._info_buttons = []
        self._favorite_buttons = {}
        self._search_rows = []
        self._search_sections = []
        self._category_lines = []
        self._poster_preference_fields = {}
        self.force_solarium_fallback_card = None

        from src.gui.ios.visibility_batch import VisibilityBatch
        self._visibility_batch = VisibilityBatch(self)
        from src.gui.ios.viewport_rows import ViewportRows
        self._viewport_rows = ViewportRows(self)
        self.search.textChanged.connect(self._visibility_batch.cancel)
        self.search.connect_filter(self._apply_search)
        self.filter_control.currentIndexChanged.connect(self._apply_search)
        self._favorites.changed.connect(self._refresh_favorites)
        ColorThemeManager.instance().theme_changed.connect(self._refresh_action_icons)

    def showEvent(self, event):
        self._fit_search_row()
        if self._inner is None and not getattr(self, "_building", False):
            self.rebuild()
        super().showEvent(event)
        QTimer.singleShot(0, self._offer_untested_tweaks)
        if not getattr(self, "_building", False):
            for tweak_id, switch in self._tweak_switches.items():
                selected = tweaks.get(tweak_id)
                checked = bool(selected is not None and selected.enabled)
                if switch.isChecked() != checked:
                    switch.blockSignals(True)
                    switch.setChecked(checked)
                    switch.blockSignals(False)
                editor=getattr(switch,'_value_editor',None)
                if editor is not None:
                    editor.setEnabled(checked and switch.isEnabled())
            self._apply_search()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_search_row()

    def _fit_search_row(self):
        """Keep search usable when translated filters need a second row."""
        margins = self._search_row.contentsMargins()
        filter_width = max(self.filter_control.sizeHint().width(),
                           self.filter_control.minimumWidth())
        required = (margins.left() + margins.right() + 240
                    + self._search_row.spacing() + filter_width)
        stacked = self.width() < required
        self._search_row.setDirection(
            QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self._search_row.setStretch(0, 0 if stacked else 1)
        self._search_row.setAlignment(
            self.filter_control, Qt.AlignLeading if stacked else Qt.Alignment())

    def _offer_untested_tweaks(self):
        from src.devicemanagement.constants import Version
        from src.gui.dialogs.confirmation import ConfirmationDialog
        from src.gui.ios.compat import _parse_version
        if not self.isVisible():
            return
        version = self.window.device_manager.get_current_device_version()
        try:
            if not Version("26") <= _parse_version(version) < Version("27"):
                return
        except ValueError:
            return
        if (self.window.settings.value("enable_incompatible_tweaks", False, type=bool)
                or self.window.settings.value("incompatible_tweaks_choice_done", False, type=bool)
                or getattr(self.window, "_untested_tweaks_prompt_shown", False)):
            return
        self.window._untested_tweaks_prompt_shown = True
        dialog = ConfirmationDialog(
            self.window, self.tr("This is not all tweaks"),
            self.tr("You can get more but they are untested with your iOS version\n"
                    "You can always change your mind in settings"),
            self.tr("Enable incompatible tweaks"))
        dialog.cancel_btn.setText(self.tr("No"))
        enabled = dialog.exec() == QDialog.Accepted
        self.window.settings.set_many({
            "enable_incompatible_tweaks": enabled,
            "incompatible_tweaks_choice_done": True,
        })
        self.window.settings.sync()
        if enabled:
            for content in self.window.findChildren(IOSSectionContent):
                if content._inner is not None:
                    content.rebuild()
        dialog.deleteLater()

    def rebuild(self):
        from src.gui.ios.incremental_builder import IncrementalBuilder
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None and not getattr(self, '_building', False):
            bar = parent.verticalScrollBar()
            self._rebuild_scroll_position = (bar, bar.value())
        if not hasattr(self, "_builder"):
            self._builder = IncrementalBuilder(self, on_error=self._build_failed)
        device = self.window.device_manager.data_singleton.current_device
        self._device_signature = tuple(getattr(device, key, None)
                                       for key in ("udid", "model", "version", "build"))
        self._building = True
        self._builder.start(self._build_rows())

    def _build_failed(self):
        # A render step raised mid-build: leave the page usable for search
        # instead of staying stuck in "building" forever.
        self._building = False
        self._loading_label.hide()

    def _build_rows(self):
        """(Re)build the section controls for the currently selected device.

        Called when first shown and when the selected device changes,
        so per-device compatibility filtering (``min_version`` /
        ``iphone_only`` / ``ipad_only`` from the registry) and HotLoad-hiding
        are re-evaluated instead of being frozen at startup, when no device is
        known yet (that would wrongly hide e.g. the Dynamic Island tweaks).
        """
        self._visibility_batch.cancel()
        self._viewport_rows.clear()
        # Tear down the previous build (widgets + layout) so the section can be
        # re-rendered in place from the single registry definition below.
        if self._inner is not None:
            self._inner.hide()
            self.layout().removeWidget(self._inner)
            self._inner.deleteLater()
            self._inner = None

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 32)
        layout.setSpacing(10)
        inner = QWidget(self)
        inner.setLayout(layout)
        self._inner = inner
        inner.hide()
        layout.setEnabled(False)
        self.layout().addWidget(inner)

        self.search._search_index = {}
        self._switch_labels = []
        self._tweak_switches = {}
        self._poster_preference_fields = {}
        self._info_buttons = []
        self._favorite_buttons = {}
        self._search_rows = []
        self._search_sections = []
        self._category_lines = []
        self.force_solarium_fallback_card = None

        try:
            device_ver = self.window.device_manager.get_current_device_version()
        except Exception:
            device_ver = ""
        try:
            model = self.window.device_manager.get_current_device_model() or ""
        except Exception:
            model = ""
        is_iphone = device_family(model) == "iphone"

        def is_compatible(tweak_id: TweakID) -> bool:
            return is_tweak_compatible(tweak_id, device_ver, is_iphone, model)

        def description_label(description):
            label = QLabel(description)
            label.setWordWrap(True)
            label.setTextFormat(Qt.PlainText)
            label.setProperty("tweakDescription", True)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._switch_labels.append(label)
            label.setStyleSheet(
                f"color: {ColorThemeManager.instance().colors.text_secondary}; font-size: 13px;")
            return label

        # Helper to create a switch row for boolean tweaks
        def make_switch(tweak_id: TweakID, title: str, description: str = "",
                        target: QVBoxLayout = None):
            if tweak_id not in tweaks:
                return
            tweak = tweaks[tweak_id]
            card = LiquidCard()
            if tweak_id == TweakID.ForceSolariumFallback:
                self.force_solarium_fallback_card = card
            if not is_compatible(tweak_id):
                card.hide()
            row_layout = QHBoxLayout(card)
            row_layout.setContentsMargins(16, 12, 16, 12)
            row_layout.setSpacing(12)

            c = ColorThemeManager.instance().colors
            label = QLabel(title)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {c.text_primary}; font-size: 15px;")
            self._switch_labels.append(label)
            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            text_layout.addWidget(label)
            if description:
                text_layout.addWidget(description_label(description))
            row_layout.addLayout(text_layout, 1)
            switch = LiquidSwitch(tweak.enabled)
            spec = SPECS_BY_ID.get(tweak_id)
            if tweak_id == TweakID.DisableSystemAperture:
                def select_aperture(checked):
                    if checked:
                        from src.gui.dialogs.confirmation import ask_confirmation
                        if not ask_confirmation(
                                self, self.tr("Test Dynamic Island availability?"),
                                self.tr("This may change Dynamic Island, the status bar and Live Activities. "
                                        "Removing the black background is not confirmed. "
                                        "Test this with Disable Dynamic Island switched off. "
                                        "Turn off and apply again to undo."),
                                self.tr("Enable experiment"), destructive=True):
                            switch.setChecked(False)
                            return
                    tweak.set_enabled(checked)
                switch.toggled.connect(select_aperture)
            elif spec is not None and spec.experimental:
                def select_experiment(checked):
                    if checked and spec.warning:
                        from src.gui.dialogs.confirmation import ask_confirmation
                        if not ask_confirmation(
                                self, title, QCoreApplication.translate("Nugget", spec.warning),
                                self.tr("Enable experiment"), destructive=True):
                            switch.setChecked(False)
                            return
                    tweak.set_enabled(checked)
                    if checked and spec.exclusive_with is not None:
                        peer = tweaks.get(spec.exclusive_with)
                        if peer is not None:
                            peer.set_enabled(False)
                        peer_switch = self._tweak_switches.get(spec.exclusive_with)
                        if peer_switch is not None:
                            peer_switch.setChecked(False)
                switch.toggled.connect(select_experiment)
            else:
                switch.toggled.connect(lambda checked: tweak.set_enabled(checked))
            if spec is not None and spec.unavailable_reason:
                switch.setEnabled(tweak.enabled)
                switch.toggled.connect(lambda checked, control=switch: control.setEnabled(checked))
                switch.setToolTip(spec.unavailable_reason)
            self._tweak_switches[tweak_id] = switch
            from src.gui.ios.feature_news import add_new_badge
            add_new_badge(row_layout, "tweak:" + tweak_id.name, card)
            row_layout.addWidget(switch)
            row_layout.addWidget(self._make_favorite_button(tweak_id, title))
            row_layout.addWidget(self._make_info_button(tweak_id, title))

            if description:
                label.setToolTip(description)
                switch.setToolTip(description)
                card.setToolTip(description)

            from awesomeui.liquid.selection_card import bind_selection_card
            bind_selection_card(card, switch)
            (target or layout).addWidget(card)
            self._search_rows.append((card, tweak_id, title, description, is_compatible(tweak_id)))

        def make_value_card(tweak_id,title,description,initial):
            from awesomeui.liquid.value_entry import GlassValueEntry
            tweak=tweaks[tweak_id]
            card=LiquidCard()
            card_layout=QHBoxLayout(card)
            text_layout=QVBoxLayout()
            label=QLabel(title)
            label.setWordWrap(True)
            label.setStyleSheet(f'color:{ColorThemeManager.instance().colors.text_primary};font-size:15px;')
            self._switch_labels.append(label)
            text_layout.addWidget(label)
            if description:
                text_layout.addWidget(description_label(description))
            card_layout.addLayout(text_layout,1)
            row=GlassValueEntry(title)
            row.setAccessibleDescription(description)
            switch=LiquidSwitch(tweak.enabled)
            switch.setAccessibleName(self.tr('Enable value: {0}').format(title))
            switch._value_editor=row
            spec=SPECS_BY_ID.get(tweak_id)
            available=not (spec and spec.unavailable_reason)
            row.setEnabled(tweak.enabled and available)
            switch.setEnabled(available)
            def select(checked):
                if checked and tweak.value is None:
                    tweak.set_value(initial,toggle_enabled=False)
                    row.set_display_value(str(initial) if isinstance(initial,str) else _fmt_number(initial))
                tweak.set_enabled(checked)
                from src.tweaks.tweak_classes import TriStateBooleanPlistTweak
                if isinstance(tweak,TriStateBooleanPlistTweak) and checked:
                    row.set_display_value('Disabled' if tweak.state is False else 'Enabled')
                row.setEnabled(checked and available)
                self.refresh_section_counts()
            switch.toggled.connect(select)
            self._tweak_switches[tweak_id]=switch
            from src.gui.ios.feature_news import add_new_badge
            add_new_badge(card_layout,'tweak:'+tweak_id.name,card)
            card_layout.addWidget(row)
            card_layout.addWidget(switch)
            card_layout.addWidget(self._make_favorite_button(tweak_id,title))
            card_layout.addWidget(self._make_info_button(tweak_id,title))
            from awesomeui.liquid.selection_card import bind_selection_card
            bind_selection_card(card,switch)
            return card,row

        def make_text_input(tweak_id,title,description='',target=None):
            if tweak_id not in tweaks or not is_compatible(tweak_id):
                return
            card,row=make_value_card(tweak_id,title,description,'')
            value=tweaks[tweak_id].value
            row.set_display_value('Not set' if value is None else (str(value) or 'Empty'))
            spec = SPECS_BY_ID.get(tweak_id)
            if spec is not None and spec.unavailable_reason:
                row.set_display_value(self.tr('Unavailable — needs verification'))
                row.setAccessibleDescription(spec.unavailable_reason)
            else:
                row.clicked.connect(lambda:self._show_text_input_dialog(tweak_id,title,'',row))
            (target or layout).addWidget(card)
            self._search_rows.append((card,tweak_id,title,description,True))

        def make_number_input(tweak_id,title,min_val=0,max_val=999,description='',step=1.0,target=None):
            if tweak_id not in tweaks or not is_compatible(tweak_id):
                return
            card,row=make_value_card(tweak_id,title,description,max(min_val,min(max_val,0)))
            value=tweaks[tweak_id].value
            row.set_display_value('Not set' if value is None else _fmt_number(value))
            spec=SPECS_BY_ID.get(tweak_id)
            if spec and spec.reset_value is not None and value==spec.reset_value:
                row.set_display_value(self.tr('Remove override'))
            if spec and spec.unavailable_reason:
                row.set_display_value(self.tr('Unavailable — needs verification'))
                row.setAccessibleDescription(spec.unavailable_reason)
            else:
                row.clicked.connect(lambda:self._show_number_input_dialog(tweak_id,title,0,row,min_val,max_val,step))
            (target or layout).addWidget(card)
            self._search_rows.append((card,tweak_id,title,description,True))

        # Render sections straight from the registry. Titles (and descriptions)
        # are stored as QT_TRANSLATE_NOOP markers and translated here, at
        # render time.
        def tr_title(spec) -> str:
            from src.gui.ios.feature_news import control_title
            return control_title(QCoreApplication.translate("Nugget", spec.title))

        def tr_description(spec) -> str:
            if not spec.description:
                return ""
            return QCoreApplication.translate("Nugget", spec.description)

        def make_poster_preferences(spec,target):
            make_switch(spec.id,tr_title(spec)+' - Apply',tr_description(spec),target)
            if spec.id not in self._tweak_switches:
                return
            from src.gui.liquid.poster_preferences import (
                render_poster_flag,
                render_poster_preferences,
            )
            renderer=render_poster_flag if spec.kind==Kind.POSTER_FLAG else render_poster_preferences
            renderer(self,spec,target)

        def make_boolean(spec,target):
            from src.tweaks.tweak_classes import TriStateBooleanPlistTweak
            tweak=tweaks.get(spec.id)
            if not isinstance(tweak,TriStateBooleanPlistTweak):
                make_switch(spec.id,tr_title(spec),tr_description(spec),target)
                return
            if not is_compatible(spec.id):
                return
            card,row=make_value_card(spec.id,tr_title(spec),tr_description(spec),True)
            control=self._tweak_switches[spec.id]
            def confirm(checked):
                if checked and spec.warning:
                    from src.gui.dialogs.confirmation import ask_confirmation
                    if not ask_confirmation(self,tr_title(spec),spec.warning,self.tr('Enable experiment'),destructive=True):
                        control.setChecked(False)
            control.toggled.connect(confirm)
            row.set_display_value('Disabled' if tweak.state is False else 'Enabled')
            def edit():
                from awesomeui.liquid.choice_editor import ChoiceDialog
                dialog=ChoiceDialog([('Disabled',False,True,None),('Enabled',True,True,None)],tweak.state)
                def save():
                    if not row.isEnabled():
                        return
                    tweak.set_state(dialog.get_value())
                    row.set_display_value('Enabled' if tweak.state else 'Disabled')
                from awesomeui.liquid.value_editor import ValueEditor
                old=getattr(self,'_value_editor_panel',None)
                if old is not None:
                    from shiboken6 import isValid
                    if isValid(old):
                        old.close()
                self._value_editor_panel=ValueEditor(self.window,row,dialog,tr_title(spec),save)
            row.clicked.connect(edit)
            target.addWidget(card)
            self._search_rows.append((card,spec.id,tr_title(spec),tr_description(spec),True))

        renderers = {
            Kind.POSTER_ARCHIVE: make_poster_preferences,
            Kind.WALLPAPER: make_poster_preferences,
            Kind.POSTER_FLAG: make_poster_preferences,
            Kind.SWITCH: make_boolean,
            Kind.TEXT: lambda spec, target: make_text_input(
                spec.id, tr_title(spec), tr_description(spec), target),
            Kind.NUMBER: lambda spec, target: make_number_input(
                spec.id, tr_title(spec), spec.min_value, spec.max_value,
                tr_description(spec), spec.step, target),
        }

        sections_to_render = self.sections if self.sections is not None else list(Section)
        hidden_sections = _hidden_sections()
        category_groups = []
        for section in sections_to_render:
            if section in hidden_sections:
                continue
            categories = {}
            for spec in SPECS_BY_SECTION[section]:
                categories.setdefault(tweak_category(spec), []).append(spec)
            if section == Section.SPRINGBOARD:
                ordered = {name: categories[name] for name in SPRINGBOARD_GROUPS if name in categories}
                ordered.update({name: rows for name, rows in categories.items() if name not in ordered})
                categories = ordered
            if "Risky Experiments" in categories:
                categories["Risky Experiments"] = categories.pop("Risky Experiments")
            if 'Wallpaper Feature Flags' in categories:
                categories['Wallpaper Feature Flags']=categories.pop('Wallpaper Feature Flags')
            category_groups.extend(categories.items())
        combined = {}
        for category, specs in category_groups:
            combined.setdefault(category, []).extend(specs)
        ordered_groups = [(name, combined.pop(name)) for name in TWEAK_CATEGORY_ORDER if name in combined]
        remaining = list(combined.items())
        normal = [group for group in ordered_groups if group[0] not in BOTTOM_TWEAK_CATEGORIES]
        bottom = [group for group in ordered_groups if group[0] in BOTTOM_TWEAK_CATEGORIES]
        ordered_groups = normal + remaining + bottom
        for category, specs in ordered_groups:
            if category == "Camera & Buttons":
                specs.sort(key=lambda spec: spec.id != TweakID.SBCoverSheetUseDefaultsValuesForCameraPrewarm)
            group = QWidget(inner)
            body = QVBoxLayout(group)
            body.setContentsMargins(0, 16, 0, 0)
            body.setSpacing(10)
            title = QCoreApplication.translate("Nugget", category)
            header = IOSSectionHeader(title)
            header.setProperty("navigationTitle", title)
            group.setProperty("categoryTitle", title)
            body.addWidget(header)
            line = QFrame(group)
            line.setFixedHeight(1)
            body.addWidget(line)
            self._category_lines.append(line)
            layout.addWidget(group)
            from awesomeui.liquid.cards import ControlGrid
            grid = ControlGrid()
            body.addLayout(grid)
            start = len(self._search_rows)
            for spec in specs:
                before = len(self._search_rows)
                renderers[spec.kind](spec, grid)
                for index in range(before, len(self._search_rows)):
                    card, *metadata = self._search_rows[index]
                    grid.removeWidget(card)
                    row = self._viewport_rows.wrap(card)
                    grid.addWidget(row)
                    self._search_rows[index] = (row, *metadata)
                yield
            section_rows = self._search_rows[start:]
            for card, *_ in section_rows:
                card.setProperty("categoryTitle", title)
            self._search_sections.append((group, section_rows))
        self._building = False
        self._loading_label.hide()
        self.refresh_section_counts()
        self._retheme()
        page = getattr(self.window, 'ios_tweaks', None)
        if page is not None and getattr(page, 'content', None) is self:
            page._applied_theme_revision = ColorThemeManager.instance().revision

        self.search_empty = IOSSearchEmpty(self)
        layout.addWidget(self.search_empty)
        layout.addStretch()

        # re-apply any remembered solarium-card visibility to the fresh card
        if self._solarium_visible is not None and self.force_solarium_fallback_card is not None:
            self.force_solarium_fallback_card.setVisible(self._solarium_visible)
        self._apply_search()
        layout.setEnabled(True)
        inner.show()
        saved_scroll = getattr(self, '_rebuild_scroll_position', None)
        if saved_scroll is not None and saved_scroll[1] > 0:
            bar, position = saved_scroll
            QTimer.singleShot(0, lambda: bar.setValue(position))
        self._viewport_rows.request()
        pages = getattr(self.window, "ios_pages", None)
        if pages is not None and hasattr(self.window, "ios_nav"):
            if pages.currentWidget().isAncestorOf(self):
                QTimer.singleShot(0, lambda: self.window._update_shared_nav(
                    pages.currentIndex()))

    def _apply_search(self, *_args):
        if self._inner is None or getattr(self, "_building", False):
            return
        self._filter_rows()

    def _filter_rows(self):
        searching = bool(self.search.text().strip())
        filter_mode = self.filter_control.currentData()
        favorites = self._favorites.names()
        matches = 0
        operations = []
        visibility = {}
        for card, tid, title, description, compatible in self._search_rows:
            enabled = bool(getattr(tweaks.get(tid), "enabled", False))
            available = compatible and not (
                tid == TweakID.ForceSolariumFallback and self._solarium_visible is False)
            if filter_mode == "enabled" and not enabled:
                available = False
            if filter_mode == "disabled" and enabled:
                available = False
            if filter_mode == "favorites" and tid.name not in favorites:
                available = False
            visible = available and self.search.matches(
                title, description, tid.name, card.property("categoryTitle"))
            operations.append((card, visible))
            visibility[card] = visible
            matches += visible
        for section, rows in self._search_sections:
            operations.append((section, any(visibility.get(row[0], False) for row in rows)))
        operations.append((self.search_empty, (searching or filter_mode != "all") and matches == 0))
        self._visibility_batch.apply(self._inner, operations)

    def refresh_section_counts(self):
        """Update enabled counts after a switch changes without rebuilding."""
        for section, rows in self._search_sections:
            enabled_count = sum(
                bool(getattr(tweaks.get(row[1]), "enabled", False))
                for row in rows)
            title = section.property("categoryTitle")
            header = section.findChild(IOSSectionHeader)
            summary=f'{title}:{enabled_count}:{len(rows)}'
            if header.property('selectionCountSummary')!=summary:
                header.setProperty('selectionCountSummary',summary)
                header.setToolTip(QCoreApplication.translate("Nugget", "{0} of {1} enabled")
                                  .format(enabled_count, len(rows)))

    def set_force_solarium_fallback_visible(self, visible: bool):
        # remember the intended state so a rebuild re-applies it (the card
        # pointer is recreated by rebuild())
        self._solarium_visible = visible
        self._apply_search()

    def _make_favorite_button(self, tweak_id, title):
        from awesomeui.liquid.controls import FavoriteButton
        button = FavoriteButton(self)
        button.setFixedSize(44, 44)
        button.setCheckable(True)
        button.setChecked(tweak_id.name in self._favorites.names())
        self._set_favorite_icon(button, button.isChecked())
        button.setIconSize(QSize(23, 23))
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(QCoreApplication.translate("Nugget", "Favorite: {0}").format(title))
        button.setToolTip(QCoreApplication.translate("Nugget", "Add or remove from favorites"))
        button.setStyleSheet(t("tweak_favorite_button"))
        button.toggled.connect(
            lambda selected, b=button, name=tweak_id.name:
            self._on_favorite_toggled(b, name, selected))
        self._favorite_buttons[tweak_id] = button
        return button

    def _refresh_favorites(self):
        names = self._favorites.names()
        for tid, button in self._favorite_buttons.items():
            selected = tid.name in names
            button.blockSignals(True)
            button.setChecked(selected)
            self._set_favorite_icon(button, selected)
            button.blockSignals(False)
        self._apply_search()

    def _on_favorite_toggled(self, button, name, selected):
        self._set_favorite_icon(button, selected)
        self._favorites.set_favorite(name, selected)

    def _set_favorite_icon(self, button, selected):
        colors = ColorThemeManager.instance().colors
        color = '#d6b967' if selected else colors.text_secondary
        icon = ":/icon/star-fill.svg" if selected else ":/icon/star.svg"
        button.setIcon(QIcon(theme_pixmap(
            icon, color, 23, button.devicePixelRatioF())))

    def _refresh_action_icons(self):
        for button in self._favorite_buttons.values():
            self._set_favorite_icon(button, button.isChecked())
        for button in self._info_buttons:
            button.setIcon(theme_icon(
                ":/icon/questionmark.circle.svg",
                ColorThemeManager.instance().colors.text_secondary))

    def _make_info_button(self, tweak_id, title):
        button = QPushButton(self)
        button.setFixedSize(36, 36)
        button.setIcon(theme_icon(":/icon/questionmark.circle.svg",
                                  ColorThemeManager.instance().colors.text_secondary))
        button.setIconSize(QSize(19, 19))
        button.setCursor(Qt.PointingHandCursor)
        help_text = QCoreApplication.translate("Nugget", "About {0}").format(title)
        button.setToolTip(help_text)
        button.setAccessibleName(help_text)
        button.setStyleSheet(t("tweak_info_button"))
        button.clicked.connect(lambda: self._show_tweak_info(tweak_id))
        self._info_buttons.append(button)
        return button

    def _show_tweak_info(self, tweak_id):
        from src.gui.dialogs.tweak_info import TweakInfoDialog
        from src.tweaks.registry import SPECS_BY_ID
        previous = getattr(self, '_tweak_info_dialog', None)
        if previous is not None:
            previous.close()
        dialog = TweakInfoDialog(SPECS_BY_ID[tweak_id], self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._tweak_info_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, '_tweak_info_dialog', None))
        dialog.show()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._description_note.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px;")
        self.filter_control._retheme()
        for lbl in self._switch_labels:
            secondary = bool(lbl.property("tweakDescription"))
            color = c.text_secondary if secondary else c.text_primary
            size = 13 if secondary else 15
            lbl.setStyleSheet(f"color: {color}; font-size: {size}px;")
        for line in self._category_lines:
            line.setStyleSheet(f"background-color: {c.border}; border: none;")
        for button in self._info_buttons:
            button.setStyleSheet(t("tweak_info_button"))
        for button in self._favorite_buttons.values():
            button.setStyleSheet(t("tweak_favorite_button"))

    def _show_text_input_dialog(self, tweak_id: TweakID, title: str, current: str, row: IOSValueRow):
        spec = SPECS_BY_ID.get(tweak_id)
        if spec is not None and spec.unavailable_reason:
            return
        saved = tweaks[tweak_id].value
        current = "" if saved is None else str(saved)
        spec = SPECS_BY_ID.get(tweak_id)
        is_bundle = bool(spec is not None and spec.bundle_identifier)
        dialog = TextInputDialog(title, current, self, bundle_identifier=is_bundle)
        def save():
            value = dialog.get_value()
            if value and spec is not None and spec.warning:
                from src.gui.dialogs.confirmation import ask_confirmation
                if not ask_confirmation(
                        self, title, QCoreApplication.translate("Nugget", spec.warning),
                        self.tr("Save experimental value"), destructive=True):
                    return
            tweaks[tweak_id].set_value(value, toggle_enabled=False)
            empty_label = "No app override" if is_bundle else "Empty"
            display = value if value else QCoreApplication.translate("Nugget", empty_label)
            row.set_display_value(display)
        from awesomeui.liquid.value_editor import ValueEditor
        old=getattr(self,'_value_editor_panel',None)
        if old is not None:
            from shiboken6 import isValid
            if isValid(old):
                old.close()
        self._value_editor_panel=ValueEditor(self.window,row,dialog,title,save,
                                            example=spec.value if spec is not None else None)

    def _show_number_input_dialog(self, tweak_id: TweakID, title: str, current, row: IOSValueRow, min_val, max_val, step: float = 1.0):
        spec = SPECS_BY_ID.get(tweak_id)
        if spec is not None and spec.unavailable_reason:
            return
        saved = tweaks[tweak_id].value
        current = 0 if saved is None else saved
        dialog = NumberInputDialog(title, current, min_val, max_val, self, step=step)
        def save():
            value = dialog.get_value()
            spec = SPECS_BY_ID.get(tweak_id)
            if spec is not None and spec.warning:
                from src.gui.dialogs.confirmation import ask_confirmation
                if not ask_confirmation(
                        self, title, QCoreApplication.translate("Nugget", spec.warning),
                        self.tr("Save experimental value"), destructive=True):
                    return
            tweaks[tweak_id].set_value(value, toggle_enabled=False)
            display = self.tr("Remove override") if spec is not None and spec.reset_value is not None and value == spec.reset_value else _fmt_number(value)
            row.set_display_value(display)
        from awesomeui.liquid.value_editor import ValueEditor
        old=getattr(self,'_value_editor_panel',None)
        if old is not None:
            from shiboken6 import isValid
            if isValid(old):
                old.close()
        self._value_editor_panel=ValueEditor(self.window,row,dialog,title,save,
                                            example=spec.value if spec is not None else None)


class IOSTweaksPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self._scroll = scroll
        self.content = IOSSectionContent(window, [section for section in Section if section != Section.POSTERBOARD], self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._retheme()

    def prepare_content(self, *, finish=True):
        if self.content._inner is None and not getattr(self.content, '_building', False):
            self.content.rebuild()
        builder = getattr(self.content, '_builder', None)
        if builder is not None and finish:
            builder.finish()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.content._retheme()

    def set_force_solarium_fallback_visible(self, visible: bool):
        self.content.set_force_solarium_fallback_visible(visible)

    def rebuild(self):
        self.content.rebuild()


class IOSSectionPage(QWidget):
    """Standalone iOS-style page for a single tweak section."""

    def __init__(self, window, section: Section, parent=None):
        super().__init__(parent)
        self.window = window
        self.section = section
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self._scroll = scroll
        self.content = IOSSectionContent(window, [section], self)
        scroll.setWidget(self.content)
        layout.addWidget(scroll)

        self._retheme()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        self.content._retheme()

    def set_force_solarium_fallback_visible(self, visible: bool):
        self.content.set_force_solarium_fallback_visible(visible)

    def rebuild(self):
        self.content.rebuild()
