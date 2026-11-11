"""Resilient syslog capture: reconnects across a device reboot.

Usage: python3 tools/capture_syslog.py out.log
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.syslog import SyslogService
from pymobiledevice3.usbmux import list_devices


async def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/opencode/syslog_all.log"
    out = open(out_path, "ab", buffering=0)
    while True:
        try:
            devices = await list_devices()
            usb = [d for d in devices if d.is_usb]
            if not usb:
                print("no device, waiting 5s...", flush=True)
                await asyncio.sleep(5)
                continue
            serial = usb[0].serial
            ld = await create_using_usbmux(serial=serial, autopair=True)
            print(f"connected to {serial}", flush=True)
            async with SyslogService(ld) as svc:
                async for line in svc.watch():
                    if not isinstance(line, (bytes, str)):
                        continue
                    if isinstance(line, str):
                        line = line.encode()
                    out.write(line + b"\n")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"connection lost ({type(e).__name__}), reconnecting in 5s...", flush=True)
            await asyncio.sleep(5)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))