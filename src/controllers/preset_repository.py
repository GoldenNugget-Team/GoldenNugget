"""Atomic local preset repository with bounded metadata reads; no tweak state or Qt."""
import copy
import json
import logging
import os
import re
import tempfile
import time
from threading import RLock

PRESET_VERSION = 2


class PresetRepository:
    def __init__(self, directory):
        self.presets_dir = os.fspath(directory)
        self._metadata_cache = {}
        self._metadata_lock = RLock()
        self.last_error = ""
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


    def get_preset_metadata(self, name: str) -> dict | None:
        """Get metadata for a preset without loading the full data."""
        file_path = self.get_preset_path(name)
        try:
            st = os.stat(file_path)
            signature = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            with self._metadata_lock:
                cached = self._metadata_cache.get(file_path)
                if cached is not None and cached[0] == signature:
                    return copy.deepcopy(cached[1])
            with open(file_path, "r", encoding="utf-8") as f:
                header = f.read(8192)
                first = re.match(r'\A\s*\{\s*"metadata"\s*:\s*', header)
                meta = None
                if first is not None:
                    try:
                        candidate, end = json.JSONDecoder().raw_decode(header, first.end())
                        if isinstance(candidate, dict) and header[end:].lstrip().startswith((',', '}')):
                            meta = candidate
                    except ValueError:
                        pass
                if meta is None:
                    f.seek(0)
                    meta = json.load(f).get("metadata", {})
            with self._metadata_lock:
                if len(self._metadata_cache) >= 256 and file_path not in self._metadata_cache:
                    self._metadata_cache.pop(next(iter(self._metadata_cache)))
                self._metadata_cache[file_path] = signature, meta
            return copy.deepcopy(meta)
        except (OSError, ValueError):
            return None


    def save_snapshot(self, name: str, snapshot: dict, description="", tags=None,
                      device_model="", ios_version="", *, should_commit=None) -> bool:
        data = copy.copy(snapshot)
        self.last_error = ""
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
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                    dir=self.presets_dir, prefix=".preset-", suffix=".tmp", delete=False) as f:
                temporary = f.name
                json.dump({"metadata": data.get("metadata", {}), **data}, f, ensure_ascii=False, indent=2)
            if should_commit is not None and not should_commit():
                return False
            os.replace(temporary, file_path)
            return True
        except Exception as e:
            self.last_error = str(e)
            logging.getLogger("GoldenNugget.presets").error("Could not save preset %s: %s", name, e)
            return False
        finally:
            if temporary is not None:
                try:
                    os.remove(temporary)
                except FileNotFoundError:
                    pass


    def delete_preset(self, name):
        path = self.get_preset_path(name)
        try:
            os.remove(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            self.last_error = str(exc)
            logging.getLogger("GoldenNugget.presets").error("Could not delete preset %s: %s", name, exc)
            return False
        with self._metadata_lock:
            self._metadata_cache.pop(path, None)
        return True
