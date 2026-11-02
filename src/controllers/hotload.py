"""HotLoad: fetch safety rules (dangerous/broken tweaks) from a remote JSON.

The remote JSON lists tweaks that are currently dangerous or broken, scoped to
specific iOS versions / device types. GoldenNugget caches a local copy in the
settings folder, checks for updates on every launch, and warns/blocks the user
from enabling flagged tweaks.

A kill switch in GoldenNugget settings turns the whole system off. When off,
fetches are skipped and no rules are applied.
"""

import json
import os
import ssl
import time
from typing import Optional

import urllib.request

from src.utils.i18n import QCoreApplication
from src.utils.paths import app_data_dir, brand_dir

from src.version import App_Version as _APP_VERSION
from src.tweaks.registry import SPECS_BY_SECTION, SECTION_FEATURES

RULES_URL = ("https://raw.githubusercontent.com/GoldenNugget-Team/"
             "GoldenNugget/main/hotload_rules.json")
RULES_FILENAME = "hotload_rules.json"
KILL_SWITCH_KEY = "hotload_enabled"

# A rule with action == KILL_ACTION tells GoldenNugget to fully shut down on
# the matching iOS versions / device types ("remote kill switch").
KILL_ACTION = "kill_app"

# Require an update before the matching app/device setup can be used again.
BAD_NEWS_ACTION = "badNews"

# A rule with action == HIDE_ACTION hides a whole feature (page) — its tweaks
# disappear from the UI, its Sidebar button and iOS home card are hidden, and
# presets refuse to load it. Scoped to iOS versions / device types like the
# other rules.
HIDE_ACTION = "hide_feature"

# A rule with action == DISABLE_DAEMON_ACTION force-disables specific daemons
# (field "daemons": a list of Daemon enum names or launchd keys) on matching
# setups: the daemons are always added to the disabled-daemons plist at apply
# time regardless of the UI toggles, their switches are locked ON in the page,
# and presets cannot turn them back on (the apply pass re-forces them).
DISABLE_DAEMON_ACTION = "disable_daemon"

# A rule with action == RISK_ACTION never blocks anything: it attaches a
# warning (fields "tweak", "level": "low"|"medium"|"high", "reason") to the
# pre-apply risk assessment on matching setups, e.g. "reported to cause a
# respring loop on iOS 27.0.1". See src/controllers/risk_assessment.py.
RISK_ACTION = "risk"

# Feature (page) name -> the tweak names that belong to it. A "hide_feature"
# rule names one of these keys; the UI and the apply/preset paths use this map
# to resolve which tweaks / pages to hide.
#
# Registry-backed features are derived from SPECS_BY_SECTION (a tweak belongs
# to its section's feature automatically). Only the non-registry features and
# a handful of pre-registry members stay explicit here.
FEATURE_TWEAKS = {
    feature: [spec.id.name for spec in specs]
    for section, feature in SECTION_FEATURES.items()
    for specs in [SPECS_BY_SECTION[section]]
}
FEATURE_TWEAKS.update({
    "Liquid Glass": FEATURE_TWEAKS["Liquid Glass"] + ["DisableSolarium"],
    "Internal": FEATURE_TWEAKS["Internal"] + ["MetalForceHudEnabled"],
    "PosterBoard": ["PosterBoard"],
    "Daemons": ["Daemons", "ClearScreenTimeAgentPlist"],
    "Status Bar": ["StatusBar"],
    "Templates": ["Templates"],
})


def _settings_dir() -> str:
    base = str(brand_dir(app_data_dir()))
    os.makedirs(base, exist_ok=True)
    return base


def _rules_path() -> str:
    return os.path.join(_settings_dir(), RULES_FILENAME)


