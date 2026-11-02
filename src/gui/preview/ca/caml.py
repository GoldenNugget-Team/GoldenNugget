"""Parse Core Animation Markup Language (CAML) documents.

Faithful port of CAPlayground's ``lib/ca/caml.ts``: parses the layer tree,
wallpaper states, state overrides, state transitions and gyro parallax groups
straight into the :mod:`ca.models` dataclasses. The namespace-agnostic helpers
match the TSX ``getElementsByTagNameNS`` scans, which is exactly how the real
Apple ```.tendies`` files are tokenised.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import Any, List, Optional

from .models import (
    CADocument,
    Animation,
    EmitterCell,
    Filter,
    GradientColor,
    Layer,
    ParallaxGroup,
    Size,
    StateTransition,
    StateTransitionElement,
    Vec2,
    Vec3,
)


def _local(tag) -> str:
    if isinstance(tag, str):
        return tag.split("}")[-1]
    return ""


def _children(el: ET.Element, name: str) -> List[ET.Element]:
    return [c for c in list(el) if _local(c.tag) == name]


def _descendants(el: ET.Element, name: str) -> List[ET.Element]:
    return [c for c in el.iter() if _local(c.tag) == name]


def _top_level_child(el: ET.Element, name: str) -> Optional[ET.Element]:
    """First element with the given local tag anywhere below ``el``.

    Container tags are fully namespaced: ``states`` / ``stateTransitions``
    hang directly off ``CALayer`` rather than off the ``caml`` root, so plain
    child lookups miss them.
    """
    return next((c for c in el.iter() if _local(c.tag) == name), None)


def _attr(el: ET.Element, name: str) -> Optional[str]:
    if el is None:
        return None
    v = el.get(name)
    return None if v is None else v


def _numeric_attr(el: ET.Element, name: str, fallback: Optional[float] = None) -> Optional[float]:
    v = _attr(el, name)
    if v is None or v == "":
        return fallback
    try:
        num = float(v)
    except ValueError:
        return fallback
    return num if math.isfinite(num) else fallback


def _boolean_attr(el: ET.Element, name: str) -> Optional[int]:
    v = _attr(el, name)
    if v is None:
        return None
    return 1 if v in ("1", "true") else 0


def _numbers(input_str: Optional[str]) -> List[float]:
    if not input_str:
        return []
    out = []
    for s in re.split(r"[;\s]+", input_str.strip()):
        if s == "":
            continue
        try:
            out.append(float(s))
        except ValueError:
            continue
    return out


def floats_to_hex_color(rgb: Optional[str]) -> Optional[str]:
    """'0.4 0.5 0.6' (optionally + alpha) -> '#667799'."""
    if not rgb:
        return None
    parts = _numbers(rgb)
    if len(parts) < 3:
        return None
    to255 = lambda f: round(max(0.0, min(1.0, f if math.isfinite(f) else 0.0)) * 255)
    r, g, b = to255(parts[0]), to255(parts[1]), to255(parts[2])
    return f"#{r:02x}{g:02x}{b:02x}"


def _rad_to_deg(rad: float) -> float:
    return rad * 180.0 / math.pi


def _valid_number(v: str, default: float) -> float:
    try:
        n = float(v)
    except ValueError:
        return default
    return n if math.isfinite(n) else default


# --------------------------------------------------------------------------- #
# Layer parsing
# --------------------------------------------------------------------------- #

def _parse_transform_rotations(transform_attr: str):
    rotations: dict = {}
    for m in re.finditer(r"rotate\(([^)]+)\)", transform_attr, re.IGNORECASE):
        inside = m.group(1).strip()
        parts = [p.strip() for p in inside.split(",")]
        angle = _valid_number(re.sub(r"deg", "", parts[0], flags=re.IGNORECASE).strip(), 0.0)
        if len(parts) >= 4:
            try:
                ax = float(parts[1])
                ay = float(parts[2])
                az = float(parts[3])
            except ValueError:
                ax = ay = az = float("nan")
            if abs(ax - 1) < 1e-6 and abs(ay) < 1e-6 and abs(az) < 1e-6:
                rotations["x"] = angle
            elif abs(ay - 1) < 1e-6 and abs(ax) < 1e-6 and abs(az) < 1e-6:
                rotations["y"] = angle
            elif abs(az - 1) < 1e-6 and abs(ax) < 1e-6 and abs(ay) < 1e-6:
                rotations["z"] = angle
        else:
            rotations["z"] = angle
    return rotations


def _parse_transform_scales(transform_attr: str):
    m = re.search(r"scale\(([^)]+)\)", transform_attr)
    if not m:
        return 1.0
    values = [float(v.strip()) if v.strip() else 1.0 for v in m.group(1).split(",")]
    return values[0] if values else 1.0


def _parse_layer_base(el: ET.Element) -> Layer:
    layer = Layer()
    layer.id = _attr(el, "id") or _attr(el, "name") or "layer"
    # CAPlayground uses a random UUID when id is missing; deterministic-ish here.
    layer.name = _attr(el, "name") or "Layer"

    bounds = _numbers(_attr(el, "bounds"))
    position = _numbers(_attr(el, "position"))
    anchor = _numbers(_attr(el, "anchorPoint"))

    layer.position.x = position[0] if len(position) > 0 else 0.0
    layer.position.y = position[1] if len(position) > 0 else 0.0
    layer.boundsOrigin.x = bounds[0] if len(bounds) > 0 else 0.0
    layer.boundsOrigin.y = bounds[1] if len(bounds) > 0 else 0.0
    layer.size.w = bounds[2] if len(bounds) > 2 else 0.0
    layer.size.h = bounds[3] if len(bounds) > 3 else 0.0
    layer.zPosition = _numeric_attr(el, "zPosition") or 0.0
    layer.opacity = _numeric_attr(el, "opacity") or 1.0
    layer.cornerRadius = _numeric_attr(el, "cornerRadius") or 0.0

    rotation_z = _numeric_attr(el, "transform.rotation.z") or 0.0
    rotation_x = _numeric_attr(el, "transform.rotation.x")
    rotation_y = _numeric_attr(el, "transform.rotation.y")
    layer.rotation = _rad_to_deg(rotation_z)
    layer.rotationX = _rad_to_deg(rotation_x) if rotation_x is not None else 0.0
    layer.rotationY = _rad_to_deg(rotation_y) if rotation_y is not None else 0.0

    if len(anchor) >= 2 and (anchor[0] != 0.5 or anchor[1] != 0.5):
        layer.anchorPoint = Vec2(anchor[0], anchor[1])
    layer.geometryFlipped = _boolean_attr(el, "geometryFlipped") or 0
    layer.masksToBounds = _boolean_attr(el, "masksToBounds") or 0
    layer.scale = 1.0
    layer.speed = _numeric_attr(el, "speed", 1.0)

    transform_attr = _attr(el, "transform") or ""
    if re.search(r"rotate\(", transform_attr, re.IGNORECASE):
        rotations = _parse_transform_rotations(transform_attr)
        if "z" in rotations and layer.rotation == 0:
            layer.rotation = rotations["z"]
        if "x" in rotations and layer.rotationX == 0:
            layer.rotationX = rotations["x"]
        if "y" in rotations and layer.rotationY == 0:
            layer.rotationY = rotations["y"]
    if re.search(r"scale\(", transform_attr, re.IGNORECASE):
        layer.scale = _parse_transform_scales(transform_attr)

    compositing = _children(el, "compositingFilter")
    if compositing:
        blend_mode = _attr(compositing[0], "filter") or "normal"
        if blend_mode in _SUPPORTED_BLEND_MODES:
            layer.blendMode = blend_mode

    filters_el = _children(el, "filters")
    if filters_el:
        parsed: List[Filter] = []
        for ca_filter in _descendants(filters_el[0], "CAFilter") + _descendants(filters_el[0], "CIFilter"):
            filter_type = _attr(ca_filter, "filter")
            if not filter_type:
                continue
            filter_name = _attr(ca_filter, "name")
            enabled = _attr(ca_filter, "enabled") != "0"
            value = 0.0
            if filter_type == "gaussianBlur":
                value = _numeric_attr(ca_filter, "inputRadius") or 0.0
            elif filter_type in ("colorContrast", "colorSaturate"):
                value = _numeric_attr(ca_filter, "inputAmount") or 1.0
            elif filter_type == "colorHueRotate":
                value = _rad_to_deg(_numeric_attr(ca_filter, "inputAngle") or 0.0)
            elif filter_type == "CISepiaTone":
                intensity = _children(ca_filter, "inputIntensity")
                value = _numeric_attr(intensity[0], "value") if intensity else 1.0
            parsed.append(Filter(name=filter_name or "Filter", type=filter_type, enabled=enabled, value=value))
        layer.filters = parsed
    return layer


_SUPPORTED_BLEND_MODES = {
    "normalBlendMode", "colorBlendMode", "colorBurnBlendMode", "colorDodgeBlendMode",
    "darkenBlendMode", "differenceBlendMode", "exclusionBlendMode", "hueBlendMode",
    "lightenBlendMode", "luminosityBlendMode", "multiplyBlendMode", "overlayBlendMode",
    "saturationBlendMode", "screenBlendMode",
}


def _parse_animations(el: ET.Element) -> List[Animation]:
    parsed: List[Animation] = []
    animations_el = _children(el, "animations")
    if not animations_el:
        return parsed
    anim_nodes = _descendants(animations_el[0], "animation") + _descendants(animations_el[0], "p")
    for anim_node in anim_nodes:
        kp = _attr(anim_node, "keyPath") or "position"
        values_node = _children(anim_node, "values")
        vals: List[Any] = []
        if values_node:
            vn = values_node[0]
            if kp == "backgroundColor":
                for c in _descendants(vn, "CGColor"):
                    parts = _numbers(_attr(c, "value"))
                    if len(parts) >= 3:
                        r = round(parts[0] * 255)
                        g = round(parts[1] * 255)
                        b = round(parts[2] * 255)
                        vals.append(f"#{r:02x}{g:02x}{b:02x}")
            elif kp == "position":
                for p in _descendants(vn, "CGPoint"):
                    parts = _numbers(_attr(p, "value"))
                    x = round(parts[0]) if len(parts) > 0 and math.isfinite(parts[0]) else 0
                    y = round(parts[1]) if len(parts) > 1 and math.isfinite(parts[1]) else 0
                    vals.append({"x": x, "y": y})
            elif kp in ("position.x", "position.y"):
                for n in list(vn):
                    v = _attr(n, "value")
                    if v is None:
                        continue
                    num = _valid_number(v, 0.0)
                    vals.append(round(num) if math.isfinite(num) else 0)
            elif kp in ("transform.rotation.x", "transform.rotation.y", "transform.rotation.z"):
                for n in list(vn):
                    v = _attr(n, "value")
                    if v is None:
                        continue
                    rad = _valid_number(v, 0.0)
                    vals.append(rad * 180.0 / math.pi)
            elif kp == "opacity":
                for n in _descendants(vn, "real"):
                    v = _attr(n, "value")
                    if v is None:
                        continue
                    vals.append(_valid_number(v, 1.0))
            elif kp == "bounds":
                for r in _descendants(vn, "CGRect"):
                    parts = _numbers(_attr(r, "value"))
                    w = round(parts[2]) if len(parts) > 2 and math.isfinite(parts[2]) else 0
                    h = round(parts[3]) if len(parts) > 3 and math.isfinite(parts[3]) else 0
                    vals.append({"w": w, "h": h})
            elif kp == "colors":
                for arr in _descendants(vn, "NSArray"):
                    stops = []
                    for cgc in _descendants(arr, "CGColor"):
                        value = _attr(cgc, "value")
                        opacity = _attr(cgc, "opacity")
                        hex_color = floats_to_hex_color(value) or "#000000"
                        stops.append({"color": hex_color, "opacity": _valid_number(opacity, 1.0) if opacity else 1.0})
                    vals.append(stops)
            elif kp == "hidden":
                for n in list(vn):
                    v = _attr(n, "value")
                    if v is None:
                        continue
                    vals.append(1 if v in ("1", "true") else 0)
            else:
                # generic: single real values (width/height scales etc.)
                for n in list(vn):
                    v = _attr(n, "value")
                    if v is None:
                        continue
                    num = _valid_number(v, 0.0)
                    if math.isfinite(num):
                        vals.append(num)

        key_times_node = _children(anim_node, "keyTimes")
        key_times = []
        if key_times_node:
            key_times = [_valid_number(_attr(k, "value") or "", 0.0) for k in list(key_times_node[0])]
        if len(key_times) > len(vals):
            key_times = key_times[: len(vals)]

        enabled = len(vals) > 0
        autorev = _attr(anim_node, "autoreverses")
        autoreverses = (_valid_number(autorev, 0.0) if autorev else 0.0) != 0.0
        dur_attr = _attr(anim_node, "duration")
        try:
            duration_seconds = float(dur_attr) if dur_attr else 0.0
        except ValueError:
            duration_seconds = 0.0
        speed_attr = _attr(anim_node, "speed")
        speed = _valid_number(speed_attr, 1.0) if speed_attr else None
        rep_count = _attr(anim_node, "repeatCount")
        rep_dur_attr = _attr(anim_node, "repeatDuration")
        infinite = rep_count == "inf" or rep_dur_attr == "inf"
        repeat_duration_seconds = None
        if not infinite and rep_dur_attr is not None:
            try:
                rep_dur = float(rep_dur_attr)
                if math.isfinite(rep_dur):
                    repeat_duration_seconds = rep_dur
            except ValueError:
                pass
        calc_mode_attr = _attr(anim_node, "calculationMode")
        timing_attr = _attr(anim_node, "timingFunction")
        calculation_mode = calc_mode_attr if calc_mode_attr in ("linear", "discrete") else "linear"
        timing_function = timing_attr if timing_attr in ("linear", "easeIn", "easeOut", "easeInEaseOut") else "linear"

        parsed.append(Animation(
            keyPath=kp,
            values=vals,
            keyTimes=key_times,
            enabled=enabled,
            autoreverses=autoreverses,
            durationSeconds=duration_seconds,
            infinite=infinite,
            repeatDurationSeconds=repeat_duration_seconds,
            speed=speed,
            calculationMode=calculation_mode,
            timingFunction=timing_function,
        ))
    return parsed


def _parse_sublayers(el: ET.Element) -> List[Layer]:
    sublayers_el = _children(el, "sublayers")
    children: List[Layer] = []
    if not sublayers_el:
        return children
    for n in sublayers_el[0]:
        tag = _local(n.tag)
        if tag == "CALayer":
            children.append(_parse_ca_layer(n))
        elif tag == "CATextLayer":
            children.append(_parse_ca_text_layer(n))
        elif tag == "CAGradientLayer":
            children.append(_parse_ca_gradient_layer(n))
        elif tag == "CAEmitterLayer":
            children.append(_parse_ca_emitter_layer(n))
        elif tag == "CATransformLayer":
            children.append(_parse_ca_transform_layer(n))
        elif tag == "CAReplicatorLayer":
            children.append(_parse_ca_replicator_layer(n))
        elif tag == "CABackdropLayer" and (_attr(n, "caplayKind") or _attr(n, "caplay.kind")) == "liquidGlass":
            children.append(_parse_ca_liquid_glass_layer(n))
    return children


def _parse_ca_video_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    children = _parse_sublayers(el)

    frame_count_attr = _attr(el, "caplayFrameCount") or _attr(el, "caplay.frameCount")
    fps_attr = _attr(el, "caplayFPS") or _attr(el, "caplay.fps")
    duration_attr = _attr(el, "caplayDuration") or _attr(el, "caplay.duration")
    auto_rev_attr = _attr(el, "caplayAutoReverses") or _attr(el, "caplay.autoReverses")
    prefix_attr = _attr(el, "caplayFramePrefix") or _attr(el, "caplay.framePrefix")
    ext_attr = _attr(el, "caplayFrameExtension") or _attr(el, "caplay.frameExtension")
    sync_w_attr = _attr(el, "caplaySyncWWithState")

    frame_count = int(float(frame_count_attr)) if frame_count_attr else None
    fps = float(fps_attr) if fps_attr else None
    duration = float(duration_attr) if duration_attr else None
    auto_reverses = auto_rev_attr in ("1", "true")
    sync_w_with_state = sync_w_attr in ("1", "true")

    frame_refs: List[str] = []
    animations_el = _children(el, "animations")
    if animations_el:
        anim_nodes = _descendants(animations_el[0], "animation")
        if anim_nodes:
            values_node = _children(anim_nodes[0], "values")
            if values_node:
                for img in _descendants(values_node[0], "CGImage"):
                    src = _attr(img, "src")
                    if src:
                        frame_refs.append(src)
            if not frame_count and frame_refs:
                frame_count = len(frame_refs)
            if not duration:
                dur_attr = _attr(anim_nodes[0], "duration")
                if dur_attr:
                    try:
                        duration = float(dur_attr)
                    except ValueError:
                        pass
            cm = (_attr(anim_nodes[0], "calculationMode") or "").lower()
            if cm in ("linear", "discrete"):
                base.calculationMode = cm  # type: ignore[attr-defined]

    contents = _children(el, "contents")
    first_frame_el = _descendants(contents[0], "CGImage") if contents else None
    first_frame_src = _attr(first_frame_el[0], "src") if first_frame_el else None
    contents_src_attr = None
    if contents and (_attr(contents[0], "type") or "").lower() == "cgimage":
        contents_src_attr = _attr(contents[0], "src")

    frame_prefix = prefix_attr or None
    frame_extension = ext_attr or None
    first_reference = (frame_refs[0] if frame_refs else None) or first_frame_src or contents_src_attr
    if first_reference:
        file_name = first_reference.split("/")[-1]
        m = re.match(r"^(.*?)(\d+)(\.[a-z0-9]+)$", file_name, re.IGNORECASE)
        if m:
            if not frame_prefix:
                frame_prefix = m.group(1)
            if not frame_extension:
                frame_extension = m.group(3)
        elif "." in file_name:
            if not frame_extension:
                frame_extension = file_name[file_name.rfind("."):]
            if not frame_prefix:
                frame_prefix = file_name[: file_name.rfind(".")]
    frame_prefix = frame_prefix or f"{base.id}_frame_"
    frame_extension = frame_extension or ".jpg"

    base.type = "video"
    base.frameCount = max(0, int(frame_count or 0))
    if fps is not None:
        base.fps = fps
    if duration is not None:
        base.duration = duration
    base.autoReverses = auto_reverses
    base.framePrefix = frame_prefix
    base.frameExtension = frame_extension
    base.syncWWithState = sync_w_with_state
    base.children = children
    base.animations = _parse_animations(el)
    return base


def _parse_ca_text_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)

    font_el = _descendants(el, "font")
    if font_el:
        base.fontFamily = _attr(font_el[0], "value") or base.fontFamily
    string_el = _descendants(el, "string")
    if string_el:
        base.text = _attr(string_el[0], "value") or ""
    base.color = floats_to_hex_color(_attr(el, "foregroundColor"))
    if _attr(el, "fontSize") is not None:
        try:
            base.fontSize = float(_attr(el, "fontSize"))
        except ValueError:
            base.fontSize = None
    base.align = _attr(el, "alignmentMode")
    wrapped_attr = _attr(el, "wrapped")
    if wrapped_attr is not None:
        base.wrapped = 1 if wrapped_attr == "1" else 0
    base.type = "text"
    base.animations = _parse_animations(el)
    return base


def _parse_ca_gradient_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)

    start = _numbers(_attr(el, "startPoint"))
    end = _numbers(_attr(el, "endPoint"))
    base.startPoint = Vec2(start[0] if len(start) > 0 else 0.0, start[1] if len(start) > 1 else 0.0)
    base.endPoint = Vec2(end[0] if len(end) > 0 else 1.0, end[1] if len(end) > 1 else 1.0)

    colors_el = _descendants(el, "colors")
    if colors_el:
        for cg_color in _children(colors_el[0], "CGColor"):
            opacity = _attr(cg_color, "opacity")
            base.colors.append(GradientColor(
                color=floats_to_hex_color(_attr(cg_color, "value")) or "#000000",
                opacity=_valid_number(opacity, 1.0) if opacity else 1.0,
            ))

    type_el = _descendants(el, "type")
    if type_el:
        type_value = _attr(type_el[0], "value")
        if type_value in ("radial", "conic"):
            base.gradientType = type_value
    base.type = "gradient"
    base.animations = _parse_animations(el)
    return base


def _parse_ca_emitter_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    emitter_position = _numbers(_attr(el, "emitterPosition"))
    emitter_size = _numbers(_attr(el, "emitterSize"))
    base.emitterPosition = Vec2(emitter_position[0] if len(emitter_position) > 0 else 0.0,
                                emitter_position[1] if len(emitter_position) > 1 else 0.0)
    base.emitterSize = Size(emitter_size[0] if len(emitter_size) > 0 else 0.0,
                            emitter_size[1] if len(emitter_size) > 1 else 0.0)
    base.renderMode = _attr(el, "renderMode") or "unordered"
    base.emitterShape = _attr(el, "emitterShape") or "point"
    base.emitterMode = _attr(el, "emitterMode") or "volume"

    cells_el = _children(el, "emitterCells")
    if cells_el:
        for c in list(cells_el[0]):
            contents = _children(c, "contents")
            image_src = None
            if contents:
                images = _descendants(contents[0], "CGImage")
                if images:
                    image_src = _attr(images[0], "src")
                else:
                    t = (_attr(contents[0], "type") or "").lower()
                    s = _attr(contents[0], "src") or ""
                    if t == "cgimage" and s:
                        image_src = s
            cell = EmitterCell()
            cell.id = _attr(c, "id") or _attr(c, "name") or "cell"
            cell.name = _attr(c, "name")
            cell.src = image_src
            color_attr = _attr(c, "color")
            if color_attr:
                cell.color = floats_to_hex_color(color_attr) or color_attr
            color_child = _children(c, "color")
            if color_child:
                v = _attr(color_child[0], "value")
                op = _attr(color_child[0], "opacity")
                hex_color = floats_to_hex_color(v)
                if hex_color:
                    cell.color = hex_color
                op_num = _valid_number(op, float("nan")) if op else float("nan")
                if math.isfinite(op_num):
                    cell.alpha = op_num
            cell.contentsScale = _valid_number(_attr(c, "contentsScale") or "", 1.0)
            cell.birthRate = _valid_number(_attr(c, "birthRate") or "", 0.0)
            cell.lifetime = _valid_number(_attr(c, "lifetime") or "", 0.0)
            cell.velocity = _valid_number(_attr(c, "velocity") or "", 0.0)
            cell.scale = _valid_number(_attr(c, "scale") or "", 1.0)
            cell.scaleRange = _valid_number(_attr(c, "scaleRange") or "", 0.0)
            cell.scaleSpeed = _valid_number(_attr(c, "scaleSpeed") or "", 0.0)
            cell.alphaRange = _valid_number(_attr(c, "alphaRange") or "", 0.0)
            cell.alphaSpeed = _valid_number(_attr(c, "alphaSpeed") or "", 0.0)
            cell.emissionRange = _rad_to_deg(_valid_number(_attr(c, "emissionRange") or "", 0.0))
            cell.emissionLongitude = _rad_to_deg(_valid_number(_attr(c, "emissionLongitude") or "", 0.0))
            cell.emissionLatitude = _rad_to_deg(_valid_number(_attr(c, "emissionLatitude") or "", 0.0))
            cell.spin = _rad_to_deg(_valid_number(_attr(c, "spin") or "", 0.0))
            cell.spinRange = _rad_to_deg(_valid_number(_attr(c, "spinRange") or "", 0.0))
            cell.xAcceleration = _valid_number(_attr(c, "xAcceleration") or "", 0.0)
            cell.yAcceleration = _valid_number(_attr(c, "yAcceleration") or "", 0.0)
            for key in ("redRange", "greenRange", "blueRange", "redSpeed", "greenSpeed", "blueSpeed"):
                setattr(cell, key, _valid_number(_attr(c, key) or "", 0.0))
            base.emitterCells.append(cell)
    base.type = "emitter"
    return base


def _parse_ca_transform_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)
    sublayer_transform = _attr(el, "sublayerTransform")
    m = re.search(r"perspective\(([^)]+)\)", sublayer_transform or "")
    base.perspective = float(m.group(1)) if m else None
    base.type = "transform"
    base.animations = _parse_animations(el)
    return base


def _parse_ca_replicator_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)
    base.instanceCount = int(_numeric_attr(el, "instanceCount") or 1)
    base.instanceDelay = _numeric_attr(el, "instanceDelay") or 0.0

    instance_transform = _attr(el, "instanceTransform")
    if instance_transform:
        m = re.search(r"translate\s*\(\s*([^,)]+)\s*,\s*([^,)]+)\s*,\s*([^,)]+)\s*\)", instance_transform)
        if m:
            try:
                t = [float(x.strip()) for x in m.groups()]
            except ValueError:
                t = [0.0, 0.0, 0.0]
            base.instanceTranslation = Vec3(*(t[:3] if len(t) == 3 else [0.0, 0.0, 0.0]))
        rm = re.search(r"rotate\s*\(\s*([^)]+)deg\s*\)", instance_transform, re.IGNORECASE)
        if rm:
            try:
                base.instanceRotation = float(rm.group(1))
            except ValueError:
                base.instanceRotation = 0.0
    sublayer_transform = _attr(el, "sublayerTransform")
    m = re.search(r"perspective\(([^)]+)\)", sublayer_transform or "")
    base.perspective = float(m.group(1)) if m else None
    base.type = "replicator"
    base.animations = _parse_animations(el)
    return base


def _parse_ca_liquid_glass_layer(el: ET.Element) -> Layer:
    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)
    base.type = "liquidGlass"
    base.animations = _parse_animations(el)
    return base


def _parse_contents_image(el: ET.Element) -> Optional[str]:
    contents = _children(el, "contents")
    if not contents:
        return None
    images = _descendants(contents[0], "CGImage")
    if images:
        return _attr(images[0], "src")
    t = (_attr(contents[0], "type") or "").lower()
    s = _attr(contents[0], "src") or ""
    if t == "cgimage" and s:
        return s
    return None


def _parse_ca_layer(el: ET.Element) -> Layer:
    kind = _attr(el, "caplayKind") or _attr(el, "caplay.kind")
    if kind == "video":
        return _parse_ca_video_layer(el)

    base = _parse_layer_base(el)
    base.children = _parse_sublayers(el)

    bg_attr = _attr(el, "backgroundColor")
    if bg_attr:
        base.backgroundColor = floats_to_hex_color(bg_attr) or bg_attr
    bg_children = _descendants(el, "backgroundColor")
    if bg_children:
        v = _attr(bg_children[0], "value")
        op = _attr(bg_children[0], "opacity")
        hex_color = floats_to_hex_color(v)
        if hex_color:
            base.backgroundColor = hex_color
        op_num = _valid_number(op, float("nan")) if op else float("nan")
        if math.isfinite(op_num):
            base.backgroundOpacity = op_num

    border_raw = _attr(el, "borderColor")
    base.borderColor = floats_to_hex_color(border_raw) or border_raw
    if _attr(el, "borderWidth") is not None:
        try:
            base.borderWidth = float(_attr(el, "borderWidth"))
        except ValueError:
            base.borderWidth = None

    image_src = _parse_contents_image(el)
    base.src = image_src
    base.type = "image" if image_src else (_attr(el, "type") or "shape")
    base.animations = _parse_animations(el)
    return base


# --------------------------------------------------------------------------- #
# Top-level document parsing
# --------------------------------------------------------------------------- #

def _parse_xml(xml: str | ET.Element) -> Optional[ET.Element]:
    if isinstance(xml, ET.Element):
        return xml
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def _get_caml_root(xml: str) -> Optional[ET.Element]:
    caml = _parse_xml(xml)
    if caml is None:
        return None
    if _local(caml.tag) == "caml":
        return caml
    for c in list(caml):
        if _local(c.tag) == "caml":
            return c
    return caml


def parse_states(xml: str) -> List[str]:
    caml = _get_caml_root(xml)
    if caml is None:
        return []
    if _descendants(caml, "wallpaperPropertyGroups"):
        return ["Locked", "Unlock", "Sleep"]
    states_el = _top_level_child(caml, "states")
    if states_el is None:
        return []
    out = []
    for n in _descendants(states_el, "LKState"):
        name = _attr(n, "name")
        if name and name.strip():
            out.append(name.strip())
    return out


def parse_state_overrides(xml: str) -> dict:
    result: dict = {}
    caml = _get_caml_root(xml)
    if caml is None:
        return result
    wallpaper_groups = _descendants(caml, "wallpaperPropertyGroups")
    if wallpaper_groups:
        for d in _descendants(wallpaper_groups[0], "NSDictionary"):
            layer_name_el = _children(d, "layerName")
            layer_name = _attr(layer_name_el[0], "value") if layer_name_el else ""
            layer = None
            for el in caml.iter():
                if _attr(el, "name") == layer_name:
                    layer = el
                    break
            target_id = _attr(layer, "id") or "" if layer is not None else ""
            key_path_el = _children(d, "keyPath")
            key_path = _attr(key_path_el[0], "value") if key_path_el else ""

            def _prop(name: str) -> float:
                el = _children(d, name)
                if not el:
                    return 0.0
                return _valid_number(_attr(el[0], "value") or "", float("nan"))

            is_rotation = key_path in ("transform.rotation.z", "transform.rotation.x", "transform.rotation.y")
            locked_v, home_v, sleep_v = _prop("v_lock"), _prop("v_home"), _prop("v_sleep")
            if is_rotation:
                locked_v = _rad_to_deg(locked_v)
                home_v = _rad_to_deg(home_v)
                sleep_v = _rad_to_deg(sleep_v)
            result.setdefault("Locked", []).append({"targetId": target_id, "keyPath": key_path, "value": locked_v})
            result.setdefault("Unlock", []).append({"targetId": target_id, "keyPath": key_path, "value": home_v})
            result.setdefault("Sleep", []).append({"targetId": target_id, "keyPath": key_path, "value": sleep_v})
    else:
        states_el = _top_level_child(caml, "states")
        if states_el is None:
            return result
        for state_node in _descendants(states_el, "LKState"):
            name = _attr(state_node, "name") or ""
            elements_el = _children(state_node, "elements")
            arr: List[dict] = []
            if elements_el:
                for sn in _descendants(elements_el[0], "LKStateSetValue"):
                    target_id = _attr(sn, "targetId") or ""
                    key_path = _attr(sn, "keyPath") or ""
                    val: Any = ""
                    value_nodes = _children(sn, "value")
                    if value_nodes:
                        vtype = _attr(value_nodes[0], "type") or ""
                        v_attr = _attr(value_nodes[0], "value") or ""
                        if v_attr == "undefined":
                            continue
                        if str(vtype).lower() in ("integer", "float", "real", "number"):
                            n = _valid_number(v_attr, float("nan"))
                            val = v_attr if not math.isfinite(n) else n
                        elif vtype == "CGColor":
                            val = floats_to_hex_color(v_attr) or "#ffffff"
                        else:
                            val = v_attr
                    if isinstance(val, (int, float)):
                        if key_path in ("transform.rotation.z", "transform.rotation.x", "transform.rotation.y"):
                            val = _rad_to_deg(float(val))
                    if target_id and key_path:
                        arr.append({"targetId": target_id, "keyPath": key_path, "value": val})
            if name:
                result[name] = arr
    return result


def parse_state_transitions(xml: str) -> List[StateTransition]:
    out: List[StateTransition] = []
    caml = _get_caml_root(xml)
    if caml is None:
        return out
    trans_el = _top_level_child(caml, "stateTransitions")
    if trans_el is None:
        return out
    for tn in _descendants(trans_el, "LKStateTransition"):
        st = StateTransition(fromState=_attr(tn, "fromState") or "", toState=_attr(tn, "toState") or "")
        elements_el = _children(tn, "elements")
        if elements_el:
            for en in _descendants(elements_el[0], "LKStateTransitionElement"):
                elem = StateTransitionElement(targetId=_attr(en, "targetId") or "", keyPath=_attr(en, "key") or "")
                anim_el = _children(en, "animation")
                if anim_el:
                    a = anim_el[0]
                    elem.animationType = _attr(a, "type") or ""
                    elem.damping = _numeric_attr(a, "damping")
                    elem.mass = _numeric_attr(a, "mass")
                    elem.stiffness = _numeric_attr(a, "stiffness")
                    elem.velocity = _numeric_attr(a, "velocity")
                    elem.duration = _numeric_attr(a, "duration")
                if elem.targetId and elem.keyPath:
                    st.elements.append(elem)
        out.append(st)
    return out


def parse_wallpaper_parallax_groups(xml: str) -> List[ParallaxGroup]:
    result: List[ParallaxGroup] = []
    caml = _get_caml_root(xml)
    if caml is None:
        return result
    root_layers = _descendants(caml, "CALayer")
    if not root_layers:
        return result
    style = _children(root_layers[0], "style")
    if not style:
        return result
    groups = _descendants(style[0], "wallpaperParallaxGroups")
    if not groups:
        return result
    layer_names = {_attr(el, "name") for el in caml.iter() if _attr(el, "name")}
    for d in _descendants(groups[0], "NSDictionary"):
        layer_name_el = _children(d, "layerName")
        layer_name = _attr(layer_name_el[0], "value") if layer_name_el else ""
        if layer_name not in layer_names:
            continue
        pg = ParallaxGroup(layerName=layer_name)

        def read(key: str, default: str) -> str:
            el = _children(d, key)
            return _attr(el[0], "value") if el else default

        pg.axis = read("axis", "x")
        pg.image = read("image", "null")
        pg.keyPath = read("keyPath", "position.x")
        pg.mapMaxTo = _valid_number(read("mapMaxTo", ""), 0.0)
        pg.mapMinTo = _valid_number(read("mapMinTo", ""), 0.0)
        pg.title = read("title", "")
        pg.view = read("view", "Floating")
        result.append(pg)
    return result


def parse_caml(xml: str) -> Optional[Layer]:
    caml = _get_caml_root(xml)
    if caml is None:
        return None
    root_layers = _descendants(caml, "CALayer")
    if not root_layers:
        return None
    root = root_layers[0]
    if _attr(root, "id") == "__capRootLayer__":
        inner = [c for c in list(root) if _local(c.tag) == "CALayer"]
        if inner:
            root = inner[0]
    return _parse_ca_layer(root)


def parse_ca_document(xml: str) -> Optional[CADocument]:
    # All readers share one parsed tree, including namespaced wrappers.
    caml = _get_caml_root(xml)
    if caml is None:
        return None
    root = parse_caml(caml)
    if root is None:
        return None
    doc = CADocument()
    doc.root = root
    doc.states = parse_states(caml)
    doc.stateOverrides = parse_state_overrides(caml)
    doc.stateTransitions = parse_state_transitions(caml)
    doc.parallax = parse_wallpaper_parallax_groups(caml)
    return doc