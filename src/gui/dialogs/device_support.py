"""Explain the selected device's support using the same local rules as the UI."""
from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.controllers.hotload import HotLoad
from src.devicemanagement.device_capabilities import device_os_text
from src.devicemanagement.passcode_support import current_passcode_theme_reason
from src.gui.ios.compat import compatibility_reasons
from src.gui.theme import ColorThemeManager, t
from src.gui.widgets import (
    IOSCard,
    IOSCollapsibleSection,
)
from src.tweaks.registry import SPECS
from src.tweaks.tweak_names import TweakID


def support_report(manager):
    tr = lambda text: device_os_text(QCoreApplication.translate("Nugget", text), model)
    version = manager.get_current_device_version() or ""
    model = manager.get_current_device_model() or ""
    safety = HotLoad(manager.pref_manager.settings)
    context = dict(device_version=version, device_model=model)
    hidden = safety.hidden_tweak_names(**context)
    hidden_reasons = safety.hidden_feature_reasons(**context)
    supported = manager.get_current_device_is_supported_by_fork()
    lines = [tr("Device: {0} · iOS {1}").format(model, version)]
    if not supported:
        lines.append(tr("Applying tweaks requires iOS 26.2 or newer."))
    else:
        lines.append(tr("This iOS version is supported by GoldenNugget."))
    lines.append(tr("Availability below follows the app's compatibility rules; it is not a test of effects on the device."))
    available, unavailable, blocked = [], [], []
    groups = {"available": [], "unavailable": [], "blocked": []}
    kill = safety.kill_rule(**context)
    for spec in SPECS:
        if spec.disabled:
            continue
        title = tr(spec.title)
        label = f"{tr(spec.section.value)} — {title}"
        reasons = compatibility_reasons(spec.id, version, model)
        rule = safety.rule_for(spec.id, **context)
        if kill:
            reason = kill.get('reason') or tr('Application blocked by safety rules')
            blocked.append(f"{label}: {reason}")
            groups["blocked"].append((tr(spec.section.value), title, reason))
        elif spec.id.name in hidden:
            reason = hidden_reasons.get(safety.feature_for(spec.id))
            reason = reason or tr('Section hidden by safety rules')
            blocked.append(f"{label}: {reason}")
            groups["blocked"].append((tr(spec.section.value), title, reason))
        elif rule:
            reason = rule.get('reason') or tr('Blocked by safety rules')
            blocked.append(f"{label}: {reason}")
            groups["blocked"].append((tr(spec.section.value), title, reason))
        elif not supported:
            reason = tr('Requires iOS 26.2 or newer')
            unavailable.append(f"{label}: {reason}")
            groups["unavailable"].append((tr(spec.section.value), title, reason))
        elif reasons:
            reason = '; '.join(reasons)
            unavailable.append(f"{label}: {reason}")
            groups["unavailable"].append((tr(spec.section.value), title, reason))
        else:
            available.append(label)
            groups["available"].append((tr(spec.section.value), title, ""))
    for title, entries in ((tr("Blocked by safety rules"), blocked),
                           (tr("Unavailable for this device"), unavailable)):
        lines.extend(["", f"{title} ({len(entries)})", *entries])
    hidden_features = sorted(safety.hidden_features(**context))
    if hidden_features:
        lines.extend(["", tr("Hidden feature pages"), *hidden_features])
    lines.extend(["", tr("Other feature pages")])
    pages = []
    for title, tid in (("PosterBoard", TweakID.PosterBoard),
                       ("Templates", TweakID.Templates),
                       ("Daemons", TweakID.Daemons),
                       ("Status Bar", TweakID.StatusBar),
                       ("Icon Themes", TweakID.IconThemes),
                       ("Passcode Theme", None)):
        rule = kill or (safety.rule_for(tid, **context) if tid is not None else None)
        feature = safety.feature_for(tid)
        if feature in hidden_reasons:
            state = hidden_reasons[feature] or tr("Section hidden by safety rules")
        elif rule:
            state = rule.get("reason") or tr("Blocked by safety rules")
        elif not supported:
            state = tr("Requires iOS 26.2 or newer")
        elif title == "Passcode Theme":
            state = current_passcode_theme_reason(manager) or tr(
                "No additional restrictions listed; setup requirements are shown on the page")
        else:
            state = tr("No additional restrictions listed; setup requirements are shown on the page")
        lines.append(f"{tr(title)}: {state}")
        pages.append((tr(title), state))
    forced = safety.disabled_daemons(**context)
    if forced:
        lines.extend(["", tr("Services forced off by safety rules")])
        lines.extend(f"{name}: {reason or tr('Forced off by safety rules')}"
                     for name, reason in sorted(forced.items()))
    if not safety.is_enabled():
        lines.extend(["", tr("HotLoad safety rules are turned off in Settings.")])
    lines.extend(["", f"{tr('Available registry tweaks')} ({len(available)})", *available])
    return dict(lines=lines, groups=groups, supported=supported,
                model=model, version=version, hidden=hidden_features, pages=pages,
                forced=forced, safety_enabled=safety.is_enabled())


def support_lines(manager):
    return support_report(manager)["lines"]


class DeviceSupportDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._model = manager.get_current_device_model()
        self.setWindowTitle(self._tr("Device Compatibility"))
        self.setMinimumWidth(520)
        self.resize(700, 660)
        report = support_report(manager)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = self._label(self._tr("Device Compatibility"), "compatTitle")
        layout.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setObjectName("compatScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("compatContent")
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(14)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        device = IOSCard()
        device_layout = QVBoxLayout(device)
        device_layout.setContentsMargins(16, 16, 16, 16)
        device_layout.setSpacing(10)
        heading = QHBoxLayout()
        name = getattr(manager, "get_current_device_name", lambda: None)() or report["model"]
        heading.addWidget(self._label(name, "compatDevice"), 1)
        state = "supported" if report["supported"] else "unsupported"
        status = self._label(self._tr({"supported": QT_TRANSLATE_NOOP("Nugget", "Supported"),
                                       "unsupported": QT_TRANSLATE_NOOP("Nugget", "Not Supported")}[state]), "compatBadge")
        status.setProperty("supportState", state)
        heading.addWidget(status, 0, Qt.AlignTop)
        device_layout.addLayout(heading)
        build = getattr(manager, "get_current_device_build", lambda: None)()
        info = self._tr("{0} · iOS {1}").format(report["model"], report["version"])
        if build:
            info += self._tr(" · Build {0}").format(build)
        device_layout.addWidget(self._label(info, "compatMuted"))
        if report["supported"]:
            explanation = self._tr("Your iOS version is supported. Some tweaks may still depend on your device or iOS version.")
        else:
            explanation = self._tr("Applying tweaks requires iOS 26.2 or newer. This device cannot apply tweaks with GoldenNugget.")
        device_layout.addWidget(self._label(explanation, "compatBody"))
        body.addWidget(device)

        counts = QHBoxLayout()
        counts.setSpacing(10)
        for key, text in (("available", QT_TRANSLATE_NOOP("Nugget", "Available")), ("unavailable", QT_TRANSLATE_NOOP("Nugget", "Unavailable")),
                          ("blocked", QT_TRANSLATE_NOOP("Nugget", "Safety Restrictions"))):
            card = IOSCard()
            column = QVBoxLayout(card)
            column.setContentsMargins(12, 12, 12, 12)
            column.setSpacing(4)
            column.addWidget(self._label(str(len(report["groups"][key])), "compatCount"))
            column.addWidget(self._label(self._tr(text), "compatMuted"))
            counts.addWidget(card, 1)
        body.addLayout(counts)
        body.addWidget(self._label(self._tr(
            "These checks use your device model, iOS version, and the app’s safety rules. "
            "Available does not mean a tweak has been tested on your device."), "compatMuted"))
        if not report["safety_enabled"]:
            warning = self._label(self._tr(
                "Automatic safety rules are off. You can turn them back on in Settings → Safety."), "compatWarning")
            body.addWidget(warning)

        for key, title in (("blocked", QT_TRANSLATE_NOOP("Nugget", "Safety Restrictions")),
                           ("unavailable", QT_TRANSLATE_NOOP("Nugget", "Unavailable on This Device")),
                           ("available", QT_TRANSLATE_NOOP("Nugget", "Available Tweaks"))):
            entries = report["groups"][key]
            section = IOSCollapsibleSection(self._tr("{0} ({1})").format(self._tr(title), len(entries)), expanded=False)
            grouped = {}
            for category, name, reason in entries:
                grouped.setdefault(category, []).append((name, reason))
            for category, items in grouped.items():
                section.body_layout.addWidget(self._entry_card(category, items))
            if not entries:
                message = self._tr("No restrictions in this category.") if key != "available" else self._tr("No tweaks are available for this device.")
                section.body_layout.addWidget(self._label(message, "compatMuted"))
            body.addWidget(section)

        pages = IOSCollapsibleSection(self._tr("Feature Sections"), expanded=False)
        for name, reason in report["pages"]:
            if reason == self._tr("No additional restrictions listed; setup requirements are shown on the page"):
                reason = self._tr("No extra restrictions listed. Check this section for setup instructions.")
            pages.body_layout.addWidget(self._entry_card(name, [("", reason)]))
        if report["hidden"]:
            pages.body_layout.addWidget(self._entry_card(self._tr("Hidden Sections"),
                [(self._tr(name), "") for name in report["hidden"]]))
        body.addWidget(pages)
        if report["forced"]:
            forced = IOSCollapsibleSection(self._tr("Services Managed by Safety Rules"), expanded=False)
            forced.body_layout.addWidget(self._entry_card(self._tr("Automatically disabled services"),
                [(name, reason or self._tr("Disabled by safety rules"))
                 for name, reason in sorted(report["forced"].items())]))
            body.addWidget(forced)
        body.addStretch()

        done = QPushButton(self._tr("Done"), self)
        done.setObjectName("cancelBtn")
        done.setMinimumHeight(48)
        done.setCursor(Qt.PointingHandCursor)
        done.clicked.connect(self.accept)
        layout.addWidget(done)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _tr(self, text):
        return device_os_text(QCoreApplication.translate("Nugget", text), self._model)

    @staticmethod
    def _label(text, name):
        label = QLabel(text)
        label.setObjectName(name)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _entry_card(self, title, entries):
        card = IOSCard()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(self._label(title, "compatSection"))
        for name, reason in entries:
            if name:
                layout.addWidget(self._label(name, "compatBody"))
            if reason:
                layout.addWidget(self._label(reason, "compatMuted"))
        return card

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog") + t("device_support_dialog"))
