"""Online icon-pack downloader dialog for the Icon Themes page.

Port of Cowabunga's ``CowabungaAPI`` + ``ThemesExploreView``: fetches
``icon-themes.json`` from the leminlimez/Cowabunga-explore-repo, shows the
available packs with previews, and downloads + imports the chosen one into
the ``IconThemesTweak`` immediately (so it shows on the page ready for Apply),
exactly like the wallpaper downloader does for ``.tendies``.

All network traffic runs through ``QNetworkAccessManager`` so the UI stays
responsive and there are no background ``QThread`` lifetime issues.
"""

import os
import tempfile
from collections import deque

from PySide6.QtCore import QCoreApplication, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.controllers.icon_themes_api import (
    DownloadableTheme,
    catalog_url,
    parse_catalog,
)
from src.gui.dialogs.confirmation import ask_confirmation
from src.gui.theme import ColorThemeManager
from src.tweaks.tweaks import TweakID, tweaks

CARD_W = 180
CARD_H = 250
PREVIEW_H = 130

# preview downloads run a few at a time so long grids can't pile up requests
PREVIEW_CONCURRENCY = 4


class _ThemeCard(QFrame):
    """A downloadable pack entry: preview + name + author/version."""

    def __init__(self, theme: DownloadableTheme, on_click, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("iconPackCard")
        self.setFixedSize(CARD_W, CARD_H)
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.preview_lbl = QLabel(self)
        self.preview_lbl.setObjectName("ipPreview")
        self.preview_lbl.setFixedHeight(PREVIEW_H)
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setText(QCoreApplication.translate("Nugget", "Loading..."))
        self.preview_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.preview_lbl)

        name = QLabel(theme.name, self)
        name.setObjectName("ipName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(name)

        meta_parts = [theme.author, theme.version]
        meta = [m for m in meta_parts if m]
        meta_lbl = QLabel(" · ".join(meta) or " ", self)
        meta_lbl.setObjectName("ipMeta")
        meta_lbl.setAlignment(Qt.AlignCenter)
        meta_lbl.setWordWrap(True)
        meta_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(meta_lbl)

        if theme.description:
            desc = QLabel(theme.description, self)
            desc.setObjectName("ipDesc")
            desc.setWordWrap(True)
            desc.setAlignment(Qt.AlignCenter)
            desc.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(desc)
        layout.addStretch()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._on_click is not None):
            self._on_click(self)
        super().mouseReleaseEvent(event)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QFrame#iconPackCard {{
                background-color: {c.bg_secondary};
                border-radius: 12px;
                border: none;
            }}
            QFrame#iconPackCard:hover {{ background-color: {c.surface_hover}; }}
            QLabel#ipPreview {{
                background-color: {c.bg_tertiary};
                border-radius: 8px;
                color: {c.text_disabled};
                font-size: 13px;
            }}
            QLabel#ipName {{ color: {c.text_primary}; font-size: 14px; font-weight: 600; }}
            QLabel#ipMeta {{ color: {c.text_secondary}; font-size: 11px; }}
            QLabel#ipDesc {{ color: {c.text_secondary}; font-size: 11px; }}
        """)

    def set_preview(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                CARD_W - 16, PREVIEW_H, Qt.KeepAspectRatio,
                Qt.SmoothTransformation)
            self.preview_lbl.setPixmap(scaled)
            return
        self.preview_lbl.setText("\U0001F5BC\ufe0f")


class IconPackDownloaderDialog(QDialog):
    """Browse + download icon packs from the Cowabunga explore repo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Download Icon Packs"))
        self.setModal(True)
        self.resize(760, 560)

        # themes that got imported by this dialog session
        self.added_bundle_ids: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.status_lbl = QLabel(
            QCoreApplication.translate("Nugget", "Loading icon packs..."), self)
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.scroll.setWidget(self.grid_host)
        layout.addWidget(self.scroll, 1)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"), self)
        close_btn.setObjectName("ipCloseBtn")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._nam = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self._nam)
        cache.setCacheDirectory(os.path.join(QStandardPaths.writableLocation(QStandardPaths.CacheLocation), "icon_previews"))
        cache.setMaximumCacheSize(64 * 1024 * 1024)
        self._nam.setCache(cache)
        self._catalog_reply = None
        self._preview_replies = []
        self._preview_queue = deque()
        self._themes = []
        self._card_indices = {}
        self._updating_visible = False
        self._download_file = None
        self._download_error = None
        self.scroll.verticalScrollBar().valueChanged.connect(self._update_visible_cards)
        self._download_reply = None
        self._downloading_theme = None
        self._downloading = False

        self._cards = []
        self._retheme()
        self._fetch_catalog()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; }}
            QScrollArea {{ background: transparent; border: none; }}
            QPushButton#ipCloseBtn {{
                background-color: {c.accent};
                border: none;
                border-radius: 10px;
                color: {c.text_inverse};
                font-size: 14px;
                padding: 10px 20px;
            }}
            QPushButton#ipCloseBtn:hover {{ background-color: {c.accent_hover}; }}
        """)
        for card in self._cards:
            card._retheme()

    # --- catalog ---

    def _fetch_catalog(self):
        url = QUrl(catalog_url())
        self._catalog_reply = self._nam.get(QNetworkRequest(url))
        self._catalog_reply.finished.connect(self._on_catalog_reply)

    def _on_catalog_reply(self):
        reply = self._catalog_reply
        self._catalog_reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError or not data:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget",
                "Could not load icon packs.\nCheck your internet connection and try again."))
            return
        try:
            themes = parse_catalog(data)
        except Exception as e:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Could not load icon packs: {0}").format(e))
            return
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "{0} icon packs available — tap one to download it.").format(len(themes)))
        self._populate(themes)

    def _populate(self, themes):
        self._themes = list(themes)
        self._preview_queue.clear()
        for card in self._cards:
            card.deleteLater()
        self._cards = []
        self._card_indices = {}
        for reply, _ in list(self._preview_replies):
            reply.abort()
        if not self._themes:
            self.grid_host.setMinimumHeight(0)
        self._update_visible_cards()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_visible_cards)

    def _update_visible_cards(self, *_):
        if not getattr(self, "_themes", None) or self._updating_visible:
            return
        self._updating_visible = True
        try:
            viewport = self.scroll.viewport()
            cols = max(1, (viewport.width() - 8) // (CARD_W + 10))
            rows = (len(self._themes) + cols - 1) // cols
            row_height = CARD_H + 10
            self.grid_host.setMinimumHeight(rows * row_height + 8)
            start_row = max(0, self.scroll.verticalScrollBar().value() // row_height - 1)
            end_row = min(rows, (self.scroll.verticalScrollBar().value() + viewport.height()) // row_height + 3)
            wanted = set(range(start_row * cols, min(len(self._themes), end_row * cols)))
            self._preview_queue = deque(card for card in self._preview_queue
                                        if card in self._cards and self._card_indices.get(card) in wanted)
            for card in list(self._cards):
                if self._card_indices[card] not in wanted:
                    self._cards.remove(card)
                    self._card_indices.pop(card)
                    for reply, owner in list(self._preview_replies):
                        if owner is card:
                            reply.abort()
                    card.deleteLater()
            present = set(self._card_indices.values())
            for index in sorted(wanted):
                if index not in present:
                    card = _ThemeCard(self._themes[index], self._on_card_click, self.grid_host)
                    self._cards.append(card)
                    self._card_indices[card] = index
                    self._enqueue_preview(card)
            for card, index in self._card_indices.items():
                card.move(4 + index % cols * (CARD_W + 10), 4 + index // cols * row_height)
                card.show()
        finally:
            self._updating_visible = False
        self._drain_preview_queue()

    # --- previews ---

    def _enqueue_preview(self, card):
        self._preview_queue.append(card)
        self._drain_preview_queue()

    def _drain_preview_queue(self):
        while self._preview_queue and len(self._preview_replies) < PREVIEW_CONCURRENCY:
            card = self._preview_queue.popleft()
            if card not in self._cards:
                continue
            request = QNetworkRequest(QUrl(card.theme.preview_url))
            request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                                 QNetworkRequest.CacheLoadControl.PreferCache)
            reply = self._nam.get(request)
            self._preview_replies.append((reply, card))
            reply.finished.connect(lambda r=reply, c=card: self._on_preview_reply(r, c))

    def _on_preview_reply(self, reply, card):
        if (reply, card) in self._preview_replies:
            self._preview_replies.remove((reply, card))
        data = bytes(reply.readAll())
        reply.deleteLater()
        if data and card in self._cards:
            card.set_preview(data)
        self._drain_preview_queue()

    # --- download + import ---

    def _on_card_click(self, card):
        if self._downloading:
            return
        theme = card.theme
        confirmed = ask_confirmation(
            self,
            QCoreApplication.translate("Nugget", "Download Icon Pack"),
            QCoreApplication.translate("Nugget", "{0}\n\nAuthor: {1}").format(
                theme.description or QCoreApplication.translate(
                    "Nugget", "Add this pack to your icon theme collection."),
                theme.author or QCoreApplication.translate("Nugget", "Unknown")),
            confirm_text=QCoreApplication.translate("Nugget", "Download"),
            icon=":/icon/brush.svg", subject=theme.name)
        if not confirmed:
            return
        self._download_theme(theme)

    def _download_theme(self, theme):
        self._downloading = True
        self._downloading_theme = theme
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Downloading \"{0}\"...").format(theme.name))
        self._download_error = None
        self._download_file = tempfile.NamedTemporaryFile(prefix="icontheme_dl_", suffix=".zip", delete=False)
        self._download_reply = self._nam.get(QNetworkRequest(QUrl(theme.download_url)))
        self._download_reply.readyRead.connect(self._drain_download)
        self._download_reply.finished.connect(self._on_download_reply)

    def _drain_download(self):
        if self._download_reply is None or self._download_file is None:
            return
        try:
            self._download_file.write(bytes(self._download_reply.readAll()))
        except OSError as error:
            self._download_error = error
            self._download_reply.abort()

    def _on_download_reply(self):
        reply = self._download_reply
        if reply is None:
            return
        self._drain_download()
        self._download_reply = None
        output, self._download_file = self._download_file, None
        theme, self._downloading_theme = self._downloading_theme, None
        error = reply.error()
        reply.deleteLater()
        self._downloading = False
        if output is None:
            return
        path = output.name
        try:
            output.close()
            if error != QNetworkReply.NetworkError.NoError or self._download_error is not None:
                raise self._download_error or RuntimeError("Download failed")
            from src.gui.dialogs.file_task import run_file_task
            tweak = tweaks[TweakID.IconThemes]
            added, skipped = run_file_task(self,
                QCoreApplication.translate("Nugget", "Import Icon Pack"),
                lambda: tweak.import_pack_zip(path, theme_name=theme.name if theme else None))
            if added == 0:
                raise RuntimeError("no icons found in archive")
            tweak.set_enabled(True)
        except Exception as exc:
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Could not import \"{0}\": {1}").format(theme.name if theme else "", exc))
            return
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        self.added_bundle_ids.extend([theme.name] * added)
        msg = QCoreApplication.translate("Nugget", "Imported {0} icons from \"{1}\".").format(added, theme.name if theme else "")
        if skipped:
            msg += " " + QCoreApplication.translate("Nugget", "({0} bundles skipped — missing icon files).").format(len(skipped))
        self.status_lbl.setText(msg)

    def done(self, result):
        if self._download_reply is not None:
            self._download_error = RuntimeError("Download cancelled")
            self._download_reply.abort()
        super().done(result)
