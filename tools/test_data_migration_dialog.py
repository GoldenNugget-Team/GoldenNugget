#!/usr/bin/env python3
"""The installer-style data-migration window (offscreen, no device).

The window is the only user-facing part of the ``GoldenNugget`` -> ``gnugget``
move, and it must look like a disk-image installer: black-and-white icon on the
left, progress bar in the middle, colour icon on the right, Migrate button
underneath the bar. These tests pin that layout and the click-through:

* nothing to move -> no window at all;
* a dismissal is remembered, and only for that exact set of files;
* clicking Migrate moves the files and turns the button into Done;
* the left artwork really is greyscale (that is the visual conceit).

Run: python tools/test_data_migration_dialog.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton

import src.utils.user_data_migration as mig

APP = QApplication.instance() or QApplication([])

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
    return [
        patch.object(mig, "app_data_dir", lambda: root / "data" / "gnugget"),
        patch.object(mig, "cache_dir", lambda: root / "cache" / "gnugget"),
        patch.object(mig, "legacy_app_data_dirs",
                     lambda: [root / "data" / "GoldenNugget"]),
        patch.object(mig, "legacy_cache_dirs",
                     lambda: [root / "cache" / "GoldenNugget"]),
        patch.object(mig, "legacy_generic_dirs", lambda: []),
    ]


def build_legacy(root: Path):
    old = root / "data" / "GoldenNugget"
    write(old / "Presets" / "Mine.json", "preset")
    write(old / "GoldenNugget" / "backup_cache" / "master" / "U" / "Manifest.db")
    return old


def is_greyscale(pixmap) -> bool:
    image = pixmap.toImage()
    if image.isNull():
        return False
    for x in range(0, image.width(), 7):
        for y in range(0, image.height(), 7):
            colour = image.pixelColor(x, y)
            if colour.alpha() == 0:
                continue
            if not (colour.red() == colour.green() == colour.blue()):
                return False
    return True


def test_no_window_without_legacy_data():
    with tempfile.TemporaryDirectory(prefix="gn_mig_ui_") as tmp:
        root = Path(tmp)
        with patch.object(mig, "app_data_dir", lambda: root / "data" / "gnugget"), \
                patch.object(mig, "cache_dir", lambda: root / "cache" / "gnugget"), \
                patch.object(mig, "legacy_app_data_dirs",
                             lambda: [root / "data" / "GoldenNugget"]), \
                patch.object(mig, "legacy_cache_dirs",
                             lambda: [root / "cache" / "GoldenNugget"]), \
                patch.object(mig, "legacy_generic_dirs", lambda: []):
            from src.gui.dialogs import data_migration
            check("nothing to move -> no window",
                  data_migration.maybe_prompt_migration() is False)


def test_layout_and_click():
    with tempfile.TemporaryDirectory(prefix="gn_mig_ui_") as tmp:
        root = Path(tmp)
        ctx = sandbox(root)
        for patch_ in ctx:
            patch_.start()
        try:
            old = build_legacy(root)
            from src.gui.dialogs.data_migration import DataMigrationDialog
            plan = mig.plan_migration()
            check("plan has entries", not plan.is_empty)

            dialog = DataMigrationDialog(plan)
            dialog.show()
            APP.processEvents()
            check("dialog is modal", dialog.isModal())

            labels = dialog.findChildren(QLabel)
            icons = [label for label in labels if label.objectName() == "migrationIcon"]
            check("two icons flank the bar", len(icons) == 2, len(icons))
            check("left icon is black and white", is_greyscale(icons[0].pixmap()))
            check("right icon keeps its colour", not is_greyscale(icons[1].pixmap()))

            bar = dialog.findChild(QProgressBar, "migrationProgress")
            check("progress bar exists", bar is not None)
            check("progress starts empty", bar.value() == 0)

            button = dialog.findChild(QPushButton)
            check("button says Migrate", button.text() == "Migrate", button.text())
            check("button sits under the bar",
                  button.y() > bar.mapTo(dialog, bar.rect().bottomLeft()).y() - 1)

            button.click()
            deadline = time.monotonic() + 10
            while dialog._running and time.monotonic() < deadline:
                APP.processEvents()

            check("migration finished", dialog.result_data is not None)
            check("no errors", not dialog.result_data.errors, dialog.result_data.errors)
            check("presets moved", (root / "data" / "gnugget" / "Presets" / "Mine.json").is_file())
            check("cache moved", (root / "data" / "gnugget" / "backup_cache"
                                  / "master" / "U" / "Manifest.db").is_file())
            check("old folder gone", not old.exists())
            check("button becomes Done", button.text() == "Done", button.text())
            check("bar is full", bar.value() == 1000, bar.value())
            dialog.deleteLater()
        finally:
            for patch_ in ctx:
                patch_.stop()


def test_dismissal_is_remembered():
    with tempfile.TemporaryDirectory(prefix="gn_mig_ui_") as tmp:
        root = Path(tmp)
        ctx = sandbox(root)
        for patch_ in ctx:
            patch_.start()
        try:
            build_legacy(root)
            plan = mig.plan_migration()
            check("not declined initially", not mig.is_declined(plan))
            mig.mark_declined(plan)
            from src.gui.dialogs import data_migration
            check("declined plan never opens the window",
                  data_migration.maybe_prompt_migration() is False)
            mig.clear_declined()
            check("clearing the marker asks again",
                  not mig.is_declined(plan))
        finally:
            for patch_ in ctx:
                patch_.stop()


def main():
    test_no_window_without_legacy_data()
    test_layout_and_click()
    test_dismissal_is_remembered()
    print(f"ALL DATA MIGRATION DIALOG CHECKS PASSED ({PASS} checks)", flush=True)


if __name__ == "__main__":
    main()
