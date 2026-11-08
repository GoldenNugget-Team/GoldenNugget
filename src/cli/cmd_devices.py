"""``Nugget devices`` — list / inspect connected iOS devices."""

import argparse
import sys


def add_parser(subp):
    parser = subp.add_parser(
        "devices",
        help="List connected iOS devices",
        description="List every device currently visible to usbmuxd, with "
                    "name, iOS version/build, model and UDID. Pass --udid to "
                    "print one device in detail.")
    parser.add_argument("--udid", default=None,
                        help="print detailed info for this device only")
    parser.set_defaults(func=run)
    return parser


def run(args) -> int:
    from src.cli.common import (
        bootstrap,
        describe_device,
        list_devices,
        make_device_manager,
    )
    settings = bootstrap()
    dm = make_device_manager(settings)
    list_devices(dm, settings)
    from src.cli.output import set_result
    fields = ('name', 'udid', 'version', 'build', 'model', 'hardware', 'cpu', 'locale', 'connected_via_usb')
    devices = [device for device in dm.devices if not args.udid or device.udid == args.udid]
    set_result({'devices': [{key: getattr(device, key, None) for key in fields} for device in devices]})

    if not getattr(dm, "devices", None):
        print("No devices connected.")
        return 1

    if args.udid:
        for i, device in enumerate(dm.devices):
            if getattr(device, "udid", None) == args.udid:
                print(f"name:      {getattr(device, 'name', '?')}")
                print(f"udid:      {getattr(device, 'udid', '?')}")
                print(f"ios:       {getattr(device, 'version', '?')} "
                      f"({getattr(device, 'build', '?')})")
                print(f"model:     {getattr(device, 'model', '?')}")
                print(f"hardware:  {getattr(device, 'hardware', '?')}")
                print(f"cpu:       {getattr(device, 'cpu', '?')}")
                print(f"locale:    {getattr(device, 'locale', '?')}")
                print(f"usb:       {getattr(device, 'usb', '?')}")
                return 0
        print(f"ERROR: device {args.udid} not found.", file=sys.stderr)
        return 1

    print(f"Connected devices ({len(dm.devices)}):")
    for i, device in enumerate(dm.devices):
        print(f"  [{i}] {describe_device(device)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", default=None)
    a = parser.parse_args(argv)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
