"""Apply a single .tendies wallpaper to a connected device (CLI).

Packs the exact device tweak flow GoldenNugget uses into a non-interactive
command you can run from a build or terminal. The tendie path, device UDID and
options can be given as arguments; anything omitted is auto-detected.

    python3 apply_wallpaper.py path/to/wallpaper.tendies
    python3 apply_wallpaper.py path/to/wallpaper.tendies --udid UDID
    python3 apply_wallpaper.py --tendie path/to/wallpaper.tendies --list
"""

import argparse
import os
import sys


def _qapp():
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    QCoreApplication.setOrganizationDomain("com.leemin")
    QCoreApplication.setApplicationName("GoldenNugget")
    return QApplication.instance() or QApplication(sys.argv)


def _pick_udid(dm, manager_settings, update_label, show_alert) -> str:
    udid = dm.get_current_device_udid()
    if udid:
        return udid
    # Refresh the device list; if exactly one device answers, use it.
    dm.get_devices(manager_settings, show_alert=show_alert)
    udid = dm.get_current_device_udid()
    if udid:
        return udid
    from restore_cache import _list_connected_devices
    devs = _list_connected_devices()
    if len(devs) == 1:
        return devs[0]
    if len(devs) > 1:
        raise RuntimeError("Multiple devices connected. Pass --udid to choose one.")
    raise RuntimeError("No device connected.")


def apply_one_tendie(tendie: str, udid: str = None, list_devices: bool = False) -> int:
    from src.controllers.settings import Settings
    from src.devicemanagement.device_manager import DeviceManager
    from src.tweaks.tweaks import TweakID, tweaks

    _qapp()
    settings = Settings("settings")
    dm = DeviceManager()

    def update_label(text):
        print("[STATUS]", text)

    def show_alert(msg):
        if msg is None:
            print("[DONE] No alert")
            return
        print("[ALERT]", getattr(msg, "title", "") or "Message")
        print("[ALERT] ", getattr(msg, "txt", msg))
        if getattr(msg, "detailed_txt", None):
            print("[ALERT DETAIL]\n", msg.detailed_txt)

    if list_devices:
        return _list_devices(dm, settings, show_alert)

    resolved = udid or _pick_udid(dm, settings, update_label, show_alert)
    if not resolved:
        print("ERROR: No device connected!")
        return 1

    print("Device:", dm.get_current_device_name(), dm.get_current_device_version(),
          dm.get_current_device_build())

    if not os.path.exists(tendie):
        print("ERROR: tendie not found:", tendie)
        return 1

    pb = tweaks[TweakID.PosterBoard]
    # A fresh PosterBoard database is fetched from the device (via the "Fetch
    # Database File" backup) right before the apply in _apply_changes, so no
    # manual fetch is needed here.
    pb.config_manager.update_for_saved_database(resolved)

    added = pb.add_tendie(tendie)
    print("Tendie added:", added, "| descriptors:", pb.get_descriptor_count())
    if not added:
        print("ERROR: failed to add tendie")
        return 1

    print("Starting apply...")
    dm.apply_changes(update_label=update_label, show_alert=show_alert)
    print("Apply finished.")
    return 0


def _list_devices(dm, settings, show_alert) -> int:
    dm.get_devices(settings, show_alert=show_alert)
    if not getattr(dm, "devices", None):
        print("No devices connected.")
        return 1
    for i, d in enumerate(getattr(dm, "devices", [])):
        print(f"{i}: {getattr(d, 'name', '?')}  "
              f"{getattr(d, 'version', '?')} ({getattr(d, 'build', '?')})  "
              f"{getattr(d, 'udid', '?')}")
    return 0


def main(argv: list = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Apply a .tendies wallpaper to a connected iOS device.",
        add_help=False,
    )
    parser.add_argument("tendie", nargs="?", default=None,
                        help="path to the .tendies wallpaper (default: prompt)")
    parser.add_argument("--udid", default=None, help="target device UDID")
    parser.add_argument("--list", action="store_true",
                        help="list connected devices and exit")
    parser.add_argument("-h", "--help", action="help")
    args, _ = parser.parse_known_args(argv)

    tendie = args.tendie
    if not tendie and not args.list:
        tendie = _prompt_path("Path to .tendies wallpaper: ")
        if not tendie:
            print("No tendie selected.")
            return 1
    return apply_one_tendie(tendie, udid=args.udid, list_devices=args.list)


def _prompt_path(label: str) -> str:
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return input(label).strip().strip('"').strip("'")
        from PySide6.QtWidgets import QFileDialog
        return QFileDialog.getOpenFileName(
            None, "Select .tendies wallpaper", "", "Tendies (*.tendies)")[0]
    except Exception:
        return ""


if __name__ == "__main__":
    sys.exit(main())
