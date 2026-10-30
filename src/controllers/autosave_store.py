import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QLockFile
from .retired_feature_flags import is_retired_feature_flag


def _merge_local_changes(local, baseline, latest):
    if local == baseline:
        return deepcopy(latest)
    if isinstance(local, dict) and isinstance(baseline, dict) and isinstance(latest, dict):
        result = deepcopy(latest)
        for key, value in local.items():
            result[key] = (_merge_local_changes(value, baseline[key], latest[key])
                           if key in baseline and key in latest else deepcopy(value))
        return result
    return deepcopy(local)


def write_autosave(path, data, baseline=None):
    path = Path(path)
    lock = QLockFile(str(path) + '.lock')
    if not lock.tryLock(200):
        raise OSError('Another GoldenNugget instance is saving this configuration.')
    temporary = None
    try:
        local = deepcopy(data['tweaks'])
        existing = {}
        if path.exists():
            previous = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(previous, dict) or not isinstance(previous.get('tweaks'), dict):
                raise ValueError('Existing AutoSave is invalid; it was not overwritten.')
            existing = previous['tweaks']
        merged = dict(existing)
        for name, entry in local.items():
            merged[name] = (_merge_local_changes(entry, baseline[name], existing[name])
                            if baseline is not None and name in baseline and name in existing
                            else deepcopy(entry))
        for name, entry in merged.items():
            if is_retired_feature_flag(entry):
                merged[name] = {**entry, 'enabled': False}
        result = {**data, 'tweaks': merged}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.autosave-', delete=False) as stream:
            temporary = stream.name
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return local
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
        lock.unlock()
