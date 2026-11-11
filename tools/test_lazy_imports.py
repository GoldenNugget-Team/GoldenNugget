#!/usr/bin/env python3
"""Check PEP 810 deferral and first-use resolution in fresh interpreters."""
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LazyImportTests(unittest.TestCase):
    def test_operation_dependencies(self):
        # Each case gets a process: another test's imports must not hide eager
        # loading. Access the imported object as well to catch broken proxies.
        cases = [
            ("src.restore", "pymobiledevice3.services.diagnostics",
             "assert callable(module.DiagnosticsService)"),
            ("src.restore.inject", "pymobiledevice3.services.mobilebackup2",
             "assert callable(module.Mobilebackup2Service)"),
            ("src.restore.afc_media", "pymobiledevice3.services.afc",
             "assert callable(module.AfcService)"),
            ("src.restore.skip_setup27", "pymobiledevice3.ca",
             "assert module.build_cloud_config({}, supervised=False)['SkipSetup']; "
             "assert callable(module.create_keybag_file)"),
        ]
        for name, dependency, operation in cases:
            with self.subTest(module=name):
                code = textwrap.dedent(f"""
                    import importlib
                    import sys
                    module = importlib.import_module({name!r})
                    if sys.version_info >= (3, 15):
                        assert {dependency!r} not in sys.modules, 'loaded before first use'
                    else:
                        assert {dependency!r} in sys.modules, 'older Python must stay eager'
                    {operation}
                    assert {dependency!r} in sys.modules, 'not resolved on first use'
                """)
                env = os.environ.copy()
                env['PYTHONPATH'] = os.pathsep.join(filter(None, (
                    str(ROOT), env.get('PYTHONPATH', ''))))
                result = subprocess.run(
                    [sys.executable, '-c', code], cwd=ROOT, env=env,
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cloud_config_needs_no_certificate_stack(self):
        if sys.version_info < (3, 15):
            self.skipTest('PEP 810 requires Python 3.15')
        code = """
import sys
from src.restore.skip_setup27 import build_cloud_config
config = build_cloud_config({}, supervised=False)
assert 'AppleID' in config['SkipSetup']
assert 'cryptography.x509' not in sys.modules
assert 'pymobiledevice3.ca' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, '-c', code], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
