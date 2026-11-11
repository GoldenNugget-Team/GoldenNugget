"""Edit existing PosterKit archives without decoding away their object graph."""
import copy
import math
import plistlib
import shutil
from pathlib import Path

FILES = {
    "Rendering": "versions/0/com.apple.posterkit.provider.instance.renderingConfiguration.plist",
    "Clock": "versions/0/com.apple.posterkit.provider.instance.titleStyleConfiguration.plist",
    "Home Screen": "versions/0/supplements/0/com.apple.posterkit.provider.supplementURL.homescreenConfiguration.plist",
}

# Only scalar fields present in the reference; class metadata and binary blobs
# remain untouched, including nested UIColor/NSData representations.
FIELDS = {
    "depthEffectDisabled", "motionEffectsDisabled", "alternateDateEnabled",
    "contentsLuminence", "isAdaptiveTimeHeightUserConfigured",
    "permanentCompactTimeEnabled", "preferredTimeMaxY", "preferredTimeMaxYLandscape",
    "preferredTitleAlignment", "preferredTitleLayout", "userConfigured",
    "adaptiveTimeHeightUserConfigured", "preferredTimeMaxYPortrait",
    "isSystemItem", "timeFontIdentifier", "timeNumberingSystem", "weight", "identifier",
    "preferredStyle", "suggested", "UIWhite", "UIAlpha",
    "selectedAppearanceType", "_dimmed", "_iconTintSource",
    "_iconUserInterfaceSize", "_iconUserInterfaceStyleType",
    "_iconUserInterfaceStyleVariant", "_alpha", "_hue", "_luminance",
    "_luminanceValue", "_saturation", "allowsModifyingLegibilityBlur",
    "legibilityBlurEnabled",
}


class PosterArchive:
    def __init__(self, path):
        self.path = Path(path)
        self.original = self.path.read_bytes()
        self.data = plistlib.loads(self.original)
        if self.data.get("$archiver") != "NSKeyedArchiver":
            raise ValueError(f"Not an NSKeyedArchiver: {self.path.name}")
        self.objects = self.data["$objects"]
        self.root = self.data["$top"]["root"]
        self.resolve(self.root)

    def resolve(self, value):
        if isinstance(value, plistlib.UID):
            if not 0 <= value.data < len(self.objects):
                raise ValueError("Invalid archive object reference")
            return self.objects[value.data]
        return value

    def fields(self):
        result = []

        def visit(value, path, seen):
            if isinstance(value, plistlib.UID):
                if value.data in seen:
                    return
                seen = seen | {value.data}
            obj = self.resolve(value)
            if not isinstance(obj, dict):
                return
            if "NS.keys" in obj and "NS.objects" in obj:
                keys, values = obj["NS.keys"], obj["NS.objects"]
                for index, (key, child) in enumerate(zip(keys, values)):
                    name = self.resolve(key)
                    child_value = self.resolve(child)
                    if isinstance(name, str):
                        child_path = path + (name,)
                        if name in ("clear", "dark", "default", "accent") and type(child_value) is str:
                            result.append((child_path, values, index, child_value))
                        else:
                            visit(child, child_path, seen)
                return
            for key, child in obj.items():
                if key.startswith("$"):
                    continue
                child_value = self.resolve(child)
                child_path = path + (key,)
                if key in FIELDS and type(child_value) in (bool, int, float, str):
                    result.append((child_path, obj, key, child_value))
                elif isinstance(child_value, dict):
                    visit(child, child_path, seen)

        visit(self.root, (), set())
        return result

    def serialize(self, changes):
        edited = copy.deepcopy(self.data)
        objects = edited["$objects"]
        # Re-enumerate a copy so aliases keep their UID graph, while edits to a
        # referenced scalar get a fresh object instead of changing every alias.
        clone = copy.copy(self)
        clone.data, clone.objects = edited, objects
        fields = {path: (container, key, old) for path, container, key, old in clone.fields()}
        for path, value in changes.items():
            container, key, old = fields[path]
            if type(value) is not type(old):
                raise TypeError(f"Incorrect value type: {'.'.join(path)}")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Numbers must be finite")
            if isinstance(container[key], plistlib.UID):
                container[key] = plistlib.UID(len(objects))
                objects.append(value)
            else:
                container[key] = value
        output = plistlib.dumps(edited, fmt=plistlib.FMT_BINARY, sort_keys=False)
        verified = plistlib.loads(output)
        if not output.startswith(b"bplist00") or verified != edited:
            raise ValueError("Archive serialization failed verification")
        clone.data, clone.objects = verified, verified["$objects"]
        actual = {path: value for path, _, _, value in clone.fields()}
        for path, value in changes.items():
            if path not in actual or type(actual[path]) is not type(value) or actual[path] != value:
                raise ValueError(f"Archive field verification failed: {'.'.join(path)}")
        return output


def save_archives(edits):
    prepared = [(archive, archive.serialize(changes)) for archive, changes in edits if changes]
    for archive, _ in prepared:
        if archive.path.read_bytes() != archive.original:
            raise ValueError(f"File changed since opening: {archive.path}")
    written = []
    try:
        for archive, output in prepared:
            backup = archive.path.with_name(archive.path.name + ".backup")
            if not backup.exists():
                shutil.copy2(archive.path, backup)
            temporary = archive.path.with_name(archive.path.name + ".goldennugget-tmp")
            try:
                temporary.write_bytes(output)
                temporary.replace(archive.path)
            finally:
                temporary.unlink(missing_ok=True)
            written.append(archive)
    except Exception:
        for archive in reversed(written):
            archive.path.write_bytes(archive.original)
        raise
