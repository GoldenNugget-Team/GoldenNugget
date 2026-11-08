"""Detect and install the Linux packages GoldenNugget needs to reach an iPhone.

USB access goes through ``usbmuxd`` (the multiplexing daemon) and the
libimobiledevice tools. Without them the device scan fails with
``ConnectionFailedToUsbmuxdError``. This module works out what is missing,
which package manager the distribution uses, and builds one privileged
script that installs the packages and starts the daemon.

Privileges are never handled here: ``pkexec`` (polkit) shows the system's own
password dialog, so the app never sees the password. Only when polkit is
unavailable does the caller fall back to ``sudo -S`` with a password it asked
for itself; :func:`privileged_command` builds both forms.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

USBMUXD_SOCKET = "/var/run/usbmuxd"
_BINARY_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/bin", "/sbin")
_TOOLS = ("idevice_id", "ideviceinfo")

_SYSTEMD_START = "systemctl start usbmuxd.service 2>/dev/null || true"

# distro family -> (package manager install argv, usbmuxd package, tools package,
#                   shell command that starts usbmuxd; failure is harmless)
_FAMILIES = {
    "arch": (["pacman", "-S", "--needed", "--noconfirm"], "usbmuxd", "libimobiledevice", _SYSTEMD_START),
    "debian": (["apt-get", "install", "-y"], "usbmuxd", "libimobiledevice-utils", _SYSTEMD_START),
    "fedora": (["dnf", "install", "-y"], "usbmuxd", "libimobiledevice-utils", _SYSTEMD_START),
    "suse": (["zypper", "--non-interactive", "install"], "usbmuxd", "libimobiledevice-tools", _SYSTEMD_START),
    # Alpine uses OpenRC; the tools live in libimobiledevice-progs.
    "alpine": (["apk", "add"], "usbmuxd", "libimobiledevice-progs",
               "rc-service usbmuxd start 2>/dev/null || true"),
    # Void uses runit: a service is enabled by linking it into /var/service.
    "void": (["xbps-install", "-Sy"], "usbmuxd", "libimobiledevice",
             "{ [ -e /var/service/usbmuxd ] || ln -s /etc/sv/usbmuxd /var/service/usbmuxd; } 2>/dev/null || true"),
}
_FAMILY_BY_ID = {
    "arch": "arch", "manjaro": "arch", "endeavouros": "arch", "cachyos": "arch", "garuda": "arch",
    "debian": "debian", "ubuntu": "debian", "linuxmint": "debian", "pop": "debian",
    "fedora": "fedora", "rhel": "fedora", "centos": "fedora", "rocky": "fedora", "almalinux": "fedora",
    "opensuse": "suse", "suse": "suse", "sles": "suse",
    "alpine": "alpine", "postmarketos": "alpine",
    "void": "void",
}


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def _find_binary(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    for directory in _BINARY_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def parse_os_release(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def detect_family(os_release_text: Optional[str] = None) -> Optional[str]:
    """Return 'arch', 'debian', 'fedora', 'suse', 'alpine' or 'void', or None."""
    if os_release_text is None:
        try:
            with open("/etc/os-release", encoding="utf-8") as handle:
                os_release_text = handle.read()
        except OSError:
            return None
    values = parse_os_release(os_release_text)
    candidates = [values.get("ID", "").lower(), *values.get("ID_LIKE", "").lower().split()]
    for candidate in candidates:
        if candidate in _FAMILY_BY_ID:
            return _FAMILY_BY_ID[candidate]
    return None


@dataclass
class DependencyStatus:
    """What is wrong with the USB stack: packages not installed, or daemon down."""
    family: Optional[str]
    missing_packages: list = field(default_factory=list)
    daemon_running: bool = True

    @property
    def ok(self) -> bool:
        return not self.missing_packages and self.daemon_running

    @property
    def can_fix(self) -> bool:
        return self.family is not None and not self.ok


def check(family: Optional[str] = None) -> DependencyStatus:
    """Inspect this machine. Non-Linux systems always report ``ok``."""
    if not is_linux():
        return DependencyStatus(family=None)
    family = family if family is not None else detect_family()
    _, usbmuxd_pkg, tools_pkg, _start = _FAMILIES.get(family, (None, "usbmuxd", "libimobiledevice", None))
    missing = []
    if not _find_binary("usbmuxd"):
        missing.append(usbmuxd_pkg)
    if not any(_find_binary(tool) for tool in _TOOLS):
        missing.append(tools_pkg)
    return DependencyStatus(
        family=family,
        missing_packages=missing,
        daemon_running=os.path.exists(USBMUXD_SOCKET),
    )


def install_script(status: DependencyStatus) -> str:
    """One POSIX shell script that installs what is missing and starts usbmuxd.

    Package names come from the fixed table above, never from user input, so
    joining them into a script is safe.
    """
    if status.family not in _FAMILIES:
        raise ValueError("unsupported distribution")
    install_argv, _usbmuxd, _tools, start_command = _FAMILIES[status.family]
    steps = ["set -e"]
    if status.missing_packages:
        steps.append(" ".join(install_argv + list(status.missing_packages)))
    # usbmuxd is socket/udev-activated on most distributions; starting it by
    # hand makes the first scan work without replugging. Failure is harmless,
    # unlike a failed package install, which `set -e` turns into a failure.
    steps.append(start_command)
    return "; ".join(steps)


def privileged_command(script: str, prefer_pkexec: bool = True) -> tuple[list, bool]:
    """Build the argv that runs ``script`` as root.

    Returns ``(argv, needs_password)``: ``pkexec`` collects the password in the
    desktop's own dialog (``needs_password`` False); the ``sudo -S`` fallback
    reads it from stdin, so the caller must supply it.
    """
    if prefer_pkexec and _find_binary("pkexec"):
        return ["pkexec", "/bin/sh", "-c", script], False
    sudo = _find_binary("sudo")
    if sudo:
        return [sudo, "-S", "-p", "", "/bin/sh", "-c", script], True
    raise RuntimeError("neither pkexec nor sudo is available")


@dataclass
class InstallResult:
    ok: bool
    cancelled: bool = False
    wrong_password: bool = False
    output: str = ""


# pkexec: 126 = not authorised / dialog dismissed, 127 = no authentication agent
_PKEXEC_CANCEL_CODES = (126, 127)


def run_install(
    status: DependencyStatus,
    password: Optional[str] = None,
    on_output: Optional[Callable[[str], None]] = None,
    prefer_pkexec: bool = True,
    popen=subprocess.Popen,
) -> InstallResult:
    """Run the install, streaming output lines to ``on_output``."""
    script = install_script(status)
    argv, needs_password = privileged_command(script, prefer_pkexec)
    if needs_password and password is None:
        raise ValueError("a password is required for the sudo fallback")
    env = dict(os.environ, LC_ALL="C", LANG="C", DEBIAN_FRONTEND="noninteractive")
    process = popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env)
    if needs_password:
        try:
            process.stdin.write(password + "\n")
            process.stdin.flush()
        except OSError:
            pass
    try:
        process.stdin.close()
    except OSError:
        pass
    lines = []
    for line in process.stdout:
        line = line.rstrip("\n")
        lines.append(line)
        if on_output:
            on_output(line)
    code = process.wait()
    output = "\n".join(lines)
    if code == 0:
        return InstallResult(ok=True, output=output)
    if not needs_password and code in _PKEXEC_CANCEL_CODES:
        return InstallResult(ok=False, cancelled=True, output=output)
    wrong = needs_password and ("incorrect password" in output.lower() or "sorry, try again" in output.lower())
    return InstallResult(ok=False, wrong_password=wrong, output=output)


def package_summary(status: DependencyStatus) -> str:
    return ", ".join(status.missing_packages) if status.missing_packages else "usbmuxd"
