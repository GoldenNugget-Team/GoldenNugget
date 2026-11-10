# Additional control verification

Base: GoldenNugget `10.0` at `9fbe88d` (2026-11-10).

## Scope

90 additional opt-in plist controls and 153 additional daemon controls. Existing registry definitions remain authoritative. All additions start unapplied; no personal preset or daemon selections are bundled. The restore, pairing, HotLoad implementation and awesomeUI submodule are unchanged.

Research-only placeholders, FeatureFlag writers, deferred Safari AppDomain delivery and the local risky daemon groups are excluded. Descriptions retain the distinction between source evidence, restore delivery and visible effects. No battery improvement is guaranteed.

## Testing

The author confirmed that the additions were device-tested. Device models/builds and per-control measurements were not supplied for this PR; no new physical-device test was run during preparation.

Local offline checks used Python 3.13 on macOS with offscreen Qt:

- `python tools/test_additional_controls.py`: 4 tests passed, exercising every added factory, unapplied defaults, plist serialization, explicit false states, registry uniqueness and added daemon label exclusions.
- Python syntax compilation and Ruff checks on changed files passed.
- Full isolated offline runner: 60/76 suites passed.
- Each of the 16 failures below was reproduced separately on untouched `10.0` at the same commit. No existing failing test was skipped, changed or relaxed in this PR.

This PR remains a draft because the full offline gate is not green. Passing serialization checks does not establish a visible effect on every OS build.

## Inherited offline failures

- `test_afc_media_safety`
- `test_autosave_option`
- `test_cache_placement`
- `test_community_tweaks`
- `test_fast_cache`
- `test_favorites_settings_search`
- `test_feature_artwork`
- `test_hotload_authority`
- `test_hotload_bad_news`
- `test_language_restart`
- `test_performance_regressions`
- `test_posterboard_backup_space`
- `test_posterboard_snapshot`
- `test_protective_filters`
- `test_reset_no_capture`
- `test_siri_ai`
