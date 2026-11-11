"""Read-only CLI apply plan based on the existing preview and local rules."""
import os


def build_apply_plan(manager):
    from src.controllers.apply_preview import (
        capture_preview,
        load_preview,
        preview_rows,
    )
    from src.controllers.hotload import HotLoad
    from src.controllers.tweak_conflicts import current_conflicts
    from src.tweaks.compatibility import compatibility_reasons, version_override_allowed
    from src.tweaks.registry import SPECS_BY_ID
    from src.tweaks.store import selection_store
    from src.tweaks.tweaks import TweakID, tweaks
    tweaks = selection_store(manager, tweaks)
    preview = capture_preview(manager)
    version, model = manager.get_current_device_version(), manager.get_current_device_model()
    context = dict(device_version=version, device_model=model)
    safety = HotLoad(manager.pref_manager.settings)
    hidden = safety.hidden_tweak_names(**context)
    issues, writers = [], []
    if not manager.get_current_device_is_supported_by_fork():
        issues.append(dict(code='unsupported_ios', message='Applying requires iOS 26.2 or newer.'))
    if not model:
        issues.append(dict(code='unknown_model', message='Device model is unknown; model compatibility cannot be verified.'))
    kill = safety.kill_rule(**context)
    if kill:
        issues.append(dict(code='kill_switch', message=kill.get('reason') or 'Application blocked by safety rules.'))
    daemons = tweaks.get(TweakID.Daemons)
    if daemons is not None and TweakID.Daemons.name not in hidden and safety.rule_for(TweakID.Daemons, **context) is None:
        for key in sorted(safety.disabled_daemon_keys(**context)):
            if key not in daemons.never_enable:
                preview['entries']['Daemons/' + key] = dict(section='Daemons', title=key, value=True)
                if key not in preview['forced']:
                    preview['forced'].append(key)
    for tid, tweak in tweaks.items():
        if tid.name in hidden or safety.rule_for(tid, **context) is not None:
            continue
        if tweak.enabled:
            reasons = compatibility_reasons(tid, version, model, allow_untested=version_override_allowed(
                version, manager.pref_manager.settings.value("enable_incompatible_tweaks", False, type=bool)))
            if reasons:
                issues.append(dict(code='incompatible_tweak', tweak=tid.name, reasons=reasons))
            spec = SPECS_BY_ID.get(tid)
            location = getattr(tweak, 'file_location', None)
            if location is not None:
                writers.append(dict(tweak=tid.name, path=location.value,
                                    key=spec.key if spec else None))
        paths = ([item.path for item in tweak.templates] if tid == TweakID.Templates else
                 [item.icon_path for item in tweak.themes] if tid == TweakID.IconThemes else [])
        for path in paths:
            if not os.path.isfile(path):
                issues.append(dict(code='missing_asset', tweak=tid.name, file=os.path.basename(path)))
    conflicts = [dict(first=item.first.name, second=item.second.name,
                      reason=item.description()) for item in current_conflicts(manager)]
    previous = load_preview(manager.get_current_device_udid(), version)
    if not preview['entries'] and not preview['queued']:
        issues.append(dict(code='empty_selection', message='No applicable tweaks or packages are selected.'))
    return dict(schema=1, dry_run=True, device=dict(model=model, ios=version),
                ready=not issues and not conflicts, issues=issues, conflicts=conflicts,
                preview=preview, changes=preview_rows(preview, previous), plist_writers=writers,
                options=dict(backup_cache=manager.pref_manager.use_backup_cache,
                             encrypted_backup=manager.pref_manager.use_encrypted_backup,
                             afc_media=manager.pref_manager.use_afc_media,
                             reboot=manager.pref_manager.auto_reboot,
                             skip_setup=manager.pref_manager.skip_setup),
                note='Selection plan only. No files are generated or restored. Live device state, encryption and free space are not probed; listed plist paths are not a complete restore manifest.')


def plan_text(plan):
    import json
    return json.dumps(plan, ensure_ascii=False, indent=2)
