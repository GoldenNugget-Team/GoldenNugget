import logging
import math
import re
from pathlib import Path

from src.tweaks.tweak_classes import Tweak

from .archive_editor import FILES, PosterArchive
from .clock_material import set_clock_material
from .clock_opacity import set_clock_opacity
from .preference_controls import CLOCK_FONT_IDENTIFIERS, number_limits

# Defaults only seed the controls; a field is written only when selected.
OPTIONS = (
    ("Clock", "clockOpacity", "Clock Opacity (Experimental)", 1.0),
    ("Clock", "titleContentStyle.frostLevel", "Clock Frost Level (Experimental)", 0.75),
    ("Clock", "titleContentStyle.preferredMaterialType", "Clock Material Type (Experimental)", 0),
    ("Clock", "adaptiveTimeConfigurations.DISPLAY_TYPE_EMBEDDED.adaptiveTimeHeightUserConfigured", "Embedded Display Custom Clock Height", False),
    ("Clock", "adaptiveTimeConfigurations.DISPLAY_TYPE_EMBEDDED.preferredTimeMaxYPortrait", "Adaptive Clock Maximum Y (Portrait)", 0.0),
    ("Clock", "adaptiveTimeConfigurations.DISPLAY_TYPE_EMBEDDED.preferredTimeMaxYLandscape", "Adaptive Clock Maximum Y (Landscape)", 0.0),
    ("Rendering", "depthEffectDisabled", "Disable Depth Effect", False),
    ("Rendering", "motionEffectsDisabled", "Disable Wallpaper Motion", False),
    ("Clock", "permanentCompactTimeEnabled", "Compact Clock", False),
    ("Clock", "alternateDateEnabled", "Alternate Date", True),
    ("Clock", "timeNumberingSystem", "Clock Numbering System (Experimental)", ""),
    ("Clock", "contentsLuminence", "Clock Content Luminance", 0.5),
    ("Clock", "isAdaptiveTimeHeightUserConfigured", "Custom Adaptive Clock Height", False),
    ("Clock", "preferredTimeMaxY", "Clock Maximum Y (Portrait)", 0.0),
    ("Clock", "preferredTimeMaxYLandscape", "Clock Maximum Y (Landscape)", 0.0),
    ("Clock", "preferredTitleAlignment", "Clock Alignment", 0),
    ("Clock", "preferredTitleLayout", "Clock Layout", 0),
    ("Clock", "userConfigured", "Clock User Configured", False),
    ("Clock", "timeFontConfiguration.isSystemItem", "Clock System Font Item", False),
    ("Clock", "timeFontConfiguration.timeFontIdentifier", "Clock Font Identifier", "PRTimeFontIdentifierSoft"),
    ("Clock", "timeFontConfiguration.weight", "Clock Font Weight", 640.0),
    ("Clock", "titleColor.identifier", "Clock Color Identifier", "vibrantMaterialColor"),
    ("Clock", "titleColor.preferredStyle", "Clock Color Style", 2),
    ("Clock", "titleColor.suggested", "Clock Suggested Color", False),
    ("Home Screen", "lockPosterAppearance.legibilityBlurEnabled", "Lock Poster Blur", False),
    ("Home Screen", "homePosterAppearance.legibilityBlurEnabled", "Home Poster Blur", False),
    ("Home Screen", "lockPosterAppearance.allowsModifyingLegibilityBlur", "Allow Lock Poster Blur Changes", True),
    ("Home Screen", "homePosterAppearance.allowsModifyingLegibilityBlur", "Allow Home Poster Blur Changes", True),
    ("Home Screen", "selectedAppearanceType", "Home Appearance Type", 0),
    ("Home Screen", "customizationConfiguration._dimmed", "Dim Home Wallpaper", False),
    ("Home Screen", "customizationConfiguration._iconTintSource", "Icon Tint Source", "wallpaperSuggestion"),
    ("Home Screen", "customizationConfiguration._iconUserInterfaceSize", "Icon Size", "SMALL"),
    ("Home Screen", "customizationConfiguration._iconUserInterfaceStyleType", "Icon Style", "color"),
    ("Home Screen", "customizationConfiguration._iconUserInterfaceStyleVariant", "Icon Style Variant", "light"),
    *(("Home Screen", "customizationConfiguration._tintColorStyle." + key, title, value)
      for key, title, value in (
          ("_alpha", "Icon Tint Alpha", 1.0),
          ("_hue", "Icon Tint Hue", 0.5063131313131314),
          ("_luminance", "Icon Tint Luminance", 0.5),
          ("_luminanceValue", "Icon Tint Luminance Value", 0.375),
          ("_saturation", "Icon Tint Saturation", 1.0),
      )),
)


