"""Read-only selection preview; its history never controls restore routing."""
import hashlib
import json
import logging
import os
import tempfile

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP

from src.restore.lastapply import lastapply_path

log = logging.getLogger("GoldenNugget.preview")


def _path(udid):
    return lastapply_path(udid) + ".preview"


def load_preview(udid, version):
    """None means unknown, including history from a different iOS version."""
    if not udid:
        return None
    try:
        with open(_path(udid), encoding="utf-8") as stream:
            record = json.load(stream)
        if (record.get("schema") == 1 and record.get("version") == version
                and isinstance(record.get("entries"), dict)
                and all(isinstance(entry, dict)
                        and all(key in entry for key in ("section", "title", "value"))
                        and isinstance(entry["section"], str)
                        and isinstance(entry["title"], str)
                        and isinstance(entry.get("display", ""), str)
                        for entry in record["entries"].values())):
            return record["entries"]
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def clear_preview(udid):
    if not udid:
        return
    try:
        os.unlink(_path(udid))
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("Could not clear preview history: %s", exc)


def write_preview(udid, version, preview):
    """Only called after successful apply; atomic and independent of lastapply."""
    if not udid:
        return
    temporary = None
    try:
        if preview is None:
            clear_preview(udid)
            return
        path = _path(udid)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=os.path.dirname(path), delete=False) as stream:
            temporary = stream.name
            json.dump({"schema": 1, "version": version,
                       "entries": preview["entries"]}, stream, ensure_ascii=False)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as exc:
        log.warning("Could not save preview history: %s", exc)
        clear_preview(udid)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def capture_preview(manager):
    """Copy pending selections without generating files or contacting a device."""
    from packaging.version import Version
    from src.controllers.hotload import HotLoad
    from src.devicemanagement.device_manager import MAX_TENDIES_PER_RESTORE
    from src.tweaks.registry import SPECS_BY_ID
    from src.tweaks.tweak_loader import load_plist_tweaks, load_daemons
    from src.tweaks.tweak_classes import AdvancedPlistTweak
    from src.tweaks.tweak_names import TweakID
    from src.tweaks.tweaks import tweaks

    load_plist_tweaks()
    load_daemons()
    version = manager.get_current_device_version()
    hotload = HotLoad(manager.pref_manager.settings)
    context = dict(device_version=version, device_model=manager.get_current_device_model())
    hidden = hotload.hidden_tweak_names(**context)
    forced = hotload.disabled_daemon_keys(**context)
    entries, queued, blocked, forced_names = {}, [], [], []

    def add(key, section, title, value, display=None):
        entries[key] = dict(section=section, title=title, value=value)
        if display is not None:
            entries[key]["display"] = display

    for tid, tweak in tweaks.items():
        spec = SPECS_BY_ID.get(tid)
        title = spec.title if spec else tid.name
        section = spec.section.value if spec else tid.name
        selected = bool(tweak.enabled or getattr(tweak, "tendies", [])
                        or getattr(tweak, "templates", []) or getattr(tweak, "themes", [])
                        or getattr(tweak, "videoFile", None))
        if tid.name in hidden or hotload.rule_for(tid, **context) is not None:
            if selected:
                blocked.append(title)
            continue
        if tid == TweakID.PosterBoard:
            for item in tweak.tendies[:MAX_TENDIES_PER_RESTORE]:
                queued.append(("PosterBoard", item.name))
            if len(tweak.tendies) > MAX_TENDIES_PER_RESTORE:
                queued.append(("PosterBoard", QCoreApplication.translate("ApplyPreview", "Only the first {0} wallpaper packages will be applied.").format(MAX_TENDIES_PER_RESTORE)))
            if tweak.videoFile:
                queued.append((QCoreApplication.translate("ApplyPreview", "Video wallpaper"), os.path.basename(tweak.videoFile)))
        elif tid == TweakID.Templates:
            queued.extend(("Templates", os.path.basename(item.path)) for item in tweak.templates)
        elif tid == TweakID.IconThemes:
            queued.extend((QCoreApplication.translate("ApplyPreview", "Icon Themes"), item.display_name) for item in tweak.themes)
        elif tid == TweakID.Daemons and tweak.enabled:
            values = tweak._filter_keys(tweak.value)
            # Mirror the apply-time whitelist extension, without mutating it.
            values.update({key: True for key in forced if key not in tweak.never_enable})
            for key, value in sorted(values.items()):
                add("Daemons/" + key, "Daemons", key, bool(value))
                if key in forced:
                    forced_names.append(key)
        elif tid == TweakID.StatusBar and tweak.enabled:
            if Version(version) >= Version("27.0"):
                for name, label in (
                    ("carrier", QT_TRANSLATE_NOOP("Nugget", "Primary carrier")),
                    ("secondary_carrier", QT_TRANSLATE_NOOP("Nugget", "Secondary carrier")),
                    ("primary_service_badge", QT_TRANSLATE_NOOP("Nugget", "Primary service badge")),
                    ("secondary_service_badge", QT_TRANSLATE_NOOP("Nugget", "Secondary service badge")),
                    ("gsm_signal_strength_bars", QT_TRANSLATE_NOOP("Nugget", "Primary signal bars")),
                    ("secondary_gsm_signal_strength_bars", QT_TRANSLATE_NOOP("Nugget", "Secondary signal bars")),
                ):
                    active = getattr(tweak, "is_" + name + "_overridden")()
                    value = getattr(tweak, "get_" + name + "_override")() if active else None
                    add("StatusBar/" + name, "Status Bar", label, value)
            else:
                add("StatusBar", "Status Bar", "Status Bar",
                    hashlib.sha256(tweak.setter.get_data()).hexdigest(),
                    QCoreApplication.translate("ApplyPreview", "{0} overrides").format(tweak.count_overrides()))
        elif tweak.enabled:
            value = tweak._filter_keys(tweak.value) if isinstance(tweak, AdvancedPlistTweak) else tweak.value
            add(tid.name, section, title, value)
    # Freeze mutable dict/list values before the apply pass can change them.
    return json.loads(json.dumps(dict(entries=entries, queued=queued, blocked=blocked,
                                     forced=forced_names)))


