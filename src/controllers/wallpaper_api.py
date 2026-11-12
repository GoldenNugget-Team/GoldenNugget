"""Wallpaper catalog + download helpers for the PosterBoard page.

Two community sources are supported:

* ``cowabunga`` — the SerStars/nugget-wallpapers repo that powers
  cowabun.ga / Pocket Poster. Serves per-category JSON files
  (``wallpapers-{custom,apple,template,passthemes}.json``) plus the
  matching ``.tendies`` payloads on raw.githubusercontent.com.
* ``caplayground`` — the CAPlayground/wallpapers repo (used by the
  CaPlayground website). Serves a single ``wallpapers.json`` that embeds
  its own ``base_url`` plus per-wallpaper ``file``/``preview`` paths.

Both return the same normalized shape so the UI can treat them identically.
"""

import hashlib
import os
import re
import time
from dataclasses import dataclass

import requests

from src.utils.paths import app_data_dir, cache_dir

COWABUNGA_BASE = "https://raw.githubusercontent.com/SerStars/nugget-wallpapers/main/"
COWABUNGA_CATEGORIES = {
    "Custom": "wallpapers-custom.json",
    "Apple": "wallpapers-apple.json",
}

CAPLAYGROUND_JSON = "https://raw.githubusercontent.com/CAPlayground/wallpapers/main/wallpapers.json"

DEFAULT_TIMEOUT = 30


@dataclass
class Wallpaper:
    """A downloadable wallpaper, normalized across both sources."""
    name: str
    preview_url: str
    download_url: str
    author: str = ""
    description: str = ""
    source: str = ""


class WallpaperAPIError(Exception):
    pass


class WallpaperSource:
    """Abstract base for a wallpaper catalog source."""
    id = ""
    label = ""

    def load(self) -> list[Wallpaper]:
        raise NotImplementedError

    def fetch_url(self, category: str = "") -> str:
        raise NotImplementedError

    def parse(self, data: bytes) -> list[Wallpaper]:
        """Parse a fetched catalog payload into normalized Wallpaper objects."""
        import json
        try:
            items = json.loads(data)
        except ValueError as e:
            raise WallpaperAPIError(f"Invalid data from {self.label}: {e}") from e
        return self._parse_items(items)

    def _parse_items(self, items):
        raise NotImplementedError


