"""Read-only device-provided Home Screen preview for the selected USB device."""
import asyncio
import logging
import time

from PySide6.QtCore import QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

from src.devicemanagement.device_capabilities import device_kind, has_dynamic_island


def _items(value):
    if isinstance(value, list):
        return [item for group in value for item in _items(group)]
    return [value] if isinstance(value, dict) else []


class PreviewWorker(QThread):
    ready = Signal(str, object)

    def __init__(self, udid, parent=None):
        super().__init__(parent)
        self.udid = udid
        self._payload = None
        self._loop = None
        self._task = None

    def cancel(self):
        self.requestInterruption()
        loop, task = self._loop, self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                return

    async def _run_fetch(self):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        if self.isInterruptionRequested():
            return None
        return await asyncio.wait_for(self._fetch(), 8)

    def run(self):
        try:
            payload = asyncio.run(self._run_fetch())
            if not self.isInterruptionRequested():
                self.ready.emit(self.udid, payload)
        except asyncio.CancelledError:
            return
        except Exception:
            logging.getLogger('GoldenNugget.device_preview').debug('Device preview unavailable', exc_info=True)
            if self._payload and not self.isInterruptionRequested():
                self.ready.emit(self.udid, self._payload)
        finally:
            self._loop = None
            self._task = None

    async def _fetch(self):
        from pymobiledevice3.services.springboard import SpringBoardServicesService

        from src.devicemanagement.session import lockdown_session
        async with lockdown_session(self.udid, autopair=False, connection_type="USB") as lockdown:
            async with SpringBoardServicesService(lockdown) as service:
                try:
                    preview = await asyncio.wait_for(service.get_wallpaper_preview_image('homescreen'), 3)
                    if preview:
                        return {'native_preview': preview}
                except Exception:
                    pass
        return await self._fetch_legacy()

    async def _fetch_legacy(self):
        from pymobiledevice3.services.springboard import SpringBoardServicesService

        from src.devicemanagement.session import lockdown_session
        async with lockdown_session(self.udid, autopair=False, connection_type="USB") as lockdown:
            async with SpringBoardServicesService(lockdown) as service:
                state = await service.get_icon_state()
                if not isinstance(state, list) or not state:
                    return None
                dock = _items(state[0])[:4]
                page = _items(state[1])[:24] if len(state) > 1 else []
                images = {}
                self._payload = {'wallpaper': None, 'page': page, 'dock': dock, 'images': images}
                for item in page + dock:
                    if self.isInterruptionRequested():
                        return None
                    identifier = item.get('displayIdentifier')
                    if not isinstance(identifier, str) or identifier in images:
                        continue
                    try:
                        images[identifier] = await asyncio.wait_for(service.get_icon_pngdata(identifier), 1)
                    except Exception:
                        break
                if not self.isInterruptionRequested():
                    try:
                        self._payload['wallpaper'] = await asyncio.wait_for(service.get_wallpaper_pngdata(), 2)
                    except Exception:
                        pass
                return self._payload


