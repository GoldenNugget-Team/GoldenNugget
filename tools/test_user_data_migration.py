#!/usr/bin/env python3
"""Offline regression suite for the user-data move (no device, no Qt).

``src/utils/user_data_migration.py`` relocates the pre-rename ``GoldenNugget``
folder into the app's new ``gnugget`` folder. The move touches user data, so
the rules are pinned here:

* it never overwrites: an entry that already exists in the new folder stays,
  the old copy is reported as skipped;
* the old *nested* layout (``GoldenNugget/GoldenNugget/backup_cache``) is laid
  over the top of the new folder instead of being copied in as a subfolder;
* the cache tree moves as well;
* emptied old folders are cleaned up, non-empty ones are left alone;
* a dismissal is remembered for exactly that set of files;
* an app that runs before the move still sees the old preferences (the
  settings store seeds itself from the old folder's JSON, read-only).

Run: python tools/test_user_data_migration.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.utils.settings as settings_module
import src.utils.user_data_migration as mig

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}")


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def sandbox(root: Path):
    """Point the module at *root* instead of the real profile."""
    mig.app_data_dir = lambda: root / "data" / "gnugget"
    mig.cache_dir = lambda: root / "cache" / "gnugget"
    mig.legacy_app_data_dirs = lambda: [root / "data" / "GoldenNugget"]
    mig.legacy_cache_dirs = lambda: [root / "cache" / "GoldenNugget"]
    mig.legacy_generic_dirs = lambda: [root / "data" / "PosterBoard"]


def build_legacy(root: Path):
    old = root / "data" / "GoldenNugget"
    write(old / "Presets" / "Mine.json", "preset")
    write(old / "preferences" / "GoldenNugget" / "settings.json", "{}")
    # The doubled folder old QStandardPaths-based builds produced.
    write(old / "GoldenNugget" / "backup_cache" / "master" / "U" / "Manifest.db")
    write(old / "GoldenNugget" / "History" / "operations.json", "[]")
    # A loose folder that used to sit next to it.
    write(root / "data" / "PosterBoard" / ".work" / "db.sqlite3", "db")
    write(root / "cache" / "GoldenNugget" / "wallpaper_cache" / "w.png")
    return old


def test_plan_and_move():
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        sandbox(root)
        old = build_legacy(root)

        plan = mig.plan_migration()
        sources = {move.source.relative_to(old) for move in plan.moves
                   if old in move.source.parents}
        check("plan: top-level presets move",
              Path("Presets") in sources)
        check("plan: the doubled folder is not moved as a folder",
              Path("GoldenNugget") not in sources)
        check("plan: its children are laid over the new root",
              Path("GoldenNugget") / "backup_cache" in sources)
        check("plan: history comes along",
              Path("GoldenNugget") / "History" in sources)
        check("plan: the photo cache moves too",
              any("wallpaper_cache" in str(move.source) for move in plan.moves))
        check("plan: nothing is written yet",
              not (root / "data" / "gnugget").exists())
        check("plan: sizes are counted", plan.total_bytes > 0, plan.total_bytes)
        check("plan: file count", plan.total_files == 6, plan.total_files)

        progress = []
        result = mig.run_migration(
            plan, on_progress=lambda moved, total, label: progress.append(label))
        new = root / "data" / "gnugget"
        check("move: reports every entry", len(result.errors) == 0, result.errors)
        check("move: presets landed", (new / "Presets" / "Mine.json").is_file())
        check("move: settings landed", (new / "preferences" / "GoldenNugget" / "settings.json").is_file())
        check("move: cache landed at the top of the new root",
              (new / "backup_cache" / "master" / "U" / "Manifest.db").is_file())
        check("move: no GoldenNugget subfolder was created",
              not (new / "GoldenNugget").exists())
        check("move: history landed", (new / "History" / "operations.json").is_file())
        check("move: photo cache landed",
              (root / "cache" / "gnugget" / "wallpaper_cache" / "w.png").is_file())
        check("move: loose PosterBoard folder landed",
              (new / "PosterBoard" / ".work" / "db.sqlite3").is_file())
        check("move: old folder removed", not old.exists())
        check("move: old cache folder removed",
              not (root / "cache" / "GoldenNugget").exists())
        check("move: progress was reported", len(progress) == len(plan.moves))
        check("move: nothing left to migrate", mig.plan_migration().is_empty)


def test_never_overwrites():
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        sandbox(root)
        old = root / "data" / "GoldenNugget"
        new = root / "data" / "gnugget"
        write(old / "Presets" / "Mine.json", "old")
        write(new / "Presets" / "Mine.json", "new")

        plan = mig.plan_migration()
        check("conflict: nothing to move", plan.is_empty)
        check("conflict: reported as skipped", len(plan.skipped) == 1, plan.skipped)

        mig.run_migration(plan)
        check("conflict: the new file wins",
              (new / "Presets" / "Mine.json").read_text() == "new")
        check("conflict: the old copy stays put",
              (old / "Presets" / "Mine.json").read_text() == "old")


def test_merge_into_existing_folder():
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        sandbox(root)
        old = root / "data" / "GoldenNugget"
        new = root / "data" / "gnugget"
        write(old / "Logs" / "a.log", "a")
        write(new / "Logs" / "b.log", "b")

        plan = mig.plan_migration()
        check("merge: only the missing file moves",
              [move.source.name for move in plan.moves] == ["a.log"], plan.moves)
        mig.run_migration(plan)
        check("merge: both files present",
              (new / "Logs" / "a.log").is_file() and (new / "Logs" / "b.log").is_file())


def test_duplicate_destination():
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        sandbox(root)
        old = root / "data" / "GoldenNugget"
        write(old / "LastApply" / "U.json", "loose")
        write(old / "GoldenNugget" / "LastApply" / "U.json", "nested")

        plan = mig.plan_migration()
        check("duplicate: one move wins", len(plan.moves) == 1, plan.moves)
        check("duplicate: the other is skipped",
              any("duplicate" in reason for _src, reason in plan.skipped),
              plan.skipped)
        mig.run_migration(plan)
        check("duplicate: the nested copy (planned first) landed",
              (root / "data" / "gnugget" / "LastApply" / "U.json").read_text() == "nested")


def test_decline_marker():
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        sandbox(root)
        write(root / "data" / "GoldenNugget" / "Presets" / "Mine.json", "p")

        plan = mig.plan_migration()
        check("marker: nothing declined yet", not mig.is_declined(plan))
        mig.mark_declined(plan)
        check("marker: dismissal remembered", mig.is_declined(plan))
        mig.clear_declined()
        check("marker: cleared", not mig.is_declined(plan))

        # A different set of files is not covered by the old dismissal.
        mig.mark_declined(plan)
        write(root / "data" / "GoldenNugget" / "Templates" / "New.json", "t")
        check("marker: a new top-level entry asks again",
              not mig.is_declined(mig.plan_migration()))


def test_preferences_survive_an_unmigrated_folder():
    """Dismissing the window must not silently reset the user's settings.

    The settings store seeds itself from the pre-rename folder's JSON until the
    move happens; the old file is only read, never rewritten.
    """
    with tempfile.TemporaryDirectory(prefix="gn_migrate_") as tmp:
        root = Path(tmp)
        old_json = root / "data" / "GoldenNugget" / "preferences" / "GoldenNugget" / "settings.json"
        new_json = root / "data" / "gnugget" / "preferences" / "GoldenNugget" / "settings.json"
        write(old_json, json.dumps({"locale_code": "ru", "ui/show_sidebar": True}))

        with patch.dict(os.environ), \
                patch.object(settings_module, "app_data_dir",
                             lambda: root / "data" / "gnugget"), \
                patch.object(settings_module, "legacy_app_data_dirs",
                             lambda: [root / "data" / "GoldenNugget"]), \
                patch.object(settings_module, "_legacy_native",
                             lambda org, app: {}):
            # A per-suite preferences dir means a sandbox: no history at all.
            os.environ["GOLDENNUGGET_PREFERENCES_DIR"] = str(root / "sandbox")
            settings_module.reset_for_tests()
            check("seed: an explicit store location never borrows history",
                  settings_module.Settings("settings").value("locale_code") is None)

            os.environ.pop("GOLDENNUGGET_PREFERENCES_DIR")
            settings_module.reset_for_tests()
            store = settings_module.Settings("settings")
            check("seed: the old preferences are read",
                  store.value("locale_code") == "ru", store.value("locale_code"))
            check("seed: boolean keys keep their type",
                  store.value("ui/show_sidebar", False, type=bool) is True)
            check("seed: reading still did not create the file",
                  not new_json.exists())

            store.setValue("accent_color", "teal")
            check("seed: the first write lands in the new folder", new_json.is_file())
            persisted = json.loads(new_json.read_text(encoding="utf-8"))
            check("seed: the old values are carried over",
                  persisted.get("locale_code") == "ru", persisted)
            check("seed: the new value is stored too",
                  persisted.get("accent_color") == "teal", persisted)
            check("seed: the old file is untouched",
                  json.loads(old_json.read_text(encoding="utf-8")) == {
                      "locale_code": "ru", "ui/show_sidebar": True})
            settings_module.reset_for_tests()


def test_format_bytes():
    check("format: bytes", mig.format_bytes(512) == "512 B")
    check("format: kilobytes", mig.format_bytes(2048) == "2 KB")
    check("format: megabytes", mig.format_bytes(407 * 1024 * 1024) == "407 MB")
    check("format: gigabytes", mig.format_bytes(3 * 1024 ** 3) == "3 GB")


def main():
    test_plan_and_move()
    test_never_overwrites()
    test_merge_into_existing_folder()
    test_duplicate_destination()
    test_decline_marker()
    test_preferences_survive_an_unmigrated_folder()
    test_format_bytes()
    print(f"ALL USER DATA MIGRATION CHECKS PASSED ({PASS} checks)", flush=True)


if __name__ == "__main__":
    main()
