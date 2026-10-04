"""Rebuild the on-device PosterBoard wallpapers into the modern Clownfish shape.

The Settings -> PosterBoard "Rebuild Database" action repacks the flat legacy
wallpaper families that are already configured on the device (Marble / Lavender)
into the modern published-layer layout, so iOS 27 turns on the Depth effect.
Mercury spatial posters are skipped outright and every other family is left
untouched.

Flow (all reuse the proven apply pipeline):

1. ``pull_posterboard_container`` pulls the whole PosterBoard container over the
   targeted mobilebackup2 channel (the one "Get Database from Device" uses) and
   materialises every payload next to its device relative path.
2. ``plan_rebuild`` asks ``posterboard_converter.conversion_action`` per
   configuration: skip Mercury, repack Marble/Lavender, keep everything else.
3. The repacked configuration folders are pushed back through the normal
   protective restore, preserving each poster's UUID so the existing database
   row and the lock/home selection keep pointing at it.

The pure planning half (``find_collections_configs`` / ``plan_rebuild`` /
``build_restore_files``) has no device imports and is covered offline by
``tools/test_posterboard_rebuild.py``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import plistlib
import re
import shutil
import sqlite3
import uuid as uuid_module
from dataclasses import dataclass, field
from random import randint

from src.tweaks.posterboard import posterboard_converter as conv
from src.utils.file_to_restore import FileToRestore

logger = logging.getLogger("GoldenNugget.posterboard")

__all__ = [
    "COLLECTIONS_EXTENSION", "POSTERBOARD_DOMAIN", "RebuildPlan", "RebuildResult",
    "find_collections_configs", "build_restore_files", "plan_rebuild",
    "repack_to_new_descriptors", "insert_into_clownfish", "find_clownfish_skeleton",
    "rebuild_posterboard",
]

COLLECTIONS_EXTENSION = "com.apple.WallpaperKit.CollectionsPoster"
POSTERBOARD_DOMAIN = "AppDomain-com.apple.PosterBoard"
DB_FILE_NAME = "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"
DESCRIPTOR_IDENTIFIER_FILE = "com.apple.posterkit.provider.descriptor.identifier"
USERINFO_FILE = "com.apple.posterkit.provider.contents.userInfo"
LOCKSCREEN_ROLE = "PRPosterRoleLockScreen"

# Plane roles in the order the Clownfish skeleton lays them out. A wallpaper
# only supplies the layers it actually has; the rest get an empty published
# layer so the depth renderer always sees the full Background/Floating/Foreground
# set (the proven Odyssey descriptor leaves its Foreground bare).
PLANE_ROLES = ("Background", "Floating", "Foreground")
# ``index.xml`` keys copied from the source plane so the inserted animation keeps
# its exact coordinate space (a 390x844 points canvas, a 3176x3176 pixel canvas,
# ...). ``publishedObjectNames`` is the one Clownfish key we add on top.
INDEX_GEOMETRY_KEYS = (
    "documentWidth", "documentHeight", "documentResizesToView",
    "unitsInPixelsInPlayer", "scalesToFitInPlayer", "geometryFlipped",
)


@dataclass
class RebuildPlan:
    """What a Rebuild Database pass would change (and the files to push)."""

    root: str
    structure_version: int
    repacked: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    files: list = field(default_factory=list)
    # ``old_uuid -> new_uuid`` for the new-descriptor rebuild mode.
    replacements: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repacked)


def find_collections_configs(root: str) -> "list[tuple[str, str]]":
    """Return ``(uuid, config_dir)`` for every CollectionsPoster configuration.

    Searches by folder name instead of hardcoding the PRBPosterExtensionDataStore
    path so it works for both the AppDomain-relative layout and the raw iOS 27
    physical tree.
    """
    configs = []
    for dirpath, dirnames, _files in os.walk(root):
        if os.path.basename(dirpath) != "configurations":
            continue
        if os.path.basename(os.path.dirname(dirpath)) != COLLECTIONS_EXTENSION:
            continue
        for entry in sorted(dirnames):
            config_dir = os.path.join(dirpath, entry)
            if os.path.isdir(config_dir):
                configs.append((entry, config_dir))
        dirnames[:] = []
    return configs


def build_restore_files(plan_root: str, paths: "list[str]") -> "list[FileToRestore]":
    """Map pulled files back onto their exact device paths.

    The pulled tree mirrors the device relative paths verbatim, so the restore
    path is simply the file's path relative to the tree root — no structure
    version or extension has to be re-derived. Callers pass only the files the
    converter actually rewrote, so unchanged assets (often many MB per
    wallpaper) are never re-uploaded.
    """
    files = []
    for path in paths:
        rel = os.path.relpath(path, plan_root).replace(os.sep, "/")
        files.append(FileToRestore(
            contents=None,
            contents_path=path,
            restore_path=f"/{rel}",
            domain=POSTERBOARD_DOMAIN,
        ))
    return files


def plan_rebuild(root: str, structure_version: int,
                 max_multiplier: float = conv.DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER,
                 repack_families=conv.REPACK_FAMILIES,
                 screen=None) -> RebuildPlan:
    """Decide and perform the in-place repack of every configured wallpaper."""
    plan = RebuildPlan(root=root, structure_version=structure_version)
    for uuid, config_dir in find_collections_configs(root):
        action = conv.conversion_action(config_dir, repack_families)
        if action == conv.ACTION_SKIP:
            plan.skipped.append(uuid)
        elif action == conv.ACTION_REPACK:
            try:
                summary = conv.convert_descriptor(config_dir, screen, max_multiplier)
            except Exception as e:  # never let one bad package abort the pass
                logger.warning("Could not repack wallpaper %s: %s", uuid, e)
                plan.failed.append((uuid, str(e)))
                continue
            plan.repacked.append(uuid)
            plan.files.extend(
                build_restore_files(root, summary.get("changed_files") or []))
        else:
            plan.kept.append(uuid)
    return plan


def find_posterboard_db(root: str, structure_version: int) -> "str | None":
    """Locate the pulled PosterBoard sqlite under a materialised tree root."""
    candidate = os.path.join(
        root, "Library", "Application Support", "PRBPosterExtensionDataStore",
        str(structure_version), DB_FILE_NAME)
    return candidate if os.path.isfile(candidate) else None


def _iter_files(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            yield os.path.join(dirpath, name)


def _rewrite_identity(config_dir: str, new_id: int) -> None:
    """Point a cloned descriptor at a freshly allocated wallpaper identifier.

    The identifier lives in three places and PosterKit expects them to agree:
    the plain ``descriptor.identifier`` sidecar, ``userInfo`` (string) and
    ``Wallpaper.plist`` (integer).
    """
    with open(os.path.join(config_dir, DESCRIPTOR_IDENTIFIER_FILE), "wb") as handle:
        handle.write(str(new_id).encode())
    for path in _iter_files(config_dir):
        name = os.path.basename(path)
        if name == USERINFO_FILE:
            with open(path, "rb") as handle:
                data = plistlib.load(handle)
            data["wallpaperRepresentingIdentifier"] = str(new_id)
            with open(path, "wb") as handle:
                plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
        elif name == "Wallpaper.plist":
            with open(path, "rb") as handle:
                data = plistlib.load(handle)
            data["identifier"] = new_id
            for variant in (data.get("assets") or {}).values():
                for entry in (variant or {}).values():
                    if isinstance(entry, dict) and "identifier" in entry:
                        entry["identifier"] = new_id
            with open(path, "wb") as handle:
                plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)


def _clone_and_convert(config_dir: str, new_uuid: str, screen,
                       max_multiplier: float) -> str:
    """Copy a descriptor folder to ``new_uuid`` and modernize the clone."""
    new_dir = os.path.join(os.path.dirname(config_dir), new_uuid)
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir)
    shutil.copytree(config_dir, new_dir)
    _rewrite_identity(new_dir, randint(10000, 99999))
    conv.convert_descriptor(new_dir, screen, max_multiplier)
    return new_dir


def rewrite_db_for_new_descriptors(db_path: str,
                                   replacements: "list[tuple[str, str]]") -> None:
    """Move each old poster row onto its new UUID, preserving every setting.

    ``posterAttributes`` (usage metadata plus SELECTED) and
    ``posterRoleMembership`` (the picker position) are copied verbatim, so the
    lock/home customisation the descriptor carries and the wallpaper's place in
    the gallery survive. The old rows are removed so no duplicate is shown.
    """
    if not replacements:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(posterId) FROM poster")
        row = cursor.fetchone()
        max_poster_id = int(row[0]) if row and row[0] is not None else 0
        for old_uuid, new_uuid in replacements:
            poster = cursor.execute(
                "SELECT posterId, providerId FROM poster WHERE UUID = ?",
                (old_uuid,)).fetchone()
            if poster is None:
                continue
            attributes = cursor.execute(
                "SELECT roleId, attributeIdentifier, attributePayload "
                "FROM posterAttributes WHERE posterUUID = ?", (old_uuid,)).fetchall()
            memberships = cursor.execute(
                "SELECT roleId, roleSortKey FROM posterRoleMembership "
                "WHERE posterUUID = ?", (old_uuid,)).fetchall()
            max_poster_id += 1
            cursor.execute(
                "INSERT INTO poster (posterId, UUID, providerId) VALUES (?, ?, ?)",
                (max_poster_id, new_uuid, poster[1]))
            for role_id, identifier, payload in attributes:
                cursor.execute(
                    "INSERT INTO posterAttributes "
                    "(posterUUID, roleId, attributeIdentifier, attributePayload) "
                    "VALUES (?, ?, ?, ?)",
                    (new_uuid, role_id, identifier, payload))
            for role_id, sort_key in memberships:
                cursor.execute(
                    "INSERT INTO posterRoleMembership "
                    "(posterUUID, roleId, roleSortKey) VALUES (?, ?, ?)",
                    (new_uuid, role_id, sort_key))
            cursor.execute("DELETE FROM posterAttributes WHERE posterUUID = ?", (old_uuid,))
            cursor.execute("DELETE FROM posterRoleMembership WHERE posterUUID = ?", (old_uuid,))
            cursor.execute("DELETE FROM poster WHERE UUID = ?", (old_uuid,))
        cursor.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'poster'",
                       (max_poster_id,))
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('poster', ?)",
                           (max_poster_id,))
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


_EMPTY_PLANE_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="{role}" allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 393 852" contentsFormat="RGBA8" cornerCurve="circular" geometryFlipped="0" hidden="0" name="{role}" position="196.5 426"/>
</caml>
"""


