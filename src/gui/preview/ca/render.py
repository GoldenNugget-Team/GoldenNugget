"""QPainter rendering of CAML scenes (lock-screen wallpaper preview).

Faithful port of CAPlayground's ``LayerRenderer`` + child renderers and the
``coordinates`` / ``layerApplication`` helpers. Compose rules mirror the CSS
model: each layer is a positioned box whose transform (translate -> rotate ->
scale, all about the anchor point) maps content onto the scene, blend modes /
filters are composited through a per-layer bitmap, and the children render in
array order without z-sorting.

Fidelity notes (deliberate, matching the user's request not to over-engineer):
* ``liquidGlass`` layers render fully transparent (children still drawn).
* ``rotateX`` / ``rotateY`` / perspective are not simulated (flat 2D).
* ``CAEmitterLayer`` is emulated as stylised particles (per cell: birth stream,
  ballistic drift under acceleration and spin, spawn point in layer coords).
* gyro parallax (``wallpaperParallaxGroups``) is parsed but not rendered.
"""

from __future__ import annotations

import math
from collections import OrderedDict
import copy as _copy
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from urllib.parse import unquote

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from src.gui.preview.tendie_preview import decode_image_bytes
from .animate import layer_animation_overrides, scene_loop_duration
from .models import CADocument, GradientColor, Layer, Vec2

if TYPE_CHECKING:
    import numpy as np

_QM = QPainter.CompositionMode

# CAPlayground lib/blending.ts ids -> Qt composition modes. The four HSL-based
# ones below are handled in numpy (Qt has no matching composition mode).
_BLEND_MODES: Dict[str, QPainter.CompositionMode] = {
    "normalBlendMode": _QM.CompositionMode_SourceOver,
    "colorBurnBlendMode": _QM.CompositionMode_ColorBurn,
    "colorDodgeBlendMode": _QM.CompositionMode_ColorDodge,
    "darkenBlendMode": _QM.CompositionMode_Darken,
    "differenceBlendMode": _QM.CompositionMode_Difference,
    "exclusionBlendMode": _QM.CompositionMode_Exclusion,
    "lightenBlendMode": _QM.CompositionMode_Lighten,
    "multiplyBlendMode": _QM.CompositionMode_Multiply,
    "overlayBlendMode": _QM.CompositionMode_Overlay,
    "screenBlendMode": _QM.CompositionMode_Screen,
}

# CSS/NPM blend modes Qt does not provide natively -> composited in numpy.
_HSL_KINDS: Dict[str, str] = {
    "hueBlendMode": "hue",
    "saturationBlendMode": "saturation",
    "colorBlendMode": "color",
    "luminosityBlendMode": "luminosity",
}

_MAX_VIDEO_FRAMES = 32
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_MAX_IMAGE_ENTRIES = 128


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class _LCG:
    __slots__ = ("_state",)

    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFF or 1

    def next_uint(self) -> int:
        self._state = (1664525 * self._state + 1013904223) & 0xFFFFFFFF
        return self._state

    def next_float(self) -> float:
        return self.next_uint() / 0xFFFFFFFF


def find_by_id(layer: Layer, wanted: str) -> Optional[Layer]:
    if layer.id == wanted:
        return layer
    for child in layer.children:
        hit = find_by_id(child, wanted)
        if hit is not None:
            return hit
    return None


def resolve_state_name(overrides: Optional[dict], state: Optional[str], default: Optional[str] = None) -> Optional[str]:
    """Map a requested state name to the closest override key.

    Appearance-split scenes (the WWDC22 ``background`` art layers) expose
    ``Locked Light``/``Locked Dark`` while callers ask for the bare
    ``Locked``. Preference order: exact key, then ``<name> Light`` (default
    appearance), then ``<name> Dark``, then ``<name>``-prefixed keys, then
    any key sharing the leading word, then ``default`` itself.
    """
    if not overrides:
        return default or state
    if state in overrides:
        return state
    for suffix in ("Light", "Dark"):
        candidate = f"{state} {suffix}"
        if candidate in overrides:
            return candidate
    prefix = str(state).split(" ", 1)[0]
    for key in overrides:
        if str(key).lower().startswith(prefix.lower()):
            return str(key)
    for key in overrides:
        if str(key).lower().startswith(str(state).lower()):
            return str(key)
    return default or state


def _layer_index(root):
    index = {}
    stack = [root] if root is not None else []
    while stack:
        layer = stack.pop()
        index.setdefault(layer.id, layer)
        stack.extend(reversed(layer.children))
    return index


def _static_layer_ids(root):
    static = set()
    def inspect(layer):
        children_static = [inspect(child) for child in layer.children]
        if not layer.animations and layer.type not in ("emitter", "video") and all(children_static):
            static.add(id(layer))
            return True
        return False
    if root is not None:
        inspect(root)
    return static


def apply_state_overrides(root: Layer, overrides: Optional[dict], state: Optional[str]) -> Layer:
    """Clone once and resolve override targets in linear time."""
    clone = _copy.deepcopy(root)
    if not overrides or not state or state == "Base State":
        return clone
    eff = resolve_state_name(overrides, state)
    listing = overrides.get(eff) or []
    if not listing and eff.endswith(" Light"):
        listing = overrides.get(eff.rsplit(" ", 1)[0]) or []
    return _apply_override_list(clone, _layer_index(clone), listing)


def _apply_override_list(clone, index, listing):
    for o in listing:
        target_id = (str(o.get("targetId") or "")).strip()
        target = index.get(target_id) or index.get(o.get("targetId"))
        if target is None:
            continue
        kp = (str(o.get("keyPath") or "")).lower()
        v = o.get("value")
        if kp == "position.y" and isinstance(v, (int, float)):
            target.position.y = float(v)
        elif kp == "position.x" and isinstance(v, (int, float)):
            target.position.x = float(v)
        elif kp == "zposition" and isinstance(v, (int, float)):
            target.zPosition = float(v)
        elif kp == "bounds.size.width" and isinstance(v, (int, float)):
            target.size.w = float(v)
        elif kp == "bounds.size.height" and isinstance(v, (int, float)):
            target.size.h = float(v)
        elif kp == "transform.scale.xy" and isinstance(v, (int, float)):
            target.scale = float(v)
        elif kp in ("transform.rotation", "transform.rotation.z") and isinstance(v, (int, float)):
            target.rotation = float(v)
        elif kp == "transform.rotation.x" and isinstance(v, (int, float)):
            target.rotationX = float(v)
        elif kp == "transform.rotation.y" and isinstance(v, (int, float)):
            target.rotationY = float(v)
        elif kp == "opacity" and isinstance(v, (int, float)):
            target.opacity = float(v)
        elif kp == "cornerradius" and isinstance(v, (int, float)):
            target.cornerRadius = float(v)
        elif kp == "borderwidth" and isinstance(v, (int, float)):
            target.borderWidth = float(v)
        elif kp == "fontsize" and isinstance(v, (int, float)):
            target.fontSize = float(v)
        elif kp == "backgroundcolor" and isinstance(v, str):
            target.backgroundColor = v
        elif kp == "bordercolor" and isinstance(v, str):
            target.borderColor = v
        elif kp == "color" and isinstance(v, str):
            target.color = v
    return clone


