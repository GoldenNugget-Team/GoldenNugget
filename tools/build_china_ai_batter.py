#!/usr/bin/env python3
"""Build ChinaAI.batter - Apple Intelligence eligibility overrides for a
China-SKU (国行) device.

Read the MEASURED FAILURE section at the bottom before changing anything in
here: on iOS 27 the override store cannot be confirmed delivered, because iOS
does not back up a single file row for the eligibilityd container.

Why this is a separate template instead of "the Siri AI switch for China":

  * The override is SKU-agnostic. ``eligibilityd`` applies the durable
    override store *before* it computes the policy, so GREYMATTER(122),
    AMERICIUM(96) and SIRI_MODE(155) are forced to "eligible" no matter what
    the inputs say - including DEVICE_REGION_CODE=CH and ChinaCellular. The
    China sub-policy (GreymatterBlockChina) is bypassed at that layer, the
    same way it is for an EU device. There is no separate China payload.
  * What still blocks a China-SKU device is *not* only a file: Apple decides
    the Settings panel, the model download and the Siri orchestration
    server-side, and the device's own MobileGestalt keys are untouched
    (GoldenNugget has no MobileGestalt support, and a template can only
    replace a whole plist there, which would destroy the device's keys).
    A mainland China Apple Account may therefore still not receive models.
    The template says so instead of pretending otherwise.

Provenance of the payload (nothing here is guessed):

  A. ``files/siri_ai/enable.data`` and ``files/siri_ai/reset.data`` - the
     MIT-licensed Project Linwood archives (mattisklein/project-linwood,
     pinned commit b9438cec65b384974a9c6be6169ec9fa1e64c83a), already
     shipped with GoldenNugget's own Siri AI switch. The build verifies
     their SHA-256 against ``src/tweaks/siri_ai.HASHES`` and refuses to
     build if they do not match.
  B. The delivery path is the one the built-in switch uses:
     ``SysContainerDomain-com.apple.eligibilityd`` /
     ``Library/Caches/NeverRestore/eligibility_overrides.data``, root:root.
     ``split_path_into_domain`` maps the device path in
     ``FileLocation.siriAIOverrides`` to exactly that domain and relative
     path, so the template lands on the same file the app writes.

Safety properties that come for free:

  * ``src/restore/restore.py`` calls ``require_protective_delivery`` on the
    final file list, not on the built-in tweak, so a template that writes
    this domain is refused unless the restore runs as a prepared, unencrypted
    protective backup. An encrypted backup, a skipped protection or a forced
    sparse delivery all fail with the same message as the built-in switch.
  * ``DeviceManager._add_community_files`` refuses a template that replaces
    a file GoldenNugget writes itself, so the built-in Siri AI switch and
    this template cannot both write the override file in one apply.

Deliberately NOT included, and why:

  * Upstream Nugget's legacy AI enabler (commit 8a5966f, "ai enabler"):
    it wrote a forged ``/var/db/eligibilityd/eligibility.plist`` with
    GREYMATTER forced eligible, and the EU enabler rewrote the OSEligibility
    asset ``/var/MobileAsset/AssetsV2/.../Config.plist``. Neither is
    shippable here: the MobileAsset path has no backup domain in
    ``src/restore/path_mapping.py`` (the loader refuses it outright), the
    answer-cache route was reported patched in iOS 26.2+, and the
    historical 37-domain snapshot predates GREYMATTER, so writing it
    replaces the device's real cache with an iOS-17-era one.
  * The CALCIUM entry of that legacy plist. It is the domain that appends
    "(China)" to Hong Kong, Macao and Taiwan names on China SKUs - a
    naming change, not an AI switch, and out of scope for this template.
  * Any MobileGestalt write (region code, generative-model-systems, device
    model). GoldenNugget has no MobileGestalt support, and a template can
    only replace the whole file, which would take the device's own keys
    with it.

The template is built with GoldenNugget-TemplateBuilder's own model and
rules, then validated with GoldenNugget's real loader by
tools/verify_community_batters.py (which globs community-batters/).

MEASURED FAILURE (2026-10-22, iPad16,2 / iOS 27.0 24A5390f / RegionInfo CH/A)
--------------------------------------------------------------------------------
The switch was selected, the apply reported no error and the payload was
injected, yet Settings showed no AI panel. From that device's own backup
(33,608 manifest rows):

  * ``SysContainerDomain-com.apple.eligibilityd`` contributes 5 directory
    rows and ZERO file rows. ``Library/Caches`` is not enumerated at all, so
    ``Library/Caches/NeverRestore/`` never appears in a backup.
  * The same is true for springboard, backboardd, apsd, akd, geod,
    metrickitd, coretelephony and every
    ``SysSharedContainerDomain-systemgroup.*`` cache container - while
    ``SysContainerDomain-com.apple.lsd`` carries 4 file rows and
    ``SystemPreferencesDomain`` carries 9, so the container format itself
    supports files. It is a per-daemon decision by iOS.
  * ``os_eligibility`` (the answer cache under ``/var/db/os_eligibility/``)
    has 0 rows in a full backup, so the answer eligibilityd actually computed
    is not observable through any backup/restore channel on this release.
  * ``com.apple.MobileGestalt`` returns 0 keys over lockdown on this device.

So the override store can neither be read back nor proven delivered, and the
restore agent has never been shown to accept an injected row for a path the
device's own backup agent refuses to enumerate. Keep the switch - it is the
only lever a batter has - but "no AI panel" is the expected outcome, not a
misconfiguration. See files/siri_ai/README.md.
"""
import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.environ.get("GOLDENNUGGET_TEMPLATEBUILDER", os.path.join(REPO, "..", "GoldenNugget-TemplateBuilder"))
OUT_DIR = os.path.join(REPO, "community-batters")

