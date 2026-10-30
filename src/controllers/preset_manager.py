from collections.abc import Mapping
# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "src.tweaks.status_bar.status_bar_c.status_setter",
)

import base64
import copy
import json
import os
import re
import shutil
import tempfile
import time
from typing import Optional

from PySide6.QtCore import QStandardPaths, QCoreApplication, QT_TRANSLATE_NOOP

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
from src.tweaks.posterboard.device_overrides import PosterKitOverrides
from src.controllers.hotload import HotLoad
from .retired_feature_flags import is_retired_feature_flag

PRESETS_DIR_NAME = "Presets"
PRESET_VERSION = 2

def _selection_store(manager):
    from src.tweaks.store import selection_store
    return selection_store(manager, tweaks)


class PresetManager:
    @property
    def tweak_store(self):
        selected = getattr(self, "_selected_store", None)
        return selected if selected is not None else tweaks

    def __init__(self, tweak_store=None):
        if tweak_store is not None and not isinstance(tweak_store, Mapping):
            raise TypeError("tweak_store must be a mapping")
        self._selected_store = tweak_store
        self.last_transfer_error = ""
        base_dir = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        # Ensure GoldenNugget-specific folder
        if not base_dir.endswith("GoldenNugget") and not base_dir.endswith("GoldenNugget/"):
            base_dir = os.path.join(base_dir, "GoldenNugget")
        self.presets_dir = os.path.join(base_dir, PRESETS_DIR_NAME)
        os.makedirs(self.presets_dir, exist_ok=True)

    def get_preset_path(self, name: str) -> str:
        return self.repository.get_preset_path(name)

    def _sanitize_name(self, name: str) -> str:
        return self.repository._sanitize_name(name)

    def list_presets(self) -> list[str]:
        return self.repository.list_presets()

    def get_preset_metadata(self, name: str) -> Optional[dict]:
        return self.repository.get_preset_metadata(name)

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

    @property
    def repository(self):
        from .preset_repository import PresetRepository
        repository = getattr(self, '_repository', None)
        if repository is None or repository.presets_dir != os.fspath(self.presets_dir):
            repository = self._repository = PresetRepository(self.presets_dir)
        return repository

    def snapshot(self):
        """A detached serializable state suitable for a background writer."""
        return copy.deepcopy(self._serialize())

    def save_snapshot(self, name, snapshot, description="", tags=None,
                      device_model="", ios_version="", *, should_commit=None):
        if name == 'AutoSave':
            return self.save_preset(name, description, tags, device_model, ios_version,
                                    _data=snapshot, _should_commit=should_commit)
        return self.repository.save_snapshot(name, snapshot, description, tags,
                                              device_model, ios_version, should_commit=should_commit)

    def save_preset(self, name: str, description: str = "", tags: list = None,
                    device_model: str = "", ios_version: str = "", *, _data=None, _should_commit=None) -> bool:
        try:
            data = self._serialize() if _data is None else _data
        except Exception as error:
            self.last_transfer_error = f'Could not serialize configuration: {error}'
            return False
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
        if name == 'AutoSave':
            from src.controllers.autosave_store import write_autosave
            try:
                if _should_commit is not None and not _should_commit():
                    return False
                self._autosave_baseline = write_autosave(
                    file_path, data, getattr(self, '_autosave_baseline', None))
                self.last_transfer_error = ''
                return True
            except Exception as error:
                self.last_transfer_error = f'Could not save AutoSave: {error}'
                return False
        try:
            snapshot = self.snapshot() if _data is None else _data
            if snapshot is None:
                return False
            return self.save_snapshot(name, snapshot, description, tags, device_model, ios_version,
                                      should_commit=_should_commit)
        except Exception:
            import logging
            logging.getLogger('GoldenNugget.presets').exception('Could not save preset %s', name)
            return False

    def load_preset(self, name: str, preview_only: bool = False) -> bool:
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Failed to read preset: {e}")
            return False
        if preview_only and not self._valid_import_structure(data):
            return False
        loaded = self._apply(data, preview_only=preview_only)
        if loaded and name == 'AutoSave' and not preview_only:
            from copy import deepcopy
            self._autosave_baseline = deepcopy(self._serialize()['tweaks'])
        return loaded

    def delete_preset(self, name: str) -> bool:
        return self.repository.delete_preset(name)

    ## EXPORT / IMPORT
    def export_preset(self, name: str, export_path: str,
                      include: Optional[list] = None, portable: bool = False) -> bool:
        """Export JSON or a portable .gnpreset with template/icon assets.

        ``include`` optionally limits the export to a subset of tweaks, given
        as a list of ``TweakID`` members (or their ``.name`` strings). When
        omitted, the whole preset is exported. ``None``/empty means full.
        """
        self.last_transfer_error = ""
        file_path = self.get_preset_path(name)
        if not os.path.isfile(file_path):
            self.last_transfer_error = 'Preset not found.'
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Add export marker
            data["exported"] = True
            data["exported_at"] = int(time.time())

            if include:
                data = self._filter_export(data, include)

            if portable or str(export_path).lower().endswith('.gnpreset'):
                from src.controllers.preset_bundle import export_bundle
                export_bundle(data, export_path)
                return True

            with open(export_path, "w", encoding="utf-8") as f:
                json.dump({"metadata": data.get("metadata", {}), **data}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            self.last_transfer_error = str(e)
            print(f"Failed to export preset: {e}")
            return False

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

    def import_preset(self, import_path: str, new_name: str = None) -> tuple[bool, str]:
        """Store JSON or a portable preset without activation; return (ok, name)."""
        if not os.path.isfile(import_path):
            return False, "File not found"
        owned_assets = None
        committed = False
        try:
            import zipfile
            if str(import_path).lower().endswith('.gnpreset') or zipfile.is_zipfile(import_path):
                from src.controllers.preset_bundle import import_bundle
                data, owned_assets = import_bundle(
                    import_path, os.path.join(self.presets_dir, 'assets'),
                    self._valid_import_structure)
            else:
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

            name = self._store_imported(data, new_name)
            committed = True
            return True, name
        except Exception as e:
            print(f"Failed to import preset: {e}")
            return False, str(e)
        finally:
            if owned_assets is not None and not committed:
                shutil.rmtree(owned_assets, ignore_errors=True)

    def _store_imported(self, data: dict, new_name: str, replace: bool = False) -> str:
        """Write validated preset ``data`` under a unique name; return the name."""
        base_name = self._sanitize_name(new_name)
        name = base_name
        counter = 1
        while not replace and os.path.isfile(self.get_preset_path(name)):
            name = f"{base_name} {counter}"
            counter += 1

        now = int(time.time())
        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"]["imported_at"] = now
        data["metadata"]["updated_at"] = now
        if "created_at" not in data["metadata"]:
            data["metadata"]["created_at"] = now

        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.presets_dir,
                                             delete=False) as f:
                temporary = f.name
                json.dump({"metadata": data.get("metadata", {}), **data}, f, ensure_ascii=False, indent=2)
            os.replace(temporary, self.get_preset_path(name))
            temporary = None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return name

    ## SHARE CODES
    def read_preset(self, name: str) -> Optional[dict]:
        try:
            with open(self.get_preset_path(name), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        return data if self._valid_import_structure(data) else None

    def share_code(self, name: str) -> str:
        """Share code for a saved preset; raises ShareCodeError when impossible."""
        from src.controllers.share_code import ShareCodeError, encode
        data = self.read_preset(name)
        if data is None:
            raise ShareCodeError(QT_TRANSLATE_NOOP("ShareCode", "The preset could not be read."))
        meta = data.get("metadata", {})
        return encode(data["tweaks"], name=name, description=meta.get("description", ""),
                      ios_version=meta.get("ios_version", "") if meta.get("ios_version") != "Unknown" else "")

    def decode_share_code(self, text: str) -> dict:
        from src.controllers.share_code import decode
        return decode(text, self._valid_import_structure)

    def import_share_code(self, text: str, new_name: str = "", catalog: dict = None,
                          replace: bool = False) -> str:
        """Store a shared setup as a new preset (never activates it); return its name.

        ``catalog`` ({"id", "sha256"}) marks a preset imported from the community
        catalog so a newer version can be offered; ``replace`` overwrites the
        preset named ``new_name`` instead of picking a free name (an update)."""
        data = self.decode_share_code(text)
        name = new_name or data["metadata"].pop("name", "") or "Shared Preset"
        data["metadata"].pop("name", None)
        data.pop("shared_count", None)
        if catalog:
            data["metadata"]["catalog"] = dict(catalog)
        return self._store_imported(data, name, replace=replace)

    @staticmethod
    def _valid_import_structure(data) -> bool:
        from .preset_codec import valid_import_structure
        return valid_import_structure(data)

    ## SERIALIZATION
    def _serialize(self) -> dict:
        self._load_all_tweaks()
        tweaks = _selection_store(self)
        tweak_data = {}
        for key, tweak in tweaks.items():
            # PosterBoard is excluded from presets: wallpapers are
            # device-specific and heavy, so they must not travel with a preset.
            if key == TweakID.PosterBoard:
                continue
            try:
                tweak_data[key.name] = self._serialize_tweak(tweak)
            except Exception as e:
                raise ValueError(f"Failed to serialize tweak {key}: {e}") from e

        return {
            "tweaks": tweak_data
        }

    def _serialize_tweak(self, tweak) -> dict:
        data = {"type": type(tweak).__name__, "enabled": tweak.enabled}
        if isinstance(tweak, AdvancedPlistTweak):
            # Store only what the UI exposes / what would actually apply.
            data["value"] = tweak._filter_keys(tweak.value)
        elif isinstance(tweak, (BasicPlistTweak,PosterKitOverrides)):
            data["value"] = copy.deepcopy(tweak.value)
        elif isinstance(tweak, TemplatesTweak):
            data["templates"] = [t.path for t in tweak.templates]
            states = tweak.tweak_states()
            if any(states):
                data["tweak_states"] = states
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
    def _apply(self, data: dict, preview_only: bool = False) -> bool:
        tweaks = _selection_store(self)
        from src.controllers.preset_apply import apply_preset_transaction, PresetApplyResult
        from src.tweaks.hidden import current_hidden_tweak_names
        try:
            self._load_all_tweaks()
            hidden_names = current_hidden_tweak_names()
            def prepare(name, tweak_data):
                if is_retired_feature_flag(tweak_data):
                    return None
                try:
                    key = TweakID[name]
                except KeyError:
                    return None
                if key not in tweaks or key == TweakID.PosterBoard or name in hidden_names:
                    return None
                candidate = copy.copy(tweaks[key])
                if isinstance(candidate, StatusBarTweak):
                    candidate.setter = copy.copy(candidate.setter)
                if preview_only and key == TweakID.Templates:
                    from types import SimpleNamespace
                    candidate.templates = [SimpleNamespace(path=path)
                                           for path in tweak_data.get('templates', [])]
                elif preview_only and key == TweakID.IconThemes:
                    candidate.themes = [IconTheme(**entry) for entry in tweak_data.get('themes', [])]
                else:
                    self._apply_tweak(candidate, tweak_data)
                return key, candidate
            self.last_apply_result = apply_preset_transaction(data.get('tweaks', {}), tweaks, prepare)
        except Exception as exc:
            self.last_apply_result = PresetApplyResult(errors=(str(exc),))
        if not self.last_apply_result.success:
            import logging
            logging.getLogger('GoldenNugget.presets').error(
                'Preset was not applied: %s', '; '.join(self.last_apply_result.errors))
        return self.last_apply_result.success

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
        elif isinstance(tweak, (BasicPlistTweak,PosterKitOverrides)):
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
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"Template not found: {path}")
                tweak.add_template(path)
            tweak.restore_tweak_states(data.get("tweak_states"), data["templates"])

    def _apply_status_bar(self, tweak: StatusBarTweak, data: dict):
        tweak.enabled = data.get("enabled", False)
        tweak.setter.silly_mode = data.get("silly_mode", False)
        if "override_data" in data:
            raw = base64.b64decode(data["override_data"], validate=True)
            new_overrides = status_ffi.new("StatusBarOverrideData *")
            struct_size = status_ffi.sizeof(new_overrides[0])
            if len(raw) != struct_size:
                raise ValueError("Invalid status bar override data size")
            status_ffi.memmove(new_overrides, raw, struct_size)
            tweak.setter.apply_changes(new_overrides)

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
                if not tweak.store_icon(theme):
                    raise OSError(f"Could not store icon: {path}")
                tweak.add_theme(theme)
            else:
                raise FileNotFoundError(f"Icon not found: {path}")

