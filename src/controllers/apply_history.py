"""Small local history of apply/reset operations."""
from datetime import datetime
import json
import os
import tempfile

from src.utils.i18n import QCoreApplication
from src.utils.paths import app_data_dir

MAX_ENTRIES = 30


def _path():
    root = os.path.join(str(app_data_dir()), "History")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "operations.json")


def load_history():
    try:
        with open(_path(), encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def record_operation(manager, mode, success, error="", reset_pages=None):
    """Append one bounded record atomically; never affects the operation result."""
    try:
        item = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": str(mode), "success": bool(success), "error": str(error or ""),
            "device": manager.get_current_device_name() or manager.get_current_device_model() or "Unknown device",
            "model": manager.get_current_device_model() or "", "ios": manager.get_current_device_version() or "",
            "udid": manager.get_current_device_udid() or "",
        }
        applied = dict(tweaks=None, daemons=None, wallpaper=None)
        if success and mode == "apply":
            preview = getattr(manager, '_last_operation_preview', None)
            if isinstance(preview, dict):
                entries = preview.get('entries', {})
                applied['tweaks'] = any(not key.startswith('Daemons/') for key in entries)
                applied['daemons'] = any(key.startswith('Daemons/') and entry.get('value') is True for key, entry in entries.items())
                applied['wallpaper'] = any(section in ('PosterBoard', QCoreApplication.translate('ApplyPreview', 'Video wallpaper')) for section, _ in preview.get('queued', []))
        elif success and mode == "reset":
            names = {getattr(page, 'name', str(page)) for page in (reset_pages or [])}
            if 'Daemons' in names:
                applied['daemons'] = False
            if 'Posterboard' in names:
                applied['wallpaper'] = False
        item['applied'] = applied
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
