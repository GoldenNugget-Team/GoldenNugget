#!/usr/bin/env python3
"""Offline classifier guard for the device beta-warning gate (no device, no GUI).

Run: python tools/test_beta_warning.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.gui.main_window_mixins import is_ios_beta_build  # noqa: E402

PASSED = 0


def check(name, cond, extra=""):
    global PASSED
    assert cond, f"FAILED: {name} {extra}"
    PASSED += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


print("== release builds never warn ==")
check("iOS 27.0.1 release (24A435)", not is_ios_beta_build("27.0.1", "24A435"))
check("iOS 26.6 release", not is_ios_beta_build("26.6", "23H320"))
check("iOS 27.2 release", not is_ios_beta_build("27.2", "24B117"))

print("== beta builds warn ==")
check("iOS 27.2 beta 3 (24B5099f)", is_ios_beta_build("27.2", "24B5099f"))
check("iOS 26.4 beta (23A5297e)", is_ios_beta_build("26.4", "23A5297e"))
check("iOS 27.0 beta 1 build", is_ios_beta_build("27.0", "24A5281g"))

print("== tolerance ==")
check("empty build is not a beta", not is_ios_beta_build("27.0.1", ""))
check("empty version is not a beta", not is_ios_beta_build("", "24B5099f"))
check("pre-26 beta is not warned (legacy flow)", not is_ios_beta_build("25.4", "22B5045e"))
check("26.0 itself is not warned (old gate)", not is_ios_beta_build("26.0", "23A5276d"))
check("garbage version does not crash", not is_ios_beta_build("not.a.ver", "24B5099f"))

print(f"{PASSED} checks passed")
print("ALL PASSED")
