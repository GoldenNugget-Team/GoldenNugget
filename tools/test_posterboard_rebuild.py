#!/usr/bin/env python3
"""Offline test for the "Rebuild Database" planning half (no device needed).

Builds a fake pulled PosterBoard tree and checks that ``plan_rebuild`` skips
Mercury, repacks only legacy Marble/Lavender configurations in place (same
UUID) and leaves everything else — including modern and non-Collections
providers — untouched, and that the pushed restore paths mirror the device
layout.

Run: python tools/test_posterboard_rebuild.py
"""
import os
import plistlib
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tweaks.posterboard import posterboard_rebuild as pr

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_pb_rebuild_")

COLLECTIONS = "com.apple.WallpaperKit.CollectionsPoster"
SV = 61

FLAT_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" bounds="0 0 390 844" name="Root Layer" position="195 422">
    <sublayers>
      <CALayer id="#1" bounds="0 0 390 844" name="content" position="195 422"/>
    </sublayers>
  </CALayer>
</caml>
"""


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def make_config(root, extension, uuid, wallpaper_plist, planes, modern=False):
    """Create one pulled configuration and return (config_dir, wallpaper_dir)."""
    config_dir = os.path.join(
        root, "Library", "Application Support", "PRBPosterExtensionDataStore",
        str(SV), "Extensions", extension, "configurations", uuid)
    contents = os.path.join(config_dir, "versions", "0", "contents")
    wallpaper = os.path.join(
        contents, f"{wallpaper_plist['identifier']}.{wallpaper_plist['name']}"
                  f"-{wallpaper_plist.get('logicalScreenClass', '')}.wallpaper")
    os.makedirs(wallpaper)
    for plane in planes:
        plane_dir = os.path.join(wallpaper, plane)
        os.makedirs(os.path.join(plane_dir, "assets"))
        with open(os.path.join(plane_dir, "main.caml"), "w", encoding="utf-8") as fp:
            fp.write(FLAT_CAML)
        index = {"documentWidth": 390.0, "documentHeight": 844.0,
                 "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": True}
        if modern:
            index["publishedObjectNames"] = ["Background"]
        with open(os.path.join(plane_dir, "index.xml"), "wb") as fp:
            plistlib.dump(index, fp)
    with open(os.path.join(wallpaper, "Wallpaper.plist"), "wb") as fp:
        plistlib.dump(wallpaper_plist, fp)
    return config_dir, wallpaper


def test_find_and_plan():
    print("\nfind_collections_configs / plan_rebuild")
    tree = os.path.join(TMP, "tree")
    marble_uuid = "11111111-1111-1111-1111-111111111111"
    lavender_uuid = "22222222-2222-2222-2222-222222222222"
    modern_uuid = "33333333-3333-3333-3333-333333333333"
    mercury_uuid = "44444444-4444-4444-4444-444444444444"

    _, marble_wallpaper = make_config(
        tree, COLLECTIONS, marble_uuid,
        {"family": "Marble", "name": "Marble", "identifier": 7401,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        ["BG-m.ca", "FL-m.ca"])
    make_config(
        tree, COLLECTIONS, lavender_uuid,
        {"family": "Lavender", "name": "Lavender", "identifier": 7402,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        ["BG-l.ca", "FL-l.ca"])
    make_config(
        tree, COLLECTIONS, modern_uuid,
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
        ["7420.Clownfish_Background-390w-844h@3x~iphone.ca"], modern=True)
    # Mercury lives under its own provider extension and must never be touched
    make_config(
        tree, "com.apple.MercuryPoster", mercury_uuid,
        {"family": "Mercury", "name": "Mercury", "identifier": 9000,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        [])

    found = dict(pr.find_collections_configs(tree))
    check("only CollectionsPoster configs found",
          set(found) == {marble_uuid, lavender_uuid, modern_uuid}, sorted(found))
    check("Mercury provider config excluded", mercury_uuid not in found)

    plan = pr.plan_rebuild(tree, SV)
    check("Marble repacked", marble_uuid in plan.repacked)
    check("Lavender repacked", lavender_uuid in plan.repacked)
    check("modern kept", modern_uuid in plan.kept)
    check("plan reports a change", plan.changed)
    check("files only from repacked configs", all(
        marble_uuid in f.restore_path or lavender_uuid in f.restore_path
        for f in plan.files), f"n={len(plan.files)}")

    with open(os.path.join(marble_wallpaper, "BG-m.ca", "index.xml"), "rb") as fp:
        data = plistlib.load(fp)
    check("Marble plane now published", data.get("publishedObjectNames") == ["Background"])
    check("Marble plane scales to fit", data.get("scalesToFitInPlayer") is True)

    rel = os.path.relpath(os.path.join(marble_wallpaper, "Wallpaper.plist"),
                          tree).replace(os.sep, "/")
    matches = [f for f in plan.files if f.restore_path == "/" + rel]
    check("restore path mirrors the tree", len(matches) == 1, rel)
    check("restore domain is PosterBoard",
          matches and matches[0].domain == pr.POSTERBOARD_DOMAIN)
    check("restore contents_path points at the pulled file",
          matches and os.path.isfile(matches[0].contents_path))


def test_failed_isolation():
    print("\nA broken package does not abort the whole pass")
    tree = os.path.join(TMP, "broken")
    good_uuid = "66666666-6666-6666-6666-666666666666"
    bad_uuid = "77777777-7777-7777-7777-777777777777"
    make_config(tree, COLLECTIONS, good_uuid,
                {"family": "Marble", "name": "Marble", "identifier": 7405,
                 "logicalScreenClass": "390w-844h@3x~iphone"},
                ["BG-g.ca"])
    _, wallpaper = make_config(tree, COLLECTIONS, bad_uuid,
                               {"family": "Lavender", "name": "Lavender", "identifier": 7406,
                                "logicalScreenClass": "390w-844h@3x~iphone"},
                               ["BG-b.ca"])
    os.remove(os.path.join(wallpaper, "BG-b.ca", "main.caml"))
    plan = pr.plan_rebuild(tree, SV)
    check("good one repacked", good_uuid in plan.repacked)
    check("broken one recorded as failed",
          [u for u, _ in plan.failed] == [bad_uuid], plan.failed)
    check("broken one not pushed",
          not any(bad_uuid in f.restore_path for f in plan.files))


def test_nothing_to_do():
    print("\nModern-only tree reports no change")
    tree = os.path.join(TMP, "modern_only")
    make_config(tree, COLLECTIONS, "55555555-5555-5555-5555-555555555555",
                {"family": "Clownfish", "name": "Clownfish", "identifier": 7421,
                 "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
                ["7421.Clownfish_Background-390w-844h@3x~iphone.ca"], modern=True)
    plan = pr.plan_rebuild(tree, SV)
    check("nothing repacked", not plan.changed and not plan.repacked)
    check("modern config kept", "55555555-5555-5555-5555-555555555555" in plan.kept)


def _make_db(tree):
    db_path = os.path.join(
        tree, "Library", "Application Support", "PRBPosterExtensionDataStore",
        str(SV), pr.DB_FILE_NAME)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE poster (posterId INTEGER PRIMARY KEY AUTOINCREMENT,"
        " UUID TEXT, providerId TEXT);"
        "CREATE TABLE posterAttributes (posterUUID TEXT, roleId TEXT,"
        " attributeIdentifier TEXT, attributePayload BLOB);"
        "CREATE TABLE posterRoleMembership (posterUUID TEXT, roleId TEXT,"
        " roleSortKey INTEGER);")
    conn.commit()
    conn.close()
    return db_path


def _seed_poster(db_path, old_uuid, provider, sort_key, selected):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO poster (posterId, UUID, providerId) VALUES (1, ?, ?)",
                 (old_uuid, provider))
    conn.execute(
        "INSERT INTO posterAttributes VALUES (?, ?, ?, ?)",
        (old_uuid, pr.LOCKSCREEN_ROLE, "PRPosterRoleAttributeTypeUsageMetadata",
         b"meta-blob"))
    if selected:
        conn.execute("INSERT INTO posterAttributes VALUES (?, ?, ?, ?)",
                     (old_uuid, pr.LOCKSCREEN_ROLE, "SELECTED", "1"))
    conn.execute("INSERT INTO posterRoleMembership VALUES (?, ?, ?)",
                 (old_uuid, pr.LOCKSCREEN_ROLE, sort_key))
    conn.commit()
    conn.close()


def _config_dir_of(wallpaper):
    """``.../configurations/<uuid>`` for a wallpaper dir from ``make_config``."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(wallpaper))))


