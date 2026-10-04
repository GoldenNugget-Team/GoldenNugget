#!/usr/bin/env python3
"""Offline test for the PosterBoard plist id rewrite (no device needed).

Guards `PosterboardTweak.update_plist_id`: the randomized identifier is still
written into the three id-bearing plists, but the wallpaper's own metadata
(family / name / the nested lockAndHome.default entry) is left exactly as the
source ships it — the `update_for_family` pass that forced the Marble /
Lavender family is gone.

Run: python tools/test_posterboard_plist_id.py
"""
import os
import plistlib
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tweaks.posterboard.posterboard_tweak import PosterboardTweak

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_pb_id_")


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def write(name: str, data: bytes) -> str:
    path = os.path.join(TMP, name)
    with open(path, "wb") as fp:
        fp.write(data)
    return path


# A wallpaper plist shaped like the stock ones: own family/name and a nested
# lockAndHome.default carrying its own name and identifier.
STOCK_WALLPAPER = {
    "family": "Marble",
    "name": "Lemon",
    "identifier": 4242,
    "assets": {
        "lockAndHome": {
            "default": {
                "name": "Lemon",
                "identifier": 4242,
                "animation": "wallpaper.ca",
            }
        }
    },
}


def test_wallpaper_plist_only_gets_the_new_id():
    print("\nWallpaper.plist: identifier rewritten, family/name untouched")
    tweak = PosterboardTweak()
    path = write("com.apple.XYZ_Wallpaper.plist", plistlib.dumps(STOCK_WALLPAPER))
    out = tweak.update_plist_id(TMP, "com.apple.XYZ_Wallpaper.plist", 77777)
    check("contents returned", out is not None and len(out) > 0)
    plist = plistlib.loads(out)
    check("top-level identifier is the new random id", plist["identifier"] == 77777,
          repr(plist["identifier"]))
    check("family is left as shipped", plist.get("family") == "Marble", repr(plist.get("family")))
    check("name is left as shipped (not forced to Lavender)",
          plist.get("name") == "Lemon", repr(plist.get("name")))
    default = plist.get("assets", {}).get("lockAndHome", {}).get("default", {})
    check("nested default.name is left as shipped",
          default.get("name") == "Lemon", repr(default.get("name")))
    check("nested default.identifier is NOT rewritten",
          default.get("identifier") == 4242, repr(default.get("identifier")))
    check("the animation reference survives", default.get("animation") == "wallpaper.ca")


def test_wallpaper_plist_without_assets():
    print("\nWallpaper.plist: minimal file still works")
    tweak = PosterboardTweak()
    path = write("com.apple.MIN_Wallpaper.plist", plistlib.dumps({"identifier": 1}))
    out = tweak.update_plist_id(TMP, "com.apple.MIN_Wallpaper.plist", 5150)
    plist = plistlib.loads(out)
    check("identifier rewritten", plist["identifier"] == 5150, repr(plist["identifier"]))
    check("no assets key invented", "assets" not in plist)


def test_other_id_files_unchanged():
    print("\nThe other two id-bearing plists still get their values")
    tweak = PosterboardTweak()
    check("descriptor.identifier is the raw id",
          tweak.update_plist_id(TMP, "com.apple.posterkit.provider.descriptor.identifier", 31337)
          == b"31337")
    path = write("com.apple.posterkit.provider.contents.userInfo",
                 plistlib.dumps({"wallpaperRepresentingIdentifier": 7, "keep": "me"}))
    out = tweak.update_plist_id(TMP, "com.apple.posterkit.provider.contents.userInfo", 31337)
    plist = plistlib.loads(out)
    check("userInfo representing identifier rewritten",
          plist["wallpaperRepresentingIdentifier"] == "31337",
          repr(plist["wallpaperRepresentingIdentifier"]))
    check("userInfo keeps its other keys", plist.get("keep") == "me")
    check("unrelated files return None (shipped as-is)",
          tweak.update_plist_id(TMP, "somethingelse.plist", 1) is None)


def test_userinfo_identifier_added_when_missing():
    print("\nuserInfo: a tendie that ships WITHOUT the key still gets it")
    tweak = PosterboardTweak()
    # A third-party tendie's userInfo looks exactly like this.
    name = "com.apple.posterkit.provider.contents.userInfo"
    path = write(name,
                 plistlib.dumps({"posterEnvironmentOverrides": b"{}",
                                 "wallpaperRepresentingFileName": "Windows_11.wallpaper"}))
    out = tweak.update_plist_id(TMP, name, 99378)
    plist = plistlib.loads(out)
    check("missing wallpaperRepresentingIdentifier is added (as a string)",
          plist.get("wallpaperRepresentingIdentifier") == "99378",
          repr(plist.get("wallpaperRepresentingIdentifier")))
    check("existing keys survive",
          plist.get("wallpaperRepresentingFileName") == "Windows_11.wallpaper")


def test_descriptor_identifier_sidecar_synthesized():
    print("\nrecursive_add: a tendie without descriptor.identifier gets one")
    import shutil
    tweak = PosterboardTweak()
    root = tempfile.mkdtemp(prefix="gn_pb_tree_")
    desc = os.path.join(root, "descriptors", "E538499C-3F95-4FEA-AE58-191E5112E194")
    contents = os.path.join(desc, "versions", "0", "contents")
    wall = os.path.join(contents, "Windows_11.wallpaper")
    os.makedirs(wall)
    with open(os.path.join(wall, "Wallpaper.plist"), "wb") as fp:
        fp.write(plistlib.dumps({"family": "Windows 11", "identifier": 7400,
                                 "assets": {"lockAndHome": {"default": {"identifier": 7400}}}}))
    with open(os.path.join(contents, "com.apple.posterkit.provider.contents.userInfo"), "wb") as fp:
        fp.write(plistlib.dumps({"posterEnvironmentOverrides": b"{}",
                                 "wallpaperRepresentingFileName": "Windows_11.wallpaper"}))
    files = []
    tweak.recursive_add(files, curr_path=root)
    sidecars = [f for f in files
                if f.restore_path.endswith("com.apple.posterkit.provider.descriptor.identifier")]
    check("exactly one sidecar stamped", len(sidecars) == 1, f"got {len(sidecars)}")
    sidecar_id = sidecars[0].contents.decode()
    check("sidecar is a numeric id", sidecar_id.isdigit(), sidecar_id)
    userinfos = [f for f in files if f.restore_path.endswith(
        "com.apple.posterkit.provider.contents.userInfo")]
    check("userInfo id matches the sidecar",
          plistlib.loads(userinfos[0].contents)["wallpaperRepresentingIdentifier"] == sidecar_id)
    wallpapers = [f for f in files if f.restore_path.endswith("Wallpaper.plist")]
    check("Wallpaper.plist id matches the sidecar",
          plistlib.loads(wallpapers[0].contents)["identifier"] == int(sidecar_id))
    shutil.rmtree(root, ignore_errors=True)


def test_helper_is_gone():
    print("\nupdate_for_family is gone")
    check("no update_for_family method", not hasattr(PosterboardTweak, "update_for_family"))


# =============================================================================
test_wallpaper_plist_only_gets_the_new_id()
test_wallpaper_plist_without_assets()
test_other_id_files_unchanged()
test_userinfo_identifier_added_when_missing()
test_descriptor_identifier_sidecar_synthesized()
test_helper_is_gone()

print(f"\nALL {PASS} CHECKS PASSED")
