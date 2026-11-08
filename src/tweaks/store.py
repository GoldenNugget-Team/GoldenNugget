"""Tweak state ownership and subscriptions, independent of Qt."""
import logging
import weakref
from collections.abc import Mapping
from contextlib import contextmanager

log = logging.getLogger("GoldenNugget.tweaks")


def selection_store(owner, default):
    """Resolve explicit headless/service state, retaining the legacy GUI default."""
    selected = getattr(owner, "tweak_store", None)
    return selected if isinstance(selected, Mapping) else default


class ChangeBus:
    def __init__(self):
        self._listeners = {}
        self._depth = 0
        self._pending = False
        self._muted = 0

    def subscribe(self, callback):
        token = object()
        reference = weakref.WeakMethod(callback) if getattr(callback, "__func__", None) is not None and getattr(callback, "__self__", None) is not None else lambda: callback
        self._listeners[token] = reference
        return lambda: self._listeners.pop(token, None)

    def notify(self):
        if self._muted:
            return
        if self._depth:
            self._pending = True
            return
        for token, reference in list(self._listeners.items()):
            callback = reference()
            if callback is None:
                self._listeners.pop(token, None)
                continue
            try:
                callback()
            except Exception:
                log.exception("Tweak change observer failed")

    @contextmanager
    def suspend(self):
        self._muted += 1
        try:
            yield
        finally:
            self._muted -= 1

    @contextmanager
    def batch(self):
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if not self._depth and self._pending:
                self._pending = False
                self.notify()


class TweakStore(dict):
    """Dict-compatible migration boundary; instances own independent observers."""
    def __init__(self, *args, changes=None, **kwargs):
        super().__init__()
        self.changes = changes if changes is not None else ChangeBus()
        self.update(*args, **kwargs)

    def __setitem__(self, key, value):
        value._change_bus = self.changes
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def commit(self, candidates):
        """Publish prepared states without replacing identities held by widgets."""
        prepared = [(self[key], dict(candidate.__dict__)) for key, candidate in candidates.items()]
        for target, values in prepared:
            target.__dict__.update(values)
        if candidates:
            self.changes.notify()


default_changes = ChangeBus()
