"""Auto-convert legacy CollectionPoster wallpapers to the modern iOS 27 shape.

GoldenNugget's apply path already force-writes a ``renderingConfiguration`` with
``depthEffectDisabled = False``, but PosterKit only turns the Depth effect on when
the wallpaper package follows the modern ("Clownfish") layout:

* every plane ``*.ca/index.xml`` declares ``publishedObjectNames``;
* the plane ``main.caml`` root ``CALayer`` carries the matching ``id`` — iOS 27
  resolves the floating/background layer from ``publishedObjectNames`` and
  refuses to build depth (collapsing the floating view into the foreground) when
  no matching layer exists. The layer's ``name`` is left untouched (a stripped
  script that resolved layers by name is gone, but the name itself is harmless);
* the plane document is the logical screen with ``scalesToFitInPlayer = true``
  and ``unitsInPixelsInPlayer = false``;
* the version ``contents`` folder carries
  ``.com.apple.posterkit.provider.contents.configurableOptions.plist`` with a
  ``preferredRenderingConfiguration`` (``depthEffectDisabled = false``) and the
  version folder carries ``com.apple.posterkit.provider.instance.renderingConfiguration.plist``
  — these are the files PosterKit reads to decide depth is allowed (a legacy
  third-party descriptor ships without them, so depth stays off);
* ``Wallpaper.plist`` is re-stamped ``family = Clownfish`` (the depth-capable
  renderer) and carries ``contentVersion`` / ``disableAdaptiveTime`` /
  ``maximumAdaptiveTimeMultiplier`` and a ``LayeredAnimation`` asset entry.

The transformation always removes a plane's external ``<scriptObject src=...>``
node (but never renames its root layer): an external script makes WallpaperKit's
``WKPlatformPackageView`` trap (``EXC_BREAKPOINT``) the moment the poster is
rendered, which trips the CollectionsPoster crash cooldown and kills
snapshots/Depth for *every* wallpaper. The stock Clownfish and the proven Odyssey
descriptor carry only an empty ``<scriptComponents/>`` node, so its removal costs
nothing. The other exception is a plane whose ``main.caml`` uses a CAML state op
the depth renderer traps on (``LKStateAddElement`` / ``CAMeshTransform``):
publishing it would keep the crash, so it is flattened to a single static image
layer instead.

Packages authored before iOS 27 (third-party ``.tendies``, Apple's iOS 17 "flow"
wallpapers, the lightweight VideoCAML templates) predate that shape, so importing
them yields a flat animation with no depth. This module detects such legacy
descriptors and rewrites them in place to the modern shape, without touching the
wallpaper's own family/name/identifier or its asset files.

The transformation is deliberately conservative: it only touches descriptor
folders that have no published plane and leaves already-modern packages alone, so
it is safe to run on every import. Everything is pure file I/O; there is an
offline test at ``tools/test_posterboard_converter.py``.
"""
import os
import plistlib
import re
import shutil
import zipfile

MODERN_CONTENT_VERSION = 1.01
DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER = 2.0

# The wallpaper family whose renderer builds the Depth effect. Legacy
# Marble/Lavender descriptors stay flat no matter the published layers until
# they are re-stamped as Clownfish (the proven Odyssey repack).
CLOWNFISH_FAMILY = "Clownfish"

# PosterKit reads these two archiver plists when it decides whether a descriptor
# is allowed to build the Depth effect. A legacy third-party wallpaper ships
# without either, so a repack must write them (both take ``depthEffectDisabled``).
CONFIGURABLE_OPTIONS_NAME = ".com.apple.posterkit.provider.contents.configurableOptions.plist"
RENDERING_CONFIGURATION_NAME = "com.apple.posterkit.provider.instance.renderingConfiguration.plist"

# Provider extension for spatial photo posters. Mercury packages are a
# different layout entirely (axonometric 3D, no floating/background planes) and
# must never be rewritten to the Clownfish shape.
MERCURY_PROVIDER = "com.apple.MercuryPoster"
MERCURY_FAMILY = "Mercury"
# Apple's flat CollectionPoster families that ship without a published layer on
# iOS 27 and therefore render with no Depth effect. These are the ones a rebuild
# repacks into the Clownfish shape.
REPACK_FAMILIES = frozenset({"Marble", "Lavender"})

# Result of ``conversion_action``: leave the package alone, rewrite it, or skip
# it outright (Mercury).
ACTION_KEEP = "keep"
ACTION_REPACK = "repack"
ACTION_SKIP = "skip"

LOGICAL_SCREEN_RE = re.compile(r"^(\d+)w-(\d+)h@(\d+)x")

_MICA_ASSET_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <MicaAssetManifest>
    <modules type="NSArray"/>
  </MicaAssetManifest>