def test_new_descriptor_rebuild():
    print("\nrepack_to_new_descriptors")
    tree = os.path.join(TMP, "newdesc")
    old_uuid = "AAAAAAAA-1111-1111-1111-111111111111"
    db_path = _make_db(tree)
    _seed_poster(db_path, old_uuid, COLLECTIONS, 7, selected=True)
    _, wallpaper = make_config(
        tree, COLLECTIONS, old_uuid,
        {"family": "Marble", "name": "Lavender", "identifier": 59997,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        ["BG.ca", "FL.ca"])

    plan = pr.repack_to_new_descriptors(tree, SV, db_path=db_path)
    check("one wallpaper repacked", len(plan.repacked) == 1, plan.repacked)
    check("replacement recorded", len(plan.replacements) == 1, plan.replacements)
    new_uuid = plan.repacked[0]
    check("new UUID differs from old", new_uuid != old_uuid)

    conn = sqlite3.connect(db_path)
    old_rows = conn.execute("SELECT * FROM poster WHERE UUID = ?", (old_uuid,)).fetchall()
    new_rows = conn.execute("SELECT posterId, UUID, providerId FROM poster WHERE UUID = ?",
                            (new_uuid,)).fetchall()
    new_attrs = conn.execute(
        "SELECT attributeIdentifier, attributePayload FROM posterAttributes "
        "WHERE posterUUID = ?", (new_uuid,)).fetchall()
    new_memberships = conn.execute(
        "SELECT roleId, roleSortKey FROM posterRoleMembership WHERE posterUUID = ?",
        (new_uuid,)).fetchall()
    conn.close()
    check("old poster row removed", old_rows == [], old_rows)
    check("new poster row registered",
          len(new_rows) == 1 and new_rows[0][2] == COLLECTIONS, new_rows)
    check("usage metadata copied",
          ("PRPosterRoleAttributeTypeUsageMetadata", b"meta-blob") in new_attrs, new_attrs)
    check("SELECTED moved to new UUID", ("SELECTED", "1") in new_attrs, new_attrs)
    check("picker position preserved",
          new_memberships == [(pr.LOCKSCREEN_ROLE, 7)], new_memberships)

    configs_dir = os.path.dirname(_config_dir_of(wallpaper))
    clone_dir = os.path.join(configs_dir, new_uuid)
    check("clone dir created", os.path.isdir(clone_dir), clone_dir)
    contents = os.path.join(clone_dir, "versions", "0", "contents")
    clone_wallpaper = [d for d in os.listdir(contents) if d.endswith(".wallpaper")][0]
    with open(os.path.join(contents, clone_wallpaper, "Wallpaper.plist"), "rb") as fp:
        clone_plist = plistlib.load(fp)
    check("clone family is Clownfish", clone_plist.get("family") == "Clownfish")
    check("clone identifier rewritten",
          isinstance(clone_plist.get("identifier"), int)
          and clone_plist["identifier"] != 59997, clone_plist.get("identifier"))
    with open(os.path.join(clone_dir, pr.DESCRIPTOR_IDENTIFIER_FILE), "rb") as fp:
        identifier_file = fp.read()
    check("descriptor.identifier matches",
          identifier_file == str(clone_plist["identifier"]).encode(), identifier_file)

    wal_files = [f for f in plan.files if f.restore_path.endswith(("-wal", "-shm"))]
    check("0-byte wal/shm shipped",
          len(wal_files) == 2 and all(f.contents == b"" for f in wal_files),
          [f.restore_path for f in wal_files])
    check("db pushed", any(f.restore_path.endswith(".sqlite3") for f in plan.files))


SOURCE_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="#1" bounds="0 0 3176 3176" name="_FLOATING" position="1588 1588">
    <sublayers>
      <CALayer id="#2" bounds="0 0 1170 2532" name="CALayer1" position="1588 1588"/>
    </sublayers>
    <states>
      <LKState name="Locked">
        <LKStateSetValue targetId="#1" keyPath="transform.scale.xy"/>
      </LKState>
    </states>
    <scriptObject src="assets/Root_Layer.js"/>
    <scriptObject src="assets/extra.js"></scriptObject>
  </CALayer>
</caml>
"""

SKELETON_PLANES = [
    "7420.Clownfish_Background-393w-852h@3x~iphone.ca",
    "7420.Clownfish_Floating-393w-852h@3x~iphone.ca",
    "7420.Clownfish_Foreground-393w-852h@3x~iphone.ca",
]


def test_insert_into_clownfish():
    print("\ninsert_into_clownfish (Clownfish skeleton + wallpaper planes)")
    tree = os.path.join(TMP, "clownfish_insert")
    skel_uuid = "CCCCCCCC-0000-0000-0000-000000000001"
    target_uuid = "CCCCCCCC-0000-0000-0000-000000000002"
    db_path = _make_db(tree)
    _seed_poster(db_path, target_uuid, COLLECTIONS, 11, selected=True)
    skel_dir, _ = make_config(
        tree, COLLECTIONS, skel_uuid,
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "393w-852h@3x~iphone",
         "assets": {"lockAndHome": {"default": {
             "identifier": 7420, "name": "Clownfish", "type": "LayeredAnimation",
             "backgroundAnimationFileName": SKELETON_PLANES[0]}}}},
        SKELETON_PLANES, modern=True)
    tgt_dir, tgt_wallpaper = make_config(
        tree, COLLECTIONS, target_uuid,
        {"family": "Lavender", "name": "Lavender", "identifier": 59997,
         "logicalScreenClass": "810w-1080h@2x~ipad"},
        ["9183.Custom_Background-810w-1080h@2x~ipad.ca",
         "9183.Custom_Floating-810w-1080h@2x~ipad.ca"])
    source_bg = os.path.join(
        tgt_wallpaper, "9183.Custom_Background-810w-1080h@2x~ipad.ca")
    with open(os.path.join(source_bg, "main.caml"), "w", encoding="utf-8") as fp:
        fp.write(SOURCE_CAML)
    with open(os.path.join(source_bg, "index.xml"), "wb") as fp:
        plistlib.dump({"documentWidth": 3176.0, "documentHeight": 3176.0,
                       "unitsInPixelsInPlayer": True, "scalesToFitInPlayer": False}, fp)
    with open(os.path.join(source_bg, "assets", "BG0.png"), "wb") as fp:
        fp.write(b"png-bytes")
    with open(os.path.join(source_bg, "assets", "Root_Layer.js"), "wb") as fp:
        fp.write(b"console.log('boom')")

    check("skeleton found", pr.find_clownfish_skeleton(tree)[1] == skel_dir)

    plan = pr.insert_tree_into_clownfish(tree, SV, db_path=db_path)
    check("skeleton kept untouched", skel_uuid in plan.kept, plan.kept)
    check("one wallpaper inserted", len(plan.repacked) == 1, plan.repacked)
    new_uuid = plan.repacked[0]
    check("replacement recorded", plan.replacements == [(target_uuid, new_uuid)],
          plan.replacements)

    clone = os.path.join(os.path.dirname(tgt_dir), new_uuid)
    contents = os.path.join(clone, "versions", "0", "contents")
    clone_wallpaper = [d for d in os.listdir(contents) if d.endswith(".wallpaper")][0]
    clone_wp = os.path.join(contents, clone_wallpaper)
    planes = sorted(d for d in os.listdir(clone_wp) if d.endswith(".ca"))
    check("Clownfish plane folders used",
          all("Clownfish" in p for p in planes), planes)

    clone_bg = os.path.join(clone_wp, SKELETON_PLANES[0])
    with open(os.path.join(clone_bg, "main.caml"), encoding="utf-8") as fp:
        bg_text = fp.read()
    check("root id published to Background", 'id="Background"' in bg_text)
    check("internal targetId remapped", 'targetId="Background"' in bg_text)
    check("source layer name preserved", 'name="_FLOATING"' in bg_text)
    check("source pixel canvas preserved", 'bounds="0 0 3176 3176"' in bg_text)
    check("external scriptObject stripped", "<scriptObject" not in bg_text, bg_text)
    check("javascript asset not copied",
          not os.path.exists(os.path.join(clone_bg, "assets", "Root_Layer.js")))
    check("source asset copied verbatim",
          os.path.isfile(os.path.join(clone_bg, "assets", "BG0.png")))
    with open(os.path.join(clone_bg, "index.xml"), "rb") as fp:
        bg_index = plistlib.load(fp)
    check("source geometry carried into index",
          bg_index.get("documentWidth") == 3176.0
          and bg_index.get("unitsInPixelsInPlayer") is True, bg_index)
    check("index publishes Background",
          bg_index.get("publishedObjectNames") == ["Background"])

    clone_fg = os.path.join(clone_wp, SKELETON_PLANES[2])
    with open(os.path.join(clone_fg, "main.caml"), encoding="utf-8") as fp:
        fg_text = fp.read()
    check("missing Foreground synthesised as empty published layer",
          'id="Foreground"' in fg_text and "<sublayers>" not in fg_text)

    with open(os.path.join(clone_wp, "Wallpaper.plist"), "rb") as fp:
        clone_plist = plistlib.load(fp)
    check("family re-stamped Clownfish", clone_plist.get("family") == "Clownfish")
    check("name taken from the wallpaper", clone_plist.get("name") == "Lavender")
    check("maximumAdaptiveTimeMultiplier set",
          clone_plist.get("maximumAdaptiveTimeMultiplier") == 2.0)
    check("asset identifier rewritten",
          clone_plist["assets"]["lockAndHome"]["default"]["identifier"]
          == clone_plist["identifier"])
    check("source wallpaper identifier unused",
          clone_plist.get("identifier") != 59997, clone_plist.get("identifier"))

    conn = sqlite3.connect(db_path)
    old_rows = conn.execute("SELECT * FROM poster WHERE UUID = ?", (target_uuid,)).fetchall()
    new_memberships = conn.execute(
        "SELECT roleId, roleSortKey FROM posterRoleMembership WHERE posterUUID = ?",
        (new_uuid,)).fetchall()
    conn.close()
    check("old row removed and picker slot kept",
          old_rows == [] and new_memberships == [(pr.LOCKSCREEN_ROLE, 11)],
          (old_rows, new_memberships))
    check("db pushed", any(f.restore_path.endswith(".sqlite3") for f in plan.files))


CRASHY_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="#1" bounds="0 0 390 844" name="Root" position="195 422">
    <sublayers>
      <CALayer id="#2" bounds="0 0 415 856" name="win11.png" meshTransform="[0 0] [0 0 0.5] v" position="-1185 427">
        <contents type="CGImage" src="assets/big.png"/>
      </CALayer>
    </sublayers>
    <states>
      <LKState name="Locked">
        <LKStateAddElement targetId="#2" keyPath="sublayers">
          <object type="CALayer" name="win11.png"/>
        </LKStateAddElement>
      </LKState>
    </states>
  </CALayer>
</caml>
"""


def test_flatten_unsupported_plane():
    print("\ninsert_into_clownfish flattens planes with trapping CAML states")
    check("detects LKStateAddElement", pr._has_unsupported_caml(CRASHY_CAML))
    check("detects meshTransform",
          pr._has_unsupported_caml('<CALayer meshTransform="[0 0]"/>'))
    check("leaves safe CAML alone",
          not pr._has_unsupported_caml(SOURCE_CAML))

    tree = os.path.join(TMP, "flatten")
    skel_uuid = "DDDDDDDD-0000-0000-0000-000000000001"
    skel_dir, _ = make_config(
        tree, COLLECTIONS, skel_uuid,
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "393w-852h@3x~iphone"},
        SKELETON_PLANES, modern=True)
    tgt_uuid = "DDDDDDDD-0000-0000-0000-000000000002"
    tgt_dir, tgt_wallpaper = make_config(
        tree, COLLECTIONS, tgt_uuid,
        {"family": "Lavender", "name": "Lavender", "identifier": 60001,
         "logicalScreenClass": "393w-852h@3x~iphone"},
        ["9183.Custom_Background-393w-852h@3x~iphone.ca"])
    source_bg = os.path.join(tgt_wallpaper,
                             "9183.Custom_Background-393w-852h@3x~iphone.ca")
    with open(os.path.join(source_bg, "main.caml"), "w", encoding="utf-8") as fp:
        fp.write(CRASHY_CAML)
    with open(os.path.join(source_bg, "index.xml"), "wb") as fp:
        plistlib.dump({"documentWidth": 3176.0, "documentHeight": 3176.0,
                       "unitsInPixelsInPlayer": True, "scalesToFitInPlayer": False}, fp)
    with open(os.path.join(source_bg, "assets", "small.png"), "wb") as fp:
        fp.write(b"x")
    with open(os.path.join(source_bg, "assets", "big.png"), "wb") as fp:
        fp.write(b"B" * 4096)

    clone = pr.insert_into_clownfish(tgt_dir, skel_dir, "DDDDDDDD-0000-0000-0000-000000000003")
    contents = os.path.join(clone, "versions", "0", "contents")
    clone_wallpaper = [d for d in os.listdir(contents) if d.endswith(".wallpaper")][0]
    clone_bg = os.path.join(contents, clone_wallpaper, SKELETON_PLANES[0])
    with open(os.path.join(clone_bg, "main.caml"), encoding="utf-8") as fp:
        bg_text = fp.read()
    check("trapping state stripped from flattened plane",
          "LKStateAddElement" not in bg_text and "<object" not in bg_text, bg_text)
    check("meshTransform stripped from flattened plane",
          "meshTransform" not in bg_text, bg_text)
    check("flattened plane uses the largest image",
          'src="assets/big.png"' in bg_text, bg_text)
    check("flattened plane publishes the role", 'id="Background"' in bg_text)
    check("all source assets still copied",
          os.path.isfile(os.path.join(clone_bg, "assets", "small.png"))
          and os.path.isfile(os.path.join(clone_bg, "assets", "big.png")))
    with open(os.path.join(clone_bg, "index.xml"), "rb") as fp:
        bg_index = plistlib.load(fp)
    check("flattened plane uses the logical skeleton geometry",
          bg_index.get("documentWidth") == 390.0
          and bg_index.get("publishedObjectNames") == ["Background"], bg_index)


# =============================================================================
try:
    test_find_and_plan()
    test_failed_isolation()
    test_nothing_to_do()
    test_new_descriptor_rebuild()
    test_insert_into_clownfish()
    test_flatten_unsupported_plane()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nALL {PASS} CHECKS PASSED")
