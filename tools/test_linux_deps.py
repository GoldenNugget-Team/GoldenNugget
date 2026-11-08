"""Offline checks for the Linux USB-dependency detection and installer."""
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.devicemanagement import linux_deps as deps

ARCH = 'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n'
UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n'
FEDORA = 'ID=fedora\n'
SUSE = 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
ALPINE = 'ID=alpine\n'
VOID = 'ID=void\n'
GENTOO = 'ID=gentoo\n'


class FakeProcess:
    def __init__(self, lines, code):
        self.stdin = io.StringIO()
        self.stdout = iter(lines)
        self._code = code

    def wait(self):
        return self._code


class Detection(unittest.TestCase):
    def test_families(self):
        for text, family in ((ARCH, 'arch'), (UBUNTU, 'debian'), (FEDORA, 'fedora'),
                             (SUSE, 'suse'), (ALPINE, 'alpine'), (VOID, 'void'),
                             (GENTOO, None), ('', None)):
            self.assertEqual(deps.detect_family(text), family, text)

    def test_missing_packages_use_the_family_names(self):
        with patch.object(deps, 'is_linux', return_value=True), \
             patch.object(deps, '_find_binary', return_value=None), \
             patch('os.path.exists', return_value=False):
            self.assertEqual(deps.check('arch').missing_packages, ['usbmuxd', 'libimobiledevice'])
            self.assertEqual(deps.check('debian').missing_packages, ['usbmuxd', 'libimobiledevice-utils'])
            status = deps.check('arch')
            self.assertFalse(status.ok)
            self.assertTrue(status.can_fix)
            self.assertFalse(status.daemon_running)

    def test_installed_tools_are_not_reported(self):
        have = {'usbmuxd': '/usr/bin/usbmuxd', 'ideviceinfo': '/usr/bin/ideviceinfo'}
        with patch.object(deps, 'is_linux', return_value=True), \
             patch.object(deps, '_find_binary', side_effect=lambda name: have.get(name)), \
             patch('os.path.exists', return_value=True):
            self.assertTrue(deps.check('arch').ok)

    def test_non_linux_is_always_ok(self):
        with patch.object(deps, 'is_linux', return_value=False):
            self.assertTrue(deps.check().ok)

    def test_unknown_distribution_cannot_be_fixed_automatically(self):
        with patch.object(deps, 'is_linux', return_value=True), patch.object(deps, 'detect_family', return_value=None), \
             patch.object(deps, '_find_binary', return_value=None), patch('os.path.exists', return_value=False):
            self.assertFalse(deps.check(None).can_fix)
        with self.assertRaises(ValueError):
            deps.install_script(deps.DependencyStatus(None, ['usbmuxd']))


class Script(unittest.TestCase):
    def test_install_script_fails_on_a_failed_install_but_not_on_a_failed_start(self):
        script = deps.install_script(deps.DependencyStatus('arch', ['usbmuxd', 'libimobiledevice'], False))
        self.assertTrue(script.startswith('set -e; pacman -S --needed --noconfirm usbmuxd libimobiledevice'))
        self.assertTrue(script.endswith('systemctl start usbmuxd.service 2>/dev/null || true'))

    def test_daemon_only_fix_skips_the_package_manager(self):
        script = deps.install_script(deps.DependencyStatus('debian', [], False))
        self.assertNotIn('apt-get', script)
        self.assertIn('systemctl start usbmuxd.service', script)

    def test_every_family_has_its_own_install_and_start_commands(self):
        expected = {
            'alpine': ('apk add usbmuxd libimobiledevice-progs', 'rc-service usbmuxd start'),
            'void': ('xbps-install -Sy usbmuxd libimobiledevice', '/etc/sv/usbmuxd'),
            'suse': ('zypper --non-interactive install usbmuxd libimobiledevice-tools', 'systemctl start'),
            'fedora': ('dnf install -y usbmuxd libimobiledevice-utils', 'systemctl start'),
        }
        for family, (install, start) in expected.items():
            with patch.object(deps, 'is_linux', return_value=True), \
                 patch.object(deps, '_find_binary', return_value=None), patch('os.path.exists', return_value=False):
                status = deps.check(family)
            script = deps.install_script(status)
            self.assertIn(install, script, family)
            self.assertIn(start, script, family)
            self.assertTrue(script.startswith('set -e; '), family)

    def test_privilege_prefers_pkexec_then_falls_back_to_sudo(self):
        both = {'pkexec': '/usr/bin/pkexec', 'sudo': '/usr/bin/sudo'}
        with patch.object(deps, '_find_binary', side_effect=lambda n: both.get(n)):
            self.assertEqual(deps.privileged_command('x'), (['pkexec', '/bin/sh', '-c', 'x'], False))
            argv, needs = deps.privileged_command('x', prefer_pkexec=False)
            self.assertEqual((argv[:3], needs), (['/usr/bin/sudo', '-S', '-p'], True))
        with patch.object(deps, '_find_binary', side_effect=lambda n: {'sudo': '/usr/bin/sudo'}.get(n)):
            self.assertTrue(deps.privileged_command('x')[1])
        with patch.object(deps, '_find_binary', return_value=None):
            with self.assertRaises(RuntimeError):
                deps.privileged_command('x')


class Runner(unittest.TestCase):
    STATUS = deps.DependencyStatus('arch', ['usbmuxd'], False)

    def run_with(self, lines, code, pkexec=True, password=None):
        seen = []
        finder = (lambda n: '/usr/bin/' + n) if pkexec else (lambda n: '/usr/bin/sudo' if n == 'sudo' else None)
        proc = FakeProcess(lines, code)
        with patch.object(deps, '_find_binary', side_effect=finder):
            result = deps.run_install(self.STATUS, password=password, on_output=seen.append,
                                      popen=lambda *a, **k: proc)
        return result, seen, proc

    def test_success_streams_output(self):
        result, seen, _ = self.run_with(['installing\n', 'done\n'], 0)
        self.assertTrue(result.ok)
        self.assertEqual(seen, ['installing', 'done'])

    def test_closed_polkit_dialog_is_a_cancel_not_a_failure(self):
        result, _, _ = self.run_with([], 126)
        self.assertTrue(result.cancelled and not result.ok)

    def test_sudo_fallback_pipes_the_password_and_detects_a_wrong_one(self):
        with self.assertRaises(ValueError):
            self.run_with([], 0, pkexec=False)
        result, _, proc = self.run_with(['Sorry, try again.\n'], 1, pkexec=False, password='hunter2')
        self.assertTrue(result.wrong_password)
        self.assertEqual(proc.stdin.getvalue() if not proc.stdin.closed else 'closed', 'closed')
        self.assertNotIn('hunter2', result.output)

    def test_failure_returns_the_package_manager_output(self):
        result, _, _ = self.run_with(['error: target not found\n'], 1)
        self.assertFalse(result.ok or result.cancelled or result.wrong_password)
        self.assertIn('target not found', result.output)


if __name__ == '__main__':
    unittest.main()