</caml>
"""


def configurable_options_plist() -> dict:
    """The ``PRPosterConfigurableOptions`` archiver plist, depth-enabled.

    Mirrors what a modern Apple CollectionsPoster descriptor ships: a
    ``preferredRenderingConfiguration`` with ``depthEffectDisabled = False`` and
    ``role = PRPosterRoleLockScreen``. Without this file PosterKit keeps the
    Depth effect off for a repacked legacy wallpaper.
    """
    from plistlib import UID
    return {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": UID(1)},
        "$objects": [
            "$null",
            {
                "preferredHomeScreenConfiguration": UID(6),
                "$class": UID(11),
                "ambientSupportedDataLayout": 0,
                "displayNameLocalizationKey": UID(0),
                "luminance": UID(5),
                "role": UID(2),
                "preferredRenderingConfiguration": UID(9),
                "preferredTimeFontConfigurations": UID(3),
                "preferredTitleColors": UID(3),
            },
            "PRPosterRoleLockScreen",
            {"NS.objects": [], "$class": UID(4)},
            {"$classname": "NSArray", "$classes": ["NSArray", "NSObject"]},
            0.5,
            {
                "preferredStyle": UID(7),
                "preferredSolidColors": UID(0),
                "$class": UID(8),
                "preferredGradientColors": UID(0),
                "allowsModifyingLegibilityBlur": True,
            },
            0,
            {
                "$classname": "PRPosterDescriptorHomeScreenConfiguration",
                "$classes": ["PRPosterDescriptorHomeScreenConfiguration", "NSObject"],
            },
            {
                "motionEffectsDisabled": False,
                "$class": UID(10),
                "depthEffectDisabled": False,
            },
            {
                "$classname": "PRPosterRenderingConfiguration",
                "$classes": ["PRPosterRenderingConfiguration", "NSObject"],
            },
            {
                "$classname": "PRPosterConfigurableOptions",
                "$classes": ["PRPosterConfigurableOptions", "NSObject"],
            },
        ],
    }


def rendering_configuration_plist() -> dict:
    """The ``PRPosterRenderingConfiguration`` archiver plist, depth-enabled."""
    from plistlib import UID
    return {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": UID(1)},
        "$objects": [
            "$null",
            {
                "motionEffectsDisabled": False,
                "$class": UID(2),
                "depthEffectDisabled": False,
            },
            {
                "$classname": "PRPosterRenderingConfiguration",
                "$classes": ["PRPosterRenderingConfiguration", "NSObject"],
            },
        ],
    }


class ConversionError(Exception):
    """Raised when a legacy descriptor cannot be modernized."""


def parse_logical_screen_class(value) -> "tuple[int, int, int] | None":
    """``"390w-844h@3x~iphone"`` -> ``(390, 844, 3)`` (``None`` when unparsable)."""
    match = LOGICAL_SCREEN_RE.match(str(value or ""))
    if not match:
        return None
    width, height, scale = (int(x) for x in match.groups())
    return width, height, scale


def plane_role(path_name: str) -> "str | None":
    """Map a plane folder name to ``Background``/``Floating``/``Foreground``."""
    name = os.path.basename(path_name).lower()
    if name.endswith(".ca"):
        name = name[:-3]
    tokens = [t for t in re.split(r"[^a-z]+", name) if t]
    if "foreground" in tokens or "fg" in tokens:
        return "Foreground"
    if "floating" in tokens or "fl" in tokens:
        return "Floating"
    if "background" in tokens or "bg" in tokens:
        return "Background"
    return None


def _get_attr(tag: str, name: str) -> "str | None":
    match = re.search(rf'\b{name}="([^"]*)"', tag)
    return match.group(1) if match else None


def _set_attr(tag: str, name: str, value: str) -> str:
    pattern = re.compile(rf'\b{name}="[^"]*"')
    if pattern.search(tag):
        return pattern.sub(f'{name}="{value}"', tag, count=1)
    end = tag.rfind(">")
    return tag[:end] + f' {name}="{value}"' + tag[end:]


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# CAML state operations the depth renderer traps on (EXC_BREAKPOINT inside
# WallpaperKit, which trips the CollectionsPoster crash cooldown and kills
# snapshots/Depth for *every* wallpaper). ``LKStateAddElement`` builds a layer
# tree at state-apply time and ``CAMeshTransform``/``meshTransform`` carries a
# mesh value the renderer cannot decode; neither appears in any working stock or
# repacked descriptor. A plane that uses them is flattened to a static image.
_UNSUPPORTED_CAML_RE = re.compile(
    r"<LKStateAddElement\b|<LKStateRemoveElement\b|\bCAMeshTransform\b"
    r"|(?:^|[\s\"])meshTransform\s*=")

# External JavaScript ``<scriptObject src="...">`` nodes make WallpaperKit's
# ``WKPlatformPackageView`` trap (EXC_BREAKPOINT) as soon as the poster renders,
# which trips the CollectionsPoster crash cooldown and kills snapshots/Depth for
# every wallpaper. The working stock Clownfish and Odyssey descriptors carry only
# an empty ``<scriptComponents/>``, so the node is stripped on import too (the
# same rule the rebuild path uses).
_SCRIPT_OBJECT_RE = re.compile(
    r"<scriptObject\b[^>]*?/\s*>|<scriptObject\b[^>]*?>.*?</scriptObject>",
    re.DOTALL)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".heic", ".heif")

# A flattened plane is a single full-screen image layer in the document space.
_FLAT_PLANE_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="{role}" allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 {width:g} {height:g}" contentsFormat="RGBA8" cornerCurve="circular" geometryFlipped="1" hidden="0" name="Root Layer" position="{cx:g} {cy:g}">
    <sublayers>
      <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 {width:g} {height:g}" contentsFormat="RGBA8" cornerCurve="circular" name="{image}" position="{cx:g} {cy:g}">
        <contents type="CGImage" src="assets/{image}"/>
      </CALayer>
    </sublayers>
  </CALayer>
</caml>
"""

_EMPTY_PLANE_CAML = """<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer id="{role}" allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 {width:g} {height:g}" contentsFormat="RGBA8" cornerCurve="circular" geometryFlipped="0" hidden="0" name="{role}" position="{cx:g} {cy:g}"/>
</caml>
"""


def _has_unsupported_caml(text: str) -> bool:
    """Whether a plane's CAML uses a state op that makes WallpaperKit trap."""
    return bool(_UNSUPPORTED_CAML_RE.search(text))


