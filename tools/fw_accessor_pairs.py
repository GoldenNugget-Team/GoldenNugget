#!/usr/bin/env python3
"""Extract the SpringBoard-style ``accessor \\0 key \\0`` tables from a dyld
shared cache, per dylib, and diff two caches.

This is the precision half of the firmware reverse-engineering workflow
(``fw_key_scan.py`` is the wide net). The SpringBoard preference table is a
flat run of NUL-separated C strings in which an accessor selector sits
directly next to the key it drives:

    ... shouldDisableDockSpecular \\0 SBDisableDockSpecular \\0 ...

A key with an adjacent accessor ("STRICT") is a key the framework itself
reads through a generated class method - the strongest evidence available
short of an on-device A/B test. A key with no neighbour ("loose") is weaker:
it exists as a literal but nothing in this table claims to read it.

Usage
    # extract one cache
    python tools/fw_accessor_pairs.py <cache> --image SpringBoardFoundation \
        --out docs/data/pairs_27.1.txt

    # diff two caches: keys present in the new one only
    python tools/fw_accessor_pairs.py <old-cache> <new-cache> \
        --image SpringBoardFoundation --diff-out docs/data/pairs_new.txt
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# TemplateBuilder lives outside the repo (same convention as
# tools/build_community_batters.py). Its known_keys_data is a snapshot of the
# registry; without it on sys.path the import below fails silently and every
# already-shipped key gets reported as NEW.
BUILDER = Path(os.environ.get("GOLDENNUGGET_TEMPLATEBUILDER",
                              "/Users/jason/GoldenNugget-TemplateBuilder"))

from fw_key_scan import parse_header  # noqa: E402  (same header layout)

CHUNK = 8 * 1024 * 1024
OVERLAP = 1 << 16

# a plausible preference key: known family prefix + identifier
KEY_RE = re.compile(
    r"^(?:SB|SBF|UISolarium|Solarium|AM[A-Z]|UIViewGlass|Calistoga|"
    r"com\.apple\.(?:SwiftUI|UIKit)\.[A-Za-z0-9_]+)[A-Za-z0-9_]*$")
# an accessor: lowerCamelCase selector-ish
ACCESSOR_RE = re.compile(r"^[a-z][A-Za-z0-9_]{2,63}$")
# any "left \0 right \0" neighbour pair of two identifier-ish strings
PAIR_RE = re.compile(
    rb"([A-Za-z][A-Za-z0-9_]{2,63})\x00([A-Za-z][A-Za-z0-9_]{2,63})\x00")


def image_range(cache: Path, mappings, images, needle: str):
    """(file_start, file_end, path) of the image whose path contains needle."""
    for load_addr, text_size, path in images:
        if needle in path:
            start = end = None
            for m_addr, m_size, m_foff in mappings:
                if m_addr <= load_addr < m_addr + m_size:
                    start = m_foff + (load_addr - m_addr)
                    end = start + text_size
                    break
            if start is not None:
                return start, end, path
    return None


def extract(cache: Path, mappings, images, needle: str):
    """{key: {"accessor": str|None, "count": int}} for one image.

    The table is a run of NUL-separated C strings in which the accessor
    *precedes* its key (verified against the raw string pool:)::

        ... ambientExtendedIdleTimer \\0 SBAmbientExtendedIdleTimer \\0 ...

    So the pairing rule is: for every key-like token, the accessor is the
    token immediately BEFORE it. A non-overlapping ``A \\0 B \\0`` regex is
    wrong here - one entry whose accessor is missing (a bare key like
    ``SBWidgetLogging``) shifts the parity and mis-pairs everything after
    it. A token stream with a one-token carry has no parity to lock onto.
    """
    found = image_range(cache, mappings, images, needle)
    if not found:
        return None, None
    start, end, path = found
    keys: dict[str, dict] = {}
    prev = b""
    pending = b""  # partial token carried across chunk reads
    with open(cache, "rb") as fh:
        fh.seek(start)
        pos = start
        while pos < end:
            want = min(CHUNK, end - pos)
            buf = pending + fh.read(want)
            pos += want
            tokens = buf.split(b"\0")
            pending = tokens.pop()  # last element may be a partial token
            for raw in tokens:
                if len(raw) < 3 or len(raw) > 64:
                    prev = raw
                    continue
                try:
                    text = raw.decode("ascii")
                except UnicodeDecodeError:
                    prev = raw
                    continue
                if KEY_RE.match(text):
                    acc = prev.decode("ascii", "replace") if prev else ""
                    entry = keys.setdefault(text, {"accessor": None, "count": 0})
                    entry["count"] += 1
                    if entry["accessor"] is None and ACCESSOR_RE.match(acc):
                        entry["accessor"] = acc
                prev = raw
    return keys, path


def load_baseline(path: Path) -> set:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in ("STRICT", "loose"):
            keys.add(parts[1])
    return keys


def known_keys() -> set:
    """Every preference key the repo already knows about.

    A silent import failure here is not harmless: it shrinks the "known" set
    and quietly turns already-shipped keys into "NEW" findings. That exact
    bug produced a wrong diff once (SBHomeScreenShowsSearchAffordance, a
    Tier-A verified registry key, was reported as new because
    ``src.tweaks.registry`` needs PySide6 and ``batter_builder`` was not on
    sys.path). Every source now reports itself and failures are loud.
    """
    keys: set[str] = set()
    loaded: list[str] = []

    sys.path.insert(0, str(REPO))
    try:
        from src.tweaks.registry import SPECS
        n = 0
        for spec in SPECS:
            if spec.key:
                keys.add(spec.key)
                n += 1
        loaded.append(f"registry:{n}")
    except Exception as exc:
        print(f"WARNING known_keys: registry import failed ({exc!r}); "
              f"re-run with a Python that has PySide6 "
              f"(~/.workbuddy/binaries/python/envs/default/bin/python)",
              file=sys.stderr)

    if BUILDER.is_dir():
        sys.path.insert(0, str(BUILDER))
    try:
        from batter_builder.known_keys_data import PATHS as KNOWN
        n = 0
        for path_keys in KNOWN.values():
            keys.update(path_keys)
            n += len(path_keys)
        loaded.append(f"template_builder:{n}")
    except Exception as exc:
        print(f"WARNING known_keys: batter_builder.known_keys_data import "
              f"failed ({exc!r}); is {BUILDER} present?", file=sys.stderr)

    for name in ("docs/data/springboard_candidates_by_category.txt",
                 "docs/data/springboard_accessor_key_pairs.txt",
                 "docs/data/registry_plist_channels.txt"):
        p = REPO / name
        if p.exists():
            keys.update(re.findall(r"[A-Za-z0-9_.]{6,}", p.read_text(errors="replace")))
            loaded.append(f"{name}")
    print(f"known_keys sources: {' '.join(loaded)} -> {len(keys)} keys",
          file=sys.stderr)
    return keys


def report(keys: dict, path: str, baseline: set, known: set) -> str:
    strict = sorted(k for k, v in keys.items() if v["accessor"])
    loose = sorted(k for k, v in keys.items() if not v["accessor"])
    new_strict = [k for k in strict if k not in baseline and k not in known]
    new_loose = [k for k in loose if k not in baseline and k not in known]
    lines = [
        f"# {path}",
        f"# STRICT {len(strict)} / loose {len(loose)} (total {len(keys)})",
        f"# new vs baseline+repo: {len(new_strict)} strict, {len(new_loose)} loose",
    ]
    lines += [f"STRICT  {k:<58} {keys[k]['accessor']}  x{keys[k]['count']}"
              for k in strict]
    lines += [f"loose   {k:<58} {'-':<58} x{keys[k]['count']}"
              for k in loose]
    if new_strict or new_loose:
        lines.append("# --- NEW ---")
        lines += [f"NEW-STRICT  {k:<52} {keys[k]['accessor']}" for k in new_strict]
        lines += [f"NEW-loose   {k}" for k in new_loose]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("caches", nargs="+", type=Path)
    ap.add_argument("--image", action="append", default=[],
                    help="substring of the image path (repeatable)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--diff-out", type=Path)
    ap.add_argument("--baseline", type=Path,
                    default=REPO / "docs/data/springboard_accessor_key_pairs.txt")
    args = ap.parse_args()

    needles = args.image or ["SpringBoardFoundation"]
    baseline = load_baseline(args.baseline)
    known = known_keys()

    if len(args.caches) == 2:
        old, new = args.caches
        old_mappings, old_images = parse_header(old)
        new_mappings, new_images = parse_header(new)
        for needle in needles:
            old_keys, old_path = extract(old, old_mappings, old_images, needle)
            new_keys, new_path = extract(new, new_mappings, new_images, needle)
            if old_keys is None or new_keys is None:
                print(f"  MISS  {needle}: "
                      f"{'old' if old_keys is None else ''}"
                      f"{'new' if new_keys is None else ''}")
                continue
            added = {k: v for k, v in new_keys.items() if k not in old_keys}
            gone = {k: v for k, v in old_keys.items() if k not in new_keys}
            print(f"\n=== {needle}: {len(old_keys)} keys @ {old.name} -> "
                  f"{len(new_keys)} @ {new.name} ===")
            print(f"  added in {new.name}: {len(added)}   removed: {len(gone)}")
            text = report(new_keys, str(new_path), baseline, known)
            if args.diff_out:
                args.diff_out.write_text(text)
                print(f"  written: {args.diff_out}")
            for k in sorted(added):
                acc = added[k]["accessor"] or "-"
                mark = " (already in repo)" if k in known or k in baseline else ""
                print(f"  + {k:<58} {acc}{mark}")
            for k in sorted(gone)[:20]:
                print(f"  - {k}")
        return 0

    for cache in args.caches:
        mappings, images = parse_header(cache)
        for needle in needles:
            keys, path = extract(cache, mappings, images, needle)
            if keys is None:
                print(f"  MISS  {needle} in {cache.name}")
                continue
            print(f"\n=== {needle} @ {cache.name}: {len(keys)} keys ===")
            text = report(keys, str(path), baseline, known)
            if args.out:
                args.out.write_text(text)
                print(f"  written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
