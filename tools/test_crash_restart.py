#!/usr/bin/env python3
"""Offline test for the crash-restart policy (no Qt, no device).

A main-thread crash must only relaunch the app when the user explicitly asks
for it — a startup crash must not loop dialog -> execv forever.
Run: python tools/test_crash_restart.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.exceptions import crash_handler  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def crash():
    try:
        raise ValueError("boom")
    except ValueError:
        crash_handler._handle_crash(*sys.exc_info())


def main():
    try:
        with patch.object(crash_handler, "_restart_app") as restart:
            crash_handler.set_presenter(lambda *a, **k: False)
            crash()
            check("no restart when the user dismisses the dialog", not restart.called)

        with patch.object(crash_handler, "_restart_app") as restart:
            crash_handler.set_presenter(lambda *a, **k: True)
            crash()
            check("restarts only when the user clicks Restart App", restart.called)

        with patch.object(crash_handler, "_restart_app") as restart:
            def broken(summary, tb, info):
                raise RuntimeError("presenter blew up")
            crash_handler.set_presenter(broken)
            crash()  # must not raise and must not restart
            check("a broken presenter never restarts", not restart.called)
    finally:
        crash_handler.set_presenter(None)

    print(f"\n{PASS} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