def plane_has_unsupported_caml(plane_dir: str) -> bool:
    """Whether the plane's ``main.caml`` carries a trapping state op."""
    main_caml = os.path.join(plane_dir, "main.caml")
    if not os.path.isfile(main_caml):
        return False
    return _has_unsupported_caml(_read_text(main_caml))


def strip_scripts(text: str) -> str:
    """Drop external ``<scriptObject>`` nodes from a plane's ``main.caml``."""
    return _SCRIPT_OBJECT_RE.sub("", text)


def _has_external_script(text: str) -> bool:
    return bool(_SCRIPT_OBJECT_RE.search(text))


def plane_has_external_script(plane_dir: str) -> bool:
    """Whether the plane's ``main.caml`` loads an external ``.js`` script."""
    main_caml = os.path.join(plane_dir, "main.caml")
    if not os.path.isfile(main_caml):
        return False
    return _has_external_script(_read_text(main_caml))


def _xml_attr(value: str) -> str:
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _pick_plane_image(plane_dir: str) -> "str | None":
    """Largest image asset in a plane, used as the flattened static frame."""
    assets = os.path.join(plane_dir, "assets")
    if not os.path.isdir(assets):
        return None
    candidates = [
        (os.path.getsize(os.path.join(assets, name)), name)
        for name in os.listdir(assets)
        if (name.lower().endswith(_IMAGE_EXTENSIONS)
            and os.path.isfile(os.path.join(assets, name)))
    ]
    if not candidates:
        return None
    return max(candidates)[1]


def _flatten_plane(role: str, plane_dir: str,
                   width: float = 393.0, height: float = 852.0) -> str:
    """Build a static single-image CAML for a plane with unsupported states."""
    image = _pick_plane_image(plane_dir)
    if not image:
        return _EMPTY_PLANE_CAML.format(
            role=role, width=width, height=height,
            cx=width / 2.0, cy=height / 2.0)
    return _FLAT_PLANE_CAML.format(
        role=role, image=_xml_attr(image), width=width, height=height,
        cx=width / 2.0, cy=height / 2.0)


# A plane that paints only a solid ``backgroundColor`` ships no ``<contents>``
# image. WallpaperKit's depth renderer force-unwraps the published Background
# layer's image and traps (``EXC_BREAKPOINT``) when it is missing — every working
# stock and repacked Clownfish background carries a real ``CGImage``. The solid
# fill is rendered to a PNG and injected so the plane always has one.
def _rgb_from_components(value: str) -> "tuple[int, int, int] | None":
    parts = value.split()
    if len(parts) < 3:
        return None
    try:
        channels = [max(0.0, min(1.0, float(part))) for part in parts[:3]]
    except ValueError:
        return None
    return tuple(int(round(channel * 255)) for channel in channels)


def _solid_background_color(text: str) -> "tuple[int, int, int] | None":
    """The first opaque solid color in a plane's CAML, if any.

    A sublayer's ``backgroundColor`` attribute (the visible fill) wins over the
    root's ``<backgroundColor>`` element, which the source often leaves at
    opacity 0.
    """
    for match in re.finditer(r'backgroundColor="([^"]+)"', text):
        rgb = _rgb_from_components(match.group(1))
        if rgb:
            return rgb
    for match in re.finditer(r'<backgroundColor\b[^>]*\bvalue="([^"]+)"', text):
        rgb = _rgb_from_components(match.group(1))
        if rgb:
            return rgb
    return None


_SELF_CLOSING_LAYER_RE = re.compile(r"<CALayer\b[^>]*/>")


def _inject_contents(text: str, image: str) -> str:
    """Give the last empty sublayer a real CGImage, leaving the CAML intact."""
    matches = list(_SELF_CLOSING_LAYER_RE.finditer(text))
    if not matches:
        return text
    match = matches[-1]
    head = match.group(0)[:-2]  # drop the trailing "/>"
    injected = (f'{head}><contents type="CGImage" '
                f'src="assets/{_xml_attr(image)}"/></CALayer>')
    return text[:match.start()] + injected + text[match.end():]


def ensure_background_image(plane_dir: str, role: str,
                            doc_width: float, doc_height: float) -> "str | None":
    """Render a color-only plane's fill to a PNG and publish it as its image.

    Returns the rewritten ``main.caml`` path, or ``None`` when the plane already
    carries a ``<contents>`` image or paints no solid color.
    """
    main_caml = os.path.join(plane_dir, "main.caml")
    if not os.path.isfile(main_caml):
        return None
    text = _read_text(main_caml)
    if "<contents" in text:
        return None
    color = _solid_background_color(text)
    if color is None:
        return None
    image = f"solid_{role.lower()}.png"
    assets = os.path.join(plane_dir, "assets")
    os.makedirs(assets, exist_ok=True)
    from PIL import Image
    Image.new(
        "RGB",
        (max(1, int(round(doc_width))), max(1, int(round(doc_height)))),
        color,
    ).save(os.path.join(assets, image))
    rewritten = _inject_contents(text, image)
    if rewritten == text:
        return None
    _write_text(main_caml, rewritten)
    return main_caml


