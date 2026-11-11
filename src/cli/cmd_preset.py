"""``Nugget preset`` — create, load and manage tweak presets."""

import argparse
import sys

from src.cli.output import set_result


def _pm():
    from src.controllers.preset_manager import PresetManager
    return PresetManager()


def _device_meta(udid):
    """Best-effort model/iOS metadata for preset tags (no device required)."""
    try:
        from src.cli.common import bootstrap, make_device_manager
        settings = bootstrap()
        dm = make_device_manager(settings)
        from src.cli.common import list_devices
        list_devices(dm, settings)
        if udid:
            for device in dm.devices:
                if getattr(device, "udid", None) == udid:
                    return getattr(device, "model", "") or "", \
                           getattr(device, "version", "") or ""
        if dm.devices:
            return (getattr(dm.devices[0], "model", "") or "",
                    getattr(dm.devices[0], "version", "") or "")
    except Exception:
        pass
    return "", ""


def add_parser(subp):
    parser = subp.add_parser(
        "preset",
        help="Save / load / manage tweak presets",
        description="Presets snapshot the current tweak state the same way the "
                    "GUI's Settings → Presets page does. They live in the "
                    "GoldenNugget app-data folder as JSON files.",
    )
    sub = parser.add_subparsers(dest="preset_sub", required=True)

    p = sub.add_parser("list", help="List all saved presets")
    p.set_defaults(func=_run_list)

    p = sub.add_parser("show", help="Show a preset's metadata")
    p.add_argument("name")
    p.set_defaults(func=_run_show)

    p = sub.add_parser("save", help="Save the current tweak state as a preset")
    p.add_argument("name")
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="", help="comma-separated tags")
    p.add_argument("--udid", default=None)
    p.set_defaults(func=_run_save)

    p = sub.add_parser("load", help="Load a preset into the tweak state")
    p.add_argument("name")
    p.add_argument("--no-save", action="store_true",
                   help="don't persist the loaded state to AutoSave")
    p.set_defaults(func=_run_load)

    p = sub.add_parser("delete", help="Delete a preset")
    p.add_argument("name")
    p.set_defaults(func=_run_delete)

    p = sub.add_parser("export", help="Export a preset to a shareable JSON file")
    p.add_argument("name")
    p.add_argument("--out", default=None, help="output path (default: <name>.json)")
    p.add_argument("--include", default="", help="comma-separated TweakID names")
    p.add_argument('--portable', action='store_true', help='Embed templates and icons in a .gnpreset archive')
    p.set_defaults(func=_run_export)

    p = sub.add_parser("import", help="Import a preset from a JSON file")
    p.add_argument("path")
    p.add_argument("--name", default=None, help="renamed on import")
    p.set_defaults(func=_run_import)
    return parser


def _run_list(args):
    pm = _pm()
    presets = pm.list_presets_with_metadata()
    set_result({'presets': presets})
    if not presets:
        print("No presets saved.")
        return 0
    print(f"Presets ({len(presets)}):")
    for meta in presets:
        desc = meta.get("description") or ""
        suffix = f" — {desc}" if desc else ""
        print(f"  {meta.get('name', '?')}{suffix}")
    return 0


def _run_show(args):
    pm = _pm()
    meta = pm.get_preset_metadata(args.name)
    if meta is None:
        print(f"ERROR: preset '{args.name}' not found.", file=sys.stderr)
        return 1
    set_result(dict(name=args.name, metadata=meta))
    print(f"name:        {args.name}")
    print(f"description: {meta.get('description', '')}")
    print(f"device:      {meta.get('device_model', 'Unknown')} "
          f"iOS {meta.get('ios_version', 'Unknown')}")
    print(f"tags:        {', '.join(meta.get('tags', []))}")
    print(f"created:     {meta.get('created_at', 0)}")
    print(f"updated:     {meta.get('updated_at', 0)}")
    print(f"version:     {meta.get('version', 1)}")
    return 0


def _run_save(args):
    from src.cli.common import autosave_preset, load_core_tweaks, seed_from_autosave
    load_core_tweaks()
    seed_from_autosave()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    model, version = _device_meta(args.udid)
    pm = _pm()
    ok = pm.save_preset(args.name, args.description, tags=tags,
                        device_model=model, ios_version=version)
    if not ok:
        print("ERROR: nothing to save (no tweaks serialized).", file=sys.stderr)
        return 1
    if args.name != "AutoSave":
        autosave_preset()
    print(f"Saved preset '{args.name}'.")
    set_result(dict(name=args.name, saved=True))
    return 0


def _run_load(args):
    from src.cli.common import autosave_preset, bootstrap, load_core_tweaks
    from src.controllers.hotload import HotLoad
    settings = bootstrap()
    load_core_tweaks()
    pm = _pm()

    hidden = pm.preset_hidden_feature_names(args.name, HotLoad(settings))
    if hidden:
        print("WARNING: this preset contains tweaks of features currently "
              f"hidden by safety rules: {', '.join(sorted(hidden))}. "
              "Those tweaks will NOT be loaded.")

    if not pm.load_preset(args.name):
        print(f"ERROR: preset '{args.name}' not found.", file=sys.stderr)
        return 1
    print(f"Loaded preset '{args.name}'.")
    if not getattr(args, "no_save", False):
        autosave_preset()
    set_result(dict(name=args.name, loaded=True, skipped_features=sorted(hidden)))
    return 0


def _run_delete(args):
    pm = _pm()
    if not pm.delete_preset(args.name):
        print(f"ERROR: preset '{args.name}' not found.", file=sys.stderr)
        return 1
    print(f"Deleted preset '{args.name}'.")
    set_result(dict(name=args.name, deleted=True))
    return 0


def _run_export(args):
    pm = _pm()
    portable = getattr(args, 'portable', False)
    out = args.out or f"{args.name}.{'gnpreset' if portable else 'json'}"
    include = [s.strip() for s in args.include.split(",") if s.strip()] or None
    if not pm.export_preset(args.name, out, include=include, portable=portable):
        print(f"ERROR: failed to export preset '{args.name}': {pm.last_transfer_error}", file=sys.stderr)
        return 1
    print(f"Exported '{args.name}' -> {out}")
    set_result(dict(name=args.name, path=out, portable=portable or out.lower().endswith('.gnpreset')))
    return 0


def _run_import(args):
    pm = _pm()
    ok, name = pm.import_preset(args.path, new_name=args.name)
    if not ok:
        print(f"ERROR: import failed: {name}", file=sys.stderr)
        return 1
    print(f"Imported preset '{name}'.")
    set_result(dict(name=name, imported=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="sub", required=True)
    add_parser(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