def render_tablet(payload):
    native = QPixmap()
    if payload.get('native_preview'):
        native.loadFromData(payload['native_preview'])
    landscape = not native.isNull() and native.width() > native.height()
    width, height = (420, 310) if landscape else (310, 420)
    if not native.isNull():
        height = round((width - 24) * native.height() / native.width()) + 24
    image = QPixmap(width + 8, height)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor('#67676b'))
    painter.setBrush(QColor('#1c1c1e'))
    painter.translate(4, 0)
    for button in (QRectF(width - 1, 48, 4, 30), QRectF(width - 1, 88, 4, 30)):
        painter.drawRoundedRect(button, 2, 2)
    painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 24, 24)
    screen = QRectF(12, 12, width - 24, height - 24)
    path = QPainterPath()
    path.addRoundedRect(screen, 14, 14)
    painter.setClipPath(path)
    painter.fillRect(screen, QColor('#101114'))
    if not native.isNull():
        painter.drawPixmap(12, 12, native.scaled(width - 24, height - 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    painter.setClipping(False)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#45454a'))
    painter.drawEllipse(QRectF(width / 2 - 2, 3, 4, 4))
    painter.end()
    return image


def render_phone(payload, model, disconnected=False):
    if device_kind(model) == 'iPad':
        return render_tablet(payload)
    image = QPixmap(268, 540)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor('#67676b'))
    painter.setBrush(QColor('#1c1c1e'))
    painter.translate(4, 0)
    for button in (QRectF(-3, 104, 4, 42), QRectF(-3, 159, 4, 42), QRectF(259, 124, 4, 64)):
        painter.drawRoundedRect(button, 2, 2)
    painter.drawRoundedRect(QRectF(1, 1, 258, 538), 38, 38)
    screen = QRectF(8, 8, 244, 524)
    clip = QPainterPath()
    clip.addRoundedRect(screen, 32, 32)
    painter.save()
    painter.setClipPath(clip)
    if disconnected:
        painter.fillRect(screen,Qt.black)
        painter.setPen(QColor('#d5d5d7'))
        font=QFont()
        font.setPixelSize(21)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.drawText(screen.adjusted(20,0,-20,0),
                         Qt.AlignCenter|Qt.TextWordWrap,'No Phone Connected')
        painter.restore()
        painter.end()
        return image
    painter.fillRect(screen, QColor('#101114'))
    wallpaper = QPixmap()
    if payload.get('wallpaper'):
        wallpaper.loadFromData(payload['wallpaper'])
    if not wallpaper.isNull():
        scaled = wallpaper.scaled(244, 524, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.drawPixmap(8 - (scaled.width() - 244) // 2, 8 - (scaled.height() - 524) // 2, scaled)
    native = QPixmap()
    if payload.get("native_preview"):
        native.loadFromData(payload["native_preview"])
    if not native.isNull():
        painter.drawPixmap(8, 8, native.scaled(244, 524, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    images = {}
    for identifier, data in payload.get('images', {}).items():
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            images[identifier] = pixmap
    for dock, items in ((False, payload.get('page', [])), (True, payload.get('dock', []))):
        if dock:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(220, 220, 230, 55))
            painter.drawRoundedRect(QRectF(18, 456, 224, 58), 20, 20)
        for index, item in enumerate(items):
            pixmap = images.get(item.get('displayIdentifier'))
            if pixmap is None:
                continue
            x = 26 + (index % 4) * 56
            y = 464 if dock else 62 + (index // 4) * 61
            painter.save()
            icon_clip = QPainterPath()
            icon_clip.addRoundedRect(QRectF(x, y, 40, 40), 10, 10)
            painter.setClipPath(icon_clip)
            painter.drawPixmap(x, y, pixmap.scaled(40, 40, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            painter.restore()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#050505'))
    if has_dynamic_island(model):
        painter.drawRoundedRect(QRectF(94, 17, 72, 20), 10, 10)
    else:
        painter.drawRoundedRect(QRectF(88, 8, 84, 22), 10, 10)
    painter.setBrush(QColor(240, 240, 245, 190))
    painter.drawRoundedRect(QRectF(92, 521, 76, 3), 1.5, 1.5)
    painter.restore()
    painter.end()
    return image


class DevicePreview(QLabel):
    preview_changed = Signal(object)

    def __init__(self, window, parent=None, scale=1.0):
        super().__init__(parent)
        self.window = window
        self._scale = scale
        self._udid = ''
        self._model = ''
        self._worker = None
        self._workers = {}
        self._cache = {}
        self._image = None
        self._native = False
        self._attempts = 0
        self._stopping = False
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start)
        self.setFixedSize(round(82 * self._scale), round(130 * self._scale))
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName(self.tr('Connected device preview'))
        self._fallback()
        self.hide()

    def _preview_size(self):
        width = 104 if device_kind(self._model) == 'iPad' else 64
        return QSize(round(width * self._scale), round(126 * self._scale))

    def _fallback(self):
        self._image = None
        self.preview_changed.emit(None)
        icon = QIcon(render_phone({}, self._model))
        self.setPixmap(icon.pixmap(self._preview_size()))
        self.setStyleSheet('background: transparent; border: none; padding: 0;')

    def set_device(self, udid, model):
        udid = udid or ''
        self.setVisible(bool(udid))
        if udid == self._udid and model == self._model:
            if self._image is None and self._worker is None and not self._retry_timer.isActive() and self._attempts < 3:
                self._retry_timer.start(0)
            return
        self._retry_timer.stop()
        self._attempts = 0
        self._udid, self._model = udid, model
        self.setFixedSize(round((112 if device_kind(model) == 'iPad' else 82) * self._scale), round(134 * self._scale))
        self._fallback()
        cached = self._cache.get(udid)
        if cached and cached[0] == model:
            self._image, self._native = cached[1:]
            self._show_image()
        self.setEnabled(bool(udid))
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._start()

    def refresh(self):
        self._attempts = 0
        self._retry_timer.stop()
        if self._worker is None:
            self._start()

    def _start(self):
        if self._stopping or self._worker is not None or not self._udid:
            return
        if getattr(self.window, 'apply_in_progress', False) or getattr(self.window, '_cache_restore_in_progress', False):
            self._retry_timer.start(1500)
            return
        existing = self._workers.get(self._udid)
        if existing is not None:
            self._worker = existing
            return
        self._attempts += 1
        self._worker = PreviewWorker(self._udid, self)
        self._workers[self._udid] = self._worker
        self._worker.ready.connect(self._loaded)
        self._worker.finished.connect(self._finished)
        self._worker.start()

    def _loaded(self, udid, payload):
        worker = self.sender()
        if worker is not self._worker or worker.isInterruptionRequested():
            return
        if udid != self._udid or not payload or not (payload.get("native_preview") or payload.get("wallpaper") or any(payload.get("images", {}).values())):
            return
        self._native = bool(payload.get("native_preview"))
        self._image = render_phone(payload, self._model)
        self._cache[udid] = (self._model, self._image, self._native)
        self._show_image()

    def _show_image(self):
        size = self._preview_size()
        self.setPixmap(self._image.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.preview_changed.emit(self._image)

    def _finished(self):
        previous = self.sender()
        if self._workers.get(previous.udid) is previous:
            del self._workers[previous.udid]
        if previous is not self._worker:
            previous.deleteLater()
            return
        self._worker = None
        restart = previous.udid != self._udid or previous.isInterruptionRequested()
        previous.deleteLater()
        if self._stopping or not self._udid:
            return
        if restart:
            self._retry_timer.start(0)
        elif self._image is None and self._attempts < 3:
            self._retry_timer.start(1000 * self._attempts)

    def stop(self):
        self._stopping = True
        self._retry_timer.stop()
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        deadline = time.monotonic() + 9
        return all(worker.wait(max(0, int((deadline - time.monotonic()) * 1000)))
                   for worker in workers)
