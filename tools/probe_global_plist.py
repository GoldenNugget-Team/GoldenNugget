"""Probe on-device /var/preferences/FeatureFlags/Global.plist via afc2.

Dev mode must be enabled. Read-only.
"""

import asyncio
import os
import plistlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3.usbmux import list_devices


async def main() -> int:
    devices = await list_devices()
    usb = [d for d in devices if d.is_usb]
    if not usb:
        print("ERROR: no USB device connected")
        return 1
    serial = usb[0].serial
    ld = await create_using_usbmux(serial=serial, autopair=True)

    print("[1] opening com.apple.afc2 ...")
    try:
        afc = AfcService(lockdown=ld, service_name="com.apple.afc2")
        await afc.connect()
    except Exception as e:
        print(f"    afc2 failed: {type(e).__name__}: {e}")
        return 1

    try:
        print("[2] /var/preferences/FeatureFlags:")
        try:
            for name in await afc.listdir("/var/preferences/FeatureFlags"):
                print(f"   - {name}")
        except Exception as e:
            print(f"   list failed: {type(e).__name__}: {e}")

        path = "/var/preferences/FeatureFlags/Global.plist"
        print(f"[3] reading {path}")
        try:
            data = await afc.get_file_contents(path)
            print(f"    {len(data)} bytes")
            try:
                plist = plistlib.loads(data)
                print(plistlib.dumps(plist, fmt=plistlib.FMT_XML).decode())
            except Exception:
                print(data)
        except Exception as e:
            print(f"   read failed: {type(e).__name__}: {e}")
    finally:
        await afc.aclose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))