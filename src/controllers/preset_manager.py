import base64
import json
import os
import time
from typing import Optional

from PySide6.QtCore import QStandardPaths, QCoreApplication

from src.tweaks.tweak_names import TweakID
from src.tweaks import tweak_loader
from src.tweaks.tweaks import tweaks
from src.tweaks.tweak_classes import (
    BasicPlistTweak, AdvancedPlistTweak,
)
from src.tweaks.posterboard.template_options.templates_tweak import TemplatesTweak
from src.tweaks.status_bar.status_bar_tweak import StatusBarTweak
from src.tweaks.status_bar.status_bar_c.status_setter import ffi as status_ffi
from src.tweaks.icon_themes.icon_themes_tweak import IconThemesTweak
from src.tweaks.icon_themes.icon_theme import IconTheme
from src.controllers.hotload import HotLoad

PRESETS_DIR_NAME = "Presets"
PRESET_VERSION = 2

class PresetManager:
    def __init__(self):
        base_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        # Ensure GoldenNugget-specific folder
        if not base_dir.endswith("GoldenNugget") and not base_dir.endswith("GoldenNugget/"):
            base_dir = os.path.join(base_dir, "GoldenNugget")
        self.presets_dir = os.path.join(base_dir, PRESETS_DIR_NAME)
        os.makedirs(self.presets_dir, exist_ok=True)

    def get_preset_path(self, name: str) -> str:
        safe_name = self._sanitize_name(name)
        return os.path.join(self.presets_dir, f"{safe_name}.json")

    def _sanitize_name(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        return safe or "Preset"

    def list_presets(self) -> list[str]:
        presets = []
        if not os.path.isdir(self.presets_dir):
            return presets
        for file in sorted(os.listdir(self.presets_dir)):
            if file.lower().endswith(".json"):
                presets.append(os.path.splitext(file)[0])
        return presets

    def get_preset_metadata(self, name: str) -> Optional[dict]:
        """Get metadata for a preset without loading the full data."""
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("metadata", {})
        except Exception:
            return None

    def preset_has_daemon_changes(self, name: str) -> bool:
        """True if the preset enables the daemon modifications or turns on any
        individual daemon (i.e. it carries daemon tweaks that would be applied)."""
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        daemon_data = data.get("tweaks", {}).get("Daemons")
        if not isinstance(daemon_data, dict):
            return False
        if daemon_data.get("enabled"):
            return True
        values = daemon_data.get("value") or {}
        return any(values.values())

    def preset_hidden_feature_names(self, name: str, hotload: HotLoad,
                                    device_version: str = "",
                                    device_model: str = "") -> list[str]:
        """Return the names of HotLoad-hidden features that this preset would
        restore (i.e. it contains at least one enabled tweak of a feature that
        is currently hidden on this device). Loading such a preset would try to
        re-enable broken/dangerous features, so the caller should not load it."""
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        hidden = hotload.hidden_features(device_version=device_version,
                                         device_model=device_model)
        if not hidden:
            return []
        tweaks_data = data.get("tweaks", {})
        if not isinstance(tweaks_data, dict):
            return []
        present_features = set()
        for key in tweaks_data:
            feature = hotload.feature_for(key)
            if feature:
                present_features.add(feature)
        return sorted(hidden & present_features)

    def list_presets_with_metadata(self) -> list[dict]:
        """List all presets with their metadata."""
        result = []
        for name in self.list_presets():
            meta = self.get_preset_metadata(name)
            if meta:
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "device_model": meta.get("device_model", "Unknown"),
                    "ios_version": meta.get("ios_version", "Unknown"),
                    "created_at": meta.get("created_at", 0),
                    "updated_at": meta.get("updated_at", 0),
                    "tags": meta.get("tags", []),
                    "version": meta.get("version", 1),
                })
        return sorted(result, key=lambda x: x.get("updated_at", 0), reverse=True)

    def save_preset(self, name: str, description: str = "", tags: list = None,
                    device_model: str = "", ios_version: str = "") -> bool:
        data = self._serialize()
        if data is None:
            return False
        
        # Add metadata
        now = int(time.time())
        meta = {
            "version": PRESET_VERSION,
            "description": description or "",
            "device_model": device_model or "Unknown",
            "ios_version": ios_version or "Unknown",
            "created_at": now,
            "updated_at": now,
            "tags": tags or [],
        }
        # Preserve original creation time if updating
        existing_meta = self.get_preset_metadata(name)
        if existing_meta and "created_at" in existing_meta:
            meta["created_at"] = existing_meta["created_at"]
        
        data["metadata"] = meta
        
        file_path = self.get_preset_path(name)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Failed to save preset: {e}")
            return False

    def load_preset(self, name: str) -> bool:
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Failed to read preset: {e}")
            return False
        return self._apply(data)

    def delete_preset(self, name: str) -> bool:
        file_path = self.get_preset_path(name)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                return True
        except Exception as e:
            print(f"Failed to delete preset: {e}")
        return False

    ## EXPORT / IMPORT
    def export_preset(self, name: str, export_path: str,
                      include: Optional[list] = None) -> bool:
        """Export a preset to a shareable JSON file.

        ``include`` optionally limits the export to a subset of tweaks, given
        as a list of ``TweakID`` members (or their ``.name`` strings). When
        omitted, the whole preset is exported. ``None``/empty means full.
        """
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Add export marker
            data["exported"] = True
            data["exported_at"] = int(time.time())

            if include:
                data = self._filter_export(data, include)

            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Failed to export preset: {e}")
            return False

    def build_export_data(self, include: Optional[list] = None) -> Optional[dict]:
        """Serialize the *current* tweak state, optionally limited to a subset.

        ``include`` is a list of ``TweakID`` members (or ``.name`` strings).
        Returns ``None`` if nothing was serialized.
        """
        data = self._serialize_subset(include)
        if data is None:
            return None
        data["exported"] = True
        data["exported_at"] = int(time.time())
        return data

    @staticmethod
    def _filter_export(data: dict, include: list) -> dict:
        """Return a copy of *data* with ``tweaks`` reduced to ``include``
        and metadata annotated as a partial export."""
        include_names = set()
        for item in include:
            include_names.add(item.name if hasattr(item, "name") else str(item))
        tweaks_data = data.get("tweaks", {})
        filtered = {key: val for key, val in tweaks_data.items()
                    if key in include_names}
        out = dict(data)
        out["tweaks"] = filtered
        out["metadata"] = dict(data.get("metadata", {}))
        out["metadata"]["partial"] = True
        out["metadata"]["included"] = sorted(include_names)
        return out

    def _serialize_subset(self, include: Optional[list] = None) -> Optional[dict]:
        """Serialize the current tweaks filtered to ``include`` (TweakIDs/names)."""
        if include is None:
            include = list(tweaks.keys())
        include_names = set()
        for item in include:
            include_names.add(item.name if hasattr(item, "name") else str(item))

        tweak_data = {}
        for key, tweak in tweaks.items():
            if key.name not in include_names:
                continue
            if key == TweakID.PosterBoard:
                continue
            try:
                tweak_data[key.name] = self._serialize_tweak(tweak)
            except Exception as e:
                print(f"Failed to serialize tweak {key}: {e}")

        if not tweak_data:
            return None
        return {"tweaks": tweak_data}

    def import_preset(self, import_path: str, new_name: str = None) -> tuple[bool, str]:
        """Import a preset from a JSON file. Returns (success, actual_name)."""
        if not os.path.isfile(import_path):
            return False, "File not found"
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Validate structure
            if not self._valid_import_structure(data):
                return False, QCoreApplication.translate(
                    "PresetTransfer", "Invalid preset file. Expected a tweak dictionary and valid preset metadata.")
            
            # Determine name
            if new_name is None:
                meta = data.get("metadata", {})
                new_name = meta.get("description", "Imported Preset")
                # Fallback to filename
                if not new_name or new_name == "Imported Preset":
                    new_name = os.path.splitext(os.path.basename(import_path))[0]
            
            # Sanitize and ensure unique
            base_name = self._sanitize_name(new_name)
            name = base_name
            counter = 1
            while os.path.isfile(self.get_preset_path(name)):
                name = f"{base_name} ({counter})"
                counter += 1
            
            # Update metadata
            now = int(time.time())
            if "metadata" not in data:
                data["metadata"] = {}
            data["metadata"]["imported_at"] = now
            data["metadata"]["updated_at"] = now
            if "created_at" not in data["metadata"]:
                data["metadata"]["created_at"] = now
            
            file_path = self.get_preset_path(name)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True, name
        except Exception as e:
            print(f"Failed to import preset: {e}")
            return False, str(e)

    @staticmethod
    def _valid_import_structure(data) -> bool:
        """Reject malformed containers before they can enter the preset list.

        Old files without metadata and unknown tweak names remain supported.
        Import stores selections only; it never enables tweaks or applies them.
        """
        if not isinstance(data, dict) or not isinstance(data.get("tweaks"), dict):
            return False
        meta = data.get("metadata", {})
        if not isinstance(meta, dict):
            return False
        for key in ("description", "device_model", "ios_version"):
            if key in meta and not isinstance(meta[key], str):
                return False
        if "tags" in meta and (not isinstance(meta["tags"], list)
                               or not all(isinstance(tag, str) for tag in meta["tags"])):
            return False
        for key in ("created_at", "updated_at", "version"):
            if key in meta and type(meta[key]) not in (int, float):
                return False
        for name, entry in data["tweaks"].items():
            if not isinstance(entry, dict):
                return False
            if "enabled" in entry and not isinstance(entry["enabled"], bool):
                return False
            if (name == "Daemons" or entry.get("type") == "AdvancedPlistTweak") and "value" in entry:
                if not isinstance(entry["value"], dict):
                    return False
            if "templates" in entry and (not isinstance(entry["templates"], list)
                                          or not all(isinstance(path, str) for path in entry["templates"])):
                return False
            if "themes" in entry:
                if not isinstance(entry["themes"], list):
                    return False
                for theme in entry["themes"]:
                    if not isinstance(theme, dict) or not all(
                            isinstance(theme.get(key, ""), str)
                            for key in ("bundle_id", "display_name", "icon_path")):
                        return False
            if "override_data" in entry:
                if not isinstance(entry["override_data"], str):
                    return False
                try:
                    base64.b64decode(entry["override_data"], validate=True)
                except ValueError:
                    return False
        return True

    ## SERIALIZATION
    def _serialize(self) -> dict:
        tweak_data = {}
        for key, tweak in tweaks.items():
            # PosterBoard is excluded from presets: wallpapers are
            # device-specific and heavy, so they must not travel with a preset.
            if key == TweakID.PosterBoard:
                continue
            try:
                tweak_data[key.name] = self._serialize_tweak(tweak)
            except Exception as e:
                print(f"Failed to serialize tweak {key}: {e}")

        return {
            "tweaks": tweak_data
        }

    def _serialize_tweak(self, tweak) -> dict:
        data = {"type": type(tweak).__name__, "enabled": tweak.enabled}
        if isinstance(tweak, AdvancedPlistTweak):
            # Store only what the UI exposes / what would actually apply.
            data["value"] = tweak._filter_keys(tweak.value)
        elif isinstance(tweak, BasicPlistTweak):
            data["value"] = tweak.value
        elif isinstance(tweak, TemplatesTweak):
            data["templates"] = [t.path for t in tweak.templates]
        elif isinstance(tweak, StatusBarTweak):
            data["enabled"] = tweak.enabled
            data["silly_mode"] = tweak.setter.silly_mode
            data["override_data"] = base64.b64encode(status_ffi.buffer(tweak.setter.current_overrides)).decode("ascii")
        elif isinstance(tweak, IconThemesTweak):
            # Icons live in the persistent IconThemes store (see
            # icon_themes_tweak.store_icon), so paths are stable across loads.
            data["themes"] = [
                {"bundle_id": t.bundle_id, "display_name": t.display_name,
                 "icon_path": t.icon_path}
                for t in tweak.themes
            ]
        # NullifyFileTweak only needs "enabled"
        return data

    ## DESERIALIZATION
    def _apply(self, data: dict) -> bool:
        try:
            # make sure every tweak exists before applying
            self._load_all_tweaks()

            # never re-enable HotLoad-hidden features: loading a preset must not
            # resurrect broken/dangerous tweaks (defense-in-depth on top of the
            # warning shown before loading)
            from src.tweaks.hidden import current_hidden_tweak_names
            hidden_names = current_hidden_tweak_names()

            if "tweaks" in data:
                for name, tweak_data in data["tweaks"].items():
                    key = None
                    try:
                        key = TweakID[name]
                    except KeyError:
                        continue
                    if key not in tweaks:
                        continue
                    # PosterBoard is excluded from presets (see _serialize); skip
                    # it on load too so old presets cannot restore wallpapers.
                    if key == TweakID.PosterBoard:
                        continue
                    if name in hidden_names:
                        continue
                    try:
                        self._apply_tweak(tweaks[key], tweak_data)
                    except Exception as e:
                        print(f"Failed to apply tweak {name}: {e}")

            return True
        except Exception as e:
            print(f"Failed to apply preset: {e}")
            return False

    def _load_all_tweaks(self):
        # idempotent: the loaders return early if the tweaks already exist
        tweak_loader.load_plist_tweaks()
        tweak_loader.load_daemons()

    def _apply_tweak(self, tweak, data: dict):
        if "enabled" in data:
            tweak.enabled = data["enabled"]

        if isinstance(tweak, AdvancedPlistTweak):
            if "value" in data:
                # Drop keys not available in the UI (e.g. unknown daemons), so
                # a stored preset can never re-enable hidden ones.
                tweak.value = tweak._filter_keys(data["value"])
        elif isinstance(tweak, BasicPlistTweak):
            if "value" in data:
                tweak.value = data["value"]
        elif isinstance(tweak, TemplatesTweak):
            self._apply_templates(tweak, data)
        elif isinstance(tweak, StatusBarTweak):
            self._apply_status_bar(tweak, data)
        elif isinstance(tweak, IconThemesTweak):
            self._apply_icon_themes(tweak, data)

    def _apply_templates(self, tweak: TemplatesTweak, data: dict):
        if "templates" in data:
            tweak.templates = []
            for path in data["templates"]:
                if os.path.isfile(path):
                    try:
                        tweak.add_template(path)
                    except Exception as e:
                        print(f"Failed to add template: {e}")

    def _apply_status_bar(self, tweak: StatusBarTweak, data: dict):
        tweak.enabled = data.get("enabled", False)
        tweak.setter.silly_mode = data.get("silly_mode", False)
        if "override_data" in data:
            try:
                raw = base64.b64decode(data["override_data"])
                new_overrides = status_ffi.new("StatusBarOverrideData *")
                struct_size = status_ffi.sizeof(new_overrides[0])
                status_ffi.memmove(new_overrides, raw, min(len(raw), struct_size))
                tweak.setter.apply_changes(new_overrides)
            except Exception as e:
                print(f"Failed to restore status bar: {e}")

    def _apply_icon_themes(self, tweak: IconThemesTweak, data: dict):
        tweak.themes = []
        for entry in data.get("themes", []):
            if not isinstance(entry, dict) or not entry.get("bundle_id"):
                continue
            path = entry.get("icon_path", "")
            if path and os.path.isfile(path):
                # Stick to the persistent store copy so the restored theme
                # stays loadable even if the original file disappeared.
                theme = IconTheme(bundle_id=entry["bundle_id"],
                                  display_name=entry.get("display_name", ""),
                                  icon_path=path)
                if tweak.store_icon(theme):
                    tweak.add_theme(theme)

