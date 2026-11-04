"""GoldenNugget's theme adapter for the shared awesomeUI controls.

Keep application settings and theme ownership here; implementations live in awesomeui.
"""
from PySide6.QtCore import QTimer
from awesomeui import configure_theme, Sidebar, SidebarTheme
from src.gui.theme import ColorThemeManager, t, theme_pixmap
from src.gui.theme.theme_manager import connect_visible_theme

configure_theme(manager=ColorThemeManager.instance, stylesheet=t,
                pixmap=theme_pixmap, connect=connect_visible_theme)

from awesomeui.controls import (
    IOSSearchField as _SearchField,
    IOSSegmentedFilter,
    IOSSearchEmpty,
    IOSSectionHeader,
    IOSCard,
    IOSCollapsibleSection as _CollapsibleSection,
    IOSNavBar as _NavBar,
    IOSValueRow,
    IOSSettingsRow,
    IOSSettingsAction,
    IOSPrimaryButton,
    IOSDangerButton,
    IOSSwitch,
    _auto_retheme,
)


class IOSSearchField(_SearchField):
    def connect_filter(self, callback):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(100)
        timer.timeout.connect(callback)
        self.textChanged.connect(lambda: timer.start())
        self._filter_timer = timer

    def matches(self, *texts):
        if not hasattr(self, "_search_index"):
            self._search_index = {}
        key = tuple(text or "" for text in texts)
        if key not in self._search_index:
            self._search_index[key] = " ".join(key).casefold()
        query = self.text()
        if query != getattr(self, "_last_query", None):
            self._last_query = query
            self._search_words = query.casefold().split()
        return all(word in self._search_index[key] for word in self._search_words)


class IOSCollapsibleSection(_CollapsibleSection):
    def _update_header_text(self):
        chevron = self.EXPANDED_CHEVRON if self._expanded else self.COLLAPSED_CHEVRON
        self.header.setText(f"{chevron}  {self._title.replace('&', '&&')}{self._title_suffix}")


class IOSNavBar(_NavBar):
    def _clear_right(self):
        # Hide the outgoing action immediately; deferred deletion alone leaves
        # an overlapping button visible during rapid page changes.
        if self._right_btn is not None:
            self._right_btn.hide()
        super()._clear_right()


class NavigationSidebar(Sidebar):
    """awesomeUI navigation with the existing page-controller bindings."""

    ITEM_NAMES = (
        "homePageBtn", "posterboardPageBtn", "templatesPageBtn", "gestaltPageBtn", "euEnablerPageBtn",
        "statusBarPageBtn", "passcodePageBtn", "springboardOptionsPageBtn",
        "internalOptionsPageBtn", "liquidGlassPageBtn", "daemonsPageBtn",
        "iconThemesPageBtn", "presetsPageBtn", "applyPageBtn", "settingsPageBtn",
    )

    def __init__(self, ui, parent=None):
        super().__init__(parent, collapsible=False)
        # Sidebar mode puts this column at the window's top left, where the
        # app-drawn window buttons live; set_top_inset grows this base margin.
        self._base_top_padding = self.layout().contentsMargins().top()
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QIcon
        for name in self.ITEM_NAMES:
            if name == "posterboardPageBtn":
                ui.sidebarDiv1 = self.add_separator()
            if name == "applyPageBtn":
                ui.sidebarDiv2 = self.add_separator()
            old = getattr(ui, name, None)
            text = old.text() if old else QCoreApplication.translate("Nugget", "Presets")
            icon = old.icon() if old else QIcon(":/icon/folder.svg")
            if name == "templatesPageBtn":
                text = QCoreApplication.translate("Nugget", "Templates")
                icon = QIcon(":/icon/file-earmark-text.svg")
            item = self.add_item(name, text, icon)
            if old is not None:
                item.setEnabled(old.isEnabled())
                item.setVisible(not old.isHidden())
                item.setToolTip(old.toolTip())
                item.setChecked(old.isChecked())
            setattr(ui, name, item)
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        colors = ColorThemeManager.instance().colors
        self.set_theme(SidebarTheme(
            background=colors.bg_secondary, border=colors.border,
            text=colors.text_primary, text_muted=colors.text_secondary,
            hover_background=colors.surface_hover,
            active_background=colors.bg_tertiary, active_indicator=colors.accent,
            separator=colors.divider, width=232, item_height=38,
        ))

    def set_top_inset(self, px):
        """Leave room above the first item for the window's own buttons.

        Only sidebar mode needs it: the shared header (which the buttons sit
        on otherwise) is hidden, so this column starts at the window's corner.
        """
        root = self.layout()
        if root is None:
            return
        margins = root.contentsMargins()
        root.setContentsMargins(margins.left(),
                                self._base_top_padding + max(0, int(px)),
                                margins.right(), margins.bottom())


from src.gui.liquid.controls import LiquidSwitch as IOSSwitch
from src.gui.liquid.controls import LiquidActionButton as IOSPrimaryButton
from src.gui.liquid.controls import LiquidDangerButton as IOSDangerButton
from src.gui.liquid.navigation import LiquidNavBar as IOSNavBar

from src.gui.liquid.controls import LiquidCard as IOSCard
