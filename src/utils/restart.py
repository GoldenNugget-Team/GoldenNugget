"""Restart the current process (POSIX exec semantics; Windows-safe spawn)."""
import os
import subprocess
import sys


def restart_app(argv=None):
    """Relaunch GoldenNugget and end this process.

    ``argv`` follows the ``os.execv`` convention — ``argv[0]`` is the
    program-name slot and is NOT passed to the new process (default:
    ``sys.argv`` when frozen, else ``[sys.executable] + sys.argv``).

    ``os.execv`` is unusable on Windows: its argument vector is joined with
    plain spaces without quoting, so every path or flag containing a space
    is silently mangled in the new process (the restarted app receives a
    broken ``sys.argv`` or a SyntaxError). There the replacement process is
    spawned and this one exits immediately; on POSIX the process is
    replaced for real.
    """
    if argv is None:
        if getattr(sys, "frozen", False):
            # PyInstaller: sys.argv[0] is already the executable path.
            argv = list(sys.argv)
        else:
            argv = [sys.executable] + list(sys.argv)
    argv = list(argv)
    if sys.platform == "win32":
        subprocess.Popen([sys.executable] + argv[1:], close_fds=True)
        os._exit(0)
    os.execv(sys.executable, argv)