def find_clownfish_skeleton(root: str) -> "tuple[str, str] | tuple[None, None]":
    """Find the stock Clownfish descriptor to use as the format skeleton.

    Prefers the Apple "Clownfish" wallpaper (its planes are the depth-capable
    Background/Floating/Foreground set). Returns ``(uuid, dir)`` or
    ``(None, None)`` when the device does not carry it.
    """
    fallback = (None, None)
    for uuid, config_dir in find_collections_configs(root):
        if conv.wallpaper_family(config_dir) != conv.CLOWNFISH_FAMILY:
            continue
        wallpaper_dir = conv._find_wallpaper_dir(config_dir)
        if not wallpaper_dir:
            continue
        roles = {conv.plane_role(p) for p in conv._plane_dirs(wallpaper_dir)}
        if roles < set(PLANE_ROLES):
            continue
        name = conv._read_plist(os.path.join(wallpaper_dir, "Wallpaper.plist")).get("name")
        if str(name) == "Clownfish":
            return uuid, config_dir
        if fallback == (None, None):
            fallback = (uuid, config_dir)
    return fallback


# External JavaScript ``<scriptObject src="...">`` nodes and their ``.js``
# assets make WallpaperKit's ``WKPlatformPackageView`` trap (EXC_BREAKPOINT) the
# moment the poster is rendered, which trips the provider's crash cooldown and
# kills snapshots/Depth for *every* wallpaper. The stock Clownfish and the
# proven-working Odyssey descriptors carry only an empty ``<scriptComponents/>``
# node, so the scripts are stripped here too. The regex/helper are shared with
# the import converter, which applies the same rule.
_SCRIPT_OBJECT_RE = conv._SCRIPT_OBJECT_RE
_strip_scripts = conv.strip_scripts