class CowabungaSource(WallpaperSource):
    id = "cowabunga"
    label = "Cowabunga"

    def __init__(self):
        self.categories = COWABUNGA_CATEGORIES

    def load(self, category: str = "Custom") -> list[Wallpaper]:
        try:
            resp = requests.get(self.fetch_url(category), timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WallpaperAPIError(f"Failed to fetch Cowabunga wallpapers: {e}") from e
        return self.parse(resp.content)

    def fetch_url(self, category: str = "Custom") -> str:
        filename = self.categories.get(category)
        if not filename:
            raise WallpaperAPIError(f"Unknown category: {category}")
        return COWABUNGA_BASE + filename

    def _parse_items(self, items):
        wallpapers = []
        for item in items:
            download = item.get("url", "")
            if not download.startswith("https://"):
                download = COWABUNGA_BASE + download
            preview = item.get("preview", "")
            if not preview.startswith("https://"):
                preview = COWABUNGA_BASE + preview
            wallpapers.append(Wallpaper(
                name=item.get("name", "Untitled"),
                preview_url=preview,
                download_url=download,
                author=item.get("authors", ""),
                description=item.get("description", ""),
                source=self.label,
            ))
        return wallpapers


class CaPlaygroundSource(WallpaperSource):
    id = "caplayground"
    label = "CaPlayground"

    def load(self, category: str = "") -> list[Wallpaper]:
        try:
            resp = requests.get(CAPLAYGROUND_JSON, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise WallpaperAPIError(f"Failed to fetch CaPlayground wallpapers: {e}") from e
        return self.parse(resp.content)

    def fetch_url(self, category: str = "") -> str:
        return CAPLAYGROUND_JSON

    def _parse_items(self, items):
        base_url = items.get("base_url", COWABUNGA_BASE) if isinstance(items, dict) else COWABUNGA_BASE
        entries = items.get("wallpapers", []) if isinstance(items, dict) else items
        wallpapers = []
        for item in entries:
            download = item.get("file", "")
            if not download.startswith("https://"):
                download = base_url + download
            preview = item.get("preview", "")
            if not preview.startswith("https://"):
                preview = base_url + preview
            wallpapers.append(Wallpaper(
                name=item.get("name", "Untitled"),
                preview_url=preview,
                download_url=download,
                author=item.get("creator", ""),
                description=item.get("description", ""),
                source=self.label,
            ))
        return wallpapers


SOURCES = {
    CowabungaSource.id: CowabungaSource(),
    CaPlaygroundSource.id: CaPlaygroundSource(),
}


# --- shared on-disk cache (cache_dir()/wallpaper_cache) ---
# Written by the wallpaper downloader dialog; reused here so the Tendies
# page can resolve real preview images for loaded .tendies files by name.


def wallpaper_cache_root() -> str:
    base = str(cache_dir())
    if not base:
        base = str(app_data_dir())
    root = os.path.join(base, "wallpaper_cache")
    os.makedirs(os.path.join(root, "catalog"), exist_ok=True)
    os.makedirs(os.path.join(root, "previews"), exist_ok=True)
    return root


def cached_preview_path(preview_url: str) -> str:
    """Local path where a preview for ``preview_url`` lives (or will live)."""
    digest = hashlib.md5(preview_url.encode("utf-8")).hexdigest()
    return os.path.join(wallpaper_cache_root(), "previews", digest + ".gif")


_all_cached_wallpapers = None
_all_cached_wallpapers_key = None
# The catalog directory is re-stat'ed at most this often. Every tendie row on
# the PosterBoard page asks for a name lookup, and each lookup used to re-stat
# every catalog file (T rows x C files). The files only change when the user
# explicitly refreshes the catalog, so a couple of seconds of staleness is
# invisible while the stat storm is not.
_CATALOG_SIG_TTL = 2.0
_catalog_sig_checked_at = 0.0
_catalog_sig_value = ""

# casefolded wallpaper name -> (catalog position, Wallpaper), rebuilt whenever
# the catalog signature changes. Lookups are dict hits instead of a scan.
_name_index: dict[str, tuple[int, Wallpaper]] | None = None
_name_index_key = None


def _catalog_signature(catalog_dir: str, files: list[str]) -> str:
    global _catalog_sig_checked_at, _catalog_sig_value
    now = time.monotonic()
    if _catalog_sig_value and now - _catalog_sig_checked_at < _CATALOG_SIG_TTL:
        return _catalog_sig_value
    parts = []
    for f in files:
        try:
            st = os.stat(os.path.join(catalog_dir, f))
            parts.append(f"{f}:{st.st_mtime}:{st.st_size}")
        except OSError:
            pass
    _catalog_sig_value = "|".join(parts)
    _catalog_sig_checked_at = now
    return _catalog_sig_value


def all_cached_wallpapers() -> list[Wallpaper]:
    """Every Wallpaper parsed from the on-disk catalog cache.

    Results are memoized and only re-read when a cached catalog file
    changes, so the Tendies page can do cheap name lookups on refresh.
    Cowabunga entries come first (they win the downloader's name dedup).
    """
    global _all_cached_wallpapers, _all_cached_wallpapers_key
    catalog_dir = os.path.join(wallpaper_cache_root(), "catalog")
    try:
        files = sorted(f for f in os.listdir(catalog_dir) if f.endswith(".json"))
    except OSError:
        return []
    if not files:
        return []

    key = _catalog_signature(catalog_dir, files)
    if key == _all_cached_wallpapers_key and _all_cached_wallpapers is not None:
        return list(_all_cached_wallpapers)

    # cowabunga first so name lookups prefer it
    order = {"cowabunga": 0, "caplayground": 1}
    files.sort(key=lambda f: (order.get(f.split("_", 1)[0], 2), f))
    result = []
    for fname in files:
        sid = fname.split("_", 1)[0]
        src = SOURCES.get(sid)
        if not src:
            continue
        try:
            with open(os.path.join(catalog_dir, fname), "r", encoding="utf-8") as f:
                result.extend(src.parse(f.read().encode("utf-8")))
        except Exception:
            continue
    _all_cached_wallpapers = result
    _all_cached_wallpapers_key = key
    return list(result)


_TENDIE_STEM_SUFFIX_RE = re.compile(r"_[0-9a-f]{8}$", re.IGNORECASE)


def _wallpaper_name_index() -> dict[str, tuple[int, Wallpaper]]:
    global _name_index, _name_index_key
    # Refresh the cache if the catalog moved on, then index it directly (the
    # public accessor copies its list, which a per-row lookup must not pay).
    all_cached_wallpapers()
    if _name_index is not None and _name_index_key == _all_cached_wallpapers_key:
        return _name_index
    index: dict[str, tuple[int, Wallpaper]] = {}
    for position, wp in enumerate(_all_cached_wallpapers or ()):
        index.setdefault(wp.name.strip().casefold(), (position, wp))
    _name_index = index
    _name_index_key = _all_cached_wallpapers_key
    return index


def find_wallpaper_by_name(file_name: str):
    """Match a ``.tendies`` file name against the cached wallpapers.

    The downloader saves imported tendies as ``<Name>_<8hex>.tendies``, so
    the trailing suffix is stripped before comparing. Returns the first
    ``Wallpaper`` (in catalog order) whose name matches case-insensitively,
    or ``None``.
    """
    stem = file_name[:-len(".tendies")] if file_name.lower().endswith(".tendies") else file_name
    candidates = {stem.strip().casefold()}
    stripped = _TENDIE_STEM_SUFFIX_RE.sub("", stem).strip().casefold()
    if stripped:
        candidates.add(stripped)
    index = _wallpaper_name_index()
    matches = [index[candidate] for candidate in candidates if candidate in index]
    if not matches:
        return None
    return min(matches, key=lambda entry: entry[0])[1]
