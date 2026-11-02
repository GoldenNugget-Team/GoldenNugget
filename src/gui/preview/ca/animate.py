"""Timeline animation evaluation for CAML layers.

Port of CAPlayground's ``hooks/use-layer-animations.ts`` (plus the shared
``cubicBezier`` / ``lerpColor`` helpers): interpolates keyframe animation
values at a given time and returns a flat ``keyPath -> value`` override dict
exactly like the TSX ``animationOverrides`` object consumed by the renderer.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

from .models import Animation, GradientColor, Size, Vec2


def _cubic_bezier(p1x: float, p1y: float, p2x: float, p2y: float):
    NEWTON_ITERATIONS = 4
    NEWTON_MIN_SLOPE = 0.001
    SUBDIVISION_PRECISION = 0.0000001
    SUBDIVISION_MAX_ITERATIONS = 10

    ax = 1.0 - 3.0 * p2x + 3.0 * p1x
    bx = 3.0 * p2x - 6.0 * p1x
    cx = 3.0 * p1x

    ay = 1.0 - 3.0 * p2y + 3.0 * p1y
    by = 3.0 * p2y - 6.0 * p1y
    cy = 3.0 * p1y

    def sample_curve_x(t: float) -> float:
        return ((ax * t + bx) * t + cx) * t

    def sample_curve_y(t: float) -> float:
        return ((ay * t + by) * t + cy) * t

    def sample_curve_derivative_x(t: float) -> float:
        return (3.0 * ax * t + 2.0 * bx) * t + cx

    def solve_curve_x(x: float) -> float:
        t2 = x
        for _ in range(NEWTON_ITERATIONS):
            slope = sample_curve_derivative_x(t2)
            if abs(slope) < NEWTON_MIN_SLOPE:
                break
            current_x = sample_curve_x(t2) - x
            t2 -= current_x / slope

        t0, t1 = 0.0, 1.0
        t2 = x
        if t2 < t0:
            return t0
        if t2 > t1:
            return t1
        for _ in range(SUBDIVISION_MAX_ITERATIONS):
            current_x = sample_curve_x(t2)
            if abs(current_x - x) < SUBDIVISION_PRECISION:
                return t2
            if x > current_x:
                t0 = t2
            else:
                t1 = t2
            t2 = (t1 - t0) * 0.5 + t0
        return t2

    def ease(x: float) -> float:
        if p1x == p1y and p2x == p2y:
            return x
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        return sample_curve_y(solve_curve_x(x))

    return ease


TIMING_FUNCTIONS = {
    "linear": lambda t: t,
    "easeIn": _cubic_bezier(0.42, 0, 1.0, 1.0),
    "easeOut": _cubic_bezier(0, 0, 0.58, 1.0),
    "easeInEaseOut": _cubic_bezier(0.42, 0, 0.58, 1.0),
}


def _build_key_times(count: int, custom: Optional[List[float]] = None, discrete: bool = False) -> List[float]:
    if custom is not None and len(custom) == count:
        return list(custom)
    if discrete:
        return [i / count for i in range(count)]
    if count <= 1:
        return [0.0]
    return [i / (count - 1) for i in range(count)]


@lru_cache(maxsize=256)
def _color_channel(hex_color: str) -> tuple:
    h = hex_color.strip().lstrip("#")
    if len(h) == 8:
        h = h[:6]
    if len(h) != 6:
        return (0.0, 0.0, 0.0)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp_color(a: str, b: str, u: float) -> str:
    ca = _color_channel(a)
    cb = _color_channel(b)
    out = [round(ca[i] + (cb[i] - ca[i]) * u) for i in range(3)]
    return f"#{out[0]:02x}{out[1]:02x}{out[2]:02x}"


@dataclass(frozen=True)
class AnimationTrack:
    key_times: tuple[float, ...]
    ordered: bool

    @classmethod
    def compile(cls, count, key_times, discrete):
        times = tuple(_build_key_times(count, key_times, discrete))
        return cls(times, all(math.isfinite(value) for value in times)
                   and all(a <= b for a, b in zip(times, times[1:])))


def _animation_track(animation):
    key = (id(animation.values), len(animation.values), id(animation.keyTimes),
           animation.calculationMode)
    cached = getattr(animation, '_prepared_track', None)
    if cached is None or cached[0] != key:
        cached = key, AnimationTrack.compile(len(animation.values), animation.keyTimes,
                                              animation.calculationMode == 'discrete')
        animation._prepared_track = cached
    return cached[1]


def interpolate_keyframe(
    keyframes: List[Any],
    autoreverses: bool,
    duration_ms: float,
    speed: float,
    delay_ms: float,
    current_time: float,
    infinite: bool,
    repeat_duration_ms: Optional[float],
    calculation_mode: str = "linear",
    timing_function: str = "linear",
    key_times: Optional[List[float]] = None,
    *, _track: Optional[AnimationTrack] = None,
) -> Any:
    if not keyframes:
        return 0
    if len(keyframes) < 2:
        return keyframes[0]

    is_discrete = calculation_mode == "discrete"
    track = _track or AnimationTrack.compile(len(keyframes), key_times, is_discrete)
    forward_key_times = track.key_times

    if current_time < delay_ms:
        return keyframes[0]

    cycle_ms = duration_ms * 2 if autoreverses else duration_ms
    effective_speed = speed if math.isfinite(speed) and speed > 0 else 1.0
    t_global = (current_time - delay_ms) * effective_speed

    if infinite:
        adjusted_time = t_global % cycle_ms if cycle_ms > 0 else 0.0
    elif repeat_duration_ms is not None and repeat_duration_ms > 0:
        if t_global >= repeat_duration_ms:
            return None
        adjusted_time = t_global % cycle_ms if cycle_ms > 0 else 0.0
    else:
        if t_global >= cycle_ms:
            return None
        adjusted_time = t_global

    easing = TIMING_FUNCTIONS.get(timing_function, TIMING_FUNCTIONS["linear"])

    if not autoreverses:
        normalized = adjusted_time / duration_ms if duration_ms > 0 else 0.0
        eased_key_time = easing(max(0.0, min(1.0, normalized)))
        path = keyframes
        path_key_times = forward_key_times
    else:
        in_forward = adjusted_time < duration_ms
        if in_forward:
            local_time = adjusted_time / duration_ms if duration_ms > 0 else 0.0
            eased_key_time = easing(max(0.0, min(1.0, local_time)))
        else:
            local_time = (adjusted_time - duration_ms) / duration_ms if duration_ms > 0 else 0.0
            eased_key_time = easing(max(0.0, min(1.0, 1.0 - local_time)))
        path = keyframes
        path_key_times = forward_key_times

    if is_discrete:
        if track.ordered:
            discrete_index = bisect_right(path_key_times, eased_key_time) - 1
            if discrete_index < 0:
                discrete_index = len(path) - 1  # preserve the legacy pre-first-key fallback
        else:
            discrete_index = len(path) - 1
            for i in range(len(path) - 1, -1, -1):
                if eased_key_time >= path_key_times[i]:
                    discrete_index = i
                    break
        return path[discrete_index]

    if track.ordered:
        seg_index = max(0, bisect_right(path_key_times, eased_key_time) - 1)
    else:
        seg_index = 0
        while seg_index < len(path_key_times) - 1 and eased_key_time >= path_key_times[seg_index + 1]:
            seg_index += 1
    seg_index = min(seg_index, len(path) - 2)

    a = path[seg_index]
    b = path[seg_index + 1]
    seg_start = path_key_times[seg_index]
    seg_end = path_key_times[seg_index + 1]
    seg_duration = seg_end - seg_start
    seg_progress = (eased_key_time - seg_start) / seg_duration if seg_duration > 0 else 0.0
    u = max(0.0, min(1.0, seg_progress))

    a_is_list = isinstance(a, list)
    b_is_list = isinstance(b, list)
    if a_is_list and b_is_list:
        path_a: List[GradientColor] = a
        path_b: List[GradientColor] = b
        count = min(len(path_a), len(path_b))
        out = []
        for i in range(count):
            sa = path_a[i]
            sb = path_b[i]
            out.append(GradientColor(
                color=lerp_color(sa.color, sb.color, u),
                opacity=sa.opacity + (sb.opacity - sa.opacity) * u,
            ))
        return out
    if isinstance(a, str) or isinstance(b, str):
        if isinstance(a, str) and isinstance(b, str):
            return lerp_color(a, b, u)
        return a if u < 0.5 else b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) + (float(b) - float(a)) * u
    if isinstance(a, dict) and isinstance(b, dict) and "x" in a and "x" in b and "y" in a and "y" in b:
        return Vec2(a["x"] + (b["x"] - a["x"]) * u, a["y"] + (b["y"] - a["y"]) * u)
    if isinstance(a, dict) and isinstance(b, dict) and "w" in a and "w" in b:
        return Size(a["w"] + (b["w"] - a["w"]) * u, a["h"] + (b["h"] - a["h"]) * u)
    return a if u < 0.5 else b


def layer_animation_overrides(
    animations: Optional[List[Animation]],
    current_time: float,
    delay_ms: float = 0.0,
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if not animations:
        return overrides

    for anim in animations:
        if not anim.enabled or not anim.keyPath or not anim.values:
            continue

        value = interpolate_keyframe(
            anim.values,
            anim.autoreverses,
            (anim.durationSeconds or 0.0) * 1000.0,
            anim.speed if anim.speed is not None else 1.0,
            delay_ms,
            current_time,
            anim.infinite,
            anim.repeatDurationSeconds * 1000.0 if anim.repeatDurationSeconds is not None else None,
            anim.calculationMode or "linear",
            anim.timingFunction or "linear",
            anim.keyTimes,
            _track=_animation_track(anim),
        )
        if value is None:
            continue

        if anim.keyPath == "position":
            if isinstance(value, dict):
                value = Vec2(float(value.get("x", 0) or 0), float(value.get("y", 0) or 0))
            overrides["position.x"] = value.x
            overrides["position.y"] = value.y
        elif anim.keyPath == "bounds":
            if isinstance(value, dict):
                value = Size(float(value.get("w", 0) or 0), float(value.get("h", 0) or 0))
            overrides["bounds.size.width"] = value.w
            overrides["bounds.size.height"] = value.h
        elif anim.keyPath == "colors":
            overrides["colors"] = value
        elif anim.keyPath == "backgroundColor":
            overrides["backgroundColor"] = value
        else:
            overrides[anim.keyPath] = value
    return overrides


def scene_loop_duration(animations: Optional[List[Animation]]) -> float:
    """Longest infinite cycle length in seconds (0 when static)."""
    longest = 0.0
    if not animations:
        return 0.0
    for a in animations:
        if a.infinite and a.durationSeconds:
            cycle = a.durationSeconds * 2 if a.autoreverses else a.durationSeconds
            longest = max(longest, cycle)
    return longest