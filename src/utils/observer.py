"""Minimal observer primitive for backend state objects.

``TweakFavorites`` used to be a ``QObject`` with a ``Signal`` so GUI pages
could refresh themselves. The backend may not depend on Qt, so this keeps the
same ``connect``/``emit``/``disconnect`` surface without it.

Semantics deliberately match a *direct* Qt connection:

* the emit runs the slots synchronously on the caller's thread;
* **slots are held weakly**, so a destroyed page that forgot to disconnect
  cannot keep itself (or a ``QWidget`` wrapper) alive, and a dead slot is
  simply dropped on the next emit — the Qt signal/slot connection is torn down
  with the receiver for the same reason;
* a slot that raises is logged and skipped. Qt routes slot exceptions to the
  crash handler and keeps delivering to the other receivers; a listener must
  never take down the state change that notified it.
"""

from __future__ import annotations

import logging
import weakref

logger = logging.getLogger("GoldenNugget.observer")


class Signal:
    def __init__(self):
        self._slots = []

    @staticmethod
    def _wrap(slot):
        if getattr(slot, "__self__", None) is not None:
            # Bound method: tie the connection to the receiver's lifetime.
            try:
                return weakref.WeakMethod(slot)
            except TypeError:
                pass
        # Plain function/lambda/closure: there is no receiver to outlive.
        return lambda: slot

    @staticmethod
    def _resolve(reference):
        try:
            return reference()
        except TypeError:  # the strong-reference fallback above
            return reference()

    def connect(self, slot):
        for reference in self._slots:
            if self._resolve(reference) == slot:
                return slot
        self._slots.append(self._wrap(slot))
        return slot

    def disconnect(self, slot=None):
        if slot is None:
            self._slots.clear()
            return
        self._slots = [reference for reference in self._slots
                       if self._resolve(reference) != slot]

    def emit(self, *args, **kwargs):
        for reference in list(self._slots):
            slot = self._resolve(reference)
            if slot is None:
                try:
                    self._slots.remove(reference)
                except ValueError:
                    pass
                continue
            try:
                slot(*args, **kwargs)
            except RuntimeError:
                # Receiver's C++ object is gone (PySide raises this when a
                # destroyed widget's bound method is called).
                logger.debug("Dropping dead slot %r", slot, exc_info=True)
                try:
                    self._slots.remove(reference)
                except ValueError:
                    pass
            except Exception:
                logger.warning("Observer slot %r failed", slot, exc_info=True)
