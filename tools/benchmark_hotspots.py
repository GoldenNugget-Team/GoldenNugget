"""Offline synthetic performance probes; no device or user data is accessed.

Run from the repository root: python3 tools/benchmark_hotspots.py
The JSON output measures existing implementations, not proposed replacements.
"""
from __future__ import annotations

import json
import os
import platform
import plistlib
import random
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def measure(function, repeats=3):
    function()  # Warm imports and filesystem caches before the timed samples.
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 3),
            "samples_ms": [round(value, 3) for value in samples]}


def manifest_probe():
    from src.restore.inject import _max_inode_in_manifest

    results = []
    for count in (1000, 10000):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE Files (flags INTEGER, file BLOB)")
            conn.executemany("INSERT INTO Files VALUES (1, ?)", (
                (plistlib.dumps({"$objects": [{}, {"InodeNumber": n}]},
                                fmt=plistlib.FMT_BINARY),)
                for n in range(count)))
            results.append({"rows": count,
                            **measure(lambda: _max_inode_in_manifest(conn))})
    return results


def media_probe():
    from src.restore.afc_media import _write_media_state, media_store_verified

    results = []
    for count in (1000, 3000):
        with tempfile.TemporaryDirectory(prefix="gn-perf-media-") as directory:
            root = Path(directory)
            folder = root / "DCIM" / "100APPLE"
            folder.mkdir(parents=True)
            entries = {}
            for n in range(count):
                name = f"DCIM/100APPLE/IMG_{n:06}.JPG"
                (root / name).write_bytes(b"x")
                entries[name] = 1
            _write_media_state(directory, count, count, 0, entries=entries)

            def verify():
                if not media_store_verified(directory):
                    raise RuntimeError("Synthetic media store failed verification")

            timing = measure(verify)
            calls = {"stat": 0, "lstat": 0}
            original_stat, original_lstat = os.stat, os.lstat

            def counted_stat(*args, **kwargs):
                calls["stat"] += 1
                return original_stat(*args, **kwargs)

            def counted_lstat(*args, **kwargs):
                calls["lstat"] += 1
                return original_lstat(*args, **kwargs)

            with patch.object(os, "stat", counted_stat), patch.object(os, "lstat", counted_lstat):
                verify()
            results.append({"files": count, **timing,
                            "python_os_metadata_calls_per_verify": calls})
    return results


def icon_probe():
    from src.tweaks.icon_themes.icon_themes_tweak import IconThemesTweak

    results = []
    for count in (1000, 5000):
        themes = [SimpleNamespace(bundle_id=f"example.icon.{n}") for n in range(count)]

        def add_all():
            tweak = IconThemesTweak.__new__(IconThemesTweak)
            tweak.themes = []
            for theme in themes:
                tweak.add_theme(theme)

        results.append({"icons": count, **measure(add_all)})
    return results


def state_probe():
    import copy

    from src.controllers.ca.models import Layer
    from src.controllers.ca.render import (
        _layer_index,
        apply_state_overrides,
        interpolated_state_root,
    )

    results = []
    for count in (200, 1000):
        root = Layer(id="root", children=[Layer(id=f"layer-{n}") for n in range(count)])
        # Targets near the end exercise the full recursive ID lookup.
        overrides = {"Locked": [{"targetId": f"layer-{n}",
                                  "keyPath": "opacity", "value": 0.5}
                                 for n in range(count * 4 // 5, count)]}
        working = copy.deepcopy(root)
        index = _layer_index(working)
        overrides['Unlock'] = [dict(item, value=1.0) for item in overrides['Locked']]
        results.append({"layers": count, "overrides": len(overrides["Locked"]),
                        **measure(lambda: apply_state_overrides(root, overrides, "Locked")),
                        "reused_transition": measure(lambda: interpolated_state_root(
                            root, overrides, 'Locked', 'Unlock', 0.5,
                            working_root=working, index=index))})
    return results


def blend_probe():
    import io

    # Import optional dependencies outside the timer; fail visibly if absent.
    import numpy  # noqa: F401
    from PIL import Image  # noqa: F401
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QImage

    from src.controllers.ca.render import _hsl_blend

    width, height = 390, 844
    pixels = bytearray(random.Random(0).randbytes(width * height * 4))
    pixels[3::4] = b"\xff" * (width * height)
    source = QImage(pixels, width, height, width * 4,
                    QImage.Format.Format_RGBA8888).copy()

    def png_roundtrip():
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        if not source.save(buffer, "PNG"):
            raise RuntimeError("Could not encode the synthetic layer")
        buffer.close()
        return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")

    return {"width": width, "height": height,
            "full_blend": measure(lambda: _hsl_blend(source, "hue")),
            "png_roundtrip_only": measure(png_roundtrip)}


def main():
    result = {"environment": {"python": sys.version.split()[0],
                              "platform": platform.platform(),
                              "machine": platform.machine()},
              "method": "median of 3 warm-cache calls; synthetic temporary data",
              "manifest_inode_scan": manifest_probe(),
              "media_verification": media_probe(),
              "icon_batch_add": icon_probe(),
              "scene_state_overrides": state_probe(),
              "hsl_layer_blend": blend_probe()}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
