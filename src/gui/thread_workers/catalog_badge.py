"""Background count for the home page's community-catalog badge."""
from PySide6.QtCore import QThread, Signal


class CatalogBadgeThread(QThread):
    """Counts catalog updates for installed presets and templates.

    ``IOSHomePage.refresh_catalog_badge`` used to do this on the GUI thread in
    a ``QTimer.singleShot(0, ...)`` right after the window was shown: it read
    every preset's metadata (one ``json.load`` per preset) and read + SHA-256'd
    every installed ``.batter`` template. That is file I/O, so it belongs on a
    worker; the badge text is filled in when the count arrives.
    """

    counted = Signal(int)

    def run(self):
        try:
            count = _count_updates()
        except Exception:
            # A badge is cosmetic: never let a broken catalog kill the thread.
            count = 0
        self.counted.emit(count)


def _count_updates() -> int:
    from src.controllers import preset_catalog
    from src.controllers.preset_manager import PresetManager

    data, _saved_at = preset_catalog.read_cache()
    if data is None:
        return 0
    # A fresh manager: the page's own one belongs to the GUI thread, and
    # everything used here (paths + a pure validator) is read-only.
    pm = PresetManager()
    entries, templates, _ = preset_catalog.parse_catalog(data, pm._valid_import_structure)
    installed = preset_catalog.installed_items(pm)
    return preset_catalog.count_updates(entries + templates, installed)