# Logical (non-pixel) iPhone posters authored against the pre-393 logical size
# are re-expressed in the player's 393x852 space, exactly as the working Odyssey
# descriptor was.
_LOGICAL_GEOMETRY = (
    ("0 0 390 844", "0 0 393 852"),
    ("195 422", "196.5 426"),
)

# The CAML-state flatten helpers are shared with the import converter (the
# PosterBoard "Import Files (.tendies)" path), which flattens the same trapping
# ops. Aliased here so the rebuild path and its test keep a single
# implementation. ``_flatten_plane(role, plane_dir)`` defaults to the 393x852
# player space, matching the skeleton ``index.xml`` geometry.
_UNSUPPORTED_CAML_RE = conv._UNSUPPORTED_CAML_RE
_FLAT_PLANE_CAML = conv._FLAT_PLANE_CAML
_IMAGE_EXTENSIONS = conv._IMAGE_EXTENSIONS
_has_unsupported_caml = conv._has_unsupported_caml
_xml_attr = conv._xml_attr
_pick_plane_image = conv._pick_plane_image
_flatten_plane = conv._flatten_plane


def _adapt_logical_geometry(text: str) -> str:
    """Rescale a 390x844 logical poster's CAML to the 393x852 player space."""
    for old, new in _LOGICAL_GEOMETRY:
        text = text.replace(old, new)
    return text


