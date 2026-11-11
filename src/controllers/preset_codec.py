"""Validation of portable preset data without repository or GUI dependencies."""
import base64


def valid_import_structure(data) -> bool:
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
        if "tweak_states" in entry and (not isinstance(entry["tweak_states"], list)
                                        or not all(isinstance(state, dict) for state in entry["tweak_states"])):
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
