"""Background startup fetches; every UI reaction runs in the Qt main thread."""
import os
from threading import Event, Thread

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class StartupServices(QObject):
    update_ready = Signal(object)
    rules_ready = Signal(bool)

    def __init__(self, app, window, manager, hotload, logger, kill_rule, show_kill):
        super().__init__(app)
        self.window, self.manager, self.hotload = window, manager, hotload
        self.log, self.kill_rule, self.show_kill = logger, kill_rule, show_kill
        self.closing = Event()
        self._required_update_dialog = None
        app.aboutToQuit.connect(self.closing.set)
        self.update_ready.connect(self._apply_update)
        self.rules_ready.connect(self._apply_rules)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._check_kill)

    def start(self):
        # Enforce cached rules immediately, including when the network is down.
        self._check_kill()
        Thread(target=self._fetch_update, name="startup-update", daemon=True).start()
        Thread(target=self._fetch_rules, name="startup-safety", daemon=True).start()
        self.timer.start()

    def _fetch_update(self):
        try:
            from src.controllers import web_request_handler
            from src.gui.version import App_Build, App_Version
            # True / False / None (check failed). None must stay None — bool(None)
            # would show "Up to date!".
            result = web_request_handler.is_update_available(App_Version, App_Build)
            if not self.closing.is_set():
                self.update_ready.emit(result)
        except Exception as exc:
            self.log.debug("Update check failed: %s", exc)
            if not self.closing.is_set():
                self.update_ready.emit(None)

    def _fetch_rules(self):
        try:
            changed = self.hotload.update()
            if not self.closing.is_set():
                self.rules_ready.emit(bool(changed))
        except Exception as exc:
            self.log.debug("HotLoad update failed: %s", exc)

    @Slot(object)
    def _apply_update(self, available):
        if not self.closing.is_set():
            self.window.ios_home.set_update_available(available)

    @Slot(bool)
    def _apply_rules(self, changed):
        if changed and not self.closing.is_set():
            self._check_kill(quiet=False)

    @Slot()
    def _check_kill(self, quiet=True):
        kill = self.kill_rule(self.manager, self.hotload)
        if kill:
            reason = kill.get("reason")
            self.log.critical("GoldenNugget killed by HotLoad rules while running: %s", reason)
            if not quiet:
                self.show_kill(kill)
            # Preserve the configured kill-switch policy, after any GUI notice.
            os._exit(1)
        if self.closing.is_set() or self._required_update_dialog is not None:
            return
        rule = self.hotload.bad_news_rule(
            self.manager.get_current_device_version() or None,
            self.manager.get_current_device_model() or None)
        if rule:
            from src.gui.dialogs.update_dialog import UpdateDialog
            self._required_update_dialog = UpdateDialog(self.window, required=True, rule=rule)
            # show() preserves ApplicationModal; open() would change it to WindowModal.
            self._required_update_dialog.show()
