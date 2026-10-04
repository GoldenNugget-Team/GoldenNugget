#!/usr/bin/env python3
"""Offline test for the legacy wallpaper converter (no device needed).

Guards `posterboard_converter`: a descriptor with no published plane is rewritten
to the modern iOS 27 shape (published root layer by NAME + id, screen-sized
document with `scalesToFitInPlayer`, `unitsInPixelsInPlayer=false`, looping, a
`LayeredAnimation` asset entry and the adaptive-time keys), while an oversized
iOS 17 "flow" canvas is scaled/centred onto the screen. Already-modern packages
must pass through untouched.

Run: python tools/test_posterboard_converter.py
"""
import os
import plistlib
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tweaks.posterboard import posterboard_converter as pc

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_pb_conv_")

FLAT_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 390 844" contentsFormat="RGBA8" geometryFlipped="0" hidden="0" name="Root Layer" position="195 422">
    <sublayers>
      <CALayer id="#1" bounds="0 0 390 844" name="content" position="195 422">
        <contents type="CGImage" src="assets/art.jpeg"/>
      </CALayer>
    </sublayers>
  </CALayer>
</caml>
"""

FLOW_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 3174 3174" contentsFormat="RGBA8" hidden="0" name="_FLOATING" position="2000 2000">
    <sublayers>
      <CALayer id="#1" bounds="0 0 3174 3174" name="_CENTER_FLOATING" position="1587 1587"/>
    </sublayers>
    <scriptObject src="assets/Root_Layer.js"/>
  </CALayer>
</caml>
"""

ROOTID_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="#1" allowsEdgeAntialiasing="1" bounds="0 0 390 844" contentsFormat="RGBA8" name="Root Layer" position="195 422" speed="1">
    <sublayers>
      <CALayer name="Background" bounds="0 0 390 844" position="195 422"/>
    </sublayers>
    <scriptObject src="assets/Root_Layer.js"/>
    <states>
      <LKState name="Unlock">
        <elements>
          <LKStateSetValue targetId="#1" keyPath="speed">
            <value type="real" value="1.4"/>
          </LKStateSetValue>
        </elements>
      </LKState>
    </states>
  </CALayer>
</caml>
"""


CRASHY_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="#1" bounds="0 0 390 844" name="Root Layer" position="195 422" meshTransform="[0 0] [0 0 0.5] v">
    <sublayers>
      <CALayer id="#2" bounds="0 0 390 844" name="content" position="195 422">
        <contents type="CGImage" src="assets/art.jpeg"/>
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


SCRIPTED_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" bounds="0 0 390 844" name="Root Layer" position="195 422">
    <sublayers>
      <CALayer id="#1" bounds="0 0 390 844" name="content" position="195 422">
        <contents type="CGImage" src="assets/art.jpeg"/>
      </CALayer>
    </sublayers>
    <scriptObject src="assets/script 1.js"/>
    <scriptComponents/>
  </CALayer>
</caml>
"""


COLOR_ONLY_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 390 844" contentsFormat="RGBA8" geometryFlipped="1" hidden="0" name="Root Layer" position="195 422" speed="1">
    <backgroundColor opacity="0" value="0.2319 0.3166 0.5"/>
    <sublayers>
      <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" backgroundColor="0.02684 0.1512 0.2793" bounds="0 0 390 844" contentsFormat="RGBA8" cornerCurve="circular" name="Background" position="195 422"/>
    </sublayers>
    <scriptComponents/>
    <states>
      <LKState name="Locked">
        <elements/>
      </LKState>
    </states>
  </CALayer>
