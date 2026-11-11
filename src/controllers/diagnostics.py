"""Local, redacted support reports. No uploads or device sessions."""
import json
import os
import platform
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from src.version import App_Build, App_Version

LOG_BYTES = 1024 * 1024
PREFERENCES = ('auto_reboot', 'use_backup_cache', 'use_afc_media',
               'use_encrypted_backup', 'skip_setup', 'hotload_enabled',
               'tweak_autosave', 'auto_refresh_posterboard', 'disable_tendies_limit')


def redact(text, private_values=()):
    text = str(text)
    values = [str(value) for value in private_values if value and len(str(value)) >= 3]
    home = str(Path.home())
    if home not in ('/', '.'):
        values.append(home)
    for value in sorted(set(values), key=len, reverse=True):
        text = text.replace(value, '<redacted>')
    text = re.sub(r'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{8}-[0-9a-f]{16}\b|\b[0-9a-f]{40}\b', '<device-id>', text)
    text = re.sub(r'(?i)[\w.+-]+@[\w.-]+\.[a-z]{2,}', '<email>', text)
    text = re.sub(r'(?i)(\b(?:password|passwd|token|secret|authorization|api[_-]?key)\b[\s\x22\x27]*[:=]\s*)(?:Bearer\s+)?(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s,;}]+)', r'\1<redacted>', text)
    text = re.sub(r'(?i)(--(?:password|token|secret)(?:=|\s+))(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|\S+)', r'\1<redacted>', text)
    text = re.sub(r'(?i)\bBearer\s+\S+', 'Bearer <redacted>', text)
    text = re.sub(r'(?i)(https?://)[^/\s:@]+:[^/\s@]+@', r'\1<redacted>@', text)
    return text


def collect_diagnostics(settings=None, manager=None, log_path=None):
    private, prefs = [], {}
    if settings is not None:
        for key in settings.allKeys():
            if any(word in key.lower() for word in ('password', 'token', 'secret', 'udid', 'serial', 'organization')):
                value = settings.value(key, '')
                if isinstance(value, str):
                    private.append(value)
        for key in PREFERENCES:
            if settings.contains(key):
                prefs[key] = settings.value(key, False, type=bool)
    device = None
    if manager is not None:
        private.extend((manager.get_current_device_udid(), manager.get_current_device_name()))
        device = dict(model=manager.get_current_device_model(), ios=manager.get_current_device_version(),
                      build=manager.get_current_device_build())
        private.append(getattr(manager, '_backup_password', None))
    dependencies = {}
    for name in ('PySide6', 'PySide6-Essentials', 'pymobiledevice3', 'cryptography', 'cffi'):
        try:
            dependencies[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            dependencies[name] = None
    if log_path is None:
        from src.controllers.nugget_logger import get_log_path
        log_path = get_log_path()
    log, log_status = '', 'unavailable'
    try:
        with open(log_path, 'rb') as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - LOG_BYTES))
            raw = stream.read(LOG_BYTES)
            if size > LOG_BYTES:
                raw = raw.partition(b'\n')[2]
            log = raw.decode('utf-8', errors='replace')
            log_status = 'tail' if size > LOG_BYTES else 'complete'
    except (OSError, TypeError):
        pass
    report = dict(schema=1, created_at=datetime.now(timezone.utc).isoformat(),
                  app=dict(version=App_Version, build=App_Build),
                  runtime=dict(python=platform.python_version(), system=platform.system(),
                               release=platform.release(), architecture=platform.machine()),
                  dependencies=dependencies, preferences=prefs, device=device,
                  log_status=log_status, log=redact(log, private),
                  note='Known identifiers and credentials are redacted. Review the report before sharing.')
    # Apply known-value redaction to string metadata too, without changing types.
    def scrub(value):
        if isinstance(value, str):
            return redact(value, private)
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value
    return scrub(report)


def write_diagnostics(destination, report):
    """Atomically write exactly the previewed report and its redacted log."""
    report = dict(report)
    log = report.pop('log', '')
    if not isinstance(log, str):
        raise ValueError('Report log must be text.')
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = stream.name
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('diagnostics.json', json.dumps(report, ensure_ascii=False, indent=2))
            archive.writestr('session.log', log)
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
