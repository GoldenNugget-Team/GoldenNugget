#!/usr/bin/env python3
"""Offline guard for the host-OS support gate (no window, no device needed).

Run: python tools/test_os_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import platform as os_module  # noqa: E402

from src.gui.os_gate import unsupported_reason  # noqa: E402

PASSED = 0


def check(name, cond, extra=""):
    global PASSED
    assert cond, f"FAILED: {name} {extra}"
    PASSED += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def for_system(system, version="", mac_ver="", libc=("glibc", "0.0")):
    """Run `unsupported_reason` against a faked host."""
    forced = {
        "system": lambda: system,
        "version": lambda: version,
        "mac_ver": lambda: (mac_ver, "", ""),
        "libc_ver": lambda: libc,
    }
    saved = {name: getattr(os_module, name) for name in forced}
    for name, fake in forced.items():
        setattr(os_module, name, fake)
    try:
        return unsupported_reason()
    finally:
        for name, real in saved.items():
            setattr(os_module, name, real)


print("== Supported hosts pass ==")
check("windows 10 passes", for_system("Windows", version="10.0.19045") is None)
check("windows 11 passes", for_system("Windows", version="10.0.26100") is None)
check("macOS 14.4 passes", for_system("Darwin", mac_ver="14.4.0") is None)
check("macOS 14.6 passes", for_system("Darwin", mac_ver="14.6.1") is None)
check("linux glibc 2.34 passes", for_system("Linux", libc=("glibc", "2.34")) is None)
check("linux glibc 2.35 passes", for_system("Linux", libc=("glibc", "2.35")) is None)

print("== Unsupported hosts state the floor ==")
GLIBC_MSG = "glibc 2.34 or later (Ubuntu 22.04 / Debian 12 / RHEL 9)"
check("windows 7 fails", for_system("Windows", version="6.1.7601") == "Windows 10 or later")
check("windows 8.1 fails", for_system("Windows", version="6.3.9600") == "Windows 10 or later")
check("macOS 12 Monterey fails", for_system("Darwin", mac_ver="12.7.6") == "macOS 14.4 or later")
check("macOS 13 Ventura fails", for_system("Darwin", mac_ver="13.6.0") == "macOS 14.4 or later")
check("linux glibc 2.31 (Ubuntu 20.04) fails", for_system("Linux", libc=("glibc", "2.31")) == GLIBC_MSG)
check("unknown platform fails", for_system("FreeBSD", version="14.0") == "FreeBSD is not a supported platform.")

print("== Tolerance of odd inputs ==")
check("musl linux is not blocked", for_system("Linux", libc=("musl", "1.2")) is None)
check("windows garbage version does not block", for_system("Windows", version="not-a-version") is None)
check("linux garbage glibc does not block", for_system("Linux", libc=("glibc", "bogus")) is None)
os.environ["GOLDENNUGGET_ALLOW_UNSUPPORTED_OS"] = "1"
check("override skips the gate", for_system("FreeBSD", version="14.0") is None)
del os.environ["GOLDENNUGGET_ALLOW_UNSUPPORTED_OS"]

print(f"{PASSED} checks passed")
print("ALL PASSED")