def interpolated_state_root(
    root: Layer,
    overrides: Optional[dict],
    from_state: str,
    to_state: str,
    progress: float,
    *, working_root=None, index=None,
) -> Layer:
    """Build a layer tree with state overrides interpolated between two states.

    Numeric overrides for the same ``(targetId, keyPath)`` are blended by
    ``progress`` (0..1); values that only exist in the target state snap in.
    Non-numeric values (colors, strings) hold the source value and switch at
    ``progress == 1``, matching how a snapped edge lands at the end of a
    transition.
    """
    if not overrides:
        return working_root if working_root is not None else _copy.deepcopy(root)
    from_list = overrides.get(from_state) or []
    to_list = overrides.get(to_state) or []
    p = max(0.0, min(1.0, float(progress)))
    to_map = {
        (str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()): o.get("value")
        for o in to_list
    }
    interp = []
    from_keys = set()
    for o in from_list:
        target_id = str(o.get("targetId") or "")
        key_path = str(o.get("keyPath") or "")
        from_keys.add((target_id, key_path.lower()))
        fv = o.get("value")
        tv = to_map.get((target_id, key_path.lower()))
        if isinstance(fv, (int, float)) and isinstance(tv, (int, float)):
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": fv + (tv - fv) * p})
        else:
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": tv if p >= 1.0 else fv})
    for o in to_list:
        target_id = str(o.get("targetId") or "")
        key_path = str(o.get("keyPath") or "")
        if (target_id, key_path.lower()) not in from_keys:
            interp.append({"targetId": target_id, "keyPath": key_path,
                           "value": o.get("value")})
    if working_root is None:
        working_root = _copy.deepcopy(root)
        index = _layer_index(working_root)
    return _apply_override_list(working_root, index, interp)


def state_transition_spec(doc: Optional[CADocument]) -> Optional[Tuple[str, str, float, float, float]]:
    """Describe a playable Locked<->Unlock poster transition.

    Returns ``(from_state, to_state, open_duration, close_duration, hold)`` for
    scenes like the Minecraft chest whose "animation" is the state machine
    (the lid flies away, the treasure interior swells) rather than a looping
    CA animation, or ``None`` when the states are identical.
    """
    if doc is None or not doc.stateOverrides:
        return None
    from_state = resolve_state_name(doc.stateOverrides, "Locked") or "Locked"
    to_state = resolve_state_name(doc.stateOverrides, "Unlock") or "Unlock"
    if from_state == to_state:
        return None
    lock_list = doc.stateOverrides.get(from_state) or []
    unlock_list = doc.stateOverrides.get(to_state) or []
    if not lock_list or not unlock_list:
        return None
    to_map = {
        (str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()): o.get("value")
        for o in unlock_list
    }
    diffs = 0
    for o in lock_list:
        fv = o.get("value")
        tv = to_map.get((str(o.get("targetId") or ""), (str(o.get("keyPath") or "")).lower()))
        if isinstance(fv, (int, float)) and isinstance(tv, (int, float)) and abs(fv - tv) > 1e-6:
            diffs += 1
    if diffs == 0:
        return None
    duration = 0.55  # CAPlayground posters use the system unlock cadence by default
    for t in (doc.stateTransitions or []):
        if getattr(t, "toState", None) == to_state or getattr(t, "toState", None) == "Unlock":
            ds = [el.duration for el in t.elements if getattr(el, "duration", None)]
            if ds:
                duration = max(0.1, max(ds))
            break
    return (from_state, to_state, duration, duration, 0.9)


