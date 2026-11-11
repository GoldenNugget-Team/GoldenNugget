"""Reproducible local probes for the rewrite; no device or persistent settings."""
import argparse
import ast
import gc
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types
from pathlib import Path

BASELINE = "HEAD"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.controllers.ca import animate, caml
from src.controllers.ca.models import Animation
from src.restore.afc_transport import MediaEntry
from src.tweaks.posterboard.template_options import templates_tweak


def baseline_source(path):
    return subprocess.check_output(["git", "show", BASELINE + ":" + path], cwd=ROOT, text=True)


def function_from_head(path, name, namespace):
    tree = ast.parse(baseline_source(path))
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(namespace)
    exec(compile(ast.Module([node], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


def median_ms(callback):
    callback()
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        callback()
        timings.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(timings), 3)


def peak_mib(callback):
    gc.collect()
    tracemalloc.start()
    try:
        retained = callback()
        peak = tracemalloc.get_traced_memory()[1]
        del retained
    finally:
        tracemalloc.stop()
    return round(peak / (1024 * 1024), 3)


def main():
    global BASELINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="HEAD", help="Git revision containing the pre-refactor code")
    BASELINE = parser.parse_args().baseline
    baseline_commit = subprocess.check_output(["git", "rev-parse", BASELINE], cwd=ROOT, text=True).strip()
    legacy_caml = function_from_head("src/controllers/ca/caml.py", "parse_ca_document", vars(caml))
    xml = '<caml><CALayer id="root"><sublayers>' + ''.join(
        f'<CALayer id="layer-{i}" opacity="0.5"/>' for i in range(1500)) + '</sublayers></CALayer></caml>'
    assert legacy_caml(xml) == caml.parse_ca_document(xml)

    legacy_animate = types.ModuleType("src.controllers.ca._baseline_animation_probe")
    legacy_animate.__package__ = "src.controllers.ca"
    sys.modules[legacy_animate.__name__] = legacy_animate
    exec(compile(baseline_source("src/controllers/ca/animate.py"), "baseline_animate.py", "exec"),
         vars(legacy_animate))
    tracks = [Animation(keyPath=f"track-{i}", values=list(range(600)),
                        keyTimes=[i / 599 for i in range(600)],
                        durationSeconds=1, infinite=True) for i in range(200)]
    assert legacy_animate.layer_animation_overrides(tracks, 501) == animate.layer_animation_overrides(tracks, 501)

    def legacy_inventory():
        entries = []
        for index in range(100000):
            relative = f"DCIM/100APPLE/IMG_{index:06}.JPG"
            entries.append(("/" + relative, relative,
                            {"st_size": index * 1024, "st_ifmt": "S_IFREG",
                             "st_mtime": "1700000000", "st_birthtime": "1700000000",
                             "st_blocks": "8", "st_nlink": "1"}))
        return entries

    def compact_inventory():
        return [MediaEntry(f"DCIM/100APPLE/IMG_{index:06}.JPG", index * 1024, "1700000000")
                for index in range(100000)]

    legacy_template_method = function_from_head(
        "src/tweaks/posterboard/template_options/templates_tweak.py", "recursive_add", vars(templates_tweak))
    legacy_template = templates_tweak.TemplatesTweak()
    legacy_template.recursive_add = types.MethodType(legacy_template_method, legacy_template)
    current_template = templates_tweak.TemplatesTweak()
    with tempfile.TemporaryDirectory(prefix="gn-rewrite-probe-") as directory:
        container = Path(directory) / "Container"
        container.mkdir()
        for index in range(3):
            with (container / f"video-{index}.mov").open("wb") as stream:
                for _ in range(8):
                    stream.write(b"x" * (1024 * 1024))
        def package(tweak):
            files = []
            tweak.recursive_add("HomeDomain", "HomeDomain", files, directory)
            return files
        template_memory = dict(files=3, bytes=3 * 8 * 1024 * 1024,
            before_peak_mib=peak_mib(lambda: package(legacy_template)),
            after_peak_mib=peak_mib(lambda: package(current_template)))
    result = dict(
        environment=dict(python=sys.version.split()[0], platform=platform.platform()),
        method="median of 3 warm calls; traced Python allocations measured separately; synthetic data",
        baseline_commit=baseline_commit,
        baseline="Git source for animation and template traversal; old five-reader CAML driver with the same current helper functions",
        caml_1500_layers=dict(before_ms=median_ms(lambda: legacy_caml(xml)),
                              after_ms=median_ms(lambda: caml.parse_ca_document(xml))),
        animation_200_tracks_600_keys=dict(before_ms=median_ms(lambda: legacy_animate.layer_animation_overrides(tracks, 501)),
                                          after_ms=median_ms(lambda: animate.layer_animation_overrides(tracks, 501))),
        template_payloads=template_memory,
        afc_inventory_100000_entries=dict(before_peak_mib=peak_mib(legacy_inventory),
                                          after_peak_mib=peak_mib(compact_inventory)),
        limits="No USB/apply timing, full frame painting or total process RSS. AFC marker/local indexes and decoded native Qt memory are outside the inventory allocation probe.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
