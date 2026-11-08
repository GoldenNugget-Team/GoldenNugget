"""``Nugget hotload`` — inspect / refresh the remote safety rules.

HotLoad fetches safety rules from the remote JSON and uses them to warn on or
block dangerous/broken tweaks. These commands inspect and update that cache.
"""

import argparse
import sys

from src.cli.output import set_result
from src.controllers.hotload import FEATURE_TWEAKS, RULES_URL, _rules_path


def _settings():
    from src.cli.common import bootstrap
    return bootstrap()


def _hotload(settings):
    from src.controllers.hotload import HotLoad
    return HotLoad(settings)


def _connected_device(dm, udid=None):
    from src.cli.common import ensure_device
    try:
        return ensure_device(dm, dm.pref_manager.settings, udid)
    except SystemExit:
        return None


def add_parser(subp):
    parser = subp.add_parser(
        "hotload",
        help="Inspect GoldenNugget safety rules",
        description="Report the local HotLoad rules cache (kill switch, flagged "
                    "tweaks, hidden features, forced daemons) or refresh it from "
                    "the remote rules JSON.",
    )
    sub = parser.add_subparsers(dest="hotload_sub", required=True)

    p = sub.add_parser("status", help="Show rules + what applies to this device")
    p.add_argument('--udid', default=None, help='Target device UDID')
    p.set_defaults(func=_run_status)

    p = sub.add_parser("refresh", help="Fetch fresh rules from the remote")
    p.add_argument("--url", default=RULES_URL, help="rules JSON URL")
    p.set_defaults(func=_run_refresh)

    p = sub.add_parser("enable", help="Turn the safety-rules kill switch ON")
    p.set_defaults(func=_run_enable)

    p = sub.add_parser("disable", help="Turn the safety-rules kill switch OFF")
    p.set_defaults(func=_run_disable)
    return parser


def _rules_summary(hotload) -> dict:
    rules = getattr(hotload, "_rules", {}) or {}
    return {
        "version": rules.get("version", 0),
        "count": len(rules.get("rules", [])),
        "fetched_at": rules.get("_fetched_at", None),
    }


def _run_status(args):
    settings = _settings()
    hotload = _hotload(settings)
    summary = _rules_summary(hotload)
    result = dict(enabled=hotload.is_enabled(), **summary, device=None,
                  flagged=[], hidden_features=[], forced_daemons={})
    set_result(result)
    print("HotLoad kill switch:", "ON" if hotload.is_enabled() else "OFF (rules ignored)")
    print(f"rules version:  {summary['version']}")
    print(f"rules count:    {summary['count']}")
    if summary["fetched_at"]:
        import datetime
        print("fetched at:    " + datetime.datetime.fromtimestamp(
            summary["fetched_at"]).isoformat())
    print("rules file:     " + _rules_path())

    from src.cli.common import make_device_manager
    dm = make_device_manager(settings)
    device = _connected_device(dm, getattr(args, 'udid', None))
    if not summary["count"]:
        if not hotload.is_enabled():
            print("(kill switch is off — no rules are applied)")
        return 0
    if device is None:
        print("\n(no device connected — skipping device-scoped rules)")
        return 0

    version = getattr(device, "version", "") or ""
    model = getattr(device, "model", "") or ""
    result['device'] = dict(model=model, ios=version)
    print(f"\ndevice: {getattr(device, 'name', '?')} iOS {version} ({model})")

    names = set()
    for members in FEATURE_TWEAKS.values():
        names.update(members)
    flagged = []
    for name in sorted(names):
        rule = hotload.rule_for(name, device_version=version, device_model=model)
        if rule is not None:
            flagged.append((name, rule.get("reason") or rule.get("action") or "flagged"))
    if flagged:
        print("\nflagged tweaks for this device:")
        for name, reason in flagged:
            print(f"  {name}: {reason}")
    else:
        print("\nno tweaks flagged for this device.")

    hidden = hotload.hidden_features(device_version=version, device_model=model)
    result['flagged'] = [dict(tweak=name, reason=reason) for name, reason in flagged]
    result['hidden_features'] = sorted(hidden)
    print("\nhidden features: " + (", ".join(sorted(hidden)) or "none"))
    forced = hotload.disabled_daemons(device_version=version, device_model=model)
    result['forced_daemons'] = forced
    if forced:
        print("\nforce-disabled daemons:")
        for name, reason in sorted(forced.items()):
            print(f"  {name}: {reason}")
    else:
        print("force-disabled daemons: none")
    return 0


def _run_refresh(args):
    settings = _settings()
    hotload = _hotload(settings)
    if not hotload.is_enabled():
        print("Kill switch is OFF — rules are ignored; enabling fetch anyway.")
    ok = hotload.update(args.url)
    if ok:
        summary = _rules_summary(hotload)
        set_result(dict(refreshed=True, **summary))
        print(f"Rules refreshed: version {summary['version']}, "
              f"{summary['count']} rules.")
        return 0
    print("ERROR: failed to fetch rules (kept the local copy).", file=sys.stderr)
    return 1


def _run_enable(args):
    settings = _settings()
    hotload = _hotload(settings)
    hotload.set_enabled(True)
    set_result(dict(enabled=True))
    print("HotLoad kill switch: ON (safety rules now apply).")
    return 0


def _run_disable(args):
    settings = _settings()
    hotload = _hotload(settings)
    hotload.set_enabled(False)
    set_result(dict(enabled=False))
    print("HotLoad kill switch: OFF (all safety rules ignored).")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="sub", required=True)
    add_parser(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