def safe_capture_preview(manager):
    try:
        return capture_preview(manager)
    except Exception:
        log.exception("Could not capture apply preview")
        return None


def preview_lines(preview, previous):
    """Describe selection differences, never promise an implicit reset."""
    q = lambda text: QCoreApplication.translate("Nugget", text)

    def label(entry):
        return f"{q(entry['section'])} — {q(entry['title'])}"

    def value(entry):
        if "display" in entry:
            return entry["display"]
        raw = entry["value"]
        if entry["section"] == "Daemons":
            return QCoreApplication.translate("ApplyPreview", "Disable service") if raw else QCoreApplication.translate("ApplyPreview", "Enable service")
        if raw is None:
            return QCoreApplication.translate("ApplyPreview", "Default")
        if isinstance(raw, bool):
            return QCoreApplication.translate("ApplyPreview", "On") if raw else QCoreApplication.translate("ApplyPreview", "Off")
        return str(raw) if not isinstance(raw, (dict, list)) else json.dumps(raw, ensure_ascii=False, sort_keys=True)

    lines = []
    entries = preview["entries"]
    if previous is None:
        lines.append(QCoreApplication.translate("ApplyPreview", "No comparable successful apply has been recorded for this device and iOS version. Current selections:"))
    for key, entry in entries.items():
        old = previous.get(key) if previous is not None else None
        if old is None:
            lines.append(QCoreApplication.translate("ApplyPreview", "{0}: selected — {1}").format(label(entry), value(entry)))
        elif old["value"] != entry["value"]:
            if value(old) == value(entry):
                lines.append(QCoreApplication.translate("ApplyPreview", "{0}: configuration changed ({1})").format(label(entry), value(entry)))
            else:
                lines.append(f"{label(entry)}: {value(old)} → {value(entry)}")
    for key, entry in (previous or {}).items():
        if key not in entries:
            lines.append(QCoreApplication.translate("ApplyPreview", "{0}: no longer selected for this apply (not a reset)").format(label(entry)))
    if not lines:
        lines.append(QCoreApplication.translate("ApplyPreview", "No selection changes since the last successful apply."))
    elif previous is None and not entries:
        lines.append(QCoreApplication.translate("ApplyPreview", "No plist tweaks or status bar overrides selected."))
    if preview["queued"]:
        lines.append(QCoreApplication.translate("ApplyPreview", "Current queue (processed again on each apply):"))
        lines.extend(f"{q(section)} — {name}" for section, name in preview["queued"])
    lines.extend(QCoreApplication.translate("ApplyPreview", "{0}: skipped by HotLoad").format(q(name)) for name in preview["blocked"])
    lines.extend(QCoreApplication.translate("ApplyPreview", "{0}: forced off by HotLoad").format(name) for name in preview["forced"])
    return lines
