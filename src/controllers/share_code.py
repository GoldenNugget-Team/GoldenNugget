"""Share a preset as one line of text or a QR code, with no server involved.

A share code is ``GN1.`` followed by base64url(zlib(JSON)). It carries only
the selections that change something; local files (templates, icon themes,
wallpapers) never travel, because the receiver does not have them. Decoding
expands the code back into a full preset in which every other tweak is off, so
loading it reproduces the sender's setup instead of merging into the
receiver's.

Decoded data is untrusted: the code is size-capped before and after
decompression and the result goes through the same validation as an
imported preset file. Importing stores a preset; it never applies anything.
"""
from __future__ import annotations

import base64
import json
import zlib

from src.utils.i18n import QT_TRANSLATE_NOOP

PREFIX = "GN1."
FORMAT_VERSION = 1
MAX_CODE_CHARS = 6000          # a version-40 QR holds 2953 bytes; leave room for pasted text
MAX_JSON_BYTES = 256 * 1024
# Local files that cannot travel inside a code.
LOCAL_ONLY = frozenset({"PosterBoard", "Templates", "IconThemes"})


class ShareCodeError(ValueError):
    pass


def encode(tweaks_data: dict, name: str = "", description: str = "", ios_version: str = "") -> str:
    """Return the share code for preset-shaped ``tweaks_data``."""
    from src.controllers.risk_assessment import is_selected
    selected = {}
    for key, entry in sorted((tweaks_data or {}).items()):
        if key in LOCAL_ONLY or not is_selected(key, entry):
            continue
        selected[key] = {field: value for field, value in entry.items() if field != "type"}
    if not selected:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "Nothing to share: no tweaks are turned on in this preset."))
    payload = {"v": FORMAT_VERSION, "t": selected}
    for field, value in (("n", name), ("d", description), ("ios", ios_version)):
        if value:
            payload[field] = str(value)[:200]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    code = PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    if len(code) > MAX_CODE_CHARS:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "This preset is too large to share as a code."))
    return code


def extract(text: str) -> str:
    """Find a share code inside pasted text (a chat message, a URL, ...)."""
    text = (text or "").strip()
    start = text.find(PREFIX)
    if start < 0:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "No GoldenNugget share code found."))
    end = start + len(PREFIX)
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    while end < len(text) and (text[end] in alphabet or text[end].isspace()):
        end += 1
    return "".join(text[start:end].split())


def decode(text: str, validate=None) -> dict:
    """Decode a code into a preset dict (``tweaks`` + ``metadata``)."""
    from src.tweaks.tweak_names import TweakID
    code = extract(text)
    if len(code) > MAX_CODE_CHARS:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The share code is too long."))
    body = code[len(PREFIX):]
    try:
        compressed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        inflater = zlib.decompressobj()
        raw = inflater.decompress(compressed, MAX_JSON_BYTES)
        if inflater.unconsumed_tail:
            raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The share code expands to too much data."))
        if not inflater.eof:
            raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The share code is damaged or incomplete."))
        payload = json.loads(raw.decode("utf-8"))
    except ShareCodeError:
        raise
    except (ValueError, zlib.error, UnicodeDecodeError) as error:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The share code is damaged or incomplete.")) from error
    if not isinstance(payload, dict) or payload.get("v") != FORMAT_VERSION \
            or not isinstance(payload.get("t"), dict):
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "This share code was made by an unsupported version of GoldenNugget."))

    shared = {key: entry for key, entry in payload["t"].items()
              if key in TweakID.__members__ and key not in LOCAL_ONLY}
    tweaks_data = {member.name: {"enabled": False} for member in TweakID
                   if member.name not in LOCAL_ONLY}
    tweaks_data.update(shared)
    metadata = {"tags": ["shared"]}
    for field, key in (("n", "name"), ("d", "description"), ("ios", "ios_version")):
        if isinstance(payload.get(field), str):
            metadata[key] = payload[field][:200]
    data = {"tweaks": tweaks_data, "metadata": metadata}
    name = metadata.pop("name", "")
    if validate is not None and not validate(data):
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The share code contains invalid tweak data."))
    data["metadata"]["name"] = name
    data["shared_count"] = len(shared)
    return data


# --- QR -------------------------------------------------------------------

def qr_matrix(code: str) -> np.ndarray:
    """QR modules as a uint8 array (0 = dark, 255 = light), without margin."""
    import cv2
    params = cv2.QRCodeEncoder_Params()
    params.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_M
    matrix = cv2.QRCodeEncoder.create(params).encode(code)
    if matrix is None or not matrix.size:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "This preset is too large for a QR code."))
    return matrix


def qr_image(code: str, module: int = 8, margin: int = 4) -> np.ndarray:
    """Black-on-white QR bitmap with the standard 4-module quiet zone."""
    import cv2
    matrix = qr_matrix(code)
    size = matrix.shape[0] * module
    image = cv2.resize(matrix, (size, size), interpolation=cv2.INTER_NEAREST)
    pad = margin * module
    return cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def read_qr(path: str) -> str:
    """Return the share code found in a QR image file (a screenshot or photo)."""
    import cv2
    import numpy as np  # deferred: QR support must not load numpy at startup
    data = np.fromfile(path, dtype=np.uint8)   # cv2.imread breaks on non-ASCII paths on Windows
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
    if image is None:
        raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The image could not be opened."))
    return read_qr_array(image)


def read_qr_array(image: np.ndarray) -> str:
    import cv2
    detector = cv2.QRCodeDetector()
    candidates = [image]
    # Small screenshots decode better when scaled up.
    if max(image.shape[:2]) < 600:
        candidates.append(cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    for candidate in candidates:
        text, _points, _ = detector.detectAndDecode(candidate)
        if text:
            if PREFIX not in text:
                raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "This QR code is not a GoldenNugget share code."))
            return text
    raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "No QR code was found in the image."))
