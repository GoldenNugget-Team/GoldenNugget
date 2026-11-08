"""Cooperative wait after an explicit Find My restore rejection."""
import asyncio
from contextvars import ContextVar
from threading import Event, Lock

from src.exceptions.nugget_exception import NuggetException
from src.utils.i18n import QCoreApplication

current_find_my_wait = ContextVar("find_my_wait", default=None)


class ApplyCancelledError(NuggetException):
    pass


class FindMyWaitControl:
    def __init__(self):
        self._lock = Lock()
        self._cancelled = Event()
        self._active = False
        self._checking = False

    def snapshot(self):
        with self._lock:
            return self._active, self._checking, self._cancelled.is_set()

    def begin(self):
        with self._lock:
            self._active = True
            self._checking = False

    def cancel(self):
        with self._lock:
            if self._active and not self._checking:
                self._cancelled.set()

    def checking(self):
        with self._lock:
            self.raise_if_cancelled()
            self._checking = True

    def raise_if_cancelled(self):
        if self._cancelled.is_set():
            raise ApplyCancelledError(QCoreApplication.translate(
                "Nugget", "Cancelled while waiting for Find My. Restoration is incomplete. "
                "Your protective backup remains on this computer; do not erase the device."))

    async def wait_for_retry(self):
        self.begin()
        for _ in range(50):
            self.raise_if_cancelled()
            await asyncio.sleep(0.1)
        self.checking()

    def finish(self):
        with self._lock:
            self._active = False
            self._checking = False