def _publish_root(text: str, role: str) -> str:
    """Tag the plane's root layer as the published depth layer.

    Only the ``id`` changes (and the internal ``targetId`` references that point
    at it); ``name``, ``bounds`` and ``transform`` stay verbatim so the inserted
    animation is untouched.
    """
    match = re.search(r"<CALayer\b[^>]*>", text)
    if not match:
        raise conv.ConversionError("main.caml has no root CALayer")
    tag = match.group(0)
    old_id = conv._get_attr(tag, "id")
    new_tag = conv._set_attr(tag, "id", role)
    if old_id and old_id != role:
        text = text.replace(f'targetId="{old_id}"', f'targetId="{role}"')
    return text[:match.start()] + new_tag + text[match.end():]


def _merge_plane_index(skeleton_index: str, source_index: str, role: str,
                       adapt_geometry: bool = False) -> None:
    """Keep the skeleton's modern ``index.xml`` but adopt the source geometry.

    A pixel canvas (e.g. a 3176x3176 frame sequence) keeps its coordinate space
    verbatim. A logical 390x844 poster is instead normalised to the skeleton's
    393x852 player space (``adapt_geometry``), matching the working Odyssey.
    The skeleton always supplies ``publishedObjectNames`` and the modern player
    defaults.
    """
    data = conv._read_plist(skeleton_index)
    source = conv._read_plist(source_index)
    if not adapt_geometry:
        for key in INDEX_GEOMETRY_KEYS:
            if key in source:
                data[key] = source[key]
    data["publishedObjectNames"] = [role]
    with open(skeleton_index, "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_XML)


def insert_into_clownfish(config_dir: str, skeleton_dir: str, new_uuid: str,
                          max_multiplier: float = conv.DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER
                          ) -> str:
    """Build a descriptor from the Clownfish skeleton + a wallpaper's planes.

    The skeleton configuration is copied wholesale (plane folder names, modern
    ``index.xml``, ``Wallpaper.plist``, the depth ``renderingConfiguration`` /
    ``configurableOptions`` plists). Each skeleton plane then receives the source
    wallpaper's ``main.caml`` and every asset file verbatim, its root layer is
    published under the matching role, and its geometry is carried over. Layers
    the wallpaper does not have stay as empty published layers.
    """
    new_dir = os.path.join(os.path.dirname(config_dir), new_uuid)
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir)
    shutil.copytree(skeleton_dir, new_dir)

    skeleton_wallpaper = conv._find_wallpaper_dir(new_dir)
    source_wallpaper = conv._find_wallpaper_dir(config_dir)
    if not skeleton_wallpaper or not source_wallpaper:
        raise conv.ConversionError("missing .wallpaper bundle")

    source_name = conv._read_plist(
        os.path.join(source_wallpaper, "Wallpaper.plist")).get("name")
    sources = {}
    for plane_dir in conv._plane_dirs(source_wallpaper):
        role = conv.plane_role(plane_dir)
        if role:
            sources[role] = plane_dir
    if "Background" not in sources:
        raise conv.ConversionError("wallpaper has no Background plane")

    for skeleton_plane in conv._plane_dirs(skeleton_wallpaper):
        role = conv.plane_role(skeleton_plane)
        if role not in PLANE_ROLES:
            continue
        for entry in os.listdir(skeleton_plane):
            if entry in ("index.xml", "assetManifest.caml"):
                continue
            path = os.path.join(skeleton_plane, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        source = sources.get(role)
        if source is None:
            conv._write_text(os.path.join(skeleton_plane, "main.caml"),
                             _EMPTY_PLANE_CAML.format(role=role))
            continue
        source_index = conv._read_plist(os.path.join(source, "index.xml"))
        pixel_canvas = bool(source_index.get("unitsInPixelsInPlayer"))
        text = _strip_scripts(conv._read_text(os.path.join(source, "main.caml")))
        if _has_unsupported_caml(text):
            logger.warning(
                "Flattening %s plane of %s: CAML uses a state op the depth "
                "renderer traps on", role, new_uuid)
            conv._write_text(os.path.join(skeleton_plane, "main.caml"),
                             _flatten_plane(role, source))
            flatten = True
        else:
            if not pixel_canvas:
                text = _adapt_logical_geometry(text)
            conv._write_text(os.path.join(skeleton_plane, "main.caml"),
                             _publish_root(text, role))
            flatten = False
        assets = os.path.join(source, "assets")
        if os.path.isdir(assets):
            destination = os.path.join(skeleton_plane, "assets")
            os.makedirs(destination, exist_ok=True)
            for asset in sorted(os.listdir(assets)):
                source_asset = os.path.join(assets, asset)
                if (os.path.isfile(source_asset)
                        and not asset.lower().endswith(".js")):
                    shutil.copy2(source_asset, os.path.join(destination, asset))
        _merge_plane_index(os.path.join(skeleton_plane, "index.xml"),
                           os.path.join(source, "index.xml"), role,
                           adapt_geometry=flatten or not pixel_canvas)
        merged = conv._read_plist(os.path.join(skeleton_plane, "index.xml"))
        conv.ensure_background_image(
            skeleton_plane, role,
            merged.get("documentWidth") or 393.0,
            merged.get("documentHeight") or 852.0)

    wallpaper_plist = os.path.join(skeleton_wallpaper, "Wallpaper.plist")
    data = conv._read_plist(wallpaper_plist)
    data["family"] = conv.CLOWNFISH_FAMILY
    data["contentVersion"] = conv.MODERN_CONTENT_VERSION
    data["disableAdaptiveTime"] = True
    data["maximumAdaptiveTimeMultiplier"] = max_multiplier
    if source_name:
        data["name"] = source_name
        default = (data.setdefault("assets", {}).setdefault("lockAndHome", {})
                   .setdefault("default", {}))
        default["name"] = source_name
    with open(wallpaper_plist, "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)

    _rewrite_identity(new_dir, randint(10000, 99999))
    return new_dir


def insert_tree_into_clownfish(root: str, structure_version: int,
                               skeleton_dir: "str | None" = None,
                               db_path: "str | None" = None,
                               max_multiplier: float = conv.DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER,
                               repack_families=conv.REPACK_FAMILIES) -> RebuildPlan:
    """Insert every legacy wallpaper into fresh Clownfish-skeleton descriptors.

    Like :func:`repack_to_new_descriptors` this creates new UUIDs and re-points
    the database rows, but the descriptor body is built from the stock Clownfish
    skeleton rather than modernizing the source configuration in place.
    """
    plan = RebuildPlan(root=root, structure_version=structure_version)
    skeleton_dir = skeleton_dir or find_clownfish_skeleton(root)[1]
    if not skeleton_dir:
        raise conv.ConversionError(
            "no Clownfish skeleton on the device; apply the Clownfish wallpaper "
            "once so its descriptor can be used as the format template")

    for old_uuid, config_dir in find_collections_configs(root):
        if os.path.abspath(config_dir) == os.path.abspath(skeleton_dir):
            plan.kept.append(old_uuid)
            continue
        action = conv.conversion_action(config_dir, repack_families)
        if action == conv.ACTION_SKIP:
            plan.skipped.append(old_uuid)
            continue
        if action != conv.ACTION_REPACK:
            plan.kept.append(old_uuid)
            continue
        try:
            new_uuid = str(uuid_module.uuid4()).upper()
            new_dir = insert_into_clownfish(config_dir, skeleton_dir, new_uuid,
                                            max_multiplier)
        except Exception as e:  # never let one bad package abort the pass
            logger.warning("Could not insert wallpaper %s: %s", old_uuid, e)
            plan.failed.append((old_uuid, str(e)))
            continue
        plan.repacked.append(new_uuid)
        plan.replacements.append((old_uuid, new_uuid))
        plan.files.extend(build_restore_files(root, list(_iter_files(new_dir))))

    if plan.replacements:
        if db_path is None:
            db_path = find_posterboard_db(root, structure_version)
        if db_path:
            rewrite_db_for_new_descriptors(db_path, plan.replacements)
            plan.files.extend(build_restore_files(root, [db_path]))
            db_rel = os.path.relpath(db_path, root).replace(os.sep, "/")
            for suffix in ("-wal", "-shm"):
                plan.files.append(FileToRestore(
                    contents=b"", contents_path=None,
                    restore_path=f"/{db_rel}{suffix}", domain=POSTERBOARD_DOMAIN))
    return plan


def repack_to_new_descriptors(root: str, structure_version: int,
                              db_path: "str | None" = None,
                              max_multiplier: float = conv.DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER,
                              repack_families=conv.REPACK_FAMILIES,
                              screen=None) -> RebuildPlan:
    """Rebuild each legacy wallpaper into a brand-new descriptor.

    Unlike :func:`plan_rebuild` (which edits the existing configuration in
    place), this clones the whole configuration folder to a fresh UUID and
    registers it in the PosterBoard database, so the lock/home customisation the
    descriptor carries (clock, widgets, home-screen icon tint/size) is kept while
    PosterKit sees a genuinely new poster and renders the Depth effect.
    """
    plan = RebuildPlan(root=root, structure_version=structure_version)
    for old_uuid, config_dir in find_collections_configs(root):
        action = conv.conversion_action(config_dir, repack_families)
        if action == conv.ACTION_SKIP:
            plan.skipped.append(old_uuid)
            continue
        if action != conv.ACTION_REPACK:
            plan.kept.append(old_uuid)
            continue
        try:
            new_uuid = str(uuid_module.uuid4()).upper()
            new_dir = _clone_and_convert(config_dir, new_uuid, screen, max_multiplier)
        except Exception as e:  # never let one bad package abort the pass
            logger.warning("Could not repack wallpaper %s: %s", old_uuid, e)
            plan.failed.append((old_uuid, str(e)))
            continue
        plan.repacked.append(new_uuid)
        plan.replacements.append((old_uuid, new_uuid))
        plan.files.extend(build_restore_files(root, list(_iter_files(new_dir))))

    if plan.replacements:
        if db_path is None:
            db_path = find_posterboard_db(root, structure_version)
        if db_path:
            rewrite_db_for_new_descriptors(db_path, plan.replacements)
            plan.files.extend(build_restore_files(root, [db_path]))
            db_rel = os.path.relpath(db_path, root).replace(os.sep, "/")
            for suffix in ("-wal", "-shm"):
                plan.files.append(FileToRestore(
                    contents=b"", contents_path=None,
                    restore_path=f"/{db_rel}{suffix}", domain=POSTERBOARD_DOMAIN))
    return plan


@dataclass
class RebuildResult:
    plan: RebuildPlan
    message: str = ""


async def rebuild_posterboard(udid: str, manager,
                              update_label=lambda x: None,
                              update_progress=lambda x: None,
                              prompt_password=None,
                              prompt_choice=None) -> RebuildResult:
    """Pull, repack and push the device's Marble/Lavender wallpapers.

    ``manager`` is the live ``DeviceManager`` (used for the protective backup and
    the restore). Raises ``NuggetException`` on any unrecoverable error; the
    caller surfaces it through the normal alert pipeline.
    """
    from src.exceptions.nugget_exception import NuggetException
    from src.restore.posterboard_backup import pull_posterboard_container
    from src.restore.storage import posterboard_dir

    out_dir = os.path.join(str(posterboard_dir()), "rebuild", udid)
    update_label("Pulling wallpapers from device...")
    tree, structure_version = await pull_posterboard_container(
        udid, out_dir, update_label, update_progress)

    update_label("Scanning wallpapers...")
    plan = await asyncio.to_thread(plan_rebuild, tree, structure_version)

    if not plan.changed:
        return RebuildResult(
            plan,
            message=("No Marble/Lavender wallpaper needed repacking. "
                     f"Skipped {len(plan.skipped)} Mercury, kept {len(plan.kept)} "
                     f"others, {len(plan.failed)} failed."))

    update_label(
        f"Repacking {len(plan.repacked)} wallpaper(s); preparing backup...")
    prepared_root = None
    try:
        prepared_root, _pb_ok = await manager._prepare_protective_backup(
            update_label, needs_posterboard=False, prompt_password=prompt_password)
    except Exception as e:
        if "disk space" in str(e).lower() or "NotEnoughDiskSpace" in type(e).__name__:
            if prompt_choice is None:
                raise
            decision = prompt_choice(
                "Not Enough Disk Space",
                "The protective backup failed because there is not enough free "
                "disk space.\n\nContinue anyway WITHOUT data protection?\n"
                "(Photos, settings and app data may be lost.)")
            if decision != "resume":
                raise NuggetException("Rebuild cancelled.")
        else:
            raise

    update_label(f"Pushing {len(plan.repacked)} repacked wallpaper(s) back...")
    await manager.start_restore(
        plan.files, update_label,
        prepared_backup_root=prepared_root,
        skip_protective_backup=(prepared_root is None),
        include_keychain=False,
        prompt_choice=prompt_choice,
        supervised=manager.pref_manager.supervised,
        organization_name=manager.pref_manager.organization_name,
    )
    return RebuildResult(
        plan,
        message=(f"Repacked {len(plan.repacked)} wallpaper(s) to the Clownfish "
                 f"format. Skipped {len(plan.skipped)} Mercury, kept "
                 f"{len(plan.kept)} others, {len(plan.failed)} failed."))
