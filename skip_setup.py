#! python3

from __future__ import annotations

import argparse
import asyncio
import sys

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.mobile_config import MobileConfigService

from restore_cache import _list_connected_devices
from src.restore.skip_setup27 import SKIP_ALL_PANES


async def apply_skip_all_setup(udid: str | None = None):
    ld = await create_using_usbmux(serial=udid)
    try:
        async with MobileConfigService(lockdown=ld) as mcs:
            cloud_config = await mcs.get_cloud_configuration() or {}
            cloud_config['SkipSetup'] = list(SKIP_ALL_PANES)
            await mcs.set_cloud_configuration(cloud_config)
    finally:
        try:
            await ld.close()
        except Exception:
            pass

def main(argv: list = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Skip all setup panes on a connected device.",
        add_help=False,
    )
    parser.add_argument("--udid", default=None, help="target device UDID")
    parser.add_argument("-h", "--help", action="help")
    args, _ = parser.parse_known_args(argv)

    udid = args.udid
    if not udid:
        connected = _list_connected_devices()
        if not connected:
            print("ERROR: no device connected. Pass --udid.")
            return 1
        if len(connected) > 1:
            print("WARNING: multiple devices; using the first:", connected[0])
        udid = connected[0]
        print("Using UDID:", udid)
    asyncio.run(apply_skip_all_setup(udid))
    print("Done: all setup panes marked as skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())