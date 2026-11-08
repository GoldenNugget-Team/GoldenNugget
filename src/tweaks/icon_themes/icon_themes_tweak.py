"""Icon theming via HomeDomain WebClip folders.

Port of Cowabunga (Lite)'s "icon theming" feature to GoldenNugget. The real
app icons are never touched: for every themed app a WebClip folder is created
at ``HomeDomain/Library/WebClips/Cowabunga_<bundleID>,<displayName>.webclip/``
containing an ``Info.plist`` whose ``ApplicationBundleIdentifier`` points at
the REAL app bundle id — so tapping the replaced icon launches the actual app
directly (no "open in Safari" banner) — and an ``icon.png``. The folders are
delivered as regular HomeDomain ``FileToRestore`` entries, so they ride the
same restore path as the well-tested HomeDomain tweak files on every
supported version.
"""

import os
import plistlib
import shutil
import tempfile
import zipfile
from collections import OrderedDict
from shutil import copyfile

from src.utils.file_to_restore import FileToRestore
from src.utils.i18n import QCoreApplication
from src.utils.paths import app_data_dir

from ..tweak_classes import Tweak
from .icon_theme import IconTheme


def persistent_themes_dir() -> str:
    """Stable folder holding the icon PNGs so applies/presets never depend on
    the original picker location (which could move or disappear)."""
    base = str(app_data_dir())
    folder = os.path.join(base, "IconThemes")
    os.makedirs(folder, exist_ok=True)
    return folder


def make_webclip_plist(bundle_id: str, display_name: str) -> bytes:
    """WebClip Info.plist exactly like Cowabunga's ``makeInfoPlist``."""
    info = {
        "ApplicationBundleIdentifier": bundle_id,
        "ApplicationBundleVersion": 1,
        "ClassicMode": False,
        "ConfigurationIsManaged": False,
        "ContentMode": "UIWebClipContentModeRecommended",
        "FullScreen": True,
        "IconIsPrecomposed": False,
        "IconIsScreenShotBased": False,
        "IgnoreManifestScope": False,
        "IsAppClip": False,
        "Orientations": 0,
        "ScenelessBackgroundLaunch": False,
        "Title": display_name,
        "WebClipStatusBarStyle": "UIWebClipStatusBarStyleDefault",
        "RemovalDisallowed": False,
    }
    return plistlib.dumps(info, fmt=plistlib.PlistFormat.FMT_XML)


