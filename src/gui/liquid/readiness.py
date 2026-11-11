import asyncio

from PySide6.QtCore import QThread, Signal

_running_checks=set()


class DeviceReadiness(QThread):
    result=Signal(str,str,str)

    def __init__(self,udid):
        super().__init__()
        self.udid=udid
        self._loop=None
        self._task=None
        _running_checks.add(self)
        self.finished.connect(self.dispose)

    def dispose(self):
        _running_checks.discard(self)
        self.deleteLater()

    def cancel(self):
        self.requestInterruption()
        if self._loop is not None and self._task is not None:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                return

    async def probe(self):
        from src.devicemanagement.session import lockdown_session
        self._loop=asyncio.get_running_loop()
        self._task=asyncio.current_task()
        if self.isInterruptionRequested():
            raise asyncio.CancelledError
        async with lockdown_session(self.udid,autopair=False,pair_timeout=2,connection_type='USB') as client:
            await client.get_value(key='DeviceName')
            return 'ready','Device connected. Keep it unlocked when you confirm.'

    def run(self):
        from pymobiledevice3.exceptions import NotPairedError

        from src.exceptions.device_errors import (
            is_device_lock_required_error,
            is_device_locked_error,
        )
        try:
            state,message=asyncio.run(asyncio.wait_for(self.probe(),5))
        except asyncio.CancelledError:
            return
        except Exception as error:
            if is_device_lock_required_error(error) or is_device_locked_error(error):
                state,message='locked','Device detected. iOS is requesting your passcode; unlock it and retry.'
            elif isinstance(error,NotPairedError):
                state,message='untrusted','Unlock your device and trust this computer.'
            else:
                state,message='unavailable','Device detected, but the USB connection could not be opened. Reconnect, then retry.'
                import logging
                logging.getLogger('GoldenNugget.readiness').debug('Paired connection check failed: %s',type(error).__name__)
        finally:
            self._loop=None
            self._task=None
        if not self.isInterruptionRequested():
            self.result.emit(self.udid,state,message)
