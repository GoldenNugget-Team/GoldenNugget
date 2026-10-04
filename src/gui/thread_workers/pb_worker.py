from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import QMessageBox
import asyncio
import queue
import traceback

from src.gui.thread_workers.apply_worker import ApplyAlertMessage


class PBDBThread(QThread):
    progress = Signal(float)
    infoLbl = Signal(str)
    alert = Signal(object)  # ApplyAlertMessage

    def update_label(self, txt: str):
        self.infoLbl.emit(txt)
    def update_progress(self, amt: float):
        self.progress.emit(amt)
    def alert_window(self, msg: ApplyAlertMessage):
        self.alert.emit(msg)
    
    def __init__(self, backup_function):
        super().__init__()
        self.backup_function = backup_function

    def do_work(self):
        self.backup_function(self.update_label, self.update_progress)

    def run(self):
        try:
            self.do_work()
        except Exception as e:
            import logging
            logging.getLogger("GoldenNugget.pb").error(
                "PosterBoard backup failed: %s\n%s", e, traceback.format_exc())
            self.infoLbl.emit("Backup Failed!")
            self.alert.emit(ApplyAlertMessage(
                f"Backup failed: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback.format_exc(),
                exc_type=type(e),
                exc_value=e,
            ))


class PBRebuildThread(QThread):
    """Repack the device's flat wallpapers into the Clownfish format.

    Runs ``posterboard_rebuild.rebuild_posterboard`` in a background thread
    (pull + protective backup + restore all touch the device for minutes). The
    password / abort-resume prompts are relayed to the main thread through
    queued signals, mirroring ``ApplyThread``.
    """

    progress = Signal(str)
    alert = Signal(object)
    finished_with_result = Signal(bool, str)
    request_text = Signal(str, str, object)
    choice_prompt = Signal(str, str, object)

    _PROMPT_TIMEOUT_SEC = 10 * 60

    def __init__(self, manager, udid: str):
        super().__init__()
        self.manager = manager
        self.udid = udid
        self.result_message = ""

    def update_label(self, txt: str):
        self.progress.emit(txt)

    def update_progress(self, value):
        if isinstance(value, str):
            self.progress.emit(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            self.progress.emit(f"Backing up... {value:6.1f}%")

    def prompt_password(self, title: str, label: str):
        box = queue.Queue(maxsize=1)
        self.request_text.emit(title, label, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return None

    def prompt_user_choice(self, title: str, text: str) -> str:
        box = queue.Queue(maxsize=1)
        self.choice_prompt.emit(title, text, box)
        try:
            return box.get(timeout=self._PROMPT_TIMEOUT_SEC)
        except queue.Empty:
            return "abort"

    def run(self):
        from src.controllers.nugget_logger import log_context
        from src.tweaks.posterboard.posterboard_rebuild import rebuild_posterboard
        try:
            log_context("START pb-rebuild", udid=self.udid)
            result = asyncio.run(rebuild_posterboard(
                self.udid, self.manager,
                update_label=self.update_label,
                update_progress=self.update_progress,
                prompt_password=self.prompt_password,
                prompt_choice=self.prompt_user_choice))
            self.result_message = result.message
            log_context("FINISH pb-rebuild OK")
            self.finished_with_result.emit(True, result.message)
        except Exception as e:
            traceback_str = traceback.format_exc()
            import logging
            logging.getLogger("GoldenNugget.pb").error(
                "PosterBoard rebuild failed: %s\n%s", e, traceback_str)
            self.alert.emit(ApplyAlertMessage(
                f"Rebuild failed: {e}",
                title="Error",
                icon=QMessageBox.Critical,
                detailed_txt=traceback_str,
                exc_type=type(e),
                exc_value=e,
            ))
            self.finished_with_result.emit(False, f"{type(e).__name__}: {e}")