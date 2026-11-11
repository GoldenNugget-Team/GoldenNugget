"""``Nugget apply`` — run the full tweak apply flow (the GUI's "Apply" page).

Starts from the auto-saved preset (or ``--preset``), lets extra ``--enable`` /
``--disable`` / ``--set`` / ``--daemon-*`` flags be mixed in on the command
line, then applies everything to the device over lockdown.
"""

import argparse
import sys


def add_parser(subp):
    parser = subp.add_parser(
        "apply",
        help="Apply the current tweak state to the device",
        description="Generate everything enabled in the tweak state and restore "
                    "it to the device (exactly what the GUI's Apply button runs). "
                    "Takes the state from AutoSave (or --preset) plus any "
                    "--enable/--disable/--set/--daemon-* overrides.",
    )
    parser.add_argument("--udid", default=None, help="target device UDID")
    parser.add_argument("--preset", default=None,
                        help="preset to start from (default: AutoSave)")
    parser.add_argument("--enable", action="append", default=[], metavar="ID",
                        help="enable a registry tweak first (repeatable)")
    parser.add_argument("--disable", action="append", default=[], metavar="ID",
                        help="disable a registry tweak first (repeatable)")
    parser.add_argument("--set", action="append", default=[], metavar="ID=VALUE",
                        help="set a tweak's value (enables it)")
    parser.add_argument("--daemon-disable", action="append", default=[],
                        metavar="DAEMON", help="disable a daemon first (repeatable)")
    parser.add_argument("--daemon-enable", action="append", default=[],
                        metavar="DAEMON", help="re-enable a daemon first (repeatable)")
    parser.add_argument("--encrypted-backup", action="store_true",
                        help="use encrypted backups (needs --password)")
    parser.add_argument("--password", default=None,
                        help="backup password for encrypted restores")
    parser.add_argument("--no-skip-setup", action="store_true",
                        help="don't mark iOS setup panes complete (default: skip)")
    parser.add_argument("--no-reboot", action="store_true",
                        help="don't auto-reboot the device after applying")
    parser.add_argument("--continue-anyway", action="store_true",
                        help="answer later device prompts with resume; a failed "
                             "protective backup still stops the apply")
    parser.add_argument('--dry-run', action='store_true', help='Show selections, paths, conflicts and local safety rules without applying')
    parser.add_argument('--ios-version', default=None, help='Offline target iOS version (requires --dry-run)')
    parser.add_argument('--model', default=None, help='Offline model identifier, e.g. iPhone16,1 (requires --dry-run --ios-version)')
    parser.set_defaults(func=run)
    return parser


def _apply_flag_tweaks(args):
    from src.cli.cmd_tweaks import _resolve_specs, parse_value
    from src.tweaks.tweaks import tweaks

    for name in args.enable:
        for spec in _resolve_specs([name]):
            tweaks[spec.id].set_enabled(True)
            print(f"[apply] enabled {spec.id.name}")
    for name in args.disable:
        for spec in _resolve_specs([name]):
            tweaks[spec.id].set_enabled(False)
            print(f"[apply] disabled {spec.id.name}")
    for item in args.set:
        if "=" not in item:
            print(f"ERROR: --set expects ID=VALUE, got '{item}'.", file=sys.stderr)
            raise SystemExit(2)
        name, _, value = item.partition("=")
        spec = _resolve_specs([name])[0]
        tweaks[spec.id].set_value(parse_value(spec, value), toggle_enabled=True)
        print(f"[apply] set {spec.id.name} = {value!r}")

    if args.daemon_disable or args.daemon_enable:
        from src.cli.cmd_daemons import _resolve_daemons, _set_keys
        from src.tweaks.tweak_loader import load_daemons
        from src.tweaks.tweaks import TweakID
        load_daemons()
        dl = tweaks[TweakID.Daemons]
        for name in args.daemon_disable:
            dl.set_enabled(True)
            for d in _resolve_daemons([name]):
                keys = _set_keys(d, True)
                print(f"[apply] disabled daemon {name} -> {', '.join(keys)}")
        for name in args.daemon_enable:
            for d in _resolve_daemons([name]):
                keys = _set_keys(d, False)
                print(f"[apply] enabled daemon {name} -> {', '.join(keys)}")


def run(args) -> int:
    from src.cli.common import (
        bootstrap,
        describe_device,
        ensure_device,
        load_core_tweaks,
        load_default_preset,
        load_prefs,
        make_device_manager,
        print_alert,
        print_status,
    )

    settings = bootstrap()
    dm = make_device_manager(settings)
    load_prefs(dm, settings)
    if args.no_skip_setup:
        dm.pref_manager.skip_setup = False
    if args.no_reboot:
        dm.pref_manager.auto_reboot = False
    if args.encrypted_backup:
        dm.pref_manager.use_encrypted_backup = True

    dry_run = getattr(args, 'dry_run', False)
    if (getattr(args, 'ios_version', None) or getattr(args, 'model', None)) and not dry_run:
        print('ERROR: --ios-version and --model require --dry-run.', file=sys.stderr)
        return 2
    if getattr(args, 'model', None) and not getattr(args, 'ios_version', None):
        print('ERROR: --model requires --ios-version.', file=sys.stderr)
        return 2
    if dry_run and getattr(args, 'ios_version', None):
        from packaging.version import Version

        from src.devicemanagement.constants import Device
        version = str(Version(args.ios_version))
        device = Device(args.udid or '', False, 'Offline target', version, '', args.model or '', '', '', '')
        dm.devices = [device]
        dm.set_current_device(0)
    else:
        device = ensure_device(dm, settings, args.udid)
    print("Device:", describe_device(device))

    load_core_tweaks()
    load_default_preset(args.preset, dm, preview_only=dry_run)
    _apply_flag_tweaks(args)

    if dry_run:
        from src.cli.output import set_result
        from src.controllers.apply_plan import build_apply_plan, plan_text
        plan = build_apply_plan(dm)
        set_result(plan)
        print(plan_text(plan))
        return 0 if plan['ready'] else 1

    def prompt_password(title, text):
        if args.password:
            return args.password
        raise RuntimeError(
            "Backup password required for an encrypted restore. "
            "Re-run with --password <your iCloud backup password>.")

    if args.continue_anyway:
        def prompt_choice(title, text):
            print(f"[warning] {title}: {text}")
            print("[warning] continuing WITHOUT data protection (--continue-anyway)")
            return "resume"
    else:
        prompt_choice = None

    print("Starting apply...")
    success = dm.apply_changes(update_label=print_status,
                     show_alert=print_alert,
                     prompt_password=prompt_password,
                     prompt_choice=prompt_choice)
    from src.cli.output import set_result
    set_result(dict(applied=success is True, udid=device.udid))
    print('Apply finished.' if success is True else 'Apply failed or stopped.')
    return 0 if success is True else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(func_run=True)
    add_parser(parser)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