</caml>
"""


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def make_descriptor(root, name, plane_files, index_data, wallpaper_plist, caml=FLAT_CAML):
    descriptor = os.path.join(root, "descriptor", name)
    wallpaper = os.path.join(descriptor, "versions", "0", "contents",
                             f"{wallpaper_plist['identifier']}.{wallpaper_plist['name']}"
                             f"-{wallpaper_plist.get('logicalScreenClass', '')}.wallpaper")
    os.makedirs(wallpaper)
    for plane in plane_files:
        plane_dir = os.path.join(wallpaper, plane)
        os.makedirs(os.path.join(plane_dir, "assets"))
        with open(os.path.join(plane_dir, "main.caml"), "w", encoding="utf-8") as fp:
            fp.write(caml)
        with open(os.path.join(plane_dir, "index.xml"), "wb") as fp:
            plistlib.dump(index_data, fp)
        with open(os.path.join(plane_dir, "assets", "art.jpeg"), "wb") as fp:
            fp.write(b"jpeg")
    with open(os.path.join(wallpaper, "Wallpaper.plist"), "wb") as fp:
        plistlib.dump(wallpaper_plist, fp)
    return descriptor, wallpaper


def read_index(plane_dir):
    with open(os.path.join(plane_dir, "index.xml"), "rb") as fp:
        return plistlib.load(fp)


def root_tag(plane_dir):
    import re
    with open(os.path.join(plane_dir, "main.caml"), encoding="utf-8") as fp:
        text = fp.read()
    return re.search(r"<CALayer\b[^>]*>", text).group(0), text


# --- flat legacy (Odyssey-style, 390x844 points) -----------------------------
def test_flat_legacy():
    print("\nFlat legacy wallpaper is published and fitted")
    root = os.path.join(TMP, "flat")
    desc, wallpaper = make_descriptor(
        root, "L0L00000-0000-0000-0000-000000000000",
        ["BG-plain.ca", "FL-plain.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "WWDC22", "name": "Flat", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("detected as legacy", pc.is_legacy_descriptor(desc))
    results = pc.convert_tree(root)
    check("one descriptor converted", len(results) == 1, str(len(results)))
    check("no longer legacy", not pc.is_legacy_descriptor(desc))
    check("screen parsed from logicalScreenClass", results[0]["screen"] == "390x844@3x")

    bg = os.path.join(wallpaper, "BG-plain.ca")
    index = read_index(bg)
    check("publishedObjectNames=Background", index.get("publishedObjectNames") == ["Background"])
    check("units are points", index.get("unitsInPixelsInPlayer") is False)
    check("scales to fit", index.get("scalesToFitInPlayer") is True)
    check("document is the screen", index.get("documentWidth") == 390.0)
    tag, _ = root_tag(bg)
    check("root name preserved for scripts", 'name="Root Layer"' in tag, tag)
    check("root carries the matching id", 'id="Background"' in tag, tag)
    check("root position preserved", 'position="195 422"' in tag, tag)

    contents_dir = os.path.dirname(os.path.dirname(bg))
    version_dir = os.path.dirname(contents_dir)
    options_path = os.path.join(contents_dir, pc.CONFIGURABLE_OPTIONS_NAME)
    check("configurableOptions written", os.path.isfile(options_path), options_path)
    check("renderingConfiguration written",
          os.path.isfile(os.path.join(version_dir, pc.RENDERING_CONFIGURATION_NAME)))
    options = None
    with open(options_path, "rb") as fp:
        options = plistlib.load(fp)
    check("configurableOptions is an NSKeyedArchiver",
          options.get("$archiver") == "NSKeyedArchiver")
    check("configurableOptions depth enabled",
          any(o.get("depthEffectDisabled") is False for o in options["$objects"]
              if isinstance(o, dict)))

    data = None
    with open(os.path.join(wallpaper, "Wallpaper.plist"), "rb") as fp:
        data = plistlib.load(fp)
    check("family re-stamped Clownfish", data.get("family") == "Clownfish",
          repr(data.get("family")))
    check("human name preserved", data.get("name") == "Flat")
    default = data["assets"]["lockAndHome"]["default"]
    check("asset type is LayeredAnimation", default.get("type") == "LayeredAnimation")
    check("background asset points at the plane",
          default.get("backgroundAnimationFileName") == "BG-plain.ca", repr(default))
    check("floating asset points at the plane",
          default.get("floatingAnimationFileNameKey") == "FL-plain.ca", repr(default))
    check("foreground synthesized for Clownfish depth",
          default.get("foregroundAnimationFileName") == "foreground.ca", repr(default))
    fg = os.path.join(wallpaper, "foreground.ca")
    check("foreground plane folder created", os.path.isdir(fg), fg)
    fg_index = read_index(fg)
    check("foreground plane published", fg_index.get("publishedObjectNames") == ["Foreground"],
          repr(fg_index.get("publishedObjectNames")))
    fg_tag, fg_text = root_tag(fg)
    check("foreground root carries the matching id", 'id="Foreground"' in fg_tag, fg_tag)
    check("foreground is an empty published root (no sublayers)",
          "<sublayers>" not in fg_text, fg_text)
    check("contentVersion filled", data.get("contentVersion") == pc.MODERN_CONTENT_VERSION)
    check("adaptive time kept on", data.get("disableAdaptiveTime") is True)


# --- oversized iOS 17 flow canvas -------------------------------------------
def test_flow_oversized():
    print("\nOversized iOS 17 flow canvas is scaled and centred")
    root = os.path.join(TMP, "flow")
    desc, wallpaper = make_descriptor(
        root, "75650000-0000-0000-0000-000000000000",
        ["7565.iOS_17_Background-390w-844h@3x~iphone.ca"],
        {"documentWidth": 3174.0, "documentHeight": 3174.0,
         "unitsInPixelsInPlayer": True, "scalesToFitInPlayer": False},
        {"family": "iOS 17", "name": "iOS 17", "identifier": 7565,
         "contentVersion": 2.06, "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=FLOW_CAML,
    )
    pc.convert_tree(root)
    plane = os.path.join(wallpaper, "7565.iOS_17_Background-390w-844h@3x~iphone.ca")
    index = read_index(plane)
    check("px canvas becomes screen-sized points", index.get("documentWidth") == 390.0)
    check("px flag cleared", index.get("unitsInPixelsInPlayer") is False)
    tag, text = root_tag(plane)
    check("_FLOATING name preserved", 'name="_FLOATING"' in tag, tag)
    check("root published as Background", 'id="Background"' in tag, tag)
    check("content scale covers the screen", 'transform="scale(0.797' in tag, tag)
    check("root position preserved", 'position="2000 2000"' in tag, tag)
    check("scriptObject stripped", "scriptObject" not in text, text)
    with open(os.path.join(wallpaper, "Wallpaper.plist"), "rb") as fp:
        data = plistlib.load(fp)
    check("existing contentVersion kept", data.get("contentVersion") == 2.06)
    check("adaptive time enabled", data.get("maximumAdaptiveTimeMultiplier") == 2.0)


# --- legacy root with an internal id referenced by its own states -------------
def test_root_id_rewritten_without_breaking_states():
    print("\nRoot id is republished and its targetId references follow")
    root = os.path.join(TMP, "rootid")
    desc, wallpaper = make_descriptor(
        root, "2EAEAFC7-0000-0000-0000-000000000000", ["BG-ubuntu.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Marble", "name": "Lavender", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=ROOTID_CAML,
    )
    pc.convert_tree(root)
    plane = os.path.join(wallpaper, "BG-ubuntu.ca")
    tag, text = root_tag(plane)
    check("root republished as Background", 'id="Background"' in tag, tag)
    check("root no longer carries the old id", 'id="#1"' not in tag, tag)
    check("root name preserved", 'name="Root Layer"' in tag, tag)
    check("targetId repointed to the role", 'targetId="Background"' in text)
    check("stale targetId gone", 'targetId="#1"' not in text)
    check("external script stripped", 'src="assets/Root_Layer.js"' not in text, text)
    check("points canvas not re-scaled", "transform=" not in tag, tag)


# --- a color-only Background gets a real image -------------------------------
def test_color_only_background_gets_image():
    print("\nColor-only Background is rendered to an image (depth trap guard)")
    root = os.path.join(TMP, "coloronly")
    _desc, wallpaper = make_descriptor(
        root, "5163C281-0000-0000-0000-000000000000",
        ["Windows_11_Background.ca", "Windows_11_Floating.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Windows 11", "name": "Windows 11", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=COLOR_ONLY_CAML,
    )
    pc.convert_tree(root)
    bg = os.path.join(wallpaper, "Windows_11_Background.ca")
    tag, text = root_tag(bg)
    check("background still published", 'id="Background"' in tag, tag)
    check("background gained a CGImage",
          'src="assets/solid_background.png"' in text, text)
    image = os.path.join(bg, "assets", "solid_background.png")
    check("rendered image exists", os.path.isfile(image), image)
    from PIL import Image
    check("image is screen-sized", Image.open(image).size == (390, 844),
          str(Image.open(image).size))
    check("states preserved", "<states>" in text, text)


# --- the import prompt only fires for a legacy package inside the archive -----
def _write_tendie(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_legacy_families():
    print("\nLegacy packages are detected straight out of the .tendies zip")
    path = _write_tendie(os.path.join(TMP, "prompt.tendies"), {
        "descriptors/LEGACY/versions/0/contents/Old.wallpaper/Wallpaper.plist":
            plistlib.dumps({"family": "Marble"}),
        "descriptors/LEGACY/versions/0/contents/Old.wallpaper/bg.ca/index.xml":
            "<plist><dict/></plist>",
        "descriptors/LEGACY/versions/0/contents/Old.wallpaper/bg.ca/main.caml":
            FLOW_CAML,
        "descriptors/MODERN/versions/0/contents/New.wallpaper/Wallpaper.plist":
            plistlib.dumps({"family": "Clownfish"}),
        "descriptors/MODERN/versions/0/contents/New.wallpaper/bg.ca/index.xml":
            pc._modern_index_xml(393, 852, "Background"),
        "__MACOSX/descriptors/LEGACY/versions/0/contents/Old.wallpaper/bg.ca/index.xml":
            "<plist><dict/></plist>",
    })
    check("only the legacy package is reported",
          pc.legacy_families(path) == ["Marble"], str(pc.legacy_families(path)))
    check("a bundle with no family falls back to its folder name",
          pc.legacy_families(_write_tendie(os.path.join(TMP, "nofam.tendies"), {
              "descriptors/X/versions/0/contents/7400.Clownfish-393w-852h@3x~iphone.wallpaper"
              "/bg.ca/index.xml": "<plist><dict/></plist>",
          })) == ["7400.Clownfish-393w-852h@3x~iphone.wallpaper"])
    check("a modern-only archive reports nothing",
          pc.legacy_families(_write_tendie(os.path.join(TMP, "modern.tendies"), {
              "descriptors/M/versions/0/contents/New.wallpaper/bg.ca/index.xml":
                  pc._modern_index_xml(393, 852, "Background"),
          })) == [])


# --- trapping CAML state is flattened on import ------------------------------
def test_flatten_legacy_plane():
    print("\nLegacy plane with a trapping CAML state is flattened on import")
    root = os.path.join(TMP, "flatten_legacy")
    desc, wallpaper = make_descriptor(
        root, "E538499C-0000-0000-0000-000000000000",
        ["Windows_11_Background.ca", "Windows_11_Floating.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Windows 11", "name": "Windows 11", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=CRASHY_CAML,
    )
    check("descriptor detected as legacy", pc.is_legacy_descriptor(desc))
    results = pc.convert_tree(root)
    check("descriptor converted", len(results) == 1, str(len(results)))
    fl = os.path.join(wallpaper, "Windows_11_Floating.ca")
    with open(os.path.join(fl, "main.caml"), encoding="utf-8") as fp:
        text = fp.read()
    check("state op stripped",
          "LKStateAddElement" not in text and "<object" not in text, text)
    check("mesh transform stripped", "meshTransform" not in text, text)
    check("flattened plane publishes the role", 'id="Floating"' in text, text)
    check("flattened plane uses a real asset", 'src="assets/art.jpeg"' in text, text)
    with open(os.path.join(wallpaper, "Wallpaper.plist"), "rb") as fp:
        data = plistlib.load(fp)
    check("family re-stamped Clownfish", data.get("family") == "Clownfish")


def test_flatten_modern_plane():
    print("\nAlready-modern plane with a trapping CAML state is flattened too")
    root = os.path.join(TMP, "flatten_modern")
    desc, wallpaper = make_descriptor(
        root, "AAAAAAA1-0000-0000-0000-000000000000",
        ["7420.Clownfish_Background-390w-844h@3x~iphone.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": True,
         "publishedObjectNames": ["Background"]},
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=CRASHY_CAML,
    )
    check("modern descriptor is not legacy", not pc.is_legacy_descriptor(desc))
    results = pc.convert_tree(root)
    check("flatten result reported",
          len(results) == 1 and results[0].get("flattened"), str(results))
    plane = os.path.join(wallpaper, "7420.Clownfish_Background-390w-844h@3x~iphone.ca")
    with open(os.path.join(plane, "main.caml"), encoding="utf-8") as fp:
        text = fp.read()
    check("modern plane state op stripped", "LKStateAddElement" not in text, text)
    check("modern plane still publishes the role", 'id="Background"' in text, text)


# --- external scripts are stripped on import (WallpaperKit trap) -------------
def test_script_stripped_on_import():
    print("\nLegacy plane's external script is stripped, plane still published")
    root = os.path.join(TMP, "script_legacy")
    desc, wallpaper = make_descriptor(
        root, "E538499C-1111-1111-1111-111111111111", ["BG-win11.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Windows 11", "name": "Windows 11", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=SCRIPTED_CAML,
    )
    check("descriptor detected as legacy", pc.is_legacy_descriptor(desc))
    pc.convert_tree(root)
    plane = os.path.join(wallpaper, "BG-win11.ca")
    tag, text = root_tag(plane)
    check("external script removed", "<scriptObject" not in text, text)
    check("empty scriptComponents kept", "<scriptComponents" in text, text)
    check("plane published, not flattened", 'id="Background"' in tag, tag)
    check("real asset kept", 'src="assets/art.jpeg"' in text, text)
    check("root name preserved", 'name="Root Layer"' in tag, tag)


def test_script_stripped_modern():
    print("\nAlready-modern plane's external script is stripped too")
    root = os.path.join(TMP, "script_modern")
    desc, wallpaper = make_descriptor(
        root, "AAAAAAA2-0000-0000-0000-000000000000",
        ["7420.Clownfish_Background-390w-844h@3x~iphone.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": True,
         "publishedObjectNames": ["Background"]},
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
        caml=SCRIPTED_CAML,
    )
    check("modern descriptor is not legacy", not pc.is_legacy_descriptor(desc))
    results = pc.convert_tree(root)
    check("sanitize reported", len(results) == 1, str(results))
    plane = os.path.join(wallpaper, "7420.Clownfish_Background-390w-844h@3x~iphone.ca")
    with open(os.path.join(plane, "main.caml"), encoding="utf-8") as fp:
        text = fp.read()
    check("modern external script removed", "<scriptObject" not in text, text)
    check("modern CGI content kept", 'src="assets/art.jpeg"' in text, text)


# --- macOS __MACOSX resource forks are ignored --------------------------------
def test_macosx_ignored():
    print("\n__MACOSX resource-fork copies are ignored")
    root = os.path.join(TMP, "macosx")
    desc, _wallpaper = make_descriptor(
        root, "BBBBBBB1-0000-0000-0000-000000000000", ["BG-x.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Marble", "name": "MacFix", "identifier": 7500,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    # A macOS zip mirrors the descriptor under __MACOSX, but holds AppleDouble
    # stubs instead of main.caml — it must never be picked up.
    junk = os.path.join(
        root, "__MACOSX", "descriptor",
        "BBBBBBB1-0000-0000-0000-000000000000", "versions", "0", "contents",
        "7500.MacFix-390w-844h@3x~iphone.wallpaper", "BG-x.ca")
    os.makedirs(junk)
    found = list(pc.iter_descriptor_dirs(root))
    check("real descriptor found",
          any(os.path.abspath(desc) == os.path.abspath(f) for f in found), str(found))
    check("__MACOSX descriptor pruned",
          all("__MACOSX" not in f for f in found), str(found))
    results = pc.convert_tree(root)
    check("only the real descriptor converted", len(results) == 1, str(len(results)))


# --- modern passes through ---------------------------------------------------
def test_modern_untouched():
    print("\nModern descriptor is left alone")
    root = os.path.join(TMP, "modern")
    desc, wallpaper = make_descriptor(
        root, "A9770B0C-D030-4AC7-9D0B-2C46D0F9EB82",
        ["7420.Clownfish_Background-390w-844h@3x~iphone.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": True,
         "publishedObjectNames": ["Background"]},
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7420,
         "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("not legacy", not pc.is_legacy_descriptor(desc))
    results = pc.convert_tree(root)
    check("nothing converted", len(results) == 0, str(len(results)))


# --- rebuild policy: Mercury skip / Marble-Lavender repack -------------------
def test_conversion_policy():
    print("\nRebuild policy skips Mercury and repacks Marble/Lavender only")
    root = os.path.join(TMP, "policy")

    mercury, _ = make_descriptor(
        root, "MERCURY-0000-0000-0000-000000000000", [],
        {"documentWidth": 390.0, "documentHeight": 844.0},
        {"family": "Mercury", "name": "Mercury", "identifier": 9000,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("mercury family is Mercury", pc.wallpaper_family(mercury) == "Mercury")
    check("mercury is skipped", pc.conversion_action(mercury) == pc.ACTION_SKIP)
    check("mercury by provider path is skipped",
          pc.is_mercury("/x/Extensions/com.apple.MercuryPoster/configurations/U"))

    marble, _ = make_descriptor(
        root, "MARBLE-0000-0000-0000-000000000000", ["BG-m.ca", "FL-m.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Marble", "name": "Marble", "identifier": 7401,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("legacy Marble is repacked", pc.conversion_action(marble) == pc.ACTION_REPACK)

    lavender, _ = make_descriptor(
        root, "LAVENDER-0000-0000-0000-000000000000", ["BG-l.ca", "FL-l.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "Lavender", "name": "Lavender", "identifier": 7402,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("legacy Lavender is repacked", pc.conversion_action(lavender) == pc.ACTION_REPACK)

    other, _ = make_descriptor(
        root, "WWDC22-0000-0000-0000-000000000000", ["BG-w.ca", "FL-w.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "WWDC22", "name": "Flat", "identifier": 7403,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("legacy other family is kept", pc.conversion_action(other) == pc.ACTION_KEEP)

    modern, _ = make_descriptor(
        root, "MODERN-0000-0000-0000-000000000000",
        ["7420.Clownfish_Background-390w-844h@3x~iphone.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": True,
         "publishedObjectNames": ["Background"]},
        {"family": "Clownfish", "name": "Clownfish", "identifier": 7404,
         "contentVersion": 1.01, "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    check("modern family is kept", pc.conversion_action(modern) == pc.ACTION_KEEP)


def test_skeleton_rename():
    print("\nConverted bundle is renamed to the stock Clownfish layout")
    root = os.path.join(TMP, "skel")
    desc, _wallpaper = make_descriptor(
        root, "L0L00000-0000-0000-0000-000000000000",
        ["BG-plain.ca", "FL-plain.ca"],
        {"documentWidth": 390.0, "documentHeight": 844.0,
         "unitsInPixelsInPlayer": False, "scalesToFitInPlayer": False},
        {"family": "WWDC22", "name": "Flat", "identifier": 7400,
         "logicalScreenClass": "390w-844h@3x~iphone"},
    )
    # userInfo without a wallpaper file name (third-party tendies ship bare).
    version_dir = os.path.join(desc, "versions", "0")
    contents_dir = os.path.join(version_dir, "contents")
    with open(os.path.join(contents_dir,
                           "com.apple.posterkit.provider.contents.userInfo"), "wb") as fp:
        plistlib.dump({"wallpaperRepresentingIdentifier": "7400"}, fp)

    pc.convert_tree(root)
    results = pc.rename_descriptors_to_skeleton(root)
    check("one bundle renamed", len(results) == 1, str(results))
    wdir = pc._find_wallpaper_dir(desc)
    check("bundle name is the skeleton convention",
          os.path.basename(wdir) == "7400.Clownfish-390w-844h@3x~iphone.wallpaper",
          os.path.basename(wdir))
    planes = sorted(os.path.basename(p) for p in pc._plane_dirs(wdir))
    check("plane names are the skeleton convention", planes == [
        "7400.Clownfish_Background-390w-844h@3x~iphone.ca",
        "7400.Clownfish_Floating-390w-844h@3x~iphone.ca",
        "7400.Clownfish_Foreground-390w-844h@3x~iphone.ca",
    ], str(planes))
    wp = plistlib.load(open(os.path.join(wdir, "Wallpaper.plist"), "rb"))
    default = wp["assets"]["lockAndHome"]["default"]
    check("asset keys point at the renamed planes",
          default.get("backgroundAnimationFileName")
          == "7400.Clownfish_Background-390w-844h@3x~iphone.ca"
          and default.get("floatingAnimationFileNameKey")
          == "7400.Clownfish_Floating-390w-844h@3x~iphone.ca"
          and default.get("foregroundAnimationFileName")
          == "7400.Clownfish_Foreground-390w-844h@3x~iphone.ca", repr(default))
    ui = plistlib.load(open(os.path.join(
        os.path.dirname(wdir),
        "com.apple.posterkit.provider.contents.userInfo"), "rb"))
    check("userInfo points at the renamed bundle",
          ui.get("wallpaperRepresentingFileName")
          == "7400.Clownfish-390w-844h@3x~iphone.wallpaper", repr(ui.get(
              "wallpaperRepresentingFileName")))
    check("index.xml declares plugins", "plugins" in open(
        os.path.join(wdir, planes[0], "index.xml"), encoding="utf-8").read())


def test_helpers():
    print("\nHelpers")
    check("parse screen", pc.parse_logical_screen_class("393w-852h@3x~iphone") == (393, 852, 3))
    check("parse screen rejects junk", pc.parse_logical_screen_class("nope") is None)
    check("bg role", pc.plane_role("BG-squair.xyz.ca") == "Background")
    check("fl role", pc.plane_role("FL-squair.xyz.ca") == "Floating")
    check("fg role", pc.plane_role("FG-squair.xyz.ca") == "Foreground")
    check("background role", pc.plane_role("7565.iOS_17_Background-390w.ca") == "Background")
    check("unknown role", pc.plane_role("video-descriptor") is None)


# =============================================================================
try:
    test_flat_legacy()
    test_flow_oversized()
    test_root_id_rewritten_without_breaking_states()
    test_color_only_background_gets_image()
    test_legacy_families()
    test_flatten_legacy_plane()
    test_flatten_modern_plane()
    test_script_stripped_on_import()
    test_script_stripped_modern()
    test_macosx_ignored()
    test_modern_untouched()
    test_conversion_policy()
    test_skeleton_rename()
    test_helpers()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nALL {PASS} CHECKS PASSED")