def flatten_unsupported_planes(descriptor_dir: str) -> "list[str]":
    """Sanitize every plane of a descriptor, in place.

    Flattens any plane carrying a trapping CAML state op and strips the external
    ``<scriptObject>`` node from every plane (both trap ``WKPlatformPackageView``).
    Returns the ``main.caml`` paths that were rewritten (empty when the package is
    already safe). Called for already-modern descriptors too: a third-party
    package can publish its layers yet still carry a script/state op that crashes.
    """
    wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
    if not wallpaper_dir:
        return []
    parsed = parse_logical_screen_class(
        _read_plist(os.path.join(wallpaper_dir, "Wallpaper.plist")).get(
            "logicalScreenClass"))
    width, height, _scale = parsed or (393, 852, 3)
    written = []
    for plane_dir in _plane_dirs(wallpaper_dir):
        role = plane_role(plane_dir)
        if not role:
            continue
        main_caml = os.path.join(plane_dir, "main.caml")
        if not os.path.isfile(main_caml):
            continue
        text = strip_scripts(_read_text(main_caml))
        if _has_unsupported_caml(text):
            _write_text(main_caml, _flatten_plane(role, plane_dir, width, height))
            written.append(main_caml)
        elif text != _read_text(main_caml):
            _write_text(main_caml, text)
            written.append(main_caml)
    return written


def _read_plist(path: str) -> dict:
    try:
        with open(path, "rb") as handle:
            data = plistlib.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_plane_index(plane_dir: str) -> dict:
    return _read_plist(os.path.join(plane_dir, "index.xml"))


def _plane_dirs(wallpaper_dir: str) -> "list[str]":
    return [
        os.path.join(wallpaper_dir, name)
        for name in sorted(os.listdir(wallpaper_dir))
        if name.endswith(".ca") and os.path.isdir(os.path.join(wallpaper_dir, name))
    ]


def _find_wallpaper_dir(descriptor_dir: str) -> "str | None":
    versions = os.path.join(descriptor_dir, "versions")
    if not os.path.isdir(versions):
        return None
    for version in sorted(os.listdir(versions)):
        contents = os.path.join(versions, version, "contents")
        if not os.path.isdir(contents):
            continue
        for name in sorted(os.listdir(contents)):
            candidate = os.path.join(contents, name)
            if name.endswith(".wallpaper") and os.path.isdir(candidate):
                return candidate
    return None


def is_modern_plane(plane_dir: str) -> bool:
    return "publishedObjectNames" in _read_plane_index(plane_dir)


def is_legacy_descriptor(descriptor_dir: str) -> bool:
    """True when the descriptor has wallpaper planes but none is published."""
    wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
    if not wallpaper_dir:
        return False
    planes = _plane_dirs(wallpaper_dir)
    if not planes:
        return False
    return not any(is_modern_plane(plane) for plane in planes)


def wallpaper_family(descriptor_dir: str) -> "str | None":
    """The ``Wallpaper.plist`` ``family`` (e.g. ``Clownfish``/``Marble``), if any."""
    wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
    if not wallpaper_dir:
        return None
    data = _read_plist(os.path.join(wallpaper_dir, "Wallpaper.plist"))
    family = data.get("family")
    return str(family) if family is not None else None


def legacy_families(tendie_path: str) -> "list[str]":
    """Families of the pre-iOS 27 packages inside a ``.tendies`` archive.

    Read straight out of the zip so the import prompt can be raised before the
    tendie is ever staged for a restore. A package counts as legacy when its
    planes ship no ``publishedObjectNames`` — the same test
    :func:`is_legacy_descriptor` applies to an extracted tree.
    """
    families = []
    with zipfile.ZipFile(tendie_path) as archive:
        bundles: set[str] = set()
        indexes: dict[str, list[str]] = {}
        plists: dict[str, bytes] = {}
        for name in archive.namelist():
            normalized = name.replace("\\", "/")
            lowered = normalized.lower()
            if "__macosx/" in lowered or os.path.basename(normalized).startswith("._"):
                continue
            parts = normalized.split("/")
            cut = next((index for index, part in enumerate(parts)
                        if part.endswith(".wallpaper")), None)
            if cut is None:
                continue
            bundle = "/".join(parts[:cut + 1])
            bundles.add(bundle)
            tail = "/".join(parts[cut + 1:])
            if tail.endswith("/index.xml"):
                indexes.setdefault(bundle, []).append(
                    archive.read(name).decode("utf-8", "replace"))
            elif tail == "Wallpaper.plist":
                plists[bundle] = archive.read(name)
        for bundle in sorted(bundles):
            planes = indexes.get(bundle) or []
            if not planes or any("publishedObjectNames" in text for text in planes):
                continue
            family = ""
            raw = plists.get(bundle)
            if raw:
                try:
                    family = str(plistlib.loads(raw).get("family") or "")
                except Exception:
                    family = ""
            families.append(family or os.path.basename(bundle))
    return families


def is_mercury(descriptor_dir: str) -> bool:
    """True for a Mercury (spatial photo) package, detected by provider path or family."""
    normalized = descriptor_dir.replace(os.sep, "/")
    if MERCURY_PROVIDER in normalized:
        return True
    family = wallpaper_family(descriptor_dir)
    return family is not None and family.lower() == MERCURY_FAMILY.lower()


def conversion_action(descriptor_dir: str,
                      repack_families: "frozenset[str] | set[str]" = REPACK_FAMILIES
                      ) -> str:
    """Decide whether a device descriptor should be repacked to Clownfish.

    Mercury is skipped outright (different layout, would be destroyed), an
    already-modern package is kept as-is, and only the flat legacy families in
    ``repack_families`` are repacked. Everything else is left untouched.
    """
    if is_mercury(descriptor_dir):
        return ACTION_SKIP
    if not is_legacy_descriptor(descriptor_dir):
        return ACTION_KEEP
    family = wallpaper_family(descriptor_dir)
    if family is not None and family in repack_families:
        return ACTION_REPACK
    return ACTION_KEEP


