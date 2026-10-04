"""Wallpaper downloader dialog for the PosterBoard page.

Lets the user browse and download wallpapers from Cowabunga and
CaPlayground. Clicking a wallpaper downloads the ``.tendies`` file and
imports it into the PosterBoard tweak immediately, so it shows up on the
Tendies tab ready for Apply.

Everything (catalog fetch, preview images, and the .tendies download) runs
through ``QNetworkAccessManager`` so the UI stays responsive and there are
no background ``QThread`` lifetime issues.
"""

import hashlib
import os
import time
import uuid

from PySide6.QtCore import Qt, QCoreApplication, QTimer, QUrl, QStandardPaths, QByteArray, QSize
from PySide6.QtGui import QPixmap, QMovie
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QScrollArea, QGridLayout, QPushButton, QWidget, QMessageBox,
    QProgressBar, QFrame,
)

from src.tweaks.tweaks import tweaks, TweakID
from src.gui.theme import ColorThemeManager


CARD_W = 150
CARD_H = 300
PREVIEW_H = 200

CATALOG_TTL = 15 * 60

# max concurrent preview downloads; everything past this waits in a queue so
# fast long scrolls can't pile up hundreds of background image requests
PREVIEW_CONCURRENCY = 10


class _WallpaperCard(QFrame):
    """A single wallpaper entry: preview + name + author, click to download."""

    def __init__(self, wallpaper, on_click, parent=None):
        super().__init__(parent)
        self.wallpaper = wallpaper
        self._on_click_cb = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("wallpaperCard")
        self._retheme()
        self.setFixedSize(CARD_W, CARD_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.preview_lbl = QLabel(self)
        self.preview_lbl.setObjectName("wpPreview")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setFixedHeight(PREVIEW_H)
        layout.addWidget(self.preview_lbl)
        self._set_loading()
        self._preview_movie = None
        self._preview_path = None
        self.preview_state = "none"
        self._playback_suppressed = False

        name = QLabel(wallpaper.name, self)
        name.setObjectName("wpName")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignCenter)
        name.setMaximumHeight(36)
        layout.addWidget(name)

        author = QLabel(wallpaper.author or " ", self)
        author.setObjectName("wpAuthor")
        author.setAlignment(Qt.AlignCenter)
        author.setWordWrap(True)
        author.setMaximumHeight(28)
        layout.addWidget(author)

        layout.addStretch()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QFrame#wallpaperCard {{
                background-color: {c.bg_secondary};
                border-radius: 12px;
                border: none;
            }}
            QFrame#wallpaperCard:hover {{ background-color: {c.surface_hover}; }}
            QLabel#wpName {{ color: {c.text_primary}; font-size: 13px; font-weight: 600; }}
            QLabel#wpAuthor {{ color: {c.text_secondary}; font-size: 11px; }}
            QLabel#wpPreview {{ background-color: {c.bg_tertiary}; border-radius: 8px; }}
        """)

    def _set_loading(self):
        c = ColorThemeManager.instance().colors
        self.preview_lbl.setText(QCoreApplication.translate("Nugget", "Loading..."))
        self.preview_lbl.setStyleSheet(
            f"background-color: {c.bg_tertiary}; border-radius: 8px;"
            f"font-size: 13px; color: {c.text_disabled};"
        )

    def _set_placeholder(self):
        c = ColorThemeManager.instance().colors
        self.preview_lbl.setText("\U0001F5BC\ufe0f")
        self.preview_lbl.setStyleSheet(
            f"background-color: {c.bg_tertiary}; border-radius: 8px;"
            f"font-size: 34px; color: {c.border};"
        )

    def set_preview_file(self, path):
        """Show a cached preview from disk. Animated GIFs run via ``QMovie``
        from the file (no raw bytes kept around); playback is suppressed
        while the dialog is busy downloading, e.g. a .tendies."""
        if not path or self.preview_state in ("ready", "failed"):
            return
        movie = QMovie(path, QByteArray())
        if movie.isValid():
            self.preview_state = "ready"
            self._preview_movie = movie
            self._preview_path = path
            box = QSize(CARD_W - 16, PREVIEW_H)

            def _fit_first_frame(*_):
                size = movie.frameRect().size()
                if not size.isEmpty():
                    try:
                        movie.setScaledSize(size.scaled(box, Qt.KeepAspectRatio))
                        movie.frameChanged.disconnect(_fit_first_frame)
                    except Exception:
                        pass

            movie.frameChanged.connect(_fit_first_frame)
            self.preview_lbl.setMovie(movie)
            if self.preview_lbl.isVisible():
                self.start_playback()
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.preview_state = "ready"
            self._preview_path = path
            self.preview_lbl.setPixmap(pixmap.scaled(
                CARD_W - 16, PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            return
        self.preview_state = "failed"
        self._set_placeholder()

    def start_playback(self):
        if self._playback_suppressed:
            return
        movie = self._preview_movie
        if movie is not None:
            try:
                movie.jumpToFrame(0)  # QMovie won't resume from a stopped EOF
            except Exception:
                pass
            movie.start()

    def stop_playback(self):
        movie = self._preview_movie
        if movie is not None:
            movie.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.start_playback()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.stop_playback()

    def mousePressEvent(self, event):
        if self._on_click_cb:
            self._on_click_cb(self.wallpaper)
        super().mousePressEvent(event)


class WallpaperDownloaderDialog(QDialog):
    """Browse + download wallpapers and import them into PosterBoard."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Download Wallpapers"))
        self.setModal(True)
        self.setFixedSize(760, 780)
        self._retheme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Top row: source picker + category + search
        top = QHBoxLayout()
        top.setSpacing(10)

        self.source_drp = QComboBox()
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "All"), "all")
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "Cowabunga"), "cowabunga")
        self.source_drp.addItem(QCoreApplication.translate("Nugget", "CaPlayground"), "caplayground")
        self.source_drp.currentIndexChanged.connect(self._on_source_changed)
        top.addWidget(self.source_drp)

        self.category_drp = QComboBox()
        self.category_drp.currentTextChanged.connect(self._on_category_changed)
        top.addWidget(self.category_drp)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(QCoreApplication.translate("Nugget", "Search wallpapers..."))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        top.addWidget(self.search_box, 1)

        layout.addLayout(top)

        # Status / progress area
        c = ColorThemeManager.instance().colors
        self.status_lbl = QLabel(QCoreApplication.translate("Nugget", "Loading..."))
        self.status_lbl.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px;")
        layout.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Grid scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._grid_host = QWidget()
        self.grid = QGridLayout(self._grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self._grid_host)
        self.scroll.verticalScrollBar().valueChanged.connect(
            lambda *_: self._schedule_window_update())
        layout.addWidget(self.scroll, 1)

        # Bottom close button
        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.accent};
                border-radius: 12px;
                color: {c.text_primary};
                font-size: 16px;
                font-weight: 600;
                padding: 12px;
                border: none;
            }}
            QPushButton:hover {{ background-color: {c.accent_hover}; }}
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._all_wallpapers = []
        self._visible_wallpapers = []
        self._cards = {}
        self._grid_cols = 1
        self._catalog_replies = []
        self._catalog_sources = set()
        self._merge_results = {}
        self._catalog_failed = {}
        self._fetch_gen = 0
        self._preview_replies = []
        self._preview_queue = []
        self._download_reply = None
        self._download_wallpaper = None
        self._busy = False
        self._window_state = None
        self._window_timer = None
        self._virtualized = True
        self._grid_total_rows = 0
        # one manager per dialog; alive as long as the dialog is
        self._nam = QNetworkAccessManager(self)

        from src.controllers.wallpaper_api import (
            CowabungaSource, CaPlaygroundSource,
        )
        self._sources = {
            "cowabunga": CowabungaSource(),
            "caplayground": CaPlaygroundSource(),
        }

        self._cache_root = self._init_cache()

        self._populate_categories()
        self._fetch_wallpapers()

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_elevated}; }}
            QLabel {{ color: {c.text_primary}; }}
            QComboBox {{
                background-color: {c.bg_secondary};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 10.5pt;
                padding: 8px 12px;
                min-height: 24px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {c.surface_hover};
                border: 1px solid {c.border};
                border-radius: 10px;
                color: {c.text_primary};
                selection-background-color: {c.accent};
            }}
            QLineEdit {{
                background-color: {c.bg_secondary};
                border: none;
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 14px;
                padding: 8px 12px;
            }}
            QScrollArea {{ background: transparent; border: none; }}
            QProgressBar {{
                background-color: {c.bg_secondary};
                border-radius: 4px;
                border: none;
                height: 7px;
                text-align: center;
            }}
            QProgressBar::chunk {{ background-color: {c.accent}; border-radius: 4px; }}
        """)

    # --- source / category handling ---

    def _populate_categories(self):
        self.category_drp.blockSignals(True)
        self.category_drp.clear()
        if self.source_drp.currentData() == "cowabunga":
            for cat in ("Custom", "Apple"):
                self.category_drp.addItem(QCoreApplication.translate("Nugget", cat))
        self.category_drp.setEnabled(self.source_drp.currentData() == "cowabunga")
        self.category_drp.blockSignals(False)

    def _on_source_changed(self, *_):
        self._populate_categories()
        self._fetch_wallpapers()

    def _on_category_changed(self, *_):
        self._fetch_wallpapers()

    # --- local cache ---

    def _init_cache(self):
        from src.controllers.wallpaper_api import wallpaper_cache_root
        return wallpaper_cache_root()

    def _hash_key(self, text):
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _catalog_cache_path(self, source_id, category):
        return os.path.join(
            self._cache_root, "catalog",
            f"{source_id}_{self._hash_key(category or '')}.json")

    def _read_catalog_cache(self, source_id, category):
        path = self._catalog_cache_path(source_id, category)
        try:
            if time.time() - os.path.getmtime(path) > CATALOG_TTL:
                return None
            with open(path, "r", encoding="utf-8") as f:
                return self._sources[source_id].parse(f.read())
        except Exception:
            return None

    def _write_catalog_cache(self, source_id, category, raw):
        try:
            with open(self._catalog_cache_path(source_id, category), "w",
                      encoding="utf-8") as f:
                f.write(raw)
        except OSError:
            pass

    def _preview_cache_path(self, url):
        from src.controllers.wallpaper_api import cached_preview_path
        return cached_preview_path(url)

    # --- catalog fetching (async via QNetworkAccessManager) ---

    def _fetch_wallpapers(self):
        self._abort_inflight()
        self._fetch_gen += 1
        gen = self._fetch_gen
        source_id = self.source_drp.currentData()
        category = self.category_drp.currentText() if source_id == "cowabunga" else ""

        self.status_lbl.setText(QCoreApplication.translate("Nugget", "Loading wallpapers..."))
        self.progress.setVisible(True)
        self._clear_cards()
        self._merge_results = {}
        self._catalog_failed = {}
        self._catalog_sources = set()

        targets = []
        if source_id == "all":
            # Dedup prefers cowabunga (already sorted by that name below).
            for sid in ("cowabunga", "caplayground"):
                targets.append((sid, "Custom" if sid == "cowabunga" else ""))
        elif source_id in self._sources:
            targets.append((source_id, category))
        else:
            targets.append(("cowabunga", category))

        for sid, cat in targets:
            try:
                url = self._sources[sid].fetch_url(cat)
            except Exception:
                continue
            cached = self._read_catalog_cache(sid, cat)
            if cached is not None:
                self._merge_results[sid] = cached
                self._catalog_sources.add(sid)
                continue
            self._request_catalog(url, sid, cat, gen)

        if self._catalog_sources and not self._catalog_replies:
            self._finish_catalog_load()
        elif not self._catalog_sources and not self._catalog_replies:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")

    def _request_catalog(self, url, source_id, category, gen):
        reply = self._nam.get(QNetworkRequest(QUrl(url)))
        self._catalog_replies.append((reply, source_id))
        reply.finished.connect(
            lambda r=reply, s=source_id, c=category, g=gen:
                self._on_catalog_reply(r, s, c, g))

    def _on_catalog_reply(self, reply, source_id, category, gen):
        if gen != self._fetch_gen:
            reply.deleteLater()
            return
        if reply in [r for r, _ in self._catalog_replies]:
            self._catalog_replies = [
                (r, s) for (r, s) in self._catalog_replies if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._catalog_failed[source_id] = reply.errorString()
        else:
            try:
                self._merge_results[source_id] = self._sources[source_id].parse(data)
                self._write_catalog_cache(source_id, category, data.decode("utf-8", "replace"))
                self._catalog_sources.add(source_id)
            except Exception as e:
                self._catalog_failed[source_id] = str(e)
        if self._catalog_replies:
            return
        if self._catalog_sources:
            self._finish_catalog_load()
        else:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")

    def _finish_catalog_load(self):
        self.progress.setVisible(False)
        if not self._merge_results:
            self._on_load_failed(
                "; ".join(str(v) for v in self._catalog_failed.values())
                or "unknown")
            return
        if self.source_drp.currentData() == "all":
            wallpapers = self._merge_dedupe()
        else:
            wallpapers = next(iter(self._merge_results.values()))
        self.status_lbl.setText(
            QCoreApplication.translate("Nugget", "{} wallpapers").format(len(wallpapers))
            if wallpapers else QCoreApplication.translate("Nugget", "No wallpapers found")
        )
        self._populate_grid(wallpapers)

    def _merge_dedupe(self) -> list:
        """Merge the all-source catalogs, dropping duplicate names.
        Cowabunga is merged first so it wins when both sources expose the
        same wallpaper (it is faster to serve and already localized)."""
        seen = set()
        merged = []
        for sid in ("cowabunga", "caplayground"):
            for wp in self._merge_results.get(sid, []):
                key = wp.name.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    merged.append(wp)
        return merged

    def _on_load_failed(self, message):
        self.progress.setVisible(False)
        self.status_lbl.setText(QCoreApplication.translate("Nugget", "Failed to load wallpapers"))
        self._show_error(
            QCoreApplication.translate("Nugget", "Failed to load wallpapers"), message)

    # --- grid (virtualized) ---

    def _clear_cards(self):
        for reply, card, path in self._preview_replies:
            reply.abort()
        self._preview_replies = []
        self._preview_queue = []
        for card in self._cards.values():
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = {}
        self._all_wallpapers = []
        self._visible_wallpapers = []
        self._window_state = None
        self._grid_total_rows = 0
        self._virtualized = True

    def _populate_grid(self, wallpapers):
        """Adopt a new catalog. Cards spawn progressively as they enter the
        viewport (+1 buffer row) but then stay materialized forever; only the
        *playback* of the previews is gated to the viewport window."""
        self._clear_cards()
        self._all_wallpapers = list(wallpapers)
        self._apply_search(self.search_box.text())

    def _apply_search(self, text):
        term = text.strip().lower()
        if not term:
            self._visible_wallpapers = list(self._all_wallpapers)
        else:
            self._visible_wallpapers = [
                w for w in self._all_wallpapers
                if term in w.name.lower() or term in w.author.lower()]
        self._rebuild_window()

    def _rebuild_window(self):
        self._virtualized = True
        self._window_state = None
        self._grid_total_rows = 0
        for card in self._cards.values():
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = {}
        self._update_visible_window()
        self._sync_playback()

    # --- scroll throttling ---

    def _schedule_window_update(self):
        """Coalesce the flurry of ``valueChanged`` signals from a fast scroll
        or glide into a single update once the scrolling settles."""
        if self._window_timer is None:
            self._window_timer = QTimer(self)
            self._window_timer.setSingleShot(True)
            self._window_timer.setInterval(60)
            self._window_timer.timeout.connect(self._on_window_update_timer)
        self._window_timer.start()

    def _on_window_update_timer(self):
        self._update_visible_window()
        self._sync_playback()

    def _update_visible_window(self):
        """Spawn the cards inside the viewport rows plus one spare row above
        and below. Cards are never torn down afterwards — they stay in place
        while scrolling through the catalog. Skips work when the row window
        has not actually moved."""
        if not self._virtualized:
            return
        wallpapers = self._visible_wallpapers
        if not wallpapers:
            self._grid_host.setMinimumHeight(0)
            self._window_state = None
            self._grid_total_rows = 0
            return
        total = len(wallpapers)
        cols = max(1, self.width() // (CARD_W + 16))
        self._grid_cols = cols
        row_h = CARD_H + self.grid.spacing()
        total_rows = (total + cols - 1) // cols

        # Pin the scrollable height up-front so the scrollbar range never
        # jumps while rows materialize during a scroll.
        host_h = total_rows * row_h + 4
        if self._grid_host.minimumHeight() != host_h:
            self._grid_host.setMinimumHeight(host_h)

        # Give every row a fixed height regardless of whether its cards are
        # materialized yet — otherwise the empty rows collapse and the grid
        # shows gaps/misaligned cards while scrolling.
        if self._grid_total_rows != total_rows:
            for r in range(self._grid_total_rows, total_rows):
                self.grid.setRowMinimumHeight(r, row_h)
            for r in range(total_rows, self._grid_total_rows):
                self.grid.setRowMinimumHeight(r, 0)
            self._grid_total_rows = total_rows

        vbar = self.scroll.verticalScrollBar()
        value = vbar.value()
        view_h = max(1, self.scroll.viewport().height())
        # The scrollbar may still hold a stale high value right after the
        # content shrank (search/reset); clamp it before computing the window.
        maximum = max(0, host_h - view_h)
        if value > maximum:
            value = maximum
        top_row = max(0, value // row_h - 1)
        bottom_row = min(total_rows - 1, (value + view_h) // row_h + 1)
        if top_row > bottom_row:
            top_row = bottom_row

        state = (top_row, bottom_row)
        if state == self._window_state:
            return
        self._window_state = state

        try:
            for row in range(top_row, bottom_row + 1):
                for col in range(cols):
                    idx = row * cols + col
                    if idx >= total:
                        break
                    if idx in self._cards:
                        continue
                    card = _WallpaperCard(wallpapers[idx],
                                          self._on_card_clicked, self._grid_host)
                    self.grid.addWidget(card, row, col)
                    self._cards[idx] = card
        except Exception:
            # Never let a transient layout error freeze the grid: degrade to
            # the classic full materialization so the dialog keeps working.
            self._fallback_full_grid()

    def _fallback_full_grid(self):
        self._virtualized = False
        for card in self._cards.values():
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards = {}
        cols = max(1, self._grid_cols)
        for i, wp in enumerate(self._visible_wallpapers):
            card = _WallpaperCard(wp, self._on_card_clicked, self._grid_host)
            self.grid.addWidget(card, i // cols, i % cols)
            self._cards[i] = card

    def _sync_playback(self):
        """Start/stop animation solely from the viewport: only the visible
        rows plus one spare row above and below play their preview; every
        card past that is fully stopped the moment it leaves the window.
        Cards stay materialized — only playback is gated."""
        wallpapers = self._visible_wallpapers
        if not wallpapers:
            return
        cols = self._grid_cols
        if cols <= 0:
            cols = max(1, self.width() // (CARD_W + 16))
        row_h = CARD_H + self.grid.spacing()
        total_rows = (len(wallpapers) + cols - 1) // cols
        vbar = self.scroll.verticalScrollBar()
        view_h = max(1, self.scroll.viewport().height())
        maximum = max(0, total_rows * row_h - view_h)
        value = min(vbar.value(), maximum)
        top = max(0, value // row_h - 1)
        bottom = min(total_rows - 1, (value + view_h) // row_h + 1)
        for idx, card in list(self._cards.items()):
            row = idx // cols
            if top <= row <= bottom:
                card._playback_suppressed = self._busy
                card.start_playback()
                self._request_preview(card)
            else:
                card.stop_playback()

    # --- previews (async via the same manager) ---

    def _request_preview(self, card):
        if card.preview_state != "none":
            return
        if not self._card_is_valid(card):
            return
        path = self._preview_cache_path(card.wallpaper.preview_url)
        if os.path.exists(path):
            card.set_preview_file(path)
            return
        if len(self._preview_replies) >= PREVIEW_CONCURRENCY:
            card.preview_state = "queued"
            self._preview_queue.append(card)
            return
        card.preview_state = "loading"
        reply = self._nam.get(QNetworkRequest(QUrl(card.wallpaper.preview_url)))
        self._preview_replies.append((reply, card, path))
        reply.finished.connect(
            lambda r=reply, c=card, p=path: self._on_preview_reply(r, c, p))

    def _kick_preview_queue(self):
        """Start queued preview downloads as soon as a slot frees up."""
        while self._preview_queue and len(self._preview_replies) < PREVIEW_CONCURRENCY:
            card = self._preview_queue.pop(0)
            if not self._card_is_valid(card):
                continue
            if card.preview_state != "queued":
                continue
            path = self._preview_cache_path(card.wallpaper.preview_url)
            if os.path.exists(path):
                card.set_preview_file(path)
                continue
            card.preview_state = "loading"
            reply = self._nam.get(QNetworkRequest(QUrl(card.wallpaper.preview_url)))
            self._preview_replies.append((reply, card, path))
            reply.finished.connect(
                lambda r=reply, c=card, p=path: self._on_preview_reply(r, c, p))

    def _on_preview_reply(self, reply, card, path):
        if reply in [r for r, _, _ in self._preview_replies]:
            self._preview_replies = [
                (r, c, p) for (r, c, p) in self._preview_replies if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            # we aborted it because the card scrolled out of view; reset to
            # "none" so scrolling back in retries cleanly instead of showing
            # a permanent "failed" placeholder
            if self._card_is_valid(card) and card.preview_state == "loading":
                card.preview_state = "none"
            self._kick_preview_queue()
            return
        if reply.error() != QNetworkReply.NetworkError.NoError or not data:
            if self._card_is_valid(card):
                card.preview_state = "failed"
                card._set_placeholder()
            self._kick_preview_queue()
            return
        # card could have been removed (deleteLater processed) during a refetch
        if not self._card_is_valid(card):
            self._kick_preview_queue()
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            card.preview_state = "failed"
            card._set_placeholder()
            self._kick_preview_queue()
            return
        card.set_preview_file(path)
        # A reply can land after the card already scrolled out of the window;
        # re-enforce the playback gate so it does not keep animating off-screen.
        self._sync_playback()
        self._kick_preview_queue()

    def _pause_previews(self):
        for card in self._cards.values():
            card._playback_suppressed = True
            card.stop_playback()

    def _resume_previews(self):
        for card in self._cards.values():
            card._playback_suppressed = False
        self._sync_playback()

    def _card_is_valid(self, card) -> bool:
        import shiboken6
        if not shiboken6.isValid(card):
            return False
        try:
            return shiboken6.isValid(card.preview_lbl)
        except RuntimeError:
            return False

    # --- download + import (async via the same manager) ---

    def _on_card_clicked(self, wallpaper):
        if self._busy:
            return
        self._busy = True
        # Free CPU for the transfer: stop the animated previews while the
        # .tendies downloads so the dialog (and the whole app) stays smooth.
        self._pause_previews()
        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Downloading {}...").format(wallpaper.name))
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._download_wallpaper = wallpaper
        self._download_reply = self._nam.get(QNetworkRequest(QUrl(wallpaper.download_url)))
        self._download_reply.downloadProgress.connect(self._on_download_progress)
        self._download_reply.finished.connect(self._on_download_finished)

    def _on_download_progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def _on_download_finished(self):
        reply = self._download_reply
        self._download_reply = None
        if reply is None:
            return
        data = bytes(reply.readAll())
        reply.deleteLater()

        self._busy = False
        self.progress.setVisible(False)
        self._resume_previews()

        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.status_lbl.setText(QCoreApplication.translate("Nugget", "Download failed"))
            self._show_error(
                QCoreApplication.translate("Nugget", "Download failed"),
                reply.errorString())
            return

        path = self._save_tendie(data, self._download_wallpaper.name)
        if path is None:
            self.status_lbl.setText(QCoreApplication.translate("Nugget", "Import failed"))
            return

        pb = tweaks[TweakID.PosterBoard]
        try:
            if not pb.add_tendie(path, self._device_version()):
                QMessageBox.warning(
                    self,
                    QCoreApplication.translate("Nugget", "Import Failed"),
                    QCoreApplication.translate(
                        "Nugget",
                        "Could not import wallpaper: you have reached the "
                        "maximum of 10 descriptors."),
                )
                self.status_lbl.setText(QCoreApplication.translate(
                    "Nugget", "Import skipped (limit reached)"))
                return
        except Exception as e:
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Import Failed"),
                QCoreApplication.translate(
                    "Nugget", "Failed to import wallpaper") + f"\n\n{e}",
            )
            self.status_lbl.setText(QCoreApplication.translate(
                "Nugget", "Import failed"))
            return

        pb_page = getattr(self.window, "ios_posterboard", None)
        if pb_page is not None:
            pb_page.refresh_tendies()

        self.status_lbl.setText(QCoreApplication.translate(
            "Nugget", "Imported {}!").format(self._download_wallpaper.name))

    def _device_version(self):
        """Connected device's iOS version, or None when there is no device."""
        try:
            return self.window.device_manager.get_current_device_version()
        except Exception:
            return None

    def _save_tendie(self, data: bytes, name: str):
        dest_dir = os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.AppDataLocation),
            "downloaded_wallpapers",
        )
        os.makedirs(dest_dir, exist_ok=True)
        safe_name = "".join(
            c for c in name if c.isalnum() or c in (" ", "-", "_")
        ).strip().replace(" ", "_")
        dest = os.path.join(dest_dir, f"{safe_name or 'wallpaper'}_{uuid.uuid4().hex[:8]}.tendies")
        try:
            with open(dest, "wb") as f:
                f.write(data)
            return dest
        except OSError as e:
            self._show_error(
                QCoreApplication.translate("Nugget", "Save Failed"), str(e))
            return None

    # --- cleanup ---

    def _abort_inflight(self):
        self._fetch_gen += 1
        for reply, _ in self._catalog_replies:
            reply.abort()
        self._catalog_replies = []
        self._catalog_sources = set()
        for reply, _, _ in self._preview_replies:
            reply.abort()
        self._preview_replies = []

    def _show_error(self, title, message):
        QMessageBox.warning(self, title, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._all_wallpapers:
            # re-derive column count / window for the new size
            self._apply_search(self.search_box.text())

    def closeEvent(self, event):
        if self._window_timer is not None:
            self._window_timer.stop()
        self._abort_inflight()
        if self._download_reply is not None:
            self._download_reply.abort()
            self._download_reply = None
        super().closeEvent(event)
