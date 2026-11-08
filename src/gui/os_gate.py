"""Qt-free OS support gate.

The released bundles require Windows 10+, macOS 14.4+ (the Qt 6.12
universal2 wheel floor) and glibc 2.34+ (the manylinux_2_34 build
container). On an older host Qt may import fine but crash later inside the
platform plugin, so the gate runs BEFORE PySide6 loads and reports through
a plain tkinter window — the one toolkit guaranteed to be in the bundle.

GOLDENNUGGET_ALLOW_UNSUPPORTED_OS=1 skips the check (CI/headless).
"""
import os
import platform

_REQUIREMENTS = {
    "Windows": "Windows 10 or later",
    "Darwin": "macOS 14.4 or later",
    "Linux": "glibc 2.34 or later (Ubuntu 22.04 / Debian 12 / RHEL 9)",
}


def unsupported_reason() -> str | None:
    """Short reason the host OS is unsupported, or None when supported."""
    if os.environ.get("GOLDENNUGGET_ALLOW_UNSUPPORTED_OS") == "1":
        return None
    system = platform.system()
    if system == "Windows":
        # platform.version() is "10.0.19045" — the last part is the build.
        try:
            return None if int(platform.version().rsplit(".", 1)[-1]) >= 10240 else _REQUIREMENTS["Windows"]
        except ValueError:
            return None  # unknown version: do not block a possibly fine host
    if system == "Darwin":
        try:
            return None if tuple(platform.mac_ver()[0].split(".")) >= ("14", "4") else _REQUIREMENTS["Darwin"]
        except ValueError:
            return None
    if system == "Linux":
        name, version = platform.libc_ver()
        if name != "glibc":
            return None
        try:
            major, minor = (int(part) for part in version.split(".")[:2])
        except ValueError:
            return None
        return None if (major, minor) >= (2, 34) else _REQUIREMENTS["Linux"]
    return f"{system or 'Unknown'} is not a supported platform."


def warn_and_exit(reason: str) -> None:
    """Minimal window telling the user this OS is not supported, then exit."""
    import tkinter

    print(f"Unsupported OS: {reason}", file=__import__("sys").stderr)
    root = tkinter.Tk()
    root.title("GoldenNugget")
    root.resizable(False, False)
    tkinter.Label(root, text="GoldenNugget does not support this operating system.",
                  justify="center", padx=24, pady=8).pack()
    tkinter.Label(root, text=reason, foreground="#666666",
                  justify="center", padx=24, pady=4).pack()
    tkinter.Button(root, text="OK", command=root.destroy, height=1, width=10).pack(padx=24, pady=10)
    root.mainloop()
    raise SystemExit(1)