def _modern_index_xml(doc_width: float, doc_height: float, role: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>assetManifest</key>
\t<string>assetManifest.caml</string>
\t<key>documentHeight</key>
\t<real>{doc_height}</real>
\t<key>documentResizesToView</key>
\t<false/>
\t<key>documentWidth</key>
\t<real>{doc_width}</real>
\t<key>dynamicGuidesEnabled</key>
\t<true/>
\t<key>geometryFlipped</key>
\t<false/>
\t<key>guidesEnabled</key>
\t<true/>
\t<key>interactiveMouseEventsEnabled</key>
\t<true/>
\t<key>interactiveShowsCursor</key>
\t<true/>
\t<key>interactiveTouchEventsEnabled</key>
\t<false/>
\t<key>loopEnd</key>
\t<real>+infinity</real>
\t<key>loopStart</key>
\t<real>0.0</real>
\t<key>loopingEnabled</key>
\t<true/>
\t<key>multitouchDisablesMouse</key>
\t<false/>
\t<key>multitouchEnabled</key>
\t<false/>
\t<key>plugins</key>
\t<array/>
\t<key>presentationMouseEventsEnabled</key>
\t<true/>
\t<key>presentationShowsCursor</key>
\t<true/>
\t<key>presentationTouchEventsEnabled</key>
\t<false/>
\t<key>publishedObjectNames</key>
\t<array>
\t\t<string>{role}</string>
\t</array>
\t<key>rootDocument</key>
\t<string>main.caml</string>
\t<key>savesWindowFrame</key>
\t<false/>
\t<key>scalesToFitInPlayer</key>
\t<true/>
\t<key>showsTouches</key>
\t<true/>
\t<key>snappingEnabled</key>
\t<true/>
\t<key>timelineMarkers</key>
\t<string>[(null)]</string>
\t<key>touchesColor</key>
\t<string>1 1 0 0.8</string>
\t<key>unitsInPixelsInPlayer</key>
\t<false/>
</dict>
</plist>
"""


def _fit_scale(tag: str, doc_width: float, doc_height: float,
               units_in_pixels: bool, pixel_scale: int) -> float:
    """Scale that fits the root canvas onto the document.

    Only pixel canvases (``unitsInPixelsInPlayer``) need a fit: a points-based
    plane already shares the screen's coordinate space and the player's
    ``scalesToFitInPlayer`` handles the last few points, so scaling it again
    would drift the artwork.
    """
    if not units_in_pixels:
        return 1.0
    bounds = _get_attr(tag, "bounds")
    if bounds:
        parts = bounds.split()
        old_width = float(parts[2]) if len(parts) >= 4 else doc_width
        old_height = float(parts[3]) if len(parts) >= 4 else doc_height
    else:
        old_width, old_height = doc_width, doc_height
    divisor = float(pixel_scale) if pixel_scale else 1.0
    point_width = old_width / divisor
    point_height = old_height / divisor
    if point_width <= 0 or point_height <= 0:
        return 1.0
    return max(doc_width / point_width, doc_height / point_height)


def _add_scale(tag: str, scale: float) -> str:
    if abs(scale - 1.0) <= 1e-6:
        return tag
    old_transform = (_get_attr(tag, "transform") or "").strip()
    new_transform = f"{old_transform} ".lstrip() if old_transform else ""
    new_transform += f"scale({scale:.6f}, {scale:.6f}, 1)"
    return _set_attr(tag, "transform", new_transform)


def modernize_main_caml(text: str, role: str, doc_width: float, doc_height: float,
                        units_in_pixels: bool, pixel_scale: int) -> str:
    """Publish the plane root layer and fit its canvas to the document.

    The legacy root holds the whole plane content and its script, and its own
    ``LKStateSetValue`` entries point at that root's existing ``id`` (usually
    ``#1``). So the root becomes the published layer (matching the working
    Odyssey descriptor, whose published root is named ``Root Layer``): its ``id``
    is set to the role and every internal ``targetId`` is repointed, its ``name``
    and ``position`` are left alone, and ``<scriptObject>`` elements are kept
    verbatim. Only a pixel canvas gets a fit ``scale``.
    """
    match = re.search(r"<CALayer\b[^>]*>", text)
    if not match:
        raise ConversionError("main.caml has no root CALayer")
    tag = match.group(0)

    old_id = _get_attr(tag, "id")
    new_tag = _set_attr(tag, "id", role)
    new_tag = _add_scale(new_tag, _fit_scale(tag, doc_width, doc_height,
                                             units_in_pixels, pixel_scale))
    if old_id and old_id != role:
        text = text.replace(f'targetId="{old_id}"', f'targetId="{role}"')
    return text[:match.start()] + new_tag + text[match.end():]


def _plane_units(index: dict, logical_width: int) -> bool:
    value = index.get("unitsInPixelsInPlayer")
    if isinstance(value, bool):
        return value
    doc_width = index.get("documentWidth")
    if isinstance(doc_width, (int, float)) and logical_width:
        return float(doc_width) > float(logical_width) + 1.0
    return True


def modernize_plane(plane_dir: str, role: str, doc_width: float, doc_height: float,
                    logical_width: int, pixel_scale: int) -> "list[str]":
    index = _read_plane_index(plane_dir)
    units_in_pixels = _plane_units(index, logical_width)
    main_caml = os.path.join(plane_dir, "main.caml")
    if not os.path.isfile(main_caml):
        raise ConversionError(f"{plane_dir} has no main.caml")
    text = strip_scripts(_read_text(main_caml))
    if _has_unsupported_caml(text):
        # Publishing the root would keep the trapping state op and crash the
        # depth renderer for every wallpaper; flatten to a static frame instead.
        text = _flatten_plane(role, plane_dir, doc_width, doc_height)
    else:
        text = modernize_main_caml(
            text, role, doc_width, doc_height, units_in_pixels, pixel_scale)
    _write_text(main_caml, text)
    # A color-only plane carries no image and traps the depth renderer; give it
    # a real CGImage rendered from its fill before it is published.
    ensure_background_image(plane_dir, role, doc_width, doc_height)
    index_path = os.path.join(plane_dir, "index.xml")
    _write_text(index_path, _modern_index_xml(doc_width, doc_height, role))
    written = [main_caml, index_path]
    manifest = os.path.join(plane_dir, "assetManifest.caml")
    if not os.path.isfile(manifest):
        _write_text(manifest, _MICA_ASSET_MANIFEST)
        written.append(manifest)
    return written


def modernize_wallpaper_plist(wallpaper_dir: str,
                              max_multiplier: float = DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER
                              ) -> dict:
    """Add the modern keys and point the asset entries at the real plane folders.

    ``family`` is switched to ``Clownfish`` — the family whose renderer enables
    the Depth effect. A legacy Marble/Lavender/WWDC22 descriptor keeps rendering
    as a flat animation even with published layers and the depth plists, while
    the same content stamped ``family = Clownfish`` (the proven Odyssey repack)
    gets Depth. The human-readable ``name`` is left alone.
    """
    path = os.path.join(wallpaper_dir, "Wallpaper.plist")
    data = _read_plist(path)
    if not data:
        raise ConversionError(f"{path} is missing or unreadable")
    data["family"] = CLOWNFISH_FAMILY
    data.setdefault("contentVersion", MODERN_CONTENT_VERSION)
    data.setdefault("disableAdaptiveTime", True)
    data.setdefault("maximumAdaptiveTimeMultiplier", max_multiplier)

    assets = data.setdefault("assets", {})
    lock_and_home = assets.setdefault("lockAndHome", {})
    default = lock_and_home.setdefault("default", {})
    default.setdefault("type", "LayeredAnimation")

    planes = {}
    for plane_dir in _plane_dirs(wallpaper_dir):
        role = plane_role(plane_dir)
        if role:
            planes[role] = os.path.basename(plane_dir)

    keys = {
        "Background": ("backgroundAnimationFileName", "backgroundAnimationFileNameKey"),
        "Floating": ("floatingAnimationFileNameKey", "floatingAnimationFileName"),
        "Foreground": ("foregroundAnimationFileName", "foregroundAnimationFileNameKey"),
    }
    for role, (primary, alternate) in keys.items():
        if role in planes:
            default[primary] = planes[role]
            if not default.get(alternate):
                default.pop(alternate, None)
        else:
            default.pop(primary, None)
            default.pop(alternate, None)

    with open(path, "wb") as handle:
        plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
    return data


def write_depth_configs(wallpaper_dir: str) -> "list[str]":
    """Write the two PosterKit archiver plists that allow the Depth effect.

    ``configurableOptions`` lives in the version ``contents`` folder (next to the
    ``.wallpaper`` bundle) while ``renderingConfiguration`` is a sibling of the
    ``contents`` folder. Both take ``depthEffectDisabled = False``.
    """
    contents_dir = os.path.dirname(wallpaper_dir)
    version_dir = os.path.dirname(contents_dir)
    written = []
    options_path = os.path.join(contents_dir, CONFIGURABLE_OPTIONS_NAME)
    with open(options_path, "wb") as handle:
        plistlib.dump(configurable_options_plist(), handle, fmt=plistlib.FMT_BINARY)
    written.append(options_path)
    rendering_path = os.path.join(version_dir, RENDERING_CONFIGURATION_NAME)
    with open(rendering_path, "wb") as handle:
        plistlib.dump(rendering_configuration_plist(), handle, fmt=plistlib.FMT_BINARY)
    written.append(rendering_path)
    return written


def synthesize_foreground_plane(wallpaper_dir: str, doc_width: float,
                                doc_height: float, pixel_scale: int,
                                dir_name: "str | None" = None) -> "list[str]":
    """Publish an empty Foreground plane when the wallpaper has none.

    The Clownfish/depth renderer builds a third (Foreground) plane; a package
    stamped ``family = Clownfish`` that only ships Background+Floating leaves the
    renderer with no foreground view provider and traps in WallpaperKit
    (EXC_BREAKPOINT), which also disables Depth/snapshots for the whole system.
    The subject cannot be segmented out of a flat image, so the plane is generated
    as an empty transparent published root (the same shape the rebuild path uses
    for a repacked wallpaper) — the Depth toggle is then a no-op instead of a
    crash. Returns the written files (``[]`` when a Foreground already exists).
    """
    planes = {plane_role(plane): plane for plane in _plane_dirs(wallpaper_dir)}
    if "Foreground" in planes:
        return []
    dest = os.path.join(wallpaper_dir, dir_name or "foreground.ca")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    main_caml = os.path.join(dest, "main.caml")
    _write_text(main_caml, _EMPTY_PLANE_CAML.format(
        role="Foreground", width=doc_width, height=doc_height,
        cx=doc_width / 2.0, cy=doc_height / 2.0))
    index_path = os.path.join(dest, "index.xml")
    _write_text(index_path, _modern_index_xml(doc_width, doc_height, "Foreground"))
    written = [main_caml, index_path]
    manifest = os.path.join(dest, "assetManifest.caml")
    _write_text(manifest, _MICA_ASSET_MANIFEST)
    written.append(manifest)
    return written


def _skeleton_names(data: dict,
                    family: str = CLOWNFISH_FAMILY
                    ) -> "tuple[str, dict[str, str]] | None":
    """Stock Clownfish bundle/plane names for a ``Wallpaper.plist`` dict.

    ``assetId`` is the numeric ``assets.lockAndHome.<variant>.identifier`` (not
    the descriptor id, which the import path randomizes afterwards — the working
    BB91 descriptor ships those two ids different too).
    """
    assets = (data.get("assets") or {}).get("lockAndHome") or {}
    variant = assets.get("default") or (next(iter(assets.values())) if assets else {})
    asset_id = variant.get("identifier")
    if asset_id is None:
        asset_id = data.get("identifier")
    logical_class = str(data.get("logicalScreenClass") or "").strip()
    if asset_id is None or not logical_class:
        return None
    asset_id = str(asset_id)
    bundle = f"{asset_id}.{family}-{logical_class}.wallpaper"
    planes = {
        role: f"{asset_id}.{family}_{role}-{logical_class}.ca"
        for role in ("Background", "Floating", "Foreground")
    }
    return bundle, planes


def rename_to_skeleton_shape(wallpaper_dir: str, data: dict,
                             family: str = CLOWNFISH_FAMILY) -> "tuple[str, dict[str, str]]":
    """Rename a bundle and its plane folders to the stock Clownfish convention.

    WallpaperKit resolves a package's planes through ``Wallpaper.plist``, but it
    also relies on the on-disk name: every working stock and repacked descriptor
    ships ``<assetId>.<Family>-<class>.wallpaper`` with
    ``<assetId>.<Family>_<Plane>-<class>.ca`` planes, and the bundle name is
    echoed verbatim in ``userInfo.wallpaperRepresentingFileName``. A converted
    third-party tendie keeps its original names (``Windows_11.wallpaper`` /
    ``background.ca``), which leaves ``WKPlatformPackageView`` unable to build
    the view and traps in WallpaperKit (``EXC_BREAKPOINT``) on the lock screen.

    Returns the (possibly renamed) wallpaper directory and the new plane names.
    """
    names = _skeleton_names(data, family)
    if not names:
        return wallpaper_dir, {}
    bundle_name, plane_names = names

    for plane_dir in _plane_dirs(wallpaper_dir):
        role = plane_role(plane_dir)
        if not role:
            continue
        target = os.path.join(wallpaper_dir, plane_names[role])
        if os.path.abspath(target) != os.path.abspath(plane_dir):
            if os.path.exists(target):
                shutil.rmtree(target)
            os.rename(plane_dir, target)

    contents_dir = os.path.dirname(wallpaper_dir)
    new_dir = os.path.join(contents_dir, bundle_name)
    if os.path.abspath(new_dir) != os.path.abspath(wallpaper_dir):
        if os.path.exists(new_dir):
            shutil.rmtree(new_dir)
        os.rename(wallpaper_dir, new_dir)
        wallpaper_dir = new_dir

    plane_keys = {
        "backgroundAnimationFileName": "Background",
        "backgroundAnimationFileNameKey": "Background",
        "foregroundAnimationFileName": "Foreground",
        "foregroundAnimationFileNameKey": "Foreground",
        "floatingAnimationFileName": "Floating",
        "floatingAnimationFileNameKey": "Floating",
    }
    wp_path = os.path.join(wallpaper_dir, "Wallpaper.plist")
    wp = _read_plist(wp_path)
    if wp:
        changed = False
        for group in (wp.get("assets") or {}).values():
            if not isinstance(group, dict):
                continue
            for variant in group.values():
                if not isinstance(variant, dict):
                    continue
                for key, role in plane_keys.items():
                    if key in variant and role in plane_names \
                            and variant[key] != plane_names[role]:
                        variant[key] = plane_names[role]
                        changed = True
        if changed:
            with open(wp_path, "wb") as handle:
                plistlib.dump(wp, handle, fmt=plistlib.FMT_BINARY)

    userinfo = os.path.join(contents_dir, "com.apple.posterkit.provider.contents.userInfo")
    if os.path.isfile(userinfo):
        ui = _read_plist(userinfo)
        if ui:
            ui["wallpaperRepresentingFileName"] = bundle_name
            with open(userinfo, "wb") as handle:
                plistlib.dump(ui, handle, fmt=plistlib.FMT_BINARY)
    return wallpaper_dir, plane_names


def rename_descriptors_to_skeleton(root: str) -> "list[dict]":
    """Rename every converted Clownfish bundle under ``root`` to the stock shape.

    Must run *after* ``convert_tree`` (which stamps ``family = Clownfish`` and
    synthesizes the Foreground plane) because the skeleton name is derived from
    the final ``Wallpaper.plist`` (asset id + logical screen class).
    """
    results = []
    for descriptor_dir in iter_descriptor_dirs(root):
        wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
        if not wallpaper_dir:
            continue
        data = _read_plist(os.path.join(wallpaper_dir, "Wallpaper.plist"))
        if str(data.get("family") or "").lower() != CLOWNFISH_FAMILY.lower():
            continue
        new_dir, _planes = rename_to_skeleton_shape(wallpaper_dir, data)
        results.append({
            "descriptor": descriptor_dir,
            "wallpaper": os.path.basename(new_dir),
            "planes": [plane_role(p) for p in _plane_dirs(new_dir)],
        })
    return results


def convert_descriptor(descriptor_dir: str,
                       screen: "tuple[int, int, int] | None" = None,
                       max_multiplier: float = DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER,
                       ) -> dict:
    """Modernize one legacy descriptor in place; return a summary dict."""
    wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
    if not wallpaper_dir:
        raise ConversionError(f"{descriptor_dir} has no wallpaper folder")

    data = _read_plist(os.path.join(wallpaper_dir, "Wallpaper.plist"))
    if screen:
        doc_width, doc_height, pixel_scale = screen
    else:
        parsed = parse_logical_screen_class(data.get("logicalScreenClass"))
        doc_width, doc_height, pixel_scale = parsed or (390, 844, 3)

    converted_planes = []
    changed_files = []
    for plane_dir in _plane_dirs(wallpaper_dir):
        role = plane_role(plane_dir)
        if not role:
            continue
        changed_files.extend(
            modernize_plane(plane_dir, role, doc_width, doc_height, doc_width, pixel_scale))
        converted_planes.append(role)

    changed_files.extend(
        synthesize_foreground_plane(wallpaper_dir, doc_width, doc_height, pixel_scale))
    if "Foreground" not in converted_planes and os.path.isdir(
            os.path.join(wallpaper_dir, "foreground.ca")):
        converted_planes.append("Foreground")

    modernize_wallpaper_plist(wallpaper_dir, max_multiplier)
    changed_files.append(os.path.join(wallpaper_dir, "Wallpaper.plist"))
    changed_files.extend(write_depth_configs(wallpaper_dir))
    return {
        "descriptor": descriptor_dir,
        "wallpaper": os.path.basename(wallpaper_dir),
        "screen": f"{doc_width}x{doc_height}@{pixel_scale}x",
        "planes": converted_planes,
        "changed_files": changed_files,
    }


def iter_descriptor_dirs(root: str):
    """Yield every folder under ``root`` that looks like a wallpaper descriptor.

    ``__MACOSX`` resource-fork trees (macOS-created ``.tendies``) mirror every
    real descriptor but hold AppleDouble stubs instead of the CAML files, so they
    are pruned or they would abort the conversion with a missing ``main.caml``.
    """
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() != "__macosx"]
        if os.path.basename(dirpath) == "versions" and os.path.isdir(dirpath):
            descriptor_dir = os.path.dirname(dirpath)
            if _find_wallpaper_dir(descriptor_dir):
                yield descriptor_dir
            dirnames[:] = []


def convert_tree(root: str, screen: "tuple[int, int, int] | None" = None,
                 max_multiplier: float = DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER,
                 dry_run: bool = False) -> "list[dict]":
    """Convert every legacy descriptor under ``root`` (extracted tendie tree)."""
    results = []
    for descriptor_dir in iter_descriptor_dirs(root):
        if not is_legacy_descriptor(descriptor_dir):
            # An already-modern package can still carry a trapping script or CAML
            # state op (third-party tendies), so sanitize any plane that does.
            if dry_run or not _descriptor_needs_sanitize(descriptor_dir):
                continue
            written = flatten_unsupported_planes(descriptor_dir)
            if written:
                results.append({
                    "descriptor": descriptor_dir,
                    "wallpaper": os.path.basename(
                        _find_wallpaper_dir(descriptor_dir) or ""),
                    "planes": [os.path.basename(os.path.dirname(p))
                               for p in written],
                    "flattened": True,
                })
            continue
        if dry_run:
            wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
            results.append({
                "descriptor": descriptor_dir,
                "wallpaper": os.path.basename(wallpaper_dir),
                "planes": [plane_role(p) for p in _plane_dirs(wallpaper_dir)],
                "dry_run": True,
            })
            continue
        results.append(convert_descriptor(descriptor_dir, screen, max_multiplier))
    return results


def _descriptor_needs_sanitize(descriptor_dir: str) -> bool:
    wallpaper_dir = _find_wallpaper_dir(descriptor_dir)
    if not wallpaper_dir:
        return False
    return any(plane_role(plane)
               and (plane_has_unsupported_caml(plane)
                    or plane_has_external_script(plane))
               for plane in _plane_dirs(wallpaper_dir))


def _parse_screen_arg(value: str) -> "tuple[int, int, int]":
    parsed = parse_logical_screen_class(value)
    if not parsed:
        raise ValueError(f"expected WxH@S (e.g. 393x852@3), got {value!r}")
    return parsed


def main(argv: "list[str] | None" = None) -> int:
    """CLI: convert a ``.tendies`` / extracted tree to the modern shape."""
    import argparse
    import shutil
    import tempfile
    import zipfile

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", help=".tendies file or extracted directory")
    parser.add_argument("--out", help="output .tendies or directory (default: <input>.converted.tendies)")
    parser.add_argument("--screen", help="override target screen, e.g. 393x852@3")
    parser.add_argument("--max-multiplier", type=float,
                        default=DEFAULT_MAX_ADAPTIVE_TIME_MULTIPLIER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    screen = _parse_screen_arg(args.screen) if args.screen else None
    is_zip = os.path.isfile(args.input) and zipfile.is_zipfile(args.input)
    work = tempfile.mkdtemp(prefix="gn_convert_")
    source_dir = work
    try:
        if is_zip:
            with zipfile.ZipFile(args.input) as archive:
                archive.extractall(work)
        else:
            source_dir = args.input

        results = convert_tree(source_dir, screen, args.max_multiplier, args.dry_run)
        for item in results:
            print(f"{'[dry] ' if args.dry_run else ''}{item['wallpaper']} "
                  f"-> {item.get('screen', '?')} planes={item.get('planes')}")
        if not results:
            print("No legacy wallpaper found (nothing to do).")
            return 0

        if args.dry_run:
            return 0

        out = args.out
        if not out:
            if is_zip:
                base = os.path.splitext(args.input)[0]
                out = base + ".converted.tendies"
            else:
                print("Converted in place.")
                return 0
        if out.endswith(".tendies"):
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
                for dirpath, _dirs, names in os.walk(source_dir):
                    for name in names:
                        full = os.path.join(dirpath, name)
                        archive.write(full, os.path.relpath(full, source_dir))
        else:
            shutil.copytree(source_dir, out, dirs_exist_ok=True)
        print(f"Wrote {out}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
