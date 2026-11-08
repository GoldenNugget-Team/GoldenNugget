"""GoldenNugget unified CLI dispatch logic.

Houses the subcommand routing and usage text for the bundled ``GoldenNugget``
binary. The executable entry point (root ``nugget_cli.py``) is only a thin
shim that calls :func:`main` here; keeping the logic inside ``src/cli``
keeps the top-level script trivial and the dispatch logic unit-testable.
"""

import sys

USAGE = """\
GoldenNugget - unified CLI

Usage:
  GoldenNugget                        Launch the GUI
  GoldenNugget --usage | --help       Show this help
  GoldenNugget <command> ... --json   Emit one JSON document; progress goes to stderr

Device & target management:
  GoldenNugget devices [--udid UDID]
      List connected devices (or show one device's details).

Tweaks:
  GoldenNugget tweaks list [--section S] [--all]
  GoldenNugget tweaks show ID
  GoldenNugget tweaks enable ID... [--value X] [--no-save]
  GoldenNugget tweaks disable ID... [--no-save]
  GoldenNugget tweaks set ID VALUE [--no-save]
      Inspect and toggle the registry (plist) tweaks. Changes persist to the
      AutoSave preset (like the GUI) unless --no-save is used.

Daemons:
  GoldenNugget daemons list | show
  GoldenNugget daemons disable DAEMON... [--no-save]
  GoldenNugget daemons enable DAEMON... [--no-save]
  GoldenNugget daemons recommended [--enable] [--no-save]
  GoldenNugget daemons master-on | master-off | screen-time on|off [--no-save]

Apply / Reset:
  GoldenNugget apply [--udid UDID] [--preset NAME]
                      [--enable ID --disable ID --set ID=VALUE]
                      [--daemon-disable DAEMON --daemon-enable DAEMON]
                      [--encrypted-backup] [--password PWD]
                      [--no-skip-setup] [--no-reboot] [--continue-anyway]
                      [--dry-run [--ios-version VERSION --model MODEL]]
      Apply the current tweak state (AutoSave preset + overrides) to the device.

  GoldenNugget reset [--udid UDID] [--status-bar|--springboard|--daemons|--internal]
                      [--no-skip-setup] [--no-reboot] [--dry-run]
      Reset tweak sections back to stock (default: all resettable sections).

Presets:
  GoldenNugget preset list | show NAME
  GoldenNugget preset save NAME [--description ...] [--tags a,b]
  GoldenNugget preset load NAME [--no-save]
  GoldenNugget preset delete NAME
  GoldenNugget preset export NAME [--out PATH] [--include ID,...] [--portable]
  GoldenNugget preset import PATH [--name NEW]

Safety rules (HotLoad):
  GoldenNugget hotload status [--udid UDID]
  GoldenNugget hotload refresh [--url URL]
  GoldenNugget hotload enable | disable

Backups:
  GoldenNugget backup create [--udid UDID] [--no-photos] [--no-posterboard]
  GoldenNugget backup list [--udid UDID]

Offline inspection / support:
  GoldenNugget wallpaper validate PATH [--ios-version VERSION] [--json]
  GoldenNugget diagnostics show [--json]
  GoldenNugget diagnostics export --out PATH [--json]

Standalone recovery / wallpapers:
  GoldenNugget apply-wallpaper [TENDIE] [--udid UDID] [--list]
  GoldenNugget restore-cache [--udid UDID] [--password PASSWORD]
                              [--source auto|cache|live] [--cache-root DIR]
                              [--timeout MINUTES] [--no-skip-setup] [--no-reboot]
  GoldenNugget restore [same options as restore-cache]
  GoldenNugget skip-setup [--udid UDID]

Backward-compatible fallbacks (used internally by the app):
  GoldenNugget -m <module> [args...]
  GoldenNugget <script>.py [args...]

For per-command details run e.g.  GoldenNugget apply --help
"""


def _run_subcommand(name: str, argv: list) -> int:
    if name == "apply-wallpaper":
        from apply_wallpaper import main
    elif name == "restore-cache":
        from restore_cache import main
    elif name == "restore":
        from restore import main
    elif name == "skip-setup":
        from skip_setup import main
    else:
        return None
    return main(argv)


def _build_parser():
    import argparse

    from src.cli import (
        cmd_apply,
        cmd_backup,
        cmd_daemons,
        cmd_devices,
        cmd_diagnostics,
        cmd_hotload,
        cmd_preset,
        cmd_reset,
        cmd_tweaks,
        cmd_wallpaper,
    )

    parser = argparse.ArgumentParser(
        prog="GoldenNugget",
        description="GoldenNugget unified CLI (GUI when run with no command). Add --json to any command for structured output.",
        add_help=True,
    )
    subp = parser.add_subparsers(dest="command", required=True)
    for module in (cmd_devices, cmd_tweaks, cmd_daemons, cmd_preset,
                   cmd_apply, cmd_reset, cmd_hotload, cmd_backup,
                   cmd_diagnostics, cmd_wallpaper):
        module.add_parser(subp)
    return parser


def dispatch(argv: list) -> int:
    from src.cli.output import run_cli
    return run_cli(argv, _dispatch)


def _dispatch(argv: list) -> int:
    # Empty argv (e.g. double-clicking GoldenNugget.exe on Windows) must fall through
    # to the GUI below — only an explicit help flag prints the usage.
    if argv and argv[0] in ("-h", "--help", "--usage"):
        print(USAGE)
        return 0

    known = {"apply-wallpaper", "restore-cache", "restore", "skip-setup",
             "devices", "tweaks", "daemons", "preset", "apply", "reset",
             "hotload", "backup", "diagnostics", "wallpaper"}
    if argv and argv[0] in known:
        if argv[0] in ("apply-wallpaper", "restore-cache", "restore",
                       "skip-setup"):
            code = _run_subcommand(argv[0], argv[1:])
            if code is not None:
                return code
            print(f"Unknown subcommand: {argv[0]}", file=sys.stderr)
            print(USAGE)
            return 2
        try:
            parser = _build_parser()
            args = parser.parse_args(argv)
        except SystemExit as e:
            return int(e.code or 0)
        return args.func(args)

    # Fall through to the classic GUI + dispatcher in main_app, which handles
    # ``-m <module>`` (background processes), ``<file>.py`` execution, and the
    # GUI when no recognized argument is present.
    from src.cli.output import is_json
    if is_json():
        print('ERROR: unknown CLI command; use --help.', file=sys.stderr)
        return 2
    from main_app import main
    return main()


def main() -> int:
    import multiprocessing
    multiprocessing.freeze_support()
    return dispatch(list(sys.argv[1:]))