class IconThemesTweak(Tweak):
    def __init__(self):
        super().__init__(key=None)
        self.themes: list[IconTheme] = []

    def uses_domains(self):
        # WebClip folders all live under HomeDomain.
        return not self.is_empty()

    def is_empty(self) -> bool:
        return not self._theme_index

    @property
    def themes(self):  # pyright: ignore[reportRedeclaration]
        """Ordered snapshot; assign a sequence to replace the collection."""
        return list(self._theme_index.values())

    @themes.setter
    def themes(self, themes):  # pyright: ignore[reportRedeclaration]
        self._theme_index = OrderedDict((theme.bundle_id, theme) for theme in themes)

    def add_theme(self, theme: IconTheme):
        self._theme_index.pop(theme.bundle_id, None)
        self._theme_index[theme.bundle_id] = theme

    def remove_theme(self, bundle_id: str):
        self._theme_index.pop(bundle_id, None)

    @staticmethod
    def strip_icon_suffix(filename: str) -> str:
        """Strip Cowabunga's icon-name suffixes (``-large``, ``@2x``, ``@3x``)
        so ``com.apple.AppStore@2x.png`` maps to the bundle id
        ``com.apple.AppStore`` — same rules as ``appIDFromIcon``."""
        base = os.path.splitext(filename)[0]
        for suffix in ("-large", "@2x", "@3x"):
            if base.endswith(suffix):
                return base[: -len(suffix)]
        return base

    @staticmethod
    def _dpi_rank(rel_path: str) -> int:
        # Prefer the most detailed icon a pack ships: top-level flat files
        # rank best, then "@3x", then "@2x" subfolders.
        parts = rel_path.replace("\\", "/").split("/")
        parent = parts[-2].lower() if len(parts) > 1 else ""
        if len(parts) == 1:
            return 0
        if "3x" in parent or "@3x" in parent:
            return 1
        if "2x" in parent or "@2x" in parent:
            return 2
        return 3

    @classmethod
    def scan_icon_pack(cls, folder: str) -> list[tuple[str, str]]:
        """Scan an icon-pack folder for ``<bundleID>.png`` files.

        Mirrors Cowabunga's theme folder (flat files named by bundle id) but
        also descends into ``2x``/``3x`` subfolders (choosing the highest-DPI
        match) and ignores ``__MACOSX``/dotfile junk found in real .theme
        archives. Returns ``[(bundle_id, abs_path)]`` sorted by bundle id.
        """
        IMAGE_EXTENSIONS = (".png", ".heic", ".jpg", ".jpeg", ".webp")
        best: dict[str, tuple[int, int, str]] = {}  # bundle_id -> (rank, len, path)
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs
                       if not d.startswith((".", "_", "__MACOSX"))]
            for name in sorted(files):
                if name.startswith(".") or name.startswith("._"):
                    continue
                if not name.lower().endswith(IMAGE_EXTENSIONS):
                    continue
                path = os.path.join(root, name)
                if not os.path.isfile(path):
                    continue
                bundle_id = cls.strip_icon_suffix(name)
                if not bundle_id:
                    continue
                rel = os.path.relpath(path, folder)
                rank = (cls._dpi_rank(rel), len(rel), path)
                prev = best.get(bundle_id)
                if prev is None or rank < prev:
                    best[bundle_id] = rank
        return sorted((bid, path) for bid, (_, _, path) in best.items())

    def import_pack(self, folder: str) -> tuple[int, list[str]]:
        """Add every icon in *folder* as a theme.

        Pack icons default to ``display_name=""`` (label hidden) matching the
        trend of these packs; per-app labels can be added individually on top.
        Returns ``(added, skipped_bundle_ids)``.
        """
        added = 0
        skipped = []
        for bundle_id, path in self.scan_icon_pack(folder):
            theme = IconTheme(bundle_id=bundle_id, icon_path=path)
            if not self.store_icon(theme):
                skipped.append(bundle_id)
                continue
            self.add_theme(theme)
            added += 1
        return added, skipped

    def import_pack_zip(self, archive_path: str,
                        theme_name: str = None) -> tuple[int, list[str]]:
        """Extract an icon-pack archive and import the icons inside.

        Follows Cowabunga: explore-repo zips store their icons in a
        ``<ThemeName>/`` folder, standalone .theme archives expose an
        ``IconBundles`` folder. Returns ``(added, skipped_bundle_ids)``.
        """
        tmp = tempfile.mkdtemp(prefix="icontheme_pack_")
        try:
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmp)
            folder = self.resolve_icon_folder(tmp, theme_name)
            return self.import_pack(folder)
        except (zipfile.BadZipFile, OSError):
            return 0, []
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def resolve_icon_folder(extract_root: str, theme_name: str = None) -> str:
        """Locate the folder holding the icons inside an extracted archive."""
        if theme_name:
            named = os.path.join(extract_root, theme_name)
            if os.path.isdir(named):
                return named
        best = extract_root
        best_len = float("inf")
        for root, dirs, files in os.walk(extract_root):
            # prefer a directory literally named IconBundles
            if os.path.basename(root) == "IconBundles":
                return root
            n = len(files)
            if n and n < best_len:
                best, best_len = root, n
        if best != extract_root:
            return best
        return extract_root

    def store_icon(self, theme: IconTheme):
        """Copy a theme's icon into the persistent store and point it there.

        Returns True when the icon is durably available for future applies.
        Idempotent for icons that already live in the store.
        """
        if theme.icon_data is not None:
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in theme.bundle_id)
            dest = os.path.join(persistent_themes_dir(), f"{safe}.png")
            try:
                with open(dest, "wb") as f:
                    f.write(theme.icon_data)
                theme.icon_path = dest
                theme.icon_data = None
                return True
            except OSError:
                return False
        if theme.icon_path and os.path.isfile(theme.icon_path):
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in theme.bundle_id)
            dest = os.path.join(persistent_themes_dir(), f"{safe}.png")
            try:
                if os.path.realpath(theme.icon_path) != os.path.realpath(dest):
                    copyfile(theme.icon_path, dest)
                theme.icon_path = dest
                return True
            except OSError:
                return False
        return False

    def sanitize_display_name(self, name: str) -> str:
        # Commas break the WebClip folder name pattern (it's a single comma-
        # separated string), and path separators would break restore paths.
        return "".join(" " if c in ",/" else c for c in name)

    def apply_tweak(self, files_to_restore: list[FileToRestore],
                    output_dir: str = None,
                    update_label=lambda x: None):
        if self.is_empty():
            return
        update_label(QCoreApplication.tr("Generating icon themes..."))
        skipped = []
        for theme in self.themes:
            display_name = self.sanitize_display_name(theme.display_name)
            folder = f"Library/WebClips/Cowabunga_{theme.bundle_id},{display_name}.webclip"

            # Info.plist
            files_to_restore.append(FileToRestore(
                contents=make_webclip_plist(theme.bundle_id, display_name),
                restore_path=f"{folder}/Info.plist",
                domain="HomeDomain"
            ))

            # icon.png — bytes by preference, then the stored path, then final
            # fallback to the persistent store copy.
            data = theme.get_icon_data()
            if data is None and theme.icon_path and os.path.isfile(theme.icon_path):
                with open(theme.icon_path, "rb") as f:
                    data = f.read()
            if data is None:
                skipped.append(theme.bundle_id)
                continue
            files_to_restore.append(FileToRestore(
                contents=data,
                restore_path=f"{folder}/icon.png",
                domain="HomeDomain"
            ))
        if skipped:
            update_label(QCoreApplication.tr(
                "Skipped icon themes without icon file: {0}").format(", ".join(skipped)))
        update_label(QCoreApplication.tr("Adding icon themes..."))