def home_state(doc: Optional[CADocument]) -> Optional[str]:
    """Return the unlocked (home-screen) state name for ``doc`` if rendering
    it visibly changes the picture, else ``None``.

    Prefers a state whose name starts with ``Unlock`` (``Unlock``,
    ``Unlock Light``, ``Unlock Dark`` ...) and returns it only when a render
    of that state actually differs from the default scene (the one the
    lock-screen loop shows). Scenes without a distinct home appearance (e.g.
    Super Mario's ``Unlock`` state, which is visually identical to ``Locked``)
    return ``None`` so the preview stays on its loop while unlocked.
    """
    if doc is None or not doc.stateOverrides or not doc.states:
        return None
    mig = None
    for s in doc.states:
        if str(s).lower().startswith("unlock"):
            mig = str(s)
            break
    if mig is None:
        return None
    try:
        base_state = resolve_state_name(doc.stateOverrides, "Locked")
        root = doc.root
        width, height = (root.size.w, root.size.h) if root else (390, 844)
        scale = min(1.0, 256 / max(width, height, 1))
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        key = (id(root), id(doc.stateOverrides), doc.revision, base_state, mig, size)
        cached = getattr(doc, "_home_state_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        base = CAMLRenderer(doc, size=size, state=base_state).render(0.0)
        home = CAMLRenderer(doc, size=size, state=mig).render(0.0)
    except Exception:
        return None
    if base is None or base.isNull() or home is None or home.isNull():
        return None
    if base.size() != home.size():
        return mig
    result = None if base == home else mig
    doc._home_state_cache = key, result
    return result


def _hex_color(hex_str: Optional[str], alpha: float = 1.0) -> Optional[QColor]:
    if not hex_str:
        return None
    text = hex_str.strip()
    m = text.lower()
    if not m.startswith("#"):
        m = "#" + m
    h = m.lstrip("#")
    if len(h) >= 8:
        h = h[:6]
    elif len(h) < 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return QColor(r, g, b, int(_clamp(alpha, 0.0, 1.0) * 255))


def _rounded_rect_path(w: float, h: float, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, radius)
    t = min(r, w / 2.0, h / 2.0)
    path.addRoundedRect(QRectF(0.0, 0.0, w, h), t, t)
    return path


def _filter_is_noop(flt) -> bool:
    """True when an enabled filter has no visual effect at its current value."""
    if not getattr(flt, "enabled", False):
        return True
    ft = flt.type
    value = flt.value
    if ft == "gaussianBlur":
        return not value or value <= 0.0
    if ft in ("colorInvert", "CISepiaTone"):
        return value is None or value <= 0.0
    if ft in ("colorContrast", "colorSaturate"):
        return value is None or abs(value - 1.0) < 1e-6
    if ft == "colorHueRotate":
        return (value or 0.0) % 360.0 == 0.0
    return False


def _apply_filters(img: QImage, filters) -> QImage:
    """GPU-free approximation of the CSS filters CAPlayground maps onto layers."""
    if not filters:
        return img
    active = [f for f in filters if not _filter_is_noop(f)]
    if not active:
        return img
    try:
        import numpy as np
    except Exception:
        return img

    from PySide6.QtGui import QImage as _QI

    src = img
    if src.format() != _QI.Format.Format_RGBA8888:
        src = src.convertToFormat(_QI.Format.Format_RGBA8888)
    w = src.width()
    h = src.height()
    arr = np.ndarray((h, w, 4), dtype=np.uint8, buffer=src.constBits(),
                     strides=(src.bytesPerLine(), 4, 1))

    for flt in active:
        ft = flt.type
        value = flt.value
        try:
            if ft == "gaussianBlur":
                from PIL import Image, ImageFilter
                pil = Image.fromarray(arr, "RGBA")
                pil = pil.filter(ImageFilter.GaussianBlur(radius=max(0.0, value)))
                arr = np.asarray(pil)
            elif ft == "colorContrast":
                from PIL import Image, ImageEnhance
                pil = Image.fromarray(arr, "RGBA")
                pil = ImageEnhance.Contrast(pil).enhance(max(0.0, value))
                arr = np.asarray(pil)
            elif ft == "colorSaturate":
                from PIL import Image, ImageEnhance
                pil = Image.fromarray(arr, "RGBA")
                pil = ImageEnhance.Color(pil).enhance(max(0.0, value))
                arr = np.asarray(pil)
            elif ft == "colorInvert":
                out = arr.copy()
                if value >= 1.0:
                    out[..., :3] = 255 - out[..., :3]
                else:
                    f = max(0.0, min(1.0, value))
                    out[..., :3] = out[..., :3] * (1.0 - f) + (255 - out[..., :3]) * f
                arr = out
            elif ft == "colorHueRotate":
                from PIL import Image
                pil = Image.fromarray(arr, "RGBA")
                pil = _hue_rotate_pil(pil, value, np)
                arr = np.asarray(pil)
            elif ft == "CISepiaTone":
                from PIL import Image
                pil = Image.fromarray(arr, "RGBA")
                pil = _sepia_pil(pil, value, np)
                arr = np.asarray(pil)
        except Exception:
            continue

    try:
        cont = np.ascontiguousarray(arr)
        out = _QI(cont.data, w, h, 4 * w, _QI.Format.Format_RGBA8888).copy()
        return out
    except Exception:
        return img


def _rgb_hue_delta(r, g, b, np=None):
    """Compute the hue angles (0..360) and max-min delta for an RGB array."""
    if np is None:
        import numpy as np
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc
    mask = delta != 0
    safe = np.where(mask, delta, 1.0)
    h = np.zeros_like(maxc)
    h = np.where(mask & (maxc == r), 60.0 * (((g - b) / safe) % 6.0), h)
    h = np.where(mask & (maxc == g), 60.0 * (((b - r) / safe) + 2.0), h)
    h = np.where(mask & (maxc == b), 60.0 * (((r - g) / safe) + 4.0), h)
    return h, delta


def _hue_rotate_pil(pil, degrees: float, np):
    arr = np.asarray(pil).astype(np.float32) / 255.0
    rgb = arr[..., :3]
    alpha = arr[..., 3]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    h, delta = _rgb_hue_delta(r, g, b, np)
    maxc = np.maximum(np.maximum(r, g), b)
    s = np.where(maxc != 0, delta / np.where(maxc, maxc, 1.0), 0.0)
    v = maxc
    h = np.mod(h + degrees, 360.0)
    floor_h = np.floor(h / 60.0)
    f = h / 60.0 - floor_h
    pp = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    h6 = np.mod(floor_h, 6.0).astype(np.float32)
    out = np.empty_like(rgb)
    sector_rgb = [(0, (v, t, pp)), (1, (q, v, pp)), (2, (pp, v, t)),
                  (3, (pp, q, v)), (4, (t, pp, v)), (5, (v, pp, q))]
    for i, comps in sector_rgb:
        mask_i = h6 == i
        out[..., 0] = np.where(mask_i, comps[0], out[..., 0])
        out[..., 1] = np.where(mask_i, comps[1], out[..., 1])
        out[..., 2] = np.where(mask_i, comps[2], out[..., 2])
    out = np.stack([out[..., 0], out[..., 1], out[..., 2], alpha], axis=-1)
    out = np.clip(out, 0.0, 1.0)
    from PIL import Image as _I
    return _I.fromarray((out * 255.0).astype(np.uint8), "RGBA")


def _sepia_pil(pil, factor: float, np):
    arr = np.asarray(pil).astype(np.float32)
    rgb = arr[..., :3]
    alpha = arr[..., 3:]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    sr = r * 0.393 + g * 0.769 + b * 0.189
    sg = r * 0.349 + g * 0.686 + b * 0.168
    sb = r * 0.272 + g * 0.534 + b * 0.131
    f = max(0.0, min(1.0, factor))
    out = rgb * (1.0 - f) + np.stack([sr, sg, sb], axis=-1) * f
    out = np.clip(out, 0.0, 255.0)
    from PIL import Image as _I
    return _I.fromarray(np.concatenate([out, alpha], axis=-1).astype(np.uint8), "RGBA")






def _hsl_blend(src: QImage, kind: str) -> QImage:
    """Preserve the preview's existing HSL approximation without a codec roundtrip.

    The old RGB -> HSL -> identical RGB conversion was an identity; its only
    net operation was compositing the original RGB onto an opaque backdrop.
    Convert to straight RGBA *before* dropping alpha, so translucent colors
    retain their RGB rather than their premultiplied values.
    """
    if src.isNull():
        return src
    out = src.convertToFormat(QImage.Format.Format_RGBA8888).copy()
    bits = out.bits()
    stride, width = out.bytesPerLine(), out.width()
    if stride == width * 4:
        bits[3::4] = b"\xff" * (width * out.height())
    else:
        alpha = b"\xff" * width
        for row in range(out.height()):
            start = row * stride
            bits[start + 3:start + width * 4:4] = alpha
    return out


class CAMLRenderer:
    """Render a parsed :class:`CADocument` to a QImage at any wall-clock time."""

    def __init__(
        self,
        doc: CADocument,
        size: Optional[Tuple[int, int]] = None,
        state: str = "Locked",
        backdrop: Optional[str] = None,
        backdrop_fill: bool = True,
    ):
        self.doc = doc
        root = doc.root
        self.scene_w = root.size.w if root else 390.0
        self.scene_h = root.size.h if root else 844.0
        self.scene_flipped = int(root.geometryFlipped or 0) if root else 0
        self.width, self.height = size or (int(self.scene_w), int(self.scene_h))
        self._render_edge = max(self.width, self.height)
        self.state = state
        if backdrop is not None:
            self.backdrop = backdrop
        elif backdrop_fill:
            self.backdrop = root.backgroundColor if root else None
        else:
            self.backdrop = None
        self._images = OrderedDict()
        self._image_bytes = 0
        self._document_revision = doc.revision
        self._default_size = size is None
        self._default_backdrop = backdrop is None and backdrop_fill
        self._video_frames = OrderedDict()
        self._state_root: Optional[Layer] = None
        self._state_root_id: Optional[object] = None
        self._static_layers = set()
        self._offscreen_cache = OrderedDict()
        self._offscreen_bytes = 0
        self._transition_key = None
        self._transition_root = None
        self._transition_index = None
        self._emitter_particles: Dict[str, List[Tuple[float, float, float, float, float]]] = {}

    # -- asset access ------------------------------------------------------ #

    def _image_for(self, name: Optional[str]) -> Optional[QImage]:
        """Resolve an asset path to a cached QImage (never requires a display).
        CAML ``contents`` strings URL-encode spaces (``assets/a%20b.png``),
        so the basename is matched both raw and decoded."""
        if not name:
            return None
        keys = [name.split("/")[-1]]
        try:
            decoded = unquote(keys[0])
            if decoded not in keys:
                keys.append(decoded)
        except Exception:
            pass
        for key in keys:
            if key in self._images:
                self._images.move_to_end(key)
                return self._images[key]
            data = self.doc.assets.get(key)
            if data:
                img = decode_image_bytes(data)
                if img is not None and not img.isNull():
                    self._cache_image(key, img)
                    return img
                self._cache_image(key, None)
        return None

    def _cache_image(self, key, image):
        cost = image.sizeInBytes() if image is not None else 0
        if cost > _MAX_IMAGE_BYTES:
            return
        while self._images and (self._image_bytes + cost > _MAX_IMAGE_BYTES
                                or len(self._images) >= _MAX_IMAGE_ENTRIES):
            _, previous = self._images.popitem(last=False)
            self._image_bytes -= previous.sizeInBytes() if previous is not None else 0
        self._images[key] = image
        self._image_bytes += cost

    def _sync_document(self):
        if self._document_revision == self.doc.revision:
            return
        self._document_revision = self.doc.revision
        root = self.doc.root
        self.scene_w = root.size.w if root else 390.0
        self.scene_h = root.size.h if root else 844.0
        self.scene_flipped = int(root.geometryFlipped or 0) if root else 0
        if self._default_size:
            self.width, self.height = int(self.scene_w), int(self.scene_h)
        self._render_edge = max(self.width, self.height)
        if self._default_backdrop:
            self.backdrop = root.backgroundColor if root else None
        self._images.clear()
        self._image_bytes = 0
        self._video_frames.clear()
        self._state_root = self._state_root_id = None
        self._transition_key = self._transition_root = self._transition_index = None
        self._static_layers.clear()
        self._offscreen_cache.clear()
        self._offscreen_bytes = 0
        self._emitter_particles.clear()

    # -- top level --------------------------------------------------------- #

    def render(self, t_ms: float = 0.0) -> QImage:
        self._sync_document()
        key = (id(self.doc), self.doc.revision, self.state)
        if self._state_root is None or self._state_root_id != key:
            self._state_root = apply_state_overrides(
                self.doc.root, self.doc.stateOverrides, self.state)
            self._state_root_id = key
            self._static_layers = _static_layer_ids(self._state_root)
            self._offscreen_cache.clear()
            self._offscreen_bytes = 0
        return self._paint_root(self._state_root, t_ms)

    def render_state_transition(
        self,
        from_state: str = "Locked",
        to_state: str = "Unlock",
        progress: float = 0.0,
        t_ms: float = 0.0,
    ) -> QImage:
        """Render the poster state transition (e.g. chest opening): each
        numeric state override is interpolated ``from_state`` -> ``to_state``
        by ``progress``; non-numeric values snap in at the end."""
        self._sync_document()
        key = (id(self.doc.root), id(self.doc.stateOverrides), self.doc.revision, from_state, to_state)
        if self._transition_key != key:
            self._transition_root = _copy.deepcopy(self.doc.root)
            self._transition_index = _layer_index(self._transition_root)
            self._transition_key = key
        root = interpolated_state_root(
            self.doc.root, self.doc.stateOverrides, from_state, to_state, progress,
            working_root=self._transition_root, index=self._transition_index)
        return self._paint_root(root, t_ms)

    def _paint_root(self, root: Layer, t_ms: float = 0.0) -> QImage:
        layers = root.children if root else []

        target = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        target.fill(Qt.GlobalColor.transparent)

        bg = _hex_color(self.backdrop)
        if bg is not None:
            target.fill(bg)

        p = QPainter(target)
        try:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            kx = self.width / self.scene_w if self.scene_w > 0 else 1.0
            ky = self.height / self.scene_h if self.scene_h > 0 else 1.0
            if kx != 1.0 or ky != 1.0:
                p.scale(kx, ky)

            use_y_up = self.scene_flipped == 0
            parent_h = self.scene_h

            bg_layers = [l for l in layers if l.name == "BACKGROUND"]
            fg_layers = [l for l in layers if l.name != "BACKGROUND"]
            for top_layers in (bg_layers, fg_layers):
                for layer in top_layers:
                    self._draw_layer(p, layer, use_y_up, parent_h, t_ms, 0.0)
        finally:
            p.end()
        return target

    # -- per-layer ---------------------------------------------------------- #

    def _draw_layer(
        self,
        p: QPainter,
        layer: Layer,
        use_y_up: bool,
        parent_h: float,
        t_ms: float,
        delay_ms: float,
    ):
        ovs = layer_animation_overrides(layer.animations, t_ms, delay_ms)
        if ovs.get("hidden") == 1 or layer.visible is False:
            return

        w = float(ovs.get("bounds.size.width", layer.size.w or 0.0))
        h = float(ovs.get("bounds.size.height", layer.size.h or 0.0))
        x = float(ovs.get("position.x", layer.position.x))
        y = float(ovs.get("position.y", layer.position.y))
        rotation = float(ovs.get("transform.rotation.z", layer.rotation or 0.0))
        opacity = float(ovs.get("opacity", layer.opacity if layer.opacity is not None else 1.0))
        bg_color = ovs.get("backgroundColor", layer.backgroundColor)
        scale = layer.scale if layer.scale else 1.0

        next_use_y_up = (not use_y_up) if (layer.geometryFlipped or 0) == 1 else use_y_up
        ap = layer.anchorPoint
        ax = float(ap.x if ap is not None and ap.x is not None else 0.5)
        ay = float(ap.y if ap is not None and ap.y is not None else 0.5)
        rot = rotation * (-1 if next_use_y_up else 1)

        # CSS top/left placement: the box is positioned by its top-left
        # corner, while CAML `position` is the ANCHOR point in parent coords.
        # In a Y-up parent the y coordinate is measured from the BOTTOM of the
        # parent (so walk up to its height), and the box top edge sits
        # (1-ay)*h above the anchor. In a Y-down parent it sits ay*h above.
        anchor_x = x
        anchor_y = (parent_h - y) if use_y_up else y
        if use_y_up:
            box_top_left_dy = -(1.0 - ay) * h
        else:
            box_top_left_dy = -ay * h
        box_top_left_dx = -ax * w - layer.boundsOrigin.x
        box_top_left_dy -= layer.boundsOrigin.y

        filters = [f for f in layer.filters if f.enabled] if layer.filters else []
        blend = _BLEND_MODES.get(layer.blendMode)
        hsl_kind = _HSL_KINDS.get(layer.blendMode)
        need_offscreen = bool(filters) or hsl_kind is not None or (
            blend is not None and blend != _QM.CompositionMode_SourceOver)

        p.save()
        p.translate(anchor_x, anchor_y)
        p.rotate(rot)
        if scale != 1.0:
            p.scale(scale, scale)
        p.translate(box_top_left_dx, box_top_left_dy)

        if need_offscreen:
            off_w = max(1, math.ceil(w))
            off_h = max(1, math.ceil(h))
            cap = self._render_edge
            if max(off_w, off_h) > cap:
                k = cap / max(off_w, off_h)
                off_w = max(1, int(off_w * k))
                off_h = max(1, int(off_h * k))
            cache_key = (id(layer), off_w, off_h, bg_color)
            off = self._offscreen_cache.get(cache_key) if id(layer) in self._static_layers else None
            if off is None:
                off = QImage(off_w, off_h, QImage.Format.Format_ARGB32_Premultiplied)
                off.fill(Qt.GlobalColor.transparent)
                op = QPainter(off)
                try:
                    if off_w != w or off_h != h:
                        op.scale(off_w / w, off_h / h)
                    self._paint_layer_content(op, layer, w, h, next_use_y_up, t_ms, delay_ms, bg_color)
                finally:
                    op.end()
                if filters:
                    off = _apply_filters(off, filters)
                if hsl_kind is not None:
                    off = _hsl_blend(off, hsl_kind)
                if id(layer) in self._static_layers and off.sizeInBytes() <= 16 * 1024 * 1024:
                    while self._offscreen_cache and (len(self._offscreen_cache) >= 128 or
                            self._offscreen_bytes + off.sizeInBytes() > 16 * 1024 * 1024):
                        _, old = self._offscreen_cache.popitem(last=False)
                        self._offscreen_bytes -= old.sizeInBytes()
                    self._offscreen_cache[cache_key] = off
                    self._offscreen_bytes += off.sizeInBytes()
            else:
                self._offscreen_cache.move_to_end(cache_key)
            if blend is not None:
                p.setCompositionMode(blend)
            if opacity < 0.999:
                p.setOpacity(_clamp(opacity, 0.0, 1.0))
            p.drawImage(QRectF(0.0, 0.0, w, h), off)
        else:
            try:
                if opacity < 0.999:
                    p.setOpacity(_clamp(opacity, 0.0, 1.0))
                self._paint_layer_content(p, layer, w, h, next_use_y_up, t_ms, delay_ms, bg_color)
            finally:
                p.restore()
            return

        p.restore()

    def _paint_layer_content(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        next_use_y_up: bool,
        t_ms: float,
        delay_ms: float,
        bg_color: Optional[str],
    ):
        # Clip to the layer box when masksToBounds (rounded when a radius is set).
        if layer.masksToBounds:
            p.save()
            radius = layer.cornerRadius or 0.0
            t = min(radius, w / 2.0, h / 2.0)
            p.setClipPath(_rounded_rect_path(w, h, t))

        corner = min(layer.cornerRadius or 0.0, w / 2.0, h / 2.0)
        is_shape = layer.type == "shape"
        if is_shape and layer.shape == "circle":
            corner = 9999.0
        if layer.type == "shape" and not bg_color and layer.fill:
            bg_color = layer.fill

        # Background fill (all layer kinds honour backgroundColor like the TSX div).
        fill = _hex_color(bg_color, layer.backgroundOpacity if layer.backgroundOpacity is not None else 1.0)
        if fill is not None and fill.alpha() > 0 and not layer.type == "liquidGlass" and bg_color:
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(_rounded_rect_path(w, h, corner))
            p.restore()

        self._paint_inner(p, layer, w, h, next_use_y_up, t_ms, delay_ms)

        # Border (stroke inside the box edge, CSS-style).
        if layer.borderWidth and layer.borderWidth > 0 and layer.borderColor:
            col = _hex_color(layer.borderColor)
            if col is not None:
                p.save()
                pen = QPen(col, float(layer.borderWidth))
                pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                inset = layer.borderWidth / 2.0
                p.drawPath(_rounded_rect_path(w - inset * 2.0, h - inset * 2.0, max(0.0, corner - inset)).translated(inset, inset))
                p.restore()

        if layer.masksToBounds:
            p.restore()

    def _paint_inner(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        use_y_up: bool,
        t_ms: float,
        delay_ms: float,
    ):
        ltype = layer.type
        if ltype == "image":
            img = self._image_for(layer.src)
            if img is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), img)
        elif ltype == "text":
            self._paint_text(p, layer, w, h)
        elif ltype == "gradient":
            self._paint_gradient(p, layer, w, h, t_ms, delay_ms)
        elif ltype == "liquidGlass":
            pass  # rendered fully transparent (per requirements)
        elif ltype == "emitter":
            self._paint_emitter(p, layer, w, h, use_y_up, t_ms)
        elif ltype == "video":
            self._paint_video(p, layer, w, h, t_ms)
        elif ltype == "shape":
            pass  # filled above

        if ltype == "replicator":
            self._paint_replicator_children(p, layer, w, h, use_y_up, t_ms, delay_ms)
        elif ltype == "video":
            if layer.syncWWithState:
                self._paint_video_sync_children(p, layer, w, h)
        else:
            for child in layer.children:
                self._draw_layer(p, child, use_y_up, h, t_ms, delay_ms)

    # -- content renderers -------------------------------------------------- #

    def _paint_text(self, p: QPainter, layer: Layer, w: float, h: float):
        if not layer.text:
            return
        family = layer.fontFamily or "Helvetica Neue"
        size = layer.fontSize or 14.0
        font = QFont()
        font.setFamily(family)
        font.setPixelSize(max(1, int(size)))
        p.setFont(font)
        col = _hex_color(layer.color) or QColor(0, 0, 0)
        p.setPen(col)

        flags = Qt.AlignmentFlag.AlignTop
        align = layer.align or "left"
        if align == "center":
            flags |= Qt.AlignmentFlag.AlignHCenter
        elif align == "right":
            flags |= Qt.AlignmentFlag.AlignRight
        elif align == "justified":
            flags |= Qt.AlignmentFlag.AlignJustify
        else:
            flags |= Qt.AlignmentFlag.AlignLeft
        if (layer.wrapped or 1) == 1:
            flags |= Qt.TextFlag.TextWordWrap.value
        else:
            flags |= Qt.TextFlag.TextSingleLine.value
        p.drawText(QRectF(0.0, 0.0, w, h), int(flags), layer.text)

    def _paint_gradient(self, p: QPainter, layer: Layer, w: float, h: float, t_ms: float, delay_ms: float):
        ovs = layer_animation_overrides(layer.animations, t_ms, delay_ms)
        colors_override = ovs.get("colors")
        resolved: List[GradientColor] = colors_override if colors_override is not None else layer.colors
        if not resolved:
            return
        sp = layer.startPoint or Vec2(0.0, 0.0)
        ep = layer.endPoint or Vec2(1.0, 1.0)
        start_x, start_y = sp.x * 100.0, sp.y * 100.0
        end_x, end_y = ep.x * 100.0, ep.y * 100.0
        grad_type = layer.gradientType or "axial"

        def make_stops(grad, colors, positions):
            for color, pos in zip(colors, positions):
                c = _hex_color(color.color, color.opacity if color.opacity is not None else 1.0)
                if c is not None:
                    grad.setColorAt(pos, c)

        same_point = abs(start_x - end_x) < 0.01 and abs(start_y - end_y) < 0.01
        if same_point:
            first = resolved[0]
            fill = _hex_color(first.color, first.opacity if first.opacity is not None else 1.0)
            if fill is not None:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawRect(QRectF(0.0, 0.0, w, h))
                p.restore()
            return

        n = len(resolved)
        positions = [i / (n - 1) for i in range(n)] if n > 1 else [0.0]

        if grad_type == "radial":
            cx = start_x / 100.0 * w
            cy = (1.0 - start_y / 100.0) * h
            radius = math.hypot(max(cx, w - cx), max(cy, h - cy))
            grad = QRadialGradient(QPointF(cx, cy), max(1.0, radius))
            make_stops(grad, resolved, positions)
        elif grad_type == "conic":
            dx = end_x - start_x
            dy = -(end_y - start_y)
            angle = math.atan2(dy, dx) + math.pi / 2.0
            cx = start_x / 100.0 * w
            cy = (1.0 - start_y / 100.0) * h
            grad = QConicalGradient(QPointF(cx, cy), math.degrees(angle))
            make_stops(grad, resolved, positions)
        else:
            dx = end_x - start_x
            dy = -(end_y - start_y)
            angle_deg = math.degrees(math.atan2(dy, dx)) + 90.0
            rad = math.radians(angle_deg)
            dir_x, dir_y = math.sin(rad), -math.cos(rad)
            cx, cy = 50.0, 50.0
            ts = []
            if abs(dir_x) > 1e-6:
                ts.append((0.0 - cx) / dir_x)
                ts.append((100.0 - cx) / dir_x)
            if abs(dir_y) > 1e-6:
                ts.append((0.0 - cy) / dir_y)
                ts.append((100.0 - cy) / dir_y)
            t0, t1 = min(ts), max(ts)
            sx = (cx + t0 * dir_x) / 100.0 * w
            sy = (cy + t0 * dir_y) / 100.0 * h
            ex2 = (cx + t1 * dir_x) / 100.0 * w
            ey2 = (cy + t1 * dir_y) / 100.0 * h
            grad = QLinearGradient(QPointF(sx, sy), QPointF(ex2, ey2))
            make_stops(grad, resolved, positions)

        p.save()
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(0.0, 0.0, w, h))
        p.restore()

    def _paint_emitter(self, p: QPainter, layer: Layer, w: float, h: float, use_y_up: bool, t_ms: float):
        if not layer.emitterCells:
            return
        ex = layer.emitterPosition.x
        ey = layer.emitterPosition.y
        if use_y_up:
            ey = h - ey
        t = t_ms / 1000.0
        for cell_idx, cell in enumerate(layer.emitterCells):
            img = self._image_for(cell.src) if cell.src else None
            if img is None:
                continue
            s = cell.scale if cell.scale else 1.0
            contents_scale = cell.contentsScale if cell.contentsScale else 1.0
            target_w = max(1, round(img.width() / contents_scale * s))
            target_h = max(1, round(img.height() / contents_scale * s))
            base_alpha = _clamp(cell.alpha, 0.0, 1.0)
            yacc = cell.yAcceleration
            if use_y_up:
                yacc = -yacc
            cache_key = f"{layer.id}|{cell_idx}"
            particles = self._emitter_particles.get(cache_key)
            if particles is None:
                particles = self._build_emitter_particles(cache_key, cell, layer.speed or 1.0)
                self._emitter_particles[cache_key] = particles
            life = max(cell.lifetime or 1.0, 1e-6)
            count = len(particles)
            stagger = life / count
            for i, (angle_jitter, speed_jitter, spin_extra, alpha_jit) in enumerate(particles):
                age = (t - i * stagger) % life
                ang = (cell.emissionLongitude or 0.0) + angle_jitter * (cell.emissionRange or 0.0)
                speed = (cell.velocity or 0.0) + speed_jitter * (cell.velocityRange or 0.0)
                ex_p = ex + math.cos(ang) * speed * age + 0.5 * (cell.xAcceleration or 0.0) * age * age
                eyp_ = ey + math.sin(ang) * speed * age + 0.5 * yacc * age * age
                al = base_alpha * max(0.0, min(1.0, 1.0 - age / life)) * (1.0 + alpha_jit)
                if al <= 0.01:
                    continue
                p.save()
                p.translate(ex_p, eyp_)
                p.rotate(math.degrees((cell.spin or 0.0) * age) + spin_extra)
                p.setOpacity(_clamp(al, 0.0, 1.0))
                p.drawImage(QRectF(-target_w / 2.0, -target_h / 2.0, target_w, target_h), img)
                p.restore()

    def _build_emitter_particles(self, cache_key: str, cell, speed: float = 1.0) -> List[Tuple[float, float, float, float]]:
        count = max(8, min(120, int((cell.birthRate or 0.0) * speed * max(cell.lifetime or 1.0, 1e-6))))
        import hashlib as _hashlib
        digest = _hashlib.md5(cache_key.encode("utf-8", "replace")).digest()
        seed = int.from_bytes(digest[:4], "little")
        jitter = _LCG(seed)
        out = []
        for _ in range(count):
            out.append(
                (
                    jitter.next_float() * 2.0 - 1.0,
                    jitter.next_float() * 2.0 - 1.0,
                    (jitter.next_float() * 2.0 - 1.0) * 30.0,
                    (jitter.next_float() * 2.0 - 1.0) * 0.15,
                )
            )
        return out

    def _paint_video(self, p: QPainter, layer: Layer, w: float, h: float, t_ms: float):
        frame_count = layer.frameCount
        if frame_count <= 0:
            return
        fps = layer.fps or 30.0
        duration = layer.duration if layer.duration else frame_count / fps
        if duration <= 0:
            return
        auto_rev = layer.autoReverses
        local_t = (t_ms / 1000.0) % duration
        if auto_rev:
            cycle = duration * 2.0
            m = (t_ms / 1000.0) % cycle
            local_t = m if m <= duration else (cycle - m)
        frame_index = int(local_t * fps) % frame_count
        img = self._video_frame(layer, frame_index)
        if img is not None:
            p.drawImage(QRectF(0.0, 0.0, w, h), img)

    def _video_frame(self, layer: Layer, index: int) -> Optional[QImage]:
        prefix = layer.framePrefix or f"{layer.id}_frame_"
        ext = layer.frameExtension or ".jpg"
        candidates = [
            f"{prefix}{index}{ext}",
            f"{index}{ext}",
            f"{prefix}{index}",
            f"{layer.id}_frame_{index}{ext}",
        ]
        cache_key = (layer.id, index)
        cached = self._video_frames.get(cache_key)
        if cached is not None:
            return cached
        for name in candidates:
            basename = name.split("/")[-1]
            try:
                decoded = unquote(basename)
            except Exception:
                decoded = basename
            data = self.doc.assets.get(basename) or self.doc.assets.get(decoded)
            if not data:
                continue
            img = decode_image_bytes(data)
            if img is not None and not img.isNull():
                self._video_frames[cache_key] = img
                while len(self._video_frames) > _MAX_VIDEO_FRAMES:
                    self._video_frames.popitem(last=False)
                return img
        return None

    def _paint_video_sync_children(self, p: QPainter, layer: Layer, w: float, h: float):
        children = layer.children
        if not children:
            return
        top_child = max(children, key=lambda c: c.zPosition or 0.0)
        if top_child.type == "image":
            img = None
            for i, child in enumerate(children):
                if child.id == top_child.id:
                    img = self._video_frame(layer, i)
                    break
            if img is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), img)

    def _paint_replicator_children(
        self,
        p: QPainter,
        layer: Layer,
        w: float,
        h: float,
        use_y_up: bool,
        t_ms: float,
        delay_ms: float,
    ):
        count = max(1, layer.instanceCount or 1)
        tx = layer.instanceTranslation.x
        ty = layer.instanceTranslation.y
        flipped = (layer.geometryFlipped or 0) == 1
        ap = layer.anchorPoint
        ax = float(ap.x if ap is not None and ap.x is not None else 0.5)
        ay = float(ap.y if ap is not None and ap.y is not None else 0.5)
        ox = ax * w
        oy = ((1.0 - ay) * h) if use_y_up else (ay * h)
        current_s = t_ms / 1000.0
        for i in range(count):
            if layer.instanceDelay and current_s < i * layer.instanceDelay:
                continue
            txi = tx * i
            tyi = ty * i if flipped else -ty * i
            rot_i = layer.instanceRotation * i
            instance_delay = layer.instanceDelay * 1000.0 * i
            p.save()
            p.translate(ox, oy)
            p.translate(txi, tyi)
            p.rotate(rot_i)
            p.translate(-ox, -oy)
            for child in layer.children:
                self._draw_layer(p, child, use_y_up, h, t_ms, delay_ms + instance_delay)
            p.restore()


