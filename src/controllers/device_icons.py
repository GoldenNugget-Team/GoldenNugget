"""Stock app icons for the iPhone Preview, read from the connected iPhone.

GoldenNugget ships no Apple artwork: SpringBoard hands over the icons the
user's own iPhone shows, and they are cached per device and iOS version so
the preview can use them offline. Without a cache the preview keeps its
drawn stand-ins.
"""
import os
import re

from PySide6.QtCore import QStandardPaths

# preview app name -> bundle id. Calendar and Clock are left out: the preview
# draws them live (today's date, the current time), a snapshot would go stale.
STOCK_BUNDLES = {
    "FaceTime": "com.apple.facetime",
    "Photos": "com.apple.mobileslideshow",
    "Camera": "com.apple.camera",
    "Mail": "com.apple.mobilemail",
    "Notes": "com.apple.mobilenotes",
    "Reminders": "com.apple.reminders",
    "Weather": "com.apple.weather",
    "Maps": "com.apple.Maps",
    "Music": "com.apple.Music",
    "Settings": "com.apple.Preferences",
    "App Store": "com.apple.AppStore",
    "Wallet": "com.apple.Passbook",
    "Health": "com.apple.Health",
    "Files": "com.apple.DocumentsApp",
    "Phone": "com.apple.mobilephone",
    "Safari": "com.apple.mobilesafari",
    "Messages": "com.apple.MobileSMS",
}


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", part or "unknown")


def cache_dir(udid: str, version: str) -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base.rstrip("/").endswith("GoldenNugget"):
        base = os.path.join(base, "GoldenNugget")
    return os.path.join(base, "DeviceIcons", _safe(udid), _safe(version))


def cached_icons(udid: str, version: str) -> dict:
    """{app name: png path} for the icons already cached for this device."""
    if not udid:
        return {}
    folder = cache_dir(udid, version)
    icons = {}
    for name, bundle in STOCK_BUNDLES.items():
        path = os.path.join(folder, bundle + ".png")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            icons[name] = path
    return icons


async def fetch_icons(udid: str, version: str) -> dict:
    """Pull every stock icon from the iPhone into the cache.

    Never asks the iPhone to trust this computer: the preview is not worth a
    pairing prompt. Apps that are not installed are skipped.
    """
    from pymobiledevice3.services.springboard import SpringBoardServicesService

    from src.devicemanagement.session import lockdown_session

    folder = cache_dir(udid, version)
    os.makedirs(folder, exist_ok=True)
    async with lockdown_session(udid, autopair=False) as lockdown:
        async with SpringBoardServicesService(lockdown) as springboard:
            for bundle in STOCK_BUNDLES.values():
                try:
                    data = await springboard.get_icon_pngdata(bundle)
                except Exception:
                    continue
                if not data:
                    continue
                path = os.path.join(folder, bundle + ".png")
                with open(path + ".part", "wb") as stream:
                    stream.write(data)
                os.replace(path + ".part", path)
    return cached_icons(udid, version)
