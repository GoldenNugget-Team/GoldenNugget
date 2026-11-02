"""Local lock-screen preview extraction for .tendies files.

A tendie is a zip of PosterBoard descriptor folders. The lock-screen art
lives in a few well-known places, which this module probes in priority order
when asked for a preview:

* ``<desc>/versions/*/contents/*.wallpaper/output.layerStack/
  portrait-layer_background.HEIC`` — the fully rendered background of
  photo/device-dump wallpapers.
* any ``*Background*.HEIC`` / ``*Background*.png|jpg`` asset inside a ``.ca``
  bundle, then any leftover image asset (largest wins).
* the first frame a ``main.caml`` animation references (video / CAML
  wallpapers, e.g. Nugget video-loop exports with ``assets/0.jpg``).

The chosen asset is decoded with Qt (HEIC decodes natively via ImageIO on
macOS and the bundled HEIF plugin on Windows; PNG/JPG anywhere) with an
OpenCV fallback for formats Qt does not ship. Only decodable assets are
returned, so a Linux box that cannot decode HEIC gracefully falls through to
a PNG/JPG frame instead of failing. Decoded previews are cached on disk next
to the wallpaper preview cache so repeat opens are instant.
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile

# zip entry name (lower-cased) -> match priority. Higher wins.
_CAML_RE = re.compile(r"<CGImage\s+src=\"([^\"]+)\"|<contents\s+[^>]*src=\"([^\"]+)\"")

# (lowercased substring, score). Scanned in order; the FIRST matching rule per
# entry decides its score so the targeted patterns always out-rank the
# generic ones below.
_RULES = (
    ("output.layerstack/portrait-layer_background.heic", 100),
    ("portrait-layer_background.heic",                   99),
    ("portrait-layer_background",                        98),
    ("output.layerstack/portrait-layer_floating.heic",   92),
    ("output.layerstack/portrait-layer_foreground.heic", 91),
    ("output.layerstack",                                90),
    ("input.segmentation/asset.resource/proxy.heic",     85),
    ("input.segmentation/asset.resource/adjusted.heic",  84),
    (".heic",                                            80),
    (".jpg",                                             70),
)
# PNG/JPEG assets further away from the screen art still beat nothing, but
# only if they are reasonably large (avatars/thumbnails are tiny).
_PNG_MIN_BYTES = 30_000

_IMAGE_EXTS = (".heic", ".jpg", ".jpeg", ".png", ".caml")


def _score_candidate(entry: str, size: int) -> int:
    """Score a zip entry as a lock-screen preview candidate (0 = skip)."""
    name = entry.lower()
    if "__macosx" in name or name.startswith("."):
        return 0
    ext = os.path.splitext(name)[1]
    if ext not in _IMAGE_EXTS:
        return 0
    for needle, score in _RULES:
        if needle in name:
            if ext == ".png" and size < _PNG_MIN_BYTES and score <= 80:
                return 0
            return score
    if ext == ".png":
        if size < _PNG_MIN_BYTES:
            return 0
        return 60
    return 0


def _sort_key(candidate):
    return -candidate[0]


def _walk_zip(zf: zipfile.ZipFile):
    """Yield (score, entry, is_caml) for every candidate in the archive."""
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        lower = name.lower()
        if "__macosx" in lower or ".ds_store" in lower:
            continue
        if lower.endswith("main.caml"):
            yield 75, name, True
            continue
        score = _score_candidate(name, info.file_size)
        if score:
            yield score, name, False


def _resolve_caml_frame(zf: zipfile.ZipFile, caml_entry: str):
    """Return the zip entry of the first frame a main.caml animates."""
    try:
        text = zf.read(caml_entry)
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return None
    match = _CAML_RE.search(text)
    if not match:
        return None
    rel = match.group(1) or match.group(2)
    if not rel:
        return None
    folder = os.path.dirname(caml_entry)
    resolved = os.path.normpath(os.path.join(folder, rel)).replace("\\", "/")
    if resolved in zf.namelist():
        return resolved
    return None


def preview_signature(tendie_path: str) -> str:
    """Stable cache key derived from the tendie file itself."""
    try:
        st = os.stat(tendie_path)
        payload = f"{os.path.abspath(tendie_path)}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        payload = os.path.abspath(tendie_path)
    return hashlib.md5(payload.encode("utf-8", "replace")).hexdigest()


def _cache_root():
    from src.controllers.wallpaper_api import wallpaper_cache_root
    root = os.path.join(wallpaper_cache_root(), "tendie_previews")
    os.makedirs(root, exist_ok=True)
    return root


def cached_preview_path(tendie_path: str) -> str:
    """Where the extracted preview for ``tendie_path`` lives (or will live)."""
    sig = preview_signature(tendie_path)
    return os.path.join(_cache_root(), f"{sig}.img")


def _decode_heif_via_pillow(data: bytes):
    """Decode HEIF/HEIC via pillow-heif (bundled libheif/libde265)."""
    try:
        import io
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            import numpy as np
            arr = np.asarray(rgb)
            from PySide6.QtGui import QImage
            return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    except Exception:
        return None


def decode_image_bytes(data: bytes):
    """Decode image bytes into a QImage via Qt, falling back to OpenCV."""
    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QImage, QImageReader

    buf = QBuffer()
    buf.setData(QByteArray(data))
    if not buf.open(QBuffer.OpenModeFlag.ReadOnly):
        return None
    img = QImageReader(buf).read()
    buf.close()
    if img is not None and not img.isNull():
        return img

    img = _decode_heif_via_pillow(data)
    if img is not None and not img.isNull():
        return img

    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8)
        cv_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if cv_img is None:
            return None
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    except Exception:
        return None


def extract_tendie_preview(tendie_path: str) -> str:
    """Extract + decode a lock-screen preview, cached on disk.

    Returns the path to a decodable image file, or ``None`` when the tendie
    carries nothing readable (and none of the cached fallbacks apply).
    """
    out_path = cached_preview_path(tendie_path)
    if os.path.exists(out_path):
        return out_path

    try:
        zf = zipfile.ZipFile(tendie_path)
    except (zipfile.BadZipFile, OSError):
        return None
    try:
        candidates = sorted(_walk_zip(zf), key=_sort_key)
        if not candidates:
            return None
        # Resolve CAML assets to real frame entries; they outrank generic
        # jpg/png when they decode.
        extra = []
        for score, entry, is_caml in candidates:
            if is_caml:
                frame = _resolve_caml_frame(zf, entry)
                if frame:
                    extra.append((79, frame, False))
        candidates = [(s, e, False) for s, e, is_caml in candidates if not is_caml]
        if extra:
            candidates.extend((s, e, ic) for s, e, ic in extra)
            candidates.sort(key=_sort_key)

        for score, entry, is_caml in candidates:
            try:
                data = zf.read(entry)
            except (KeyError, OSError, zipfile.BadZipFile):
                continue
            if not data:
                continue
            img = decode_image_bytes(data)
            if img is None or img.isNull():
                continue
            # Skip composites that are clearly not lock-screen art: horizontal
            # strips (sprite sheets / parallax bands) and tall banners render
            # as a garbled preview. Phone wallpapers sit between ~1:2.5 and
            # ~2.5:1 even after cropping.
            h = max(1, img.height())
            aspect = img.width() / h
            if aspect > 3.0 or aspect < 0.3:
                continue
            try:
                img.save(out_path, "PNG")
                return out_path
            except OSError:
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                continue
        return None
    finally:
        zf.close()


