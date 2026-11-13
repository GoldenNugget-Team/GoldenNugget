"""Last payloads of preference files GoldenNugget itself created on a device.

A preference file delivered as a new file (the backup had no baseline row for
it) never shows up in a later backup: after the restore the device considers
it already uploaded, so no later incremental session re-uploads it and no
manifest row ever appears host-side. A keyed reset (PreferenceKeyReset)
resolves against backup rows, so without a record of what we delivered such a
file could never be reset — the reset skipped it as "nothing to reset" while
the tweak keys stayed live on the device. This store keeps, per file, the
payload GoldenNugget delivered last; a reset removes the reset keys from that
payload instead of skipping.
"""

import base64
import json
import logging
import os

from src.utils.paths import app_data_dir

log = logging.getLogger("GoldenNugget.created_baselines")


def _path(udid) -> str:
    folder = os.path.join(str(app_data_dir()), "LastApply")
    os.makedirs(folder, exist_ok=True)
    safe = "".join(c for c in str(udid) if c.isalnum() or c in "._-")
    return os.path.join(folder, f"{safe}.created.json")


def load(udid) -> dict:
    """Map ``{domain}/{path}`` -> payload bytes we last delivered; {} when none."""
    try:
        with open(_path(udid), encoding="utf-8") as stream:
            data = json.load(stream)
        return {key: base64.b64decode(value)
                for key, value in data.items()
                if isinstance(key, str) and isinstance(value, str)}
    except (OSError, ValueError, TypeError):
        return {}


def record(udid, payloads: dict) -> None:
    """Merge ``{domain}/{path} -> bytes`` into the per-device record.

    Never cleared: the files persist on the device across applies and resets,
    and each delivery (apply or reset) overwrites its entry with the payload
    that now sits on the device.
    """
    if not udid or not payloads:
        return
    merged = {key: base64.b64encode(value).decode("ascii")
              for key, value in load(udid).items()}
    merged.update({key: base64.b64encode(value).decode("ascii")
                   for key, value in payloads.items()})
    try:
        with open(_path(udid), "w", encoding="utf-8") as stream:
            json.dump(merged, stream)
    except OSError as exc:
        log.warning("Could not save created-baseline history: %s", exc)
