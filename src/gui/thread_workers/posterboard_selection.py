"""Load a device's saved wallpaper configuration without blocking the GUI."""
import logging

from PySide6.QtCore import QThread, Signal


class PosterBoardSelectionWorker(QThread):
    ready = Signal(str, object, str)

    def __init__(self, udid, parent=None):
        super().__init__(parent)
        self.udid = udid

    def run(self):
        try:
            from src.tweaks.posterboard.pb_config_manager import PBConfigManager
            snapshot = PBConfigManager()
            snapshot.update_for_saved_database(self.udid)
            self.ready.emit(self.udid, (snapshot.database, snapshot.saved_items), '')
        except Exception as error:
            logging.getLogger('GoldenNugget.device_selection').exception('Saved wallpaper configuration could not be loaded')
            self.ready.emit(self.udid, None, str(error))
