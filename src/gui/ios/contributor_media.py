"""Asynchronous public GitHub credits with a small persistent cache."""
import hashlib
import json
import re
import time
import weakref
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from src.utils.paths import cache_dir

GITHUB_NAME = re.compile(r'[A-Za-z0-9_-]+\Z')
TRANSLATIONS_REPOSITORY = 'GoldenNugget-Team/gNugget-i18n'
_CACHE_SECONDS = 24 * 60 * 60
_MAX_BYTES = 2 * 1024 * 1024
# Avatars and the contributor list are decorative. Starting the first fetch at
# build time put the whole QtNetwork stack (CFNetwork init on macOS: ~0.4 s) and
# the on-disk cache reads on the startup path, before the window was painted.
# Deferring by one short tick keeps that off startup; the images still land
# before the credits panel can be scrolled into view.
_DEFER_MS = 150


def github_owner(link):
    parsed = urlparse(link)
    parts = parsed.path.strip('/').split('/')
    if parsed.scheme == 'https' and parsed.hostname == 'github.com' and GITHUB_NAME.fullmatch(parts[0]):
        return parts[0]
    return None


class ContributorMedia(QObject):
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls(QApplication.instance())
        return cls._instance

    def __init__(self, parent):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        # Qt's CacheLocation still answers the pre-rename folder; the app owns
        # its paths in src.utils.paths (see tools/test_storage.py).
        self.cache = cache_dir() / 'contributors'
        self.pending = {}

    def fetch(self, url, callback):
        """Schedule a fetch after the first frame (see ``_DEFER_MS``)."""
        QTimer.singleShot(_DEFER_MS, lambda: self._fetch_now(url, callback))

    def _fetch_now(self, url, callback):
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.cache / key
        cached = None
        try:
            if path.stat().st_size <= _MAX_BYTES:
                cached = path.read_bytes()
                if time.time() - path.stat().st_mtime < _CACHE_SECONDS:
                    QTimer.singleShot(0, lambda: callback(cached))
                    return
        except OSError:
            pass
        if url in self.pending:
            self.pending[url].append(callback)
            return
        self.pending[url] = [callback]
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b'User-Agent', b'GoldenNugget-Credits')
        request.setRawHeader(b'Accept', b'application/vnd.github+json' if 'api.github.com/' in url else b'image/*')
        request.setTransferTimeout(10000)
        reply = self.manager.get(request)
        reply.downloadProgress.connect(lambda received, total: reply.abort() if max(received, total) > _MAX_BYTES else None)

        def finished():
            data = cached
            if reply.error() == QNetworkReply.NoError:
                result = bytes(reply.readAll())
                if 0 < len(result) <= _MAX_BYTES:
                    data = result
                    try:
                        self.cache.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                    except OSError:
                        pass
            callbacks = self.pending.pop(url, [])
            reply.deleteLater()
            for ready in callbacks:
                ready(data)
        reply.finished.connect(finished)

    def avatar(self, button, link, paint):
        owner = github_owner(link)
        direct = urlparse(link).scheme == 'https' and urlparse(link).hostname == 'cdn.discordapp.com'
        if not owner and not direct:
            return
        target = weakref.ref(button)

        def ready(data):
            widget = target()
            if data and widget is not None and isValid(widget):
                paint(widget, data)
        self.fetch(link if direct else f'https://github.com/{owner}.png?size=176', ready)

    def contributors(self, repository, callback):
        people = {}

        def page(number):
            def ready(data):
                try:
                    rows = json.loads(data) if data else None
                except (ValueError, TypeError):
                    rows = None
                if not isinstance(rows, list):
                    callback(list(people.values()), False)
                    return
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    login = row.get('login')
                    if isinstance(login, str) and GITHUB_NAME.fullmatch(login):
                        people[login.casefold()] = login
                if len(rows) == 100 and number < 100:
                    page(number + 1)
                else:
                    callback(list(people.values()), True)
            self.fetch(f'https://api.github.com/repos/{repository}/contributors?per_page=100&page={number}', ready)
        page(1)
