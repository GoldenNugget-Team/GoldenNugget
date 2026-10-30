"""Lock-screen preview dialog for a .tendies file.

Renders the tendie's wallpaper (extracted and decoded locally by
``tendie_preview``) inside an iPhone ``PhoneFrame``. When nothing decodable
exists inside the file itself — container-type tendies, or HEIC-only art on a
platform without a HEIF plugin — a matching catalog preview (already cached
by the PosterBoard cards, or fetched in the background) is shown instead.
"""

import os

from PySide6.QtCore import Qt, QUrl, QCoreApplication, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src.gui.ios.phone_frame import (
    DEVICE_PT_H, DEVICE_PT_W, PhoneFrame,
)
from src.gui.theme import ColorThemeManager, t

_MAX_EDGE = 2556  # downscale wallpapers to the iPhone 15 native long edge


class TendiePreviewDialog(QDialog):

    def __init__(self, tendie, parent=None):
        super().__init__(parent)
        self._tendie = tendie
        self._reply = None
        self._nam = QNetworkAccessManager(self)
        self._dark = False
        self._closed = False

        self.setWindowTitle(QCoreApplication.translate(
            "Nugget", "Lock Screen Preview"))
        self.setModal(True)

        # Size the phone to the real iPhone 15 (393x852 pt), fitted to the
        # screen when the desktop is not tall enough for the whole device.
        screen = QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen else 900
        fit = max(0.4, min(1.0, (avail_h - 180) / float(DEVICE_PT_H)))
        frame_w = max(240, round(DEVICE_PT_W * fit))
        frame_h = max(500, round(DEVICE_PT_H * fit))
        self.setMinimumWidth(frame_w + 48)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._frame = PhoneFrame()
        self._frame.setFixedSize(frame_w, frame_h)
        layout.addWidget(self._frame, 0, Qt.AlignmentFlag.AlignHCenter)

        c = ColorThemeManager.instance().colors
        self._hint = QLabel(QCoreApplication.translate(
            "Nugget", "Loading preview..."))
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 12px; background: transparent;")
        layout.addWidget(self._hint)

        self._variant_btn = QPushButton()
        self._variant_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._variant_btn.setStyleSheet(
            f"QPushButton {{ background-color: {c.border}; color: {c.text_inverse}; "
            "border: none; border-radius: 12px; padding: 10px 24px; "
            "font-size: 14px; }"
            f"QPushButton:hover {{ background-color: {c.scrollbar_pressed}; }}")
        self._variant_btn.clicked.connect(self._toggle_appearance)
        self._variant_btn.hide()
        layout.addWidget(self._variant_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"))
        self._close_btn = close_btn
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {c.border}; color: {c.text_inverse}; "
            "border: none; border-radius: 12px; padding: 10px 24px; "
            "font-size: 14px; }"
            f"QPushButton:hover {{ background-color: {c.scrollbar_pressed}; }}")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._retheme()
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._tendie_bundle = None
        QTimer.singleShot(0, self._load)

    def _retheme(self):
        self.setStyleSheet(t('confirm_dialog'))
        self._hint.setStyleSheet(t('home_subtitle'))
        self._variant_btn.setStyleSheet(t('mini_button'))
        self._close_btn.setStyleSheet(t('mini_button'))

    # ---- loading -------------------------------------------------------

    def _appearance_host(self):
        """Scene that carries the Light/Dark appearance states, if any."""
        from src.controllers.ca import bundle_has_appearance_variants
        bundle = self._tendie_bundle
        if bundle is None or not bundle_has_appearance_variants(bundle):
            return None
        for doc in (bundle.background, bundle.wallpaper, bundle.floating):
            if doc is not None and doc.states and any(
                    "Light" in str(s) for s in doc.states) and any(
                    "Dark" in str(s) for s in doc.states):
                return doc
        return None

    def _set_appearance_button(self, host):
        if host is None:
            self._variant_btn.hide()
            return
        label = (QCoreApplication.translate("Nugget", "Dark variant")
                 if not self._dark
                 else QCoreApplication.translate("Nugget", "Light variant"))
        self._variant_btn.setText(label)
        self._variant_btn.show()

    def _toggle_appearance(self):
        self._dark = not self._dark
        if not self._setup_ca():
            self._variant_btn.hide()

    def _setup_ca(self) -> bool:
        """Render the preferred (or composited) scene, honouring the selected
        Light/Dark appearance. Returns True when a scene rendered."""
        try:
            from src.controllers.ca import (
                appearance_variant_state, document_loop_duration, home_state,
                preview_renderer, state_transition_spec,
            )
            from src.controllers.ca.tendie import preferred_scene
            bundle = self._tendie_bundle
            if bundle is None:
                return False
            doc, key = preferred_scene(bundle)
            if doc is None:
                return False
            root = doc.root
            scene_w = root.size.w if root else 390.0
            scene_h = root.size.h if root else 844.0
            dev_w, dev_h = self._frame.device_pixel_size()
            k = max(dev_w / max(scene_w, 1.0), dev_h / max(scene_h, 1.0))
            render_size = (max(1, int(scene_w * k)), max(1, int(scene_h * k)))
            host = self._appearance_host()
            if host is not None:
                eff = appearance_variant_state(
                    host, "Locked", self._dark) or "Locked"
            else:
                eff = "Locked"
            bg_state = eff if (key == "floating" and bundle.background is not None) else None
            loop = document_loop_duration(doc)
            renderer = preview_renderer(bundle, key, size=render_size,
                                        state=eff, bg_state=bg_state)
            home_renderer = None
            home = home_state(doc)
            if home is not None:
                home_renderer = preview_renderer(bundle, key, size=render_size,
                                                 state=home, bg_state=bg_state)
            self._set_appearance_button(host)
            if loop > 0.5:
                self._frame.set_ca_scene(
                    renderer, loop, home_renderer=home_renderer)
                self._hint.setText(QCoreApplication.translate(
                    "Nugget",
                    "Playing the tendie's Core Animation scene. "
                    "Swipe up to unlock."))
            else:
                transition = state_transition_spec(doc)
                if transition:
                    self._frame.set_ca_transition(renderer, transition)
                    self._hint.setText(QCoreApplication.translate(
                        "Nugget", "Swipe up to unlock."))
                else:
                    self._frame.set_ca_scene(renderer, 0.0)
                    self._hint.setText(QCoreApplication.translate(
                        "Nugget",
                        "Rendered from the tendie's Core Animation scene."))
            return True
        except Exception:
            return False

    def _load(self):
        """Prefer a live CAML scene render, then bitmap extraction, then the
        catalog preview."""
        from src.gui.dialogs.file_task import start_file_task
        tendie_path = self._tendie.path

        def load():
            from src.controllers.ca.tendie import load_tendie
            from src.controllers.tendie_preview import extract_tendie_preview
            bundle = load_tendie(tendie_path)
            # Avoid extracting the fallback when a valid scene exists.
            if bundle is not None and any((bundle.floating, bundle.wallpaper, bundle.background)):
                return bundle, None
            return bundle, extract_tendie_preview(tendie_path)

        self._load_task = start_file_task(self, load, self._loaded, lambda _: self._loaded((None, None)))

    def _loaded(self, result):
        if self._closed:
            return
        self._tendie_bundle, path = result
        # Only set up CA if the dialog is still open
        if self._setup_ca():
            return
        if self._tendie_bundle is not None and path is None:
            from src.gui.dialogs.file_task import start_file_task
            from src.controllers.tendie_preview import extract_tendie_preview
            tendie_path = self._tendie.path
            self._load_task = start_file_task(self, lambda: extract_tendie_preview(tendie_path),
                            lambda fallback: self._loaded((None, fallback)),
                            lambda _: self._loaded((None, None)))
            return
        if path and os.path.exists(path):
            self._apply_image(path, local=True)
            return

        try:
            from src.controllers.wallpaper_api import (
                find_wallpaper_by_name, cached_preview_path,
            )
            wallpaper = find_wallpaper_by_name(self._tendie.name)
        except Exception:
            wallpaper = None
        if wallpaper is None:
            self._show_placeholder()
            return
        cached = cached_preview_path(wallpaper.preview_url)
        if os.path.exists(cached):
            self._apply_image(cached, local=False)
            return
        self._hint.setText(QCoreApplication.translate(
            "Nugget",
            "Wallpaper not found in the file on this device, fetching a "
            "reference preview..."))
        self._reply = self._nam.get(
            QNetworkRequest(QUrl(wallpaper.preview_url)))
        self._reply.finished.connect(self._on_fetch_done)

    def _on_fetch_done(self):
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        ok = reply.error() == QNetworkReply.NetworkError.NoError and data
        url = reply.url().toString()
        reply.deleteLater()
        if not ok:
            self._show_placeholder()
            return
        try:
            from src.controllers.wallpaper_api import cached_preview_path
            path = cached_preview_path(url)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            self._show_placeholder()
            return
        self._apply_image(path, local=False)

    def _apply_image(self, path, local):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._show_placeholder()
            return
        long_edge = max(pixmap.width(), pixmap.height())
        if long_edge > _MAX_EDGE:
            scale = _MAX_EDGE / long_edge
            pixmap = pixmap.scaled(
                max(1, int(pixmap.width() * scale)),
                max(1, int(pixmap.height() * scale)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self._frame.set_wallpaper(pixmap)
        if local:
            self._hint.setText(QCoreApplication.translate(
                "Nugget",
                "Pre-rendered from the tendie file on this device."))
        else:
            self._hint.setText(QCoreApplication.translate(
                "Nugget",
                "Reference preview from the wallpaper gallery."))

    def _show_placeholder(self):
        self._frame.set_placeholder(QCoreApplication.translate(
            "Nugget",
            "No wallpaper image could be decoded from this file."))
        self._hint.setText(QCoreApplication.translate(
            "Nugget",
            "This tendie bundles device layout data only, or its art uses a "
            "format unavailable on this system."))

    # ---- lifecycle ------------------------------------------------------

    def closeEvent(self, event):
        self._closed = True
        # Stop any running Core Animation
        if hasattr(self, '_frame') and self._frame is not None:
            # Stop the timer to prevent it from firing after close
            self._frame._stop_ca()
        task = getattr(self, '_load_task', None)
        if task is not None:
            task.cancel()
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        super().closeEvent(event)

    def reject(self):
        self._closed = True
        task = getattr(self, '_load_task', None)
        if task is not None:
            task.cancel()
        if self._reply is not None:
            self._reply.abort()
            self._reply = None
        super().reject()
