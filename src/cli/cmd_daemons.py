"""``Nugget daemons`` — disable / enable launchd daemons (the "Daemons" page).

Uses the same ``Daemon`` enum + ``INTERFACE_KEYS`` filtering the GUI uses, so
only interface-visible keys ever reach the disabled-daemons plist.
"""

import argparse
import sys

from src.tweaks import tweak_loader
from src.tweaks.daemons_tweak import RECOMMENDED_ANALYTICS, Daemon
from src.tweaks.tweaks import TweakID, tweaks


def _daemons():
    tweak_loader.load_daemons()
    return tweaks[TweakID.Daemons]


def _resolve_daemons(names):
    members = {d.name: d for d in Daemon}
    out = []
    for name in names:
        member = members.get(name) or members.get(name.upper())
        if member is not None:
            out.append(member)
            continue
        # raw launchd key
        if any(name in d.value for d in Daemon):
            out.append(name)
            continue
        print(f"ERROR: unknown daemon '{name}' (use a Daemon name from "
              f"'Nugget daemons list' or a launchd key).", file=sys.stderr)
        raise SystemExit(1)
    return out


def _set_keys(daemon, value):
    keys = daemon.value if isinstance(daemon, Daemon) else [daemon]
    _daemons().set_multiple_values(keys, value=value)
    return keys


def _save_if(args):
    from src.cli.common import autosave_preset
    if not getattr(args, "no_save", False) and not autosave_preset():
        print("note: nothing serializable, AutoSave not written.")
    _result()


def _result():
    from src.cli.output import set_result
    dl = _daemons()
    set_result(dict(enabled=dl.enabled, values=dl.value,
                    daemons=[dict(name=d.name, keys=d.value,
                                  disabled=any((dl.value or {}).get(k, False) for k in d.value)) for d in Daemon]))


def add_parser(subp):
    parser = subp.add_parser(
        "daemons",
        help="Disable or enable launchd daemons",
        description="The Daemons feature: disable system daemons (maps to the "
                    "disabled-daemons plist). 'list' shows every togglable "
                    "daemon; disable/enable accept a Daemon name or launchd key.",
    )
    sub = parser.add_subparsers(dest="daemons_sub", required=True)

    p = sub.add_parser("list", help="List all togglable daemons")
    p.set_defaults(func=_run_list)

    p = sub.add_parser("show", help="Show the current daemons plist state")
    p.set_defaults(func=_run_show)

    p = sub.add_parser("disable", help="Disable (add) daemons")
    p.add_argument("names", nargs="+", metavar="DAEMON",
                   help="Daemon name or launchd key")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=_run_disable)

    p = sub.add_parser("enable", help="Re-enable (remove) daemons")
    p.add_argument("names", nargs="+", metavar="DAEMON")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=_run_enable)

    p = sub.add_parser("recommended", help="One-tap analytics/telemetry set")
    p.add_argument("--enable", action="store_true",
                   help="re-enable the recommended set (default: disable it)")
    p.add_argument("--no-save", action="store_true")
    p.set_defaults(func=_run_recommended)

    for state in ("on", "off"):
        p = sub.add_parser(f"master-{state}", help=f"Set the Daemons master {state}")
        p.add_argument("--no-save", action="store_true")
        p.set_defaults(func=_run_master, state=(state == "on"))

    return parser


def _run_list(args):
    from src.cli.common import seed_from_autosave
    _daemons()
    seed_from_autosave()
    dl = tweaks[TweakID.Daemons]
    value = dl.value or {}
    _result()
    print("Daemons (master " + ("ON" if dl.enabled else "off") + "):")
    for d in Daemon:
        enabled = any(value.get(k, False) for k in d.value)
        flags = " [disabled]" if enabled else ""
        print(f"  {d.name:<32} {','.join(d.value)}{flags}")
    return 0


def _run_show(args):
    from src.cli.common import seed_from_autosave
    dl = _daemons()
    seed_from_autosave()
    print("master enabled:", dl.enabled)
    _result()
    value = dl.value or {}
    if not value:
        print("(no daemons disabled)")
        return 0
    for key in sorted(value):
        print(f"  {key}: {value[key]}")
    return 0


def _run_disable(args):
    from src.cli.common import load_core_tweaks, seed_from_autosave
    load_core_tweaks()
    seed_from_autosave()
    dl = _daemons()
    dl.set_enabled(True)  # master switch, like the GUI when toggling a daemon
    for name in args.names:
        for d in _resolve_daemons([name]):
            keys = _set_keys(d, True)
            print(f"disabled {name} -> {', '.join(keys)}")
    _save_if(args)
    return 0


def _run_enable(args):
    from src.cli.common import load_core_tweaks, seed_from_autosave
    load_core_tweaks()
    seed_from_autosave()
    for name in args.names:
        keys = _set_keys(_resolve_daemons([name])[0], False)
        print(f"enabled {name} -> {', '.join(keys)}")
    _save_if(args)
    return 0


def _run_recommended(args):
    from src.cli.common import load_core_tweaks, seed_from_autosave
    load_core_tweaks()
    seed_from_autosave()
    dl = _daemons()
    dl.set_enabled(True)
    for d in RECOMMENDED_ANALYTICS:
        _set_keys(d, not args.enable)
    print(("disabled" if not args.enable else "enabled")
          + f" {len(RECOMMENDED_ANALYTICS)} daemons (recommended set)")
    _save_if(args)
    return 0


def _run_master(args):
    from src.cli.common import seed_from_autosave
    load_daemons_for_cli()
    seed_from_autosave()
    _daemons().set_enabled(args.state)
    print("daemons master:", "ON" if args.state else "off")
    _save_if(args)
    return 0


def load_daemons_for_cli():
    from src.cli.common import load_core_tweaks
    load_core_tweaks()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="sub", required=True)
    add_parser(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