class HotLoad:
    def __init__(self, settings=None):
        self.settings = settings
        self._rules = {"version": 0, "rules": []}
        self._load_local()

    # --- storage ---------------------------------------------------------
    def _load_local(self):
        try:
            with open(_rules_path(), "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed, dict) and "rules" in parsed:
                self._rules = parsed
        except Exception:
            self._rules = {"version": 0, "rules": []}

    def is_enabled(self) -> bool:
        if self.settings is None:
            return True
        try:
            return bool(self.settings.value(KILL_SWITCH_KEY, True, type=bool))
        except Exception:
            return True

    def set_enabled(self, enabled: bool):
        if self.settings is None:
            return
        self.settings.setValue(KILL_SWITCH_KEY, bool(enabled))
        try:
            self.settings.sync()
        except Exception:
            pass

    # --- fetching --------------------------------------------------------
    def update(self, url: Optional[str] = None) -> bool:
        """Fetch fresh rules and cache them in the settings folder. On any
        failure the existing local copy is kept (rules always load locally).

        Returns True when a rule set was fetched successfully, False otherwise.
        """
        if not self.is_enabled():
            return False
        url = url or RULES_URL
        try:
            import certifi
            # Some Python installs (notably on macOS) have no system CA
            # bundle configured. Add bundled roots while retaining local CAs.
            context = ssl.create_default_context()
            context.load_verify_locations(cafile=certifi.where())
            req = urllib.request.Request(url, headers={"User-Agent": "GoldenNugget"})
            with urllib.request.urlopen(req, timeout=15, context=context) as resp:
                data = resp.read()
            parsed = json.loads(data.decode("utf-8"))
            if not isinstance(parsed, dict) or "rules" not in parsed:
                return False
            parsed["_fetched_at"] = int(time.time())
            path = _rules_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=2)
            self._rules = parsed
            return True
        except Exception as e:
            print(f"[HotLoad] update failed: {e}")
            return False

    # --- matching --------------------------------------------------------
    def rule_for(self, tweak_id, device_version=None, device_model=None,
                 app_version=None) -> Optional[dict]:
        """Return the first applicable rule for a tweak (by its TweakID name),
        or None when it is not flagged for this device/iOS/app. The kill switch
        being off returns None for everything."""
        if not self.is_enabled():
            return None
        tweak_name = getattr(tweak_id, "name", str(tweak_id))
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("tweak") != tweak_name or rule.get("action") in (RISK_ACTION, BAD_NEWS_ACTION):
                    continue
                if not self._rule_applicable(rule, device_version, device_model, app_version):
                    continue
                return rule
            except Exception:
                continue
        return None

    def kill_rule(self, device_version=None, device_model=None,
                  app_version=None) -> Optional[dict]:
        """Return the first applicable rule that fully disables GoldenNugget
        on this device/iOS/app (action == "kill_app"), or None.

        This is the remote "kill switch": a matching rule means the app should
        not initialize (or, if already running, should shut down like a crash).
        """
        if not self.is_enabled():
            return None
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("action") != KILL_ACTION:
                    continue
                if not self._rule_applicable(rule, device_version, device_model, app_version):
                    continue
                return rule
            except Exception:
                continue
        return None

    def bad_news_rule(self, device_version=None, device_model=None,
                      app_version=None) -> Optional[dict]:
        """First matching mandatory-update rule, respecting the HotLoad switch."""
        if not self.is_enabled():
            return None
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("action") == BAD_NEWS_ACTION and self._rule_applicable(
                        rule, device_version, device_model, app_version):
                    return rule
            except Exception:
                continue
        return None

    def risk_notes(self, device_version=None, device_model=None,
                   app_version=None) -> list:
        """Warn-only "risk" rules that match this setup, in file order."""
        if not self.is_enabled():
            return []
        notes = []
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("action") != RISK_ACTION or not rule.get("tweak"):
                    continue
                if self._rule_applicable(rule, device_version, device_model, app_version):
                    notes.append(rule)
            except Exception:
                continue
        return notes

    def feature_for(self, tweak_id) -> Optional[str]:
        """Return the feature (page) name a tweak belongs to, or None."""
        name = getattr(tweak_id, "name", str(tweak_id))
        for feature, members in FEATURE_TWEAKS.items():
            if name in members:
                return feature
        return None

    def hidden_features(self, device_version=None, device_model=None,
                        app_version=None) -> set:
        """Set of feature (page) names hidden by "hide_feature" rules for this
        setup. These features are removed from the UI entirely and their tweaks
        never apply — the whole point is to keep broken/dangerous features out
        of sight so nobody can enable them accidentally."""
        return set(self.hidden_feature_reasons(device_version, device_model, app_version))

    def hidden_feature_reasons(self, device_version=None, device_model=None,
                               app_version=None) -> dict:
        """Matching hidden pages and their reasons, for the compatibility UI."""
        hidden = {}
        if not self.is_enabled():
            return hidden
        if device_version is not None and self._compare(str(device_version), "26.6.1") == 0:
            hidden["Daemons"] = (
                "Daemon changes are blocked on iOS 26.6.1 because a reported "
                "configuration caused the device to freeze at the passcode screen."
            )
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("action") != HIDE_ACTION:
                    continue
                if not self._rule_applicable(rule, device_version, device_model, app_version):
                    continue
                feature = rule.get("feature")
                if feature and feature in FEATURE_TWEAKS:
                    hidden.setdefault(feature, rule.get("reason") or "")
            except Exception:
                continue
        return hidden

    def hidden_tweak_names(self, device_version=None, device_model=None,
                           app_version=None) -> set:
        """Set of every tweak name that belongs to a currently-hidden feature."""
        names = set()
        hidden = self.hidden_features(device_version, device_model, app_version)
        for feature in hidden:
            names.update(FEATURE_TWEAKS[feature])
        return names

    def disabled_daemons(self, device_version=None, device_model=None,
                         app_version=None) -> dict:
        """Daemons force-disabled by "disable_daemon" rules for this setup,
        as {daemon name-or-key: reason}. Empty when the kill switch is off or
        no rule matches. The first matching rule per daemon wins."""
        if not self.is_enabled():
            return {}
        forced = {}
        for rule in self._rules.get("rules", []):
            try:
                if rule.get("action") != DISABLE_DAEMON_ACTION:
                    continue
                if not self._rule_applicable(rule, device_version, device_model, app_version):
                    continue
                reason = rule.get("reason")
                for item in rule.get("daemons") or []:
                    name = str(item).strip()
                    if not name:
                        continue
                    forced.setdefault(name, reason)
            except Exception:
                continue
        return forced

    def disabled_daemon_keys(self, device_version=None, device_model=None,
                             app_version=None) -> set:
        """Resolve "disable_daemon" rules into the concrete launchd keys that
        must sit in the disabled-daemons plist on this setup. Accepts either
        Daemon enum member names (e.g. "ScreenTime") or raw launchd keys."""
        names = self.disabled_daemons(device_version, device_model, app_version)
        if not names:
            return set()
        from src.tweaks.daemons_tweak import Daemon
        members = {d.name: d for d in Daemon}
        all_keys = {k for d in Daemon for k in d.value}
        keys = set()
        for name in names:
            member = members.get(name)
            if member is not None:
                keys.update(member.value)
            elif name in all_keys:
                keys.add(name)
        return keys

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _compare(v1, v2):
        a = [int(x) for x in str(v1).replace(",", ".").split(".") if x.isdigit()]
        b = [int(x) for x in str(v2).replace(",", ".").split(".") if x.isdigit()]
        a += [0] * (len(b) - len(a))
        b += [0] * (len(a) - len(b))
        return (a > b) - (a < b)

    def _rule_applicable(self, rule: dict, device_version, device_model,
                         app_version: Optional[str] = None) -> bool:
        """Whether a rule applies to this setup: it is enabled and its version
        (app and/or iOS) / model bounds match. When no app_version is given,
        the running app's own version is used (so existing callers are scoped
        automatically)."""
        if rule.get("disabled", True) is False:
            return False
        if app_version is None:
            app_version = _APP_VERSION
        return (self._app_version_applicable(rule, app_version)
                and self._version_applicable(rule, device_version)
                and self._model_applicable(rule, device_model))

    def _app_version_applicable(self, rule: dict, app_version) -> bool:
        """App-version scoping of a rule (the version the rule "propagates"
        to): exact set via ``app_versions`` or a range via
        ``min_app_version`` / ``max_app_version``."""
        exact = rule.get("app_versions")
        if exact:
            if app_version is None:
                return False
            return any(self._compare(app_version, v) == 0 for v in exact)
        lo = rule.get("min_app_version")
        hi = rule.get("max_app_version")
        if lo is None and hi is None:
            return True
        if app_version is None:
            return False
        v = str(app_version)
        if lo is not None and self._compare(v, str(lo)) < 0:
            return False
        if hi is not None and self._compare(v, str(hi)) > 0:
            return False
        return True

    def _version_applicable(self, rule: dict, device_version) -> bool:
        lo = rule.get("min_version")
        hi = rule.get("max_version")
        if lo is None and hi is None:
            return True
        if device_version is None:
            return False
        v = str(device_version)
        if lo is not None and self._compare(v, str(lo)) < 0:
            return False
        if hi is not None and self._compare(v, str(hi)) > 0:
            return False
        return True

    def _model_applicable(self, rule: dict, device_model) -> bool:
        only = rule.get("only_models")
        if not only:
            return True
        if device_model is None:
            return False
        model = str(device_model)
        return any(model.startswith(p) for p in only)