# --------------------------------------------------------------------------- #
# Convenience helpers
# --------------------------------------------------------------------------- #

class SceneCompositeRenderer:
    """Render a wallpaper as several scenes composited like the lock screen.

    Photo-style tendies split their art: the ``background`` scene carries the
    full-bleed picture and the ``floating`` scene the animated character. This
    renderer paints the floating scene over the background one so the figure
    sits on its photograph instead of floating alone on an empty canvas.
    """

    def __init__(self, background: Optional[CAMLRenderer], floating: Optional[CAMLRenderer]):
        self._background = background
        self._floating = floating
        if background is not None and floating is not None:
            self.width, self.height = floating.width, floating.height
        elif background is not None:
            self.width, self.height = background.width, background.height
        else:
            self.width, self.height = floating.width, floating.height

    def _composite(self, bg: Optional[QImage], fl: Optional[QImage]) -> QImage:
        w = self.width
        h = self.height
        out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        try:
            if bg is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), bg)
            if fl is not None:
                p.drawImage(QRectF(0.0, 0.0, w, h), fl)
        finally:
            p.end()
        return out

    def render(self, t_ms: float = 0.0) -> QImage:
        bg = self._background.render(t_ms) if self._background is not None else None
        fl = self._floating.render(t_ms) if self._floating is not None else None
        return self._composite(bg, fl)

    def render_state_transition(self, from_state: str = "Locked", to_state: str = "Unlock",
                                progress: float = 0.0, t_ms: float = 0.0) -> QImage:
        bg = self._background.render(t_ms) if self._background is not None else None
        fl = None
        if self._floating is not None:
            fl = self._floating.render_state_transition(from_state, to_state, progress, t_ms)
        return self._composite(bg, fl)