sys.path.insert(0, REPO)
sys.path.insert(0, BUILDER)

from batter_builder import batter as batter_io  # noqa: E402
from batter_builder import rules  # noqa: E402
from batter_builder.model import Template, Tweak, Write  # noqa: E402

from src.tweaks.basic_plist_locations import FileLocation  # noqa: E402
from src.tweaks.siri_ai import HASHES  # noqa: E402

AUTHOR = "Jason"

# The device path the eligibilityd container stores the override store in.
# split_path_into_domain() turns it into
#   domain: SysContainerDomain-com.apple.eligibilityd
#   path:   Library/Caches/NeverRestore/eligibility_overrides.data
OVERRIDE_PATH = FileLocation.siriAIOverrides.value

ENABLE_SOURCE = "eligibility_overrides.enable.data"
RESET_SOURCE = "eligibility_overrides.reset.data"

# The loader refuses descriptions longer than this.
DESCRIPTION_LIMIT = 500

ENABLE_DESCRIPTION = (
    "Forces GREYMATTER, AMERICIUM and SIRI_MODE eligible in eligibilityd "
    "before the policy is computed, bypassing the China-SKU block (region CH) "
    "at the eligibility layer - the Project Linwood archive, same payload as "
    "the built-in Siri AI switch. MEASURED on iPad16,2 / iOS 27.0 CH/A: "
    "applied cleanly but no AI panel appeared, since iOS backs up zero file "
    "rows for this container. "
    "Experimental. Needs an unencrypted protective backup, English (US) Siri "
    "and a reboot. Replaces ALL overrides."
)

RESET_DESCRIPTION = (
    "Writes a valid eligibility override archive with an empty override map: "
    "clears EVERY override on the device, including ones other tools "
    "installed, and cannot restore a previous map. Reboot required. Turn "
    "this switch off when Apple Intelligence (China SKU) is on - two "
    "switches writing the same file are refused - and turn the built-in Siri "
    "AI switch off as well."
)

TEMPLATE_DESCRIPTION = (
    "Apple Intelligence for a China-SKU (国行) device. Delivers the Project "
    "Linwood eligibility override archive - the same payload as the built-in "
    "Siri AI switch - so eligibilityd reports GREYMATTER, AMERICIUM and "
    "SIRI_MODE eligible before it computes the policy, bypassing the "
    "China-SKU block at the eligibility layer. MEASURED 2026-10-22 on iPad16,2 "
    "/ iOS 27.0 CH/A: apply reported no error, no AI panel. Experimental - "
    "see the switch description."
)


def payload(action: str) -> bytes:
    """The bundled override archive, with the app's own hash check."""
    path = os.path.join(REPO, "files", "siri_ai", f"{action}.data")
    with open(path, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != HASHES[action]:
        raise SystemExit(f"files/siri_ai/{action}.data does not match the "
                         f"hash the app checks - refusing to build.")
    return data


def file_tweak(tweak_id: str, label: str, description: str, source: str) -> Tweak:
    return Tweak(
        id=tweak_id,
        label=label,
        description=description,
        default=False,
        # No upper bound: the override store is applied before the policy is
        # computed and is not tied to one minor version, so a 27.x device
        # must not be silently skipped. The template-level min_version still
        # keeps it off anything older than 27.0, and the description carries
        # the "verified on 27.0 only" caveat.
        min_version="27.0",
        writes=[Write("file", OVERRIDE_PATH, source=source, owner=0)],
    )


def build() -> Template:
    for text in (ENABLE_DESCRIPTION, RESET_DESCRIPTION):
        if len(text) > DESCRIPTION_LIMIT:
            raise SystemExit(f"description too long ({len(text)} > "
                             f"{DESCRIPTION_LIMIT})")
    return Template(
        title="Apple Intelligence (China SKU)",
        author=AUTHOR,
        description=TEMPLATE_DESCRIPTION,
        min_version="27.0",
        tags=["china", "apple intelligence", "eligibility"],
        tweaks=[
            file_tweak("AppleIntelligence.CN", "Apple Intelligence (China SKU)",
                       ENABLE_DESCRIPTION, ENABLE_SOURCE),
            file_tweak("ResetEligibilityOverrides", "Reset eligibility overrides",
                       RESET_DESCRIPTION, RESET_SOURCE),
        ],
        entries={
            ENABLE_SOURCE: payload("enable"),
            RESET_SOURCE: payload("reset"),
        },
    )


def main() -> int:
    template = build()
    issues = rules.validate(template)
    errors = rules.errors(issues)
    if errors:
        for issue in errors:
            print(f"ERROR {issue}")
        return 1
    for issue in issues:
        print(f"warn  {issue}")

    ids = [t.id for t in template.tweaks]
    assert len(ids) == len(set(ids)), "duplicate tweak ids"

    out = os.path.join(OUT_DIR, "ChinaAI.batter")
    batter_io.save(template, out)
    print(f"written: {out}  ({len(template.tweaks)} tweaks)")
    for name in sorted(template.entries):
        print(f"  {name} ({len(template.entries[name])} bytes)")
    for t in template.tweaks:
        for w in t.writes:
            print(f"  {t.id:28s} -> {w.path} (source {w.source}, owner {w.owner})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
