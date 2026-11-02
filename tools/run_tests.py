#!/usr/bin/env python3
"""Run the offline regression scripts in isolated processes, locally or in CI."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]


def run_suite(script, log_path, timeout):
    with tempfile.TemporaryDirectory(prefix=f"gn_{script.stem}_") as sandbox:
        sandbox = Path(sandbox)
        env = os.environ.copy()
        env.update({
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONUNBUFFERED": "1",
            "XDG_CONFIG_HOME": str(sandbox / "config"),
            "XDG_DATA_HOME": str(sandbox / "data"),
            "XDG_CACHE_HOME": str(sandbox / "cache"),
            "GOLDENNUGGET_BACKUP_DIR": str(sandbox / "backups"),
            "GOLDENNUGGET_PREFERENCES_DIR": str(sandbox / "preferences"),
            "GOLDENNUGGET_LOG_FILE": str(sandbox / "session.log"),
        })
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(ROOT), str(ROOT / "src" / "qt"), env.get("PYTHONPATH", ""))))
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, str(script)], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"))
            try:
                code = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass  # It finished between wait() timing out and kill().
                process.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                log.write(f"\nTIMEOUT after {timeout}s\n".encode())
                return "TIMEOUT"
        return "PASS" if code == 0 else f"FAIL (exit {code})"


def main(argv=None):
    scripts = {path.stem: path for path in sorted((ROOT / "tools").glob("test_*.py"))}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Optional test names, e.g. test_theme")
    parser.add_argument("--list", action="store_true", help="List available suites without running them")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds allowed per suite (default: 120)")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "test-results")
    args = parser.parse_args(argv)
    selected = [name.removesuffix(".py") for name in args.tests] or list(scripts)
    unknown = set(selected) - scripts.keys()
    if unknown:
        parser.error("Unknown test(s): " + ", ".join(sorted(unknown)))
    if not scripts:
        parser.error("No test_*.py scripts found")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.list:
        print("\n".join(selected))
        return 0
    args.report_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    failed = 0
    for name in selected:
        started = time.monotonic()
        log_path = args.report_dir / f"{name}.log"
        result = run_suite(scripts[name], log_path, args.timeout)
        seconds = time.monotonic() - started
        rows.append(f"| {name} | {result} | {seconds:.1f} |")
        print(f"{result}: {name} ({seconds:.1f}s)", flush=True)
        if result != "PASS":
            failed += 1
            print(log_path.read_text(encoding="utf-8", errors="replace"), flush=True)
    summary = (f"# Offline tests: {len(selected) - failed}/{len(selected)} suites passed\n\n"
               "| Suite | Result | Seconds |\n| --- | --- | ---: |\n" + "\n".join(rows) + "\n")
    (args.report_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\n{len(selected) - failed}/{len(selected)} suites passed; logs: {args.report_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
