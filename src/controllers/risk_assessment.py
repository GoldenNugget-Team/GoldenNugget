"""Pre-apply risk assessment: one Low / Medium / High verdict for a selection.

The verdict combines what the app already knows about a selection into one
place: per-tweak risk profiles (the table below), device compatibility,
warn-only HotLoad ``risk`` rules published for specific iOS versions, and
facts about the apply itself (battery, free space, how much changes at once).

It works on preset-shaped data (``{"TweakName": {"enabled": ..., "value": ...}}``),
so the same assessment covers the current selection, a saved preset and a
setup someone shared as a code. Nothing here talks to a device.

The verdict is advice, not a guarantee: the table lists what is known to go
wrong, and an unlisted tweak is "low" only in the sense that nothing is known.
"""
from dataclasses import dataclass, field
from enum import IntEnum

from src.utils.i18n import QCoreApplication, QT_TRANSLATE_NOOP

from src.tweaks.registry import SPECS_BY_ID, Section
from src.tweaks.tweak_names import TweakID

CONTEXT = "RiskAssessment"
MANY_CHANGES = 20


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @classmethod
    def parse(cls, value, default=None):
        try:
            return cls[str(value).strip().upper()]
        except (KeyError, AttributeError):
            return default

    def label(self) -> str:
        return QCoreApplication.translate(CONTEXT, _LEVEL_LABELS[self])


_LEVEL_LABELS = {
    RiskLevel.LOW: QT_TRANSLATE_NOOP("RiskAssessment", "Low risk"),
    RiskLevel.MEDIUM: QT_TRANSLATE_NOOP("RiskAssessment", "Medium risk"),
    RiskLevel.HIGH: QT_TRANSLATE_NOOP("RiskAssessment", "High risk"),
}

# Tweak name -> (level, why). Only what can actually hurt belongs here.
TWEAK_RISKS = {
    "SiriAI": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Replaces all eligibility overrides. Only verified on iPhone 16 Pro, iOS 27.0 build 24A437; Siri requires English (US).")),
    "ResetSiriAIOverrides": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Clears all eligibility overrides, including those installed by other tools. Previous overrides cannot be recovered by this reset.")),
    "WatchOSCompatibility": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Rewrites Apple Watch pairing data. If the watch stops pairing, reset this tweak.")),
    "RTL": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Forces the layout direction in every app, which can make some screens hard to use.")),
    "LTR": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Forces the layout direction in every app, which can make some screens hard to use.")),
    "ClearScreenTimeAgentPlist": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Clears a Screen Time settings file. Resetting the tweak does not bring its old contents back.")),
    "IgnoreSolariumHardwareCheck": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Turns on effects Apple did not enable for this hardware; expect lag or app crashes.")),
    "SBHideLowPowerAlerts": (RiskLevel.LOW, QT_TRANSLATE_NOOP(
        "RiskAssessment", "You will not be warned when the battery is almost empty.")),
    "SBDontDimOrLockOnAC": (RiskLevel.LOW, QT_TRANSLATE_NOOP(
        "RiskAssessment", "The screen stays on while charging, which wears an OLED display faster.")),
}

