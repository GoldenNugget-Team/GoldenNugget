"""``Nugget reset`` — reset tweak sections back to defaults (the GUI's
"Reset Tweaks" flow).

Restores stock values for the selected sections straight to the device.
"""

import argparse
import sys

from src.utils.pages import Page


def add_parser(subp):
    parser = subp.add_parser(
        "reset",
        help="Reset tweak sections to defaults",
        description="Restore stock values for the selected sections "
                    "(uses the same reset + restore path as the GUI).",
    )
    parser.add_argument("--udid", default=None, help="target device UDID")
    parser.add_argument("--status-bar", action="store_true",
                        help="reset the Status Bar section")
    parser.add_argument("--springboard", action="store_true",
                        help="reset the SpringBoard section")
    parser.add_argument("--daemons", action="store_true",
                        help="reset the Daemons section")
    parser.add_argument("--internal", action="store_true",
                        help="reset the Internal Options section")
    parser.add_argument("--community", action="store_true",
                        help="reset what community tweaks from templates wrote")
    parser.add_argument("--no-skip-setup", action="store_true",
                        help="don't mark iOS setup panes complete")
    parser.add_argument("--no-reboot", action="store_true",
                        help="don't auto-reboot after resetting")
    parser.add_argument('--dry-run', action='store_true', help='List reset sections without connecting or resetting')
    parser.set_defaults(func=run)
    return parser


def _resolve_pages(args, dm) -> list:
    from src.utils.pages import get_resettable_pages
    explicit = []
    if args.status_bar:
        explicit.append(Page.StatusBar)
    if args.springboard:
        explicit.append(Page.Springboard)
    if args.daemons:
        explicit.append(Page.Daemons)
    if args.internal:
        explicit.append(Page.InternalOptions)
    if getattr(args, "community", False):
        explicit.append(Page.Templates)
    if explicit:
        return explicit
    pages = get_resettable_pages(dm)
    print(f"Resetting all resettable sections "
          f"({', '.join(p.getPageName() for p in pages)}).")
    return pages


def run(args) -> int:
    from src.cli.common import (
        bootstrap,
        describe_device,
        ensure_device,
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

    from src.cli.output import set_result
    if getattr(args, 'dry_run', False):
        pages = _resolve_pages(args, dm)
        result = dict(dry_run=True, sections=[page.name for page in pages],
                      note='Reset writes stock defaults. Device support and live state have not been checked.')
        set_result(result)
        print(result)
        return 0
    device = ensure_device(dm, settings, args.udid)
    print("Device:", describe_device(device))

    pages = _resolve_pages(args, dm)
    print("Starting reset...")
    success = dm.reset_tweaks(pages, settings,
                    update_label=print_status,
                    show_alert=print_alert)
    set_result(dict(reset=success is True, sections=[page.name for page in pages], udid=device.udid))
    print('Reset finished.' if success is True else 'Reset failed or stopped.')
    return 0 if success is True else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_parser(parser)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
