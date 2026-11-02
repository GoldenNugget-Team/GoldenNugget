"""Regression guard: the backend must not import Qt.

The rule for this repository is that everything outside ``src/gui`` / ``src/qt``
(and ``main_app.py``) runs without PySide6 at all — the CLI, the backup/restore
engine and the tweak compilers must work on a machine with no Qt installed, and
the GUI must never be an accidental dependency of a backend module.

This test imports every backend module in a subprocess where ``PySide6``,
``shiboken6`` and ``PyQt*`` are blocked at the import system, so even a lazy
``import`` inside a function body is invisible — what matters is the module's
own import graph. Any hit is reported with the offending module and traceback.

Run::

    python tools/test_backend_qt_free.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BACKEND_DIRS = (
    "src/controllers",
    "src/devicemanagement",
    "src/restore",
    "src/tweaks",
    "src/utils",
    "src/cli",
    "src/exceptions",
)

CHILD = textwrap.dedent(
    """
    import importlib
    import json
    import sys
    import traceback

    BLOCKED = ("PySide6", "shiboken6", "PyQt5", "PyQt6", "PySide2")


    class QtImportBlocked(ImportError):
        pass


    class Blocker:
        def find_module(self, name, path=None):
            return self if name.split(".")[0] in BLOCKED else None

        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise QtImportBlocked(f"backend imported Qt module {name!r}")
            return None

    sys.meta_path.insert(0, Blocker())

    violations = {}
    errors = {}
    for module in json.loads(sys.argv[1]):
        try:
            importlib.import_module(module)
        except QtImportBlocked as exc:
            violations[module] = traceback.format_exc()
        except BaseException as exc:  # noqa: BLE001 - unrelated import failure
            errors[module] = f"{type(exc).__name__}: {exc}"
    print("<<<RESULT>>>")
    print(json.dumps({"violations": violations, "errors": errors}))
    """
)


def backend_modules() -> list[str]:
    modules = []
    for directory in BACKEND_DIRS:
        for path in sorted((REPO / directory).rglob("*.py")):
            if path.name.startswith("_") and path.name != "__init__.py":
                continue
            relative = path.relative_to(REPO).with_suffix("")
            parts = list(relative.parts)
            if parts[-1] == "__init__":
                parts.pop()
            modules.append(".".join(parts))
    return modules


def main() -> int:
    modules = backend_modules()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    process = subprocess.run(
        [sys.executable, "-c", CHILD, json.dumps(modules)],
        cwd=str(REPO), env=env, capture_output=True, text=True,
    )
    output = process.stdout
    marker = "<<<RESULT>>>"
    if marker not in output:
        print("child process failed:", file=sys.stderr)
        print(process.stdout, file=sys.stderr)
        print(process.stderr, file=sys.stderr)
        return 1

    payload = json.loads(output.split(marker, 1)[1].strip())
    violations = payload["violations"]
    errors = payload["errors"]

    for module, message in sorted(errors.items()):
        print(f"[skip] {module}: {message}")

    if violations:
        for module, trace in sorted(violations.items()):
            print(f"[FAIL] {module} imports Qt:\n{trace}")
        print(f"\n{len(violations)} backend module(s) still import Qt.")
        return 1

    print(f"OK: {len(modules)} backend modules import with Qt blocked "
          f"({len(errors)} unrelated import failure(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