def option_key(group, path):
    return group + ":" + path


class PosterKitOverrides(Tweak):
    def __init__(self):
        super().__init__("PosterKitOverrides", value={})

    def stage(self, root):
        from src.utils.file_to_restore import FileToRestore
        allowed = {option_key(group, path): default for group, path, _, default in OPTIONS}
        for key, value in self.value.items():
            if key not in allowed or (type(value) is not type(allowed[key])
                    and not (type(allowed[key]) is float and type(value) is int)):
                raise ValueError(f"Invalid PosterKit setting: {key}")
            if key=='Clock:timeFontConfiguration.timeFontIdentifier' and value not in CLOCK_FONT_IDENTIFIERS:
                raise ValueError('Choose a clock font identifier from the available candidates, not a runtime symbol.')
            if type(value) in (int,float):
                lower,upper,_=number_limits(key.split(':',1)[1],allowed[key])
                if not math.isfinite(value) or not lower<=value<=upper:
                    raise ValueError(f'PosterKit value outside allowed editor range: {key}')
            if key == "Clock:timeNumberingSystem" and (not value.strip() or value == "$null"):
                raise ValueError("Enter a numbering-system identifier, or uncheck Use for Clock Numbering System.")
        records, matched = [], set()
        for group, suffix in FILES.items():
            requested = {tuple(key.split(":", 1)[1].split(".")): (key, value)
                         for key, value in self.value.items() if key.startswith(group + ":")}
            if not requested:
                continue
            for file in Path(root).rglob("*.plist"):
                marker = "Library/Application Support/PRBPosterExtensionDataStore/"
                relative = file.relative_to(root).as_posix()
                filename = suffix.rsplit("/", 1)[-1]
                archive_path = (r"/configurations/[^/]+/versions/[^/]+/"
                                + (r"supplements/[^/]+/" if group == "Home Screen" else "")
                                + re.escape(filename) + r"$")
                if marker not in relative or not re.search(archive_path, relative):
                    continue
                archive = PosterArchive(file)
                available = {path: old for path, _, _, old in archive.fields()}
                changes = {}
                opacity = requested.get(("clockOpacity",))
                material = {path[1]: (key, value) for path, (key, value) in requested.items()
                            if path[0] == "titleContentStyle"}
                for path, (key, value) in requested.items():
                    if path == ("clockOpacity",):
                        continue
                    if path not in available:
                        continue
                    old = available[path]
                    if type(old) in (int, float) and type(value) in (int, float):
                        if type(old) is int and float(value).is_integer():
                            value = int(value)
                        elif type(old) is float:
                            value = float(value)
                    changes[path] = value
                    matched.add(key)
                if changes or opacity is not None or material:
                    contents = archive.serialize(changes)
                    if material:
                        contents = set_clock_material(contents, {
                            field: value for field, (_, value) in material.items()})
                        matched.update(key for key, _ in material.values())
                        logging.getLogger(__name__).info("PosterKit clock material %s: %s", relative, material)
                    if opacity is not None:
                        contents = set_clock_opacity(contents, opacity[1])
                        matched.add(opacity[0])
                        logging.getLogger(__name__).info(
                            "PosterKit clock opacity %s = %s (outer and nested color archives)",
                            relative, opacity[1])
                    logging.getLogger(__name__).info(
                        "PosterKit staging %s: %s", relative,
                        {".".join(path): value for path, value in changes.items()})
                    records.append(FileToRestore(
                        contents=contents,
                        restore_path="/" + marker + relative.split(marker, 1)[1],
                        domain="AppDomain-com.apple.PosterBoard"))
        missing = set(self.value) - matched
        if missing:
            raise ValueError("Selected PosterKit fields were absent from the device backup: " + ", ".join(sorted(missing)))
        logging.getLogger(__name__).info("PosterKit staged %d binary archive(s)", len(records))
        return records
