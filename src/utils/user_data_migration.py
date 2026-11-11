"""Move user data from the pre-rename folders into ``gnugget``.

The app used to keep its files under ``GoldenNugget`` (macOS
``~/Library/Application Support/GoldenNugget``, ``~/.local/share/GoldenNugget``,
``%APPDATA%/GoldenNugget``). They now live under ``gnugget``
(see :mod:`src.utils.paths`). This module describes and performs that move.

Design rules:

* **Nothing is deleted before it has been moved.** Every entry is relocated
  with ``os.rename``/``shutil.move`` (a same-volume move is an instant rename,
  so a multi-gigabyte backup cache costs no time and no extra disk space).
* **The plan is computed without touching the disk.** :func:`plan_migration` is
  read-only, so a caller can show the size/count before the user commits.
* **Merging never overwrites.** When both the old and the new folder already
  hold the same name, the entry is skipped and reported; the user's current
  file wins over the older copy.
* **Qt-free.** The window that drives this lives in
  ``src.gui.dialogs.data_migration``; the CLI and tests use this module
  directly.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.paths import (
    LEGACY_APP_NAMES,
    app_data_dir,
    cache_dir,
    legacy_app_data_dirs,
    legacy_cache_dirs,
    legacy_generic_dirs,
)

logger = logging.getLogger("GoldenNugget.migration")

#: Sidecar recording a declined migration, so the app does not ask on every
#: launch. Deliberately NOT in the settings store: writing a settings file
#: before the move would make the old (authoritative) settings look like a
#: conflict.
DECLINED_MARKER = ".migration_declined"


@dataclass(frozen=True)
class Move:
    """One top-level entry that will be relocated."""

    source: Path
    destination: Path
    files: int
    bytes: int

    @property
    def label(self) -> str:
        return self.source.name


@dataclass
class MigrationPlan:
    moves: list[Move] = field(default_factory=list)
    #: ``(source, reason)`` for entries that stay where they are.
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    #: Legacy roots that would be emptied by the move (removed afterwards).
    roots: list[Path] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.moves

    @property
    def total_files(self) -> int:
        return sum(move.files for move in self.moves)

    @property
    def total_bytes(self) -> int:
        return sum(move.bytes for move in self.moves)

    @property
    def signature(self) -> str:
        """Stable identity of the pending move (used by the decline marker)."""
        return "|".join(sorted(f"{move.source}->{move.destination}"
                               for move in self.moves))


@dataclass
class MigrationResult:
    moved_files: int = 0
    moved_bytes: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors and not self.cancelled


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #

def _measure(path: Path) -> tuple[int, int]:
    """``(file count, byte count)`` of *path* (a file or a directory tree)."""
    if path.is_symlink() or path.is_file():
        try:
            return 1, path.lstat().st_size
        except OSError:
            return 1, 0
    files = 0
    total = 0
    for current, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            try:
                total += os.lstat(os.path.join(current, name)).st_size
            except OSError:
                continue
            files += 1
    return files, total


def _collect(source: Path, destination: Path, plan: MigrationPlan,
             ignore: frozenset[Path] = frozenset()) -> None:
    """Record the moves that merge *source* into *destination*.

    *ignore* holds subfolders that are planned against a different destination
    (the pre-rename nested ``GoldenNugget`` folder is laid over the new root
    instead of being copied into it as a subfolder).
    """
    try:
        entries = sorted(os.scandir(source), key=lambda entry: entry.name)
    except OSError as exc:
        plan.skipped.append((source, str(exc)))
        return
    for entry in entries:
        src = Path(entry.path)
        if src in ignore:
            continue
        dst = destination / entry.name
        if not os.path.lexists(dst):
            files, size = _measure(src)
            if files:
                plan.moves.append(Move(src, dst, files, size))
            continue
        if entry.is_dir(follow_symlinks=False) and dst.is_dir() \
                and not dst.is_symlink():
            _collect(src, dst, plan)
            continue
        plan.skipped.append((src, "already exists in the new folder"))


def _root_pairs() -> list[tuple[Path, Path, frozenset[Path]]]:
    """``(source root, destination root, subfolders planned separately)``."""
    pairs: list[tuple[Path, Path]] = [
        (legacy, app_data_dir()) for legacy in legacy_app_data_dirs()]
    pairs += [(legacy, cache_dir()) for legacy in legacy_cache_dirs()]
    pairs += [(legacy, app_data_dir() / legacy.name)
              for legacy in legacy_generic_dirs()]
    pairs = [(source, target) for source, target in pairs
             if source.is_dir() and source != target]

    # Old builds that used QStandardPaths ended up with a second brand folder
    # inside the first (``GoldenNugget/GoldenNugget/backup_cache``). The new
    # layout has no nesting, so those children belong at the top of the new
    # folder: plan them first, and keep the outer walk from moving the
    # wrapper folder itself.
    result: list[tuple[Path, Path, frozenset[Path]]] = []
    for source, target in pairs:
        nested = frozenset(
            child for child in (source / name for name in LEGACY_APP_NAMES)
            if child.is_dir() and child != target)
        for child in sorted(nested):
            result.append((child, target, frozenset()))
        result.append((source, target, nested))
    return result


def plan_migration() -> MigrationPlan:
    """Describe the pending move without changing anything on disk."""
    plan = MigrationPlan()
    for source, destination, ignore in _root_pairs():
        before = len(plan.moves)
        _collect(source, destination, plan, ignore)
        if len(plan.moves) > before:
            plan.roots.append(source)

    # Two legacy trees can carry the same name (a loose top-level ``LastApply``
    # and the nested one). The first plan wins; the duplicate stays put.
    destinations = set()
    unique: list[Move] = []
    for move in plan.moves:
        if move.destination in destinations:
            plan.skipped.append((move.source, "duplicate destination"))
            continue
        destinations.add(move.destination)
        unique.append(move)
    plan.moves = unique
    plan.roots = [root for root in plan.roots if root.is_dir()]
    return plan


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #

def _prune_empty(root: Path) -> None:
    """Remove *root* and its now-empty subfolders, deepest first."""
    for current, _dirs, _names in os.walk(root, topdown=False,
                                          onerror=lambda _e: None):
        try:
            os.rmdir(current)
        except OSError:
            pass


def run_migration(plan: MigrationPlan, on_progress=None,
                  should_cancel=None) -> MigrationResult:
    """Perform *plan*.

    ``on_progress(moved_bytes, total_bytes, label)`` is called after every
    entry; ``should_cancel()`` is polled before every entry. Both are optional.
    """
    result = MigrationResult(skipped=list(plan.skipped))
    total = max(plan.total_bytes, 1)
    for move in plan.moves:
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            break
        try:
            # The plan was computed when the dialog opened; if the destination
            # appeared meanwhile (second instance, a worker), shutil.move would
            # nest the folder INSIDE it — re-check and skip instead.
            if move.destination.exists() or move.destination.is_symlink():
                logger.warning("Destination appeared after planning — skipping %s",
                               move.source)
                result.skipped.append((move.source, "already exists in the new folder"))
                continue
            move.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(move.source), str(move.destination))
        except OSError as exc:
            logger.warning("Could not move %s: %s", move.source, exc)
            result.errors.append((str(move.source), str(exc)))
            continue
        result.moved_files += move.files
        result.moved_bytes += move.bytes
        if on_progress is not None:
            on_progress(result.moved_bytes, total, move.label)
        logger.info("Moved %s -> %s", move.source, move.destination)

    if not result.cancelled:
        for root in plan.roots:
            _prune_empty(root)
    return result


# --------------------------------------------------------------------------- #
# Decline marker
# --------------------------------------------------------------------------- #

def _marker_path() -> Path:
    return app_data_dir() / DECLINED_MARKER


def is_declined(plan: MigrationPlan) -> bool:
    """True when the user already dismissed *this* exact move."""
    try:
        return _marker_path().read_text(encoding="utf-8").strip() == plan.signature
    except OSError:
        return False


def mark_declined(plan: MigrationPlan) -> None:
    try:
        path = _marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.signature, encoding="utf-8")
    except OSError:
        pass


def clear_declined() -> None:
    try:
        _marker_path().unlink()
    except OSError:
        pass


def format_bytes(value: int) -> str:
    """Human size for the dialog subtitle (``407 MB``, ``1.2 GB``)."""
    size = float(max(0, value))
    if size < 1024:
        return f"{size:.0f} B"
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            text = f"{size:.0f}" if unit == "KB" else f"{size:.1f}"
            return f"{text.removesuffix('.0')} {unit}"
    return f"{size:.1f} TB"
