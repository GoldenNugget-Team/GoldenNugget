"""Community Catalog page: the preset and template catalog as its own page."""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.gui.dialogs.preset_catalog import (
    CatalogDialog,
    _device_context,
    refresh_template_list,
)


class IOSCatalogPage(QWidget):
    """Hosts an embedded CatalogDialog, built when the page is first shown so
    the catalog is only downloaded once someone opens it. A different iPhone
    rebuilds it, since the iOS filter and risk verdicts depend on the device."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.panel = None
        self._device = None

    def showEvent(self, event):
        super().showEvent(event)
        self.ensure_panel()

    def hideEvent(self, event):
        super().hideEvent(event)
        home = getattr(self.window, "ios_home", None)
        if home is not None and hasattr(home, "refresh_catalog_badge"):
            home.refresh_catalog_badge()

    def ensure_panel(self):
        version, model, hotload = _device_context(self.window)
        if self.panel is not None and self._device == (version, model):
            return self.panel
        if self.panel is not None:
            self.panel.stop()
            self._layout.removeWidget(self.panel)
            self.panel.deleteLater()
        self._device = (version, model)
        self.panel = CatalogDialog(self.window.ios_presets.preset_manager, version, model, hotload,
                                   self, embedded=True)
        self.panel.on_change = self._on_change
        self._layout.addWidget(self.panel)
        self.panel.show()
        return self.panel

    def _on_change(self):
        presets = getattr(self.window, "ios_presets", None)
        if presets is not None and hasattr(presets, "refresh"):
            presets.refresh()
        if self.panel is not None and self.panel.added_templates:
            refresh_template_list(self.window)