# Daemon group name (src.tweaks.daemons_tweak.Daemon) -> (level, why).
DAEMON_RISKS = {
    "thermalmonitord": (RiskLevel.HIGH, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Turns off thermal monitoring: the iPhone can overheat or shut down under load.")),
    "Location": (RiskLevel.MEDIUM, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Turns off location services: Find My, Maps and emergency location stop working.")),
    "OTA": (RiskLevel.LOW, QT_TRANSLATE_NOOP(
        "RiskAssessment", "Blocks iOS updates, including security fixes.")),
}


@dataclass(frozen=True)
class RiskFactor:
    level: RiskLevel
    text: str


@dataclass
class RiskReport:
    factors: list = field(default_factory=list)

    @property
    def level(self) -> RiskLevel:
        return max((factor.level for factor in self.factors), default=RiskLevel.LOW)

    def sorted_factors(self) -> list:
        """Most serious first; equal levels keep their discovery order."""
        return sorted(self.factors, key=lambda factor: -factor.level)


def _tr(text):
    return QCoreApplication.translate(CONTEXT, text)


def _title(name):
    try:
        spec = SPECS_BY_ID.get(TweakID[name])
    except KeyError:
        spec = None
    if name == "Daemons":
        return QCoreApplication.translate("Nugget", "Daemons")
    if name == "StatusBar":
        return QCoreApplication.translate("Nugget", "Status Bar")
    return QCoreApplication.translate("Nugget", spec.title) if spec else name


def is_selected(name, entry) -> bool:
    """Whether a preset entry would change anything when applied."""
    if not isinstance(entry, dict):
        return False
    if entry.get("templates") or entry.get("themes"):
        return True
    return entry.get("enabled") is True


def disabled_daemon_keys(entry) -> set:
    if not is_selected("Daemons", entry) or not isinstance(entry.get("value"), dict):
        return set()
    return {key for key, off in entry["value"].items() if off is True}


def _daemon_factors(keys):
    from src.tweaks.daemons_tweak import Daemon
    factors = []
    for member in Daemon:
        risk = DAEMON_RISKS.get(member.name)
        if risk and keys & set(member.value):
            factors.append(RiskFactor(risk[0], f"{_title('Daemons')} — {member.name}: {_tr(risk[1])}"))
    return factors


def assess(tweaks_data, device_version="", device_model="", *, hotload=None, extra=()):
    """Assess preset-shaped ``tweaks_data``; ``extra`` adds apply-time factors."""
    from src.tweaks.compatibility import device_compatibility_reasons as compatibility_reasons
    report = RiskReport()
    selected = {name: entry for name, entry in (tweaks_data or {}).items()
                if is_selected(name, entry)}

    incompatible = []
    experimental = []
    for name, entry in selected.items():
        risk = TWEAK_RISKS.get(name)
        if risk:
            report.factors.append(RiskFactor(risk[0], f"{_title(name)}: {_tr(risk[1])}"))
        try:
            tid = TweakID[name]
        except KeyError:
            continue
        spec = SPECS_BY_ID.get(tid)
        if device_version and compatibility_reasons(tid, device_version, device_model):
            incompatible.append(_title(name))
        elif spec is not None and not risk and spec.section in (Section.LIQUID_GLASS, Section.INTERNAL):
            experimental.append(_title(name))

    report.factors.extend(_daemon_factors(disabled_daemon_keys(selected.get("Daemons"))))
    if incompatible:
        report.factors.append(RiskFactor(RiskLevel.HIGH, _tr(
            "Not made for this iPhone or iOS version: {0}.").format(", ".join(incompatible))))

    if hotload is not None:
        for rule in hotload.risk_notes(device_version or None, device_model or None):
            name = str(rule.get("tweak"))
            if name not in selected:
                continue
            level = RiskLevel.parse(rule.get("level"), RiskLevel.MEDIUM)
            reason = str(rule.get("reason") or "") or _tr(
                "Reported as problematic on this iOS version.")
            report.factors.append(RiskFactor(level, f"{_title(name)}: {reason}"))

    if experimental:
        report.factors.append(RiskFactor(RiskLevel.LOW, _tr(
            "{0} debug or experimental option(s); they can cause visual glitches.").format(len(experimental))))
    if len(selected) > MANY_CHANGES:
        report.factors.append(RiskFactor(RiskLevel.MEDIUM, _tr(
            "{0} tweaks at once: if something breaks, the cause is hard to find. "
            "Consider applying in smaller batches.").format(len(selected))))
    report.factors.extend(extra)
    return report


def apply_factors(*, conflicts=0, battery=None, storage_low=False, first_apply=False,
                  wallpapers=0):
    """Factors that only exist for an apply on a connected device."""
    factors = []
    if battery is not None and battery.get("percent") is not None \
            and not battery.get("charging") and battery["percent"] <= 20:
        factors.append(RiskFactor(RiskLevel.HIGH, _tr(
            "Battery at {0}% and not charging: if the iPhone switches off mid-restore, the apply fails.").format(
                int(battery["percent"]))))
    if storage_low:
        factors.append(RiskFactor(RiskLevel.HIGH, _tr(
            "Little free space on the iPhone: the restore may fail partway.")))
    if conflicts:
        factors.append(RiskFactor(RiskLevel.MEDIUM, _tr(
            "{0} conflict(s) between selected tweaks.").format(conflicts)))
    if wallpapers:
        factors.append(RiskFactor(RiskLevel.LOW, _tr(
            "{0} wallpaper package(s): a broken one can leave a blank Lock Screen until it is removed.").format(wallpapers)))
    if first_apply:
        factors.append(RiskFactor(RiskLevel.LOW, _tr(
            "First apply on this iPhone with this iOS version.")))
    return factors


def community_factors(active):
    """Factors for community tweaks from .batter templates.

    ``active`` is community_tweaks.active(): (template name, tweak, writes)."""
    from src.tweaks.posterboard.community_tweaks import RISK_HIGH, RISK_MEDIUM, write_risk
    factors, low = [], 0
    for name, tweak, writes in active:
        label = f"{name} — {tweak.label}"
        high = sorted({write.path for write in writes if write_risk(write) == RISK_HIGH})
        whole = sorted({write.path for write in writes if write_risk(write) == RISK_MEDIUM})
        if high:
            factors.append(RiskFactor(RiskLevel.HIGH, _tr(
                "{0}: writes system files ({1}). A mistake there can stop the iPhone from starting "
                "or pairing.").format(label, ", ".join(high))))
        if whole:
            factors.append(RiskFactor(RiskLevel.MEDIUM, _tr(
                "{0}: replaces {1} as a whole; whatever the iPhone kept in it is lost and a reset "
                "cannot bring it back.").format(label, ", ".join(whole))))
        if not high and not whole:
            low += 1
    if low:
        factors.append(RiskFactor(RiskLevel.LOW, _tr(
            "{0} community tweak(s) from templates; GoldenNugget does not know what their keys do.").format(low)))
    return factors
