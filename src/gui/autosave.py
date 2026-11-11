"""Qt autosave scheduling kept separate from window navigation and settings."""
import logging

from PySide6 import QtCore

from src.controllers.autosave_state import AutosaveState
from src.tweaks.tweak_classes import subscribe_tweak_changes

log = logging.getLogger("GoldenNugget.autosave")


class _TweakChangeRelay(QtCore.QObject):
    changed = QtCore.Signal()

    def notify(self):
        self.changed.emit()


class AutosaveMixin:
    def _get_autosave_state(self):
        if not hasattr(self, "autosave_state"):
            self.autosave_state = AutosaveState()
        return self.autosave_state

    def _register_tweak_autosave(self):
        """Register callback to auto-save preset when tweaks change."""
        if isinstance(self, QtCore.QObject):
            self._tweak_change_relay = _TweakChangeRelay(self)
            self._tweak_change_relay.changed.connect(self._on_tweak_changed)
            callback = self._tweak_change_relay.notify
        else:
            callback = self._on_tweak_changed
        self._unsubscribe_tweak_changes = subscribe_tweak_changes(callback)
        app = QtCore.QCoreApplication.instance()
        if app is not None and isinstance(self, QtCore.QObject):
            app.aboutToQuit.connect(self._flush_autosave)


    def _on_tweak_changed(self):
        """Called when any tweak value changes - schedule autosave."""
        if not getattr(self, "_tweak_counts_pending", False):
            self._tweak_counts_pending = True
            if QtCore.QCoreApplication.instance() is not None:
                QtCore.QTimer.singleShot(0, self._refresh_tweak_counts)
        self._get_autosave_state().changed()
        if not self.autosave_enabled() or getattr(self, "_autosave_closing", False):
            return
        self._preset_autosave_pending = True
        if QtCore.QCoreApplication.instance() is None:
            return  # Headless callers may flush explicitly.
        timer = getattr(self, "_preset_autosave_timer", None)
        if timer is None:
            timer = QtCore.QTimer(self if isinstance(self, QtCore.QObject) else None)
            timer.setSingleShot(True)
            timer.timeout.connect(self._save_autosave_preset)
            self._preset_autosave_timer = timer
        timer.start(500)

    def _refresh_tweak_counts(self):
        self._tweak_counts_pending = False
        try:
            for page in getattr(self, "ios_pages", []):
                content = getattr(page, "content", None)
                if content is not None and hasattr(content, "refresh_section_counts"):
                    content.refresh_section_counts()
        except Exception:
            pass
        if hasattr(self, "ios_home"):
            self.ios_home.selection_counts_requested.emit()


    def _save_autosave_preset(self):
        """Save current tweak state to AutoSave preset."""
        self._preset_autosave_pending = False
        state = self._get_autosave_state()
        if not self.autosave_enabled():
            # Second guard: a debounce timer scheduled before the switch was
            # flipped off still fires, and must not resurrect the file.
            return
        if getattr(self, "_autosave_closing", False):
            return
        if getattr(self, "_autosave_task", None) is not None:
            self._autosave_again = True
            return
        revision = state.revision
        state.status = "saving"
        try:
            args = dict(tags=["auto"],
                        device_model=self.device_manager.get_current_device_model() or "",
                        ios_version=self.device_manager.get_current_device_version() or "")
            if not isinstance(self, QtCore.QObject):
                result = self.preset_manager.save_preset("AutoSave", "Automatic save of last tweak configuration", **args)
                state.finish(revision, result)
                return
            from src.gui.dialogs.file_task import start_file_task
            manager = self.preset_manager
            pref = self.device_manager.pref_manager
            snapshot = manager.snapshot()
            if snapshot is None:
                raise ValueError("Could not prepare an autosave snapshot")
            def saved(result):
                if getattr(self, "_autosave_closing", False):
                    return
                state.finish(revision, result, enabled=self.autosave_enabled())
                if state.status == "error":
                    log.error("Autosave failed: %s", state.error)
                self._autosave_task = None
                if getattr(self, "_autosave_again", False) and not getattr(self, "_autosave_closing", False):
                    self._autosave_again = False
                    self._save_autosave_preset()
            self._autosave_task = start_file_task(self,
                lambda: manager.save_snapshot("AutoSave", snapshot, "Automatic save of last tweak configuration", should_commit=lambda: bool(pref.tweak_autosave), **args),
                saved, saved, must_finish=True)
        except Exception as exc:
            state.finish(revision, exc)
            log.exception("Could not prepare autosave")

    def _flush_autosave(self):
        """Drain the writer before the final synchronous save on shutdown."""
        if getattr(self, "_autosave_closing", False):
            return
        self._autosave_closing = True
        timer = getattr(self, "_preset_autosave_timer", None)
        if timer is not None:
            timer.stop()
        task = getattr(self, "_autosave_task", None)
        if task is not None:
            task.worker.wait()
        state = self._get_autosave_state()
        pending = task is not None or self._preset_autosave_pending or getattr(self, "_autosave_again", False) or state.dirty
        if pending and self.autosave_enabled():
            result = self.preset_manager.save_preset("AutoSave", "Automatic save of last tweak configuration",
                tags=["auto"], device_model=self.device_manager.get_current_device_model() or "",
                ios_version=self.device_manager.get_current_device_version() or "")
            state.finish(state.revision, result)
            if state.status == "error":
                log.error("Final autosave failed: %s", state.error)
        self._preset_autosave_pending = False