def preview_renderer(bundle, key: str, size: Optional[Tuple[int, int]] = None,
                     state: str = "Locked", bg_state: Optional[str] = None):
    """Build the lock-screen renderer for a tendie bundle.

    Photo-style wallpapers split their art between a ``floating`` scene (the
    animated character) and a ``background`` scene (the full-bleed photo).
    When the preferred scene is :attr:`floating` and a ``background`` scene
    exists, the two are composited exactly like the lock screen shows them:
    floating over background, the floating scene's own root backdrop dropped
    so the opaque solid that pads an otherwise-empty canvas can't hide the
    picture. Single-scene tendies (DVD, Super, Rolling, iOS...) render the
    one scene as today.

    ``bg_state`` optionally overrides the state passed to the composited
    background scene (e.g. ``Lock PortraitUp Dark`` for the photo wallpapers'
    appearance variants) while ``state`` drives the floating scene's lock or
    unlock appearance.
    """
    if key == "floating" and bundle.background is not None:
        bg_doc = bundle.background
        if bg_doc.root is not None and bg_doc.root.children:
            background = CAMLRenderer(bg_doc, size=size, state=bg_state or state)
            floating = CAMLRenderer(bundle.floating, size=size, state=state,
                                    backdrop_fill=False)
            return SceneCompositeRenderer(background, floating)
    doc = getattr(bundle, key, None) or bundle.floating or bundle.background
    return CAMLRenderer(doc, size=size, state=state)


