# GoldenNugget Desktop 9.7.7

## General

- An iOS 27 apply no longer starts unless the selective backup finished and
  was verified, and the previous backup is kept until the restore finishes
  (data-loss guard).

## Fixes

- Live phase-5 media push passes `include_historical=False`, dead restore
  phase helpers are gone, and hotload rules are written atomically
  (`.part` + replace) so a failed write cannot lose them.
- The backup disk-space preflight no longer demands the device's whole used
  capacity; the static minimum is enforced instead.
- Clear-file ("nullify") tweak payloads are delivered as-is, without a backup
  baseline merge, so resetting a file that never entered a backup works.
- Unreadable or missing managed-preference baselines (ManagedPreferencesDomain)
  degrade to whole-payload delivery instead of aborting the apply (issue #85,
  e.g. upgrading iOS 26.6 → 27.x).
- The Phase 3 pre-start "Find My" wait is bounded to one 15-minute window
  across all retry attempts, so a wedged device can no longer hang the
  restore forever.
- PosterBoard wallpapers: the solid-color image is injected into the colored
  layer instead of the last self-closing CALayer (issue #90).
- Status bar: an enabled blank-carrier override now builds a hiding cellular
  entry instead of collapsing into the reset record (issue #83); the GUI
  shows "Hidden" for it.
- Tendie archives: members are re-validated right before `extractall`,
  closing the TOCTOU window against the import-time safety check.
- Crash handling: dialogs are only built on the GUI thread — off-thread
  crashes log and post an event instead of creating windows (macOS abort).
  A broken presenter can no longer cause a crash loop, and restarting after
  a crash is Windows-safe (`os.execv` mangled argv there).
- The stale progress card is hidden when a data restore completes.
- Fix repository pointers
