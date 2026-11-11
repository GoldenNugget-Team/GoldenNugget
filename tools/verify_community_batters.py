#!/usr/bin/env python3
"""Verify the generated .batter files with GoldenNugget's own loader.

Three independent checks per file:
  1. TemplateBuilder round-trip: batter.load() reads the archive back.
  2. GoldenNugget's real loader: community_tweaks.parse_tweaks() must accept
     the config (it raises CommunityTweakError on anything the app refuses).
     File writes are read from the archive the same way the app reads them
     (src/tweaks/posterboard/template_file.py _source_reader).
  3. Cross-template merge: enable every tweak in every template at once and
     run community_tweaks.collect() - catches plist key clashes between
     templates (e.g. two Feature Flags groups writing the same category).

Two tweaks in one template that write the same path with different bytes are
a combination the app refuses on purpose (ChinaAI's enable and reset
switches). The merge simulation keeps the first of such a pair and prints
which one it dropped, so the check stays honest instead of failing on a
state a user cannot reach.
"""
import glob
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = "/Users/jason/GoldenNugget-TemplateBuilder"
OUT_DIR = os.path.join(REPO, "community-batters")

sys.path.insert(0, REPO)
sys.path.insert(0, BUILDER)

from batter_builder import batter as batter_io  # noqa: E402
from batter_builder import rules  # noqa: E402

from src.tweaks.posterboard.community_tweaks import (  # noqa: E402
    MAX_SOURCE_BYTES,
    MAX_TOTAL_SOURCE_BYTES,
    collect,
    parse_tweaks,
)


def source_reader(archive: zipfile.ZipFile, config_name: str):
    """Read a file write's source out of the archive, like the app does."""
    base = config_name[:-len("config.json")]
    names = set(archive.namelist())
    total = [0]

    def read(relative: str) -> bytes:
        name = base + relative
        if name not in names:
            raise AssertionError(f"missing file in template: {relative!r}")
        size = archive.getinfo(name).file_size
        total[0] += size
        if size > MAX_SOURCE_BYTES or total[0] > MAX_TOTAL_SOURCE_BYTES:
            raise AssertionError("template files are too large")
        return archive.read(name)

    return read


def drop_exclusive(tweaks):
    """Keep the first of any two tweaks the app would refuse to merge.

    The app's own rule (community_tweaks.collect): plist writes to one path
    merge their keys, but a whole-file write clashes with another whole-file
    write of the same path unless the bytes are identical, and with any
    plist write of that path. ChinaAI's enable and reset switches are one
    such pair - same file, different payload.
    """
    kept, dropped = [], []
    plist_paths = set()
    file_paths = {}
    for tweak in tweaks:
        writes = tweak.active_writes()
        clash = False
        for write in writes:
            if write.type == "plist":
                if write.path in file_paths:
                    clash = True
            elif write.path in plist_paths:
                clash = True
            elif write.path in file_paths and file_paths[write.path] != write.data:
                clash = True
            if clash:
                break
        if clash:
            dropped.append(tweak.id)
            continue
        kept.append(tweak)
        for write in writes:
            if write.type == "plist":
                plist_paths.add(write.path)
            else:
                file_paths.setdefault(write.path, write.data)
    return kept, dropped


def main():
    paths = sorted(glob.glob(os.path.join(OUT_DIR, "*.batter")))
    if not paths:
        print("no .batter files found")
        return 1
    ok = True
    all_lists = []
    for path in paths:
        name = os.path.basename(path)
        # 1. round-trip through the builder's reader
        template = batter_io.load(path)
        issues = rules.validate(template)
        errors = rules.errors(issues)
        # 2. GoldenNugget's own loader, on the raw config.json
        with zipfile.ZipFile(path) as archive:
            config_name = next(n for n in archive.namelist()
                               if n.lower().endswith("config.json"))
            raw = json.loads(archive.read(config_name).decode("utf-8"))
            try:
                tweaks = parse_tweaks(raw.get("tweaks", []),
                                      source_reader(archive, config_name))
                loaded = f"{len(tweaks)} tweaks accepted"
            except Exception as error:
                loaded = f"LOADER REFUSED: {error}"
                tweaks = []
                ok = False
        for tweak in tweaks:
            tweak.enabled = True  # simulate every switch on
        kept, dropped = drop_exclusive(tweaks)
        if dropped:
            print(f"       note: {name} keeps {kept[0].id} and drops "
                  f"{', '.join(dropped)} (same file, different payload)")
        status = "OK " if not errors else "ERR"
        print(f"[{status}] {name}: {len(template.tweaks)} tweaks, "
              f"{len(errors)} builder errors | {loaded}")
        for issue in errors:
            ok = False
            print(f"       ERROR {issue.where}: {issue.text}")
        all_lists.append((template.title, kept))

    # 3. everything on at once, for two iOS versions
    for version in ("26.1", "27.0"):
        try:
            plists, files = collect(all_lists, version)
            print(f"\ncollect() with every tweak on, iOS {version}: "
                  f"{len(plists)} plist files, {len(files)} whole files")
            for path in sorted(plists):
                keys = plists[path][0]
                print(f"  {path}: {len(keys)} keys")
            for path in sorted(files):
                print(f"  {path}: {len(files[path][0])} bytes")
        except Exception as error:
            ok = False
            print(f"\ncollect() iOS {version} FAILED: {error}")

    print("\nALL OK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