def _appearance_slot_key(name: str) -> Tuple[str, Tuple[str, ...]]:
    """Group a variant state by its lock/sleep/home slot and orientation.

    ``Lock PortraitUp Light`` -> ``("Lock", ("PortraitUp",))``,
    ``Locked Dark`` -> ``("Locked", ())``, ``Sleep LandscapeLeft Dark`` ->
    (``Sleep``, (``LandscapeLeft``,)). The lighter ``Lock``/``Locked`` (and
    ``Unlock``/``Unlocked``) tokens compare equal so a caller asking for
    ``Locked`` matches ``Lock PortraitUp Light``.
    """
    tokens = [t for t in name.split() if t not in ("Light", "Dark")]
    if not tokens:
        return (name, ())
    head = tokens[0]
    head = {"Unlock": "Unlock", "Unlocked": "Unlock"}.get(head, head)
    orientation = tuple(t for t in tokens[1:] if t in
                        ("PortraitUp", "PortraitDown",
                         "LandscapeLeft", "LandscapeRight"))
    return (head, orientation)


def appearance_variant_state(doc: Optional[CADocument], state: Optional[str],
                             dark: bool) -> Optional[str]:
    """Return ``state`` with the Light/Dark appearance swapped for ``doc``.

    Split wallpapers name their variants `<state> Light`/`<state> Dark`
    (Cipher) or `Lock PortraitUp Light`/`Lock PortraitUp Dark` (the photo
    wallpapers, keyed by orientation). The swap preserves the non-appearance
    tokens — orientation, lock/unlock — so ``Lock PortraitUp Light`` becomes
    ``Lock PortraitUp Dark`` and ``Locked`` becomes ``Lock PortraitUp Dark``.
    Returns the input when ``doc`` has no matching variant.
    """
    if state is None or doc is None or not doc.states:
        return state
    states = [str(s) for s in doc.states]
    cur = str(state)
    target = "Dark" if dark else "Light"

    cur_slot, cur_orient = _appearance_slot_key(cur)
    if cur_slot == "Locked":
        cur_slot = "Lock"
    for name in states:
        slot, orient = _appearance_slot_key(name)
        slot = "Lock" if slot == "Locked" else slot
        if slot == cur_slot and orient == cur_orient and target in name:
            return name
    if cur_slot and cur_slot != cur:
        for name in states:
            slot, orient = _appearance_slot_key(name)
            slot = "Lock" if slot == "Locked" else slot
            if slot == cur_slot and target in name:
                return name
    for name in states:
        if target in name and name != cur:
            return name
    return state


def bundle_has_appearance_variants(bundle) -> bool:
    """True when any scene in ``bundle`` offers both a Light and a Dark state."""
    if bundle is None:
        return False
    for doc in (bundle.floating, bundle.background, bundle.wallpaper):
        if doc is None or not doc.states:
            continue
        has_light = any("Light" in str(s) for s in doc.states)
        has_dark = any("Dark" in str(s) for s in doc.states)
        if has_light and has_dark:
            return True
    return False


_EMITTER_AMBIENT_LOOP = 3.0


def document_loop_duration(doc: CADocument) -> float:
    """Seconds of the longest infinite animation cycle (0 = static scene).

    Live ``CAEmitterLayer`` outlets animate even without any ``CAAnimation``
    (falling leaves, drifting particles), so a scene with a live emitter counts
    as motion with a short ambient loop.
    """
    if doc is None or doc.root is None:
        return 0.0
    longest = 0.0

    def walk(layer: Layer):
        nonlocal longest
        longest = max(longest, scene_loop_duration(layer.animations))
        if layer.type == "emitter" and layer.emitterCells:
            longest = max(longest, _EMITTER_AMBIENT_LOOP)
        for child in layer.children:
            walk(child)

    walk(doc.root)
    return longest
