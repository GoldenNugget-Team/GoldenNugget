"""Small local history of apply/reset operations."""
from datetime import datetime
import json
import os
import tempfile

from PySide6.QtCore import QStandardPaths

MAX_ENTRIES = 30


def _path():
    root = os.path.join(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation), "GoldenNugget", "History")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "operations.json")


def load_history():
    try:
        with open(_path(), encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def record_operation(manager, mode, success, error=""):
    """Append one bounded record atomically; never affects the operation result."""
    try:
        item = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": str(mode), "success": bool(success), "error": str(error or ""),
            "device": manager.get_current_device_name() or manager.get_current_device_model() or "Unknown device",
            "model": manager.get_current_device_model() or "", "ios": manager.get_current_device_version() or "",
            "udid": manager.get_current_device_udid() or "",
        }
        records = (load_history() + [item])[-MAX_ENTRIES:]
        path = _path()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as stream:
            temporary = stream.name
            json.dump(records, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except Exception:
        temporary = locals().get("temporary")
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def clear_history():
    try:
        os.unlink(_path())
    except FileNotFoundError:
        pass
