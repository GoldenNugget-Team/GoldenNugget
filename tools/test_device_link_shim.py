#!/usr/bin/env python3
"""Offline test for the DeviceLink compatibility shims (no device needed).

Verifies that enumerating a missing directory (e.g. the ``Snapshot`` payload
dir probed during incremental backups) answers with an empty listing instead of
crashing on ``path.iterdir()``, and that a device which goes silent mid-transfer
raises ``DeviceLinkStalled`` instead of blocking forever.
Run: python tools/test_device_link_shim.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.exceptions.device_errors import is_connection_error  # noqa: E402
from src.restore import protective  # noqa: E402  (installs the shims on import)
from src.restore.device_link_adapter import (  # noqa: E402
    DeviceLinkStalled,
    recv_timeout_secs,
)

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


class FakeStatus:
    def __init__(self):
        self.calls = []

    async def status_response(self, status_code, status_str="", status_dict=None):
        self.calls.append((status_code, status_str, status_dict))


class FakeLink:
    def __init__(self, root: Path):
        self.root_path = root
        self.status = FakeStatus()

    async def status_response(self, status_code, status_str="", status_dict=None):
        await self.status.status_response(status_code, status_str, status_dict)


async def main():
    from pymobiledevice3.services.device_link import DeviceLink

    assert getattr(DeviceLink, "_gn_contents_installed", False), "shim not installed"

    tmp = Path(tempfile.mkdtemp(prefix="gn_dl_shim_"))

    handler = DeviceLink.contents_of_directory

    # nested dir with a file -> regular entries come back
    (tmp / "existing").mkdir()
    (tmp / "existing" / "file.txt").write_text("hello")

    link = FakeLink(tmp)
    await handler(link, ["DLContentsOfDirectory", "existing"])
    check("existing dir lists entries", link.status.calls[0][2].get("file.txt") is not None)

    # missing dir (the Snapshot probe) -> empty dict, no crash
    link2 = FakeLink(tmp)
    await handler(link2, ["DLContentsOfDirectory", "missing"])
    check("missing dir answers empty", link2.status.calls[0][2] == {})

    # --- silence budget: a read that never completes must not hang ------ #
    check("recv-timeout shim installed",
          getattr(DeviceLink, "_gn_recv_timeout_installed", False))
    check("recv-timeout default is a positive budget", recv_timeout_secs() > 0)

    class HangingService:
        async def recvall(self, size):
            await asyncio.sleep(30)

    class FastService:
        async def recvall(self, size):
            return b"abcd"[:size]

    recvall = DeviceLink._recvall

    stalled = object.__new__(DeviceLink)
    stalled.service = HangingService()
    stalled.root_path = tmp
    stalled._gn_recv_timeout = 0.05   # per-link override keeps the suite fast
    started = asyncio.get_running_loop().time()
    try:
        await recvall(stalled, 4)
    except DeviceLinkStalled as error:
        elapsed = asyncio.get_running_loop().time() - started
        check("silent device raises DeviceLinkStalled", True)
        check("stall detected quickly", elapsed < 5, f"{elapsed:.2f}s")
        check("stall message names the transfer and the retry",
              "device transfer" in str(error) and "try again" in str(error))
        # A dead transfer must NOT be classified as a transient link flap, or
        # the apply would silently replay the whole backup.
        check("stall is not treated as a connection error",
              not is_connection_error(error))
    else:
        raise AssertionError("FAILED: silent device did not raise")

    healthy = object.__new__(DeviceLink)
    healthy.service = FastService()
    healthy.root_path = tmp
    healthy._gn_recv_timeout = 0.05
    check("a responsive device still reads normally",
          await recvall(healthy, 4) == b"abcd")

    print(f"\n{15 + PASS} assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\nALL PASSED ({PASS} checks)")